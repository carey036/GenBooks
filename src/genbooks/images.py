"""文章正文里的图片处理：下载、压缩、内嵌进 epub。

相比旧实现的修正：
  * 旧代码写文件用 ``self.imgid``、压缩/删除却用参数 ``imgid``，靠调用处
    恰好相等才没错；这里改成单一来源，不存在两个 id。
  * 旧代码用 ``"jpg" in src`` / ``"png" in src`` 猜格式，会把 ``logo.png?w=100``
    之外的 ``.webp``/``.gif``/无扩展名的全部漏掉；这里按真实 Content-Type +
    PIL 探测决定格式。
  * 下载失败区分「网络失败」和「不是图片」，都只跳过这一张图，不影响整篇。
"""

from __future__ import annotations

import io
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from PIL import Image

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# epub 里只允许这几种图片格式
_MEDIA_TYPES = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}
_EXT = {"jpeg": "jpg", "png": "png", "gif": "gif"}

CONNECT_TIMEOUT = 10                 # 连接超时（秒）
DOWNLOAD_TIMEOUT = 20               # 单张图读取超时（秒）
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 单张图上限，防止把书撑爆
IMAGE_WORKERS = 8                   # 并发下载线程数
BATCH_TIMEOUT = 180                 # 一篇文章所有图片的总下载上限（秒）


@dataclass
class ImageAsset:
    """一张准备写进 epub 的图片。"""

    name: str        # 例如 img0.jpg
    media_type: str
    data: bytes


class ImageDownloader:
    def __init__(
        self,
        quality: int = 100,
        grayscale: bool = True,
        referer: str = "",
        name_prefix: str = "",
    ):
        self.quality = max(1, min(100, quality))
        self.grayscale = grayscale
        self.referer = referer
        # 只保存请求头，不建共享 Session（见 fetch() 里的说明）
        self.base_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if referer:
            self.base_headers["Referer"] = referer
        # 每张图必须全局唯一。多源合并时每个源会各自 new 一个 downloader，
        # 若计数器都从 0 开始，不同源的图片会同名互相覆盖（zip 里出现
        # Duplicate name，最终显示的图张冠李戴）。
        self._prefix = name_prefix
        self._counter = 0
        self._lock = threading.Lock()
        self.failed = 0

    def _next_name(self, fmt: str) -> str:
        # 并发下载时多线程会同时取号，必须加锁，否则两张图会拿到同一个名字
        with self._lock:
            name = f"{self._prefix}img{self._counter}.{_EXT[fmt]}"
            self._counter += 1
            return name

    def _compress(self, raw: bytes) -> tuple[str, bytes] | None:
        """把任意图片转成 epub 友好的格式并压缩。不是图片则返回 None。"""
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:  # noqa: BLE001 - PIL 对坏数据抛的异常类型很杂
            return None

        fmt = (img.format or "").lower()
        # webp/bmp/tiff 之类转成 jpeg；gif 保留（可能是动图）
        if fmt == "gif" and getattr(img, "is_animated", False):
            return "gif", raw
        if fmt not in _MEDIA_TYPES or fmt == "gif":
            fmt = "jpeg"
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA").convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

        if self.grayscale and fmt != "gif" and img.mode in ("RGB", "RGBA"):
            # 电子墨水屏设备上灰度更省空间，也更小
            img = img.convert("L")

        buf = io.BytesIO()
        save_fmt = "JPEG" if fmt == "jpeg" else fmt.upper()
        # 灰度图保存为 JPEG 时 quality 才是有效参数
        img.save(buf, format=save_fmt, quality=self.quality, optimize=True)
        return fmt, buf.getvalue()

    def fetch(self, url: str) -> ImageAsset | None:
        """下载并处理一张图片；失败返回 None（调用方删掉该 img 标签）。"""
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith(("http://", "https://")):
            log.debug("跳过非 http 图片：%s", url)
            return None

        # 第一轮：正常请求。第二轮：很多图床（知乎/微信等）校验 Referer，
        # 没带或带错会返回 403，这里用图片自身的域名做 Referer 重试一次。
        attempts = [None]
        if not self.referer:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            attempts.append(f"{parsed.scheme}://{parsed.netloc}/")

        last_error = ""
        for referer in attempts:
            headers = dict(self.base_headers)
            if referer:
                headers["Referer"] = referer
            try:
                # 每次请求用独立的 session / 连接。
                #
                # 不能共用 self.session：requests.Session 内部的连接池不是
                # 为多线程并发设计的，8 个线程同时抢同一个池时会互相阻塞，
                # 实测表现为「所有线程 sleep、既无网络 I/O 也无 CPU 占用」
                # 的假死，任务永远不结束。图片数量有限，放弃连接复用的代价
                # 远小于卡死。
                resp = requests.get(
                    url,
                    timeout=(CONNECT_TIMEOUT, DOWNLOAD_TIMEOUT),
                    headers=headers,
                )
                resp.raise_for_status()
                raw = resp.content
                if len(raw) > MAX_IMAGE_BYTES:
                    log.warning("图片过大，跳过：%s", url)
                    return None
                break
            except requests.RequestException as e:
                last_error = str(e)
                raw = b""
                continue

        if not raw:
            self.failed += 1
            log.warning("图片下载失败 %s：%s", url, last_error)
            return None

        processed = self._compress(raw)
        if processed is None:
            self.failed += 1
            log.warning("不是可识别的图片，跳过：%s", url)
            return None

        fmt, data = processed
        return ImageAsset(self._next_name(fmt), _MEDIA_TYPES[fmt], data)


