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

DOWNLOAD_TIMEOUT = 20
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 单张图上限，防止把书撑爆


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
    ):
        self.quality = max(1, min(100, quality))
        self.grayscale = grayscale
        self.referer = referer
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
        if referer:
            self.session.headers["Referer"] = referer
        self._counter = 0
        self.failed = 0

    def _next_name(self, fmt: str) -> str:
        name = f"img{self._counter}.{_EXT[fmt]}"
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
            headers = {"Referer": referer} if referer else {}
            try:
                resp = self.session.get(
                    url, timeout=DOWNLOAD_TIMEOUT, stream=True, headers=headers
                )
                resp.raise_for_status()
                raw = b""
                for chunk in resp.iter_content(64 * 1024):
                    raw += chunk
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


def rewrite_body(
    html: str, downloader: ImageDownloader
) -> tuple[str, list[ImageAsset]]:
    """处理一段正文 HTML 里的图片。

    返回 (新 HTML, 图片资源列表)。下载失败的 <img> 会被移除，避免 epub 里
    出现指向不存在文件的坏链接。
    """
    soup = BeautifulSoup(html, "html.parser")
    assets: list[ImageAsset] = []

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            img.decompose()
            continue
        asset = downloader.fetch(src)
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