def collect_image_urls(html: str, max_images: int = 0) -> list[str]:
    """从正文里取出需要下载的图片 URL（受 max_images 限制）。"""
    soup = BeautifulSoup(html, "html.parser")
    imgs = soup.find_all("img")
    if max_images > 0:
        imgs = imgs[:max_images]
    out: list[str] = []
    for img in imgs:
        src = img.get("src") or img.get("data-src") or ""
        if src:
            out.append(src)
    return out


def rewrite_body(
    html: str,
    downloader: ImageDownloader,
    pool: "ThreadPoolExecutor | None" = None,
    max_images: int = 0,
    prefetched: "dict[str, ImageAsset | None] | None" = None,
) -> tuple[str, list[ImageAsset]]:
    """处理一段正文 HTML 里的图片。

    返回 (新 HTML, 图片资源列表)。下载失败的 <img> 会被移除，避免 epub 里
    出现指向不存在文件的坏链接。

    ``prefetched`` 是预先批量下载好的 ``{url: ImageAsset|None}``。整本书的
    图片一次性并发下载，比「按文章分批等」快得多：后者每篇文章都要等自己
    那批图跑完，线程池在批次边界会空转。``_next_name`` 有锁保护，并发安全。
    """
    soup = BeautifulSoup(html, "html.parser")
    assets: list[ImageAsset] = []

    imgs = list(soup.find_all("img"))
    if not imgs:
        return str(soup), assets

    # 超过上限的图直接删掉，只留前面几张，避免一篇几十张图把整轮任务拖死
    if max_images > 0 and len(imgs) > max_images:
        for extra in imgs[max_images:]:
            extra.decompose()
        log.info("本篇图片 %d 张，超出上限，只保留前 %d 张", len(imgs), max_images)
        imgs = imgs[:max_images]

    srcs = [(img.get("src") or img.get("data-src") or "") for img in imgs]

    if prefetched is not None:
        results = prefetched
    elif pool is not None:
        # 同一 URL 只下载一次；结果按 URL 回填
        unique = list(dict.fromkeys(s for s in srcs if s))
        results: dict[str, ImageAsset | None] = {}
        futures = {u: pool.submit(downloader.fetch, u) for u in unique}
        deadline = time.monotonic() + BATCH_TIMEOUT
        for url, fut in futures.items():
            remaining = max(1.0, deadline - time.monotonic())
            try:
                results[url] = fut.result(timeout=remaining)
            except FuturesTimeout:
                # 兜底：单张图卡住不应该让整本书永远出不来
                log.warning("图片下载超时，跳过：%s", url)
                results[url] = None
            except Exception as e:  # noqa: BLE001 - 单张图失败不影响整篇
                log.warning("图片下载异常 %s：%s", url, e)
                results[url] = None
    else:
        results = {}

    for img, src in zip(imgs, srcs):
        if not src:
            img.decompose()
            continue
        asset = results.get(src) if src in results else downloader.fetch(src)
        if asset is None:
            img.decompose()
            continue
        img["src"] = asset.name
        # 去掉可能存在的懒加载属性，避免阅读器忽略 src
        for attr in ("data-src", "srcset", "loading", "width", "height"):
            if img.has_attr(attr):
                del img[attr]
        assets.append(asset)

    return str(soup), assets


def strip_images(html: str) -> str:
    """不保存图片时，把 <img> 全部去掉。"""
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        img.decompose()
    return str(soup)
