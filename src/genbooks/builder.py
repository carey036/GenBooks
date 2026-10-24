"""把抓取到的文章构建成 epub。

设计取舍：不再手写 content.opf / toc.ncx / toc.html 等 XML 模板（旧实现
keys.py 里那一堆），改用 ebooklib 生成标准 EPUB3。这样：
  * mimetype 由库保证「第一个 entry 且不压缩」，符合 OCF 规范
  * nav.xhtml（EPUB3 目录）和 toc.ncx（兼容旧设备）都自动生成
  * 不用再维护几百行容易漏字段的模板字符串

目录结构（两层）：

    ├── 书伴 (7)                      ← 源分组
    │   ├── 亚马逊 Kindle Unlimited 正式更名…
    │   ├── 国产墨水屏难赚钱…
    │   └── …
    ├── 少数派 (3)
    │   └── …

每篇文章是独立的 xhtml 文件，可以在阅读器里单独跳转、单独定位。
一个源只有一篇文章时不再额外套一层分组，直接平铺。
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ebooklib import epub

from .config import FeedConfig
from .feeds import Post
from .images import (
    BATCH_TIMEOUT,
    IMAGE_WORKERS,
    ImageDownloader,
    collect_image_urls,
    rewrite_body,
    strip_images,
)

log = logging.getLogger(__name__)

# 正文基础样式，各 feed 的 css 会追加在后面
BASE_CSS = """
body { font-family: serif; line-height: 1.6; }
h2.article-title { font-size: 1.4em; font-weight: bold; margin-bottom: 0.3em; }
h2.group-title { font-size: 1.6em; font-weight: bold; border-bottom: 2px solid #333;
                 padding-bottom: 0.3em; margin-bottom: 1em; }
.article-meta { font-size: 0.8em; color: #666; margin-bottom: 1em; }
img { max-width: 100%; height: auto; }
"""


@dataclass
class Chapter:
    """一个 RSS 源的一组文章。"""

    title: str
    posts: list[Post] = field(default_factory=list)
    css: str = ""
    saveimg: bool = False
    imgquality: int = 100
    max_images: int = 0
    site: str = ""


def _esc(text: str) -> str:
    """最小化 HTML 转义，防止标题里的 < & 破坏结构。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _xhtml(title: str, body: str) -> str:
    """包一层完整的 XHTML 外壳。

    坑 1：这里**不能**带 ``<?xml version="1.0" encoding="utf-8"?>`` 声明。
    ebooklib 内部用 lxml 的 HTML 解析器处理 content，遇到带 encoding 声明
    的 unicode 字符串会直接抛 ValueError，该章节（以及连带依赖它的
    nav.xhtml）会静默丢失。

    坑 2：**不能**把自定义 CSS 放进 ``<head>`` 的 ``<style>``。ebooklib 的
    ``EpubHtml.get_content()`` 会丢掉原文档整个 head，只按
    ``self.title/metas/links`` 重新生成（epub.py 里保留原 head 的那段代码
    是被注释掉的）。写在 head 里的 style 会被无声忽略，表现为「配置了
    css 但阅读器里毫无效果」。自定义样式改为独立 CSS 文件，见
    ``build_epub`` 里的 ``_link_css``。
    """
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>{_esc(title)}</title>"
        '<link rel="stylesheet" href="style.css" type="text/css"/>'
        f"</head><body>{body}</body></html>"
    )


def _link_css(item: "epub.EpubHtml", href: str) -> None:
    """给某个章节挂一个额外的样式表。

    走 EpubHtml.links 而不是在 HTML 里写 <link>/<style>，因为 ebooklib 生成
    文件时会重建 head，只认 links 里登记过的样式表。
    """
    item.add_link(href=href, rel="stylesheet", type="text/css")


def _article_body(
    post: Post,
    chapter: Chapter,
    downloader: ImageDownloader,
    prefetched=None,
) -> tuple[str, list]:
    """处理一篇正文：图片替换/剥离，返回 (html, 图片资源列表)。

    图片已经在 _prefetch_images 里批量下好了，这里只做替换。
    """
    body = post.body or ""
    assets = []
    if chapter.saveimg:
        body, assets = rewrite_body(
            body,
            downloader,
            max_images=chapter.max_images,
            prefetched=prefetched,
        )
    else:
        body = strip_images(body)
    return body, assets


def build_epub(
    title: str,
    chapters: list[Chapter],
    output: Path,
    cover: Path | None = None,
    css: str = "",
) -> Path:
    """生成 epub 文件，返回路径。"""
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("zh")
    book.add_author("GenBooks")

    if cover and cover.exists():
        try:
            book.set_cover(cover.name, cover.read_bytes(), create_page=False)
        except Exception as e:  # noqa: BLE001 - 封面坏了不该拖垮整本书
            log.warning("封面加载失败，已忽略：%s", e)
    else:
        if cover:
            log.warning("找不到封面文件 %s，将不带封面生成", cover)

    style = BASE_CSS + "\n" + css
    style_item = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=style.encode("utf-8"),
    )
    book.add_item(style_item)

    spine: list = []
    toc: list = []

    # 先把全书要用的图片一次性并发下载好，再串行组装各章。
    # 按文章分批下载时，每篇都要等自己那批图跑完，线程池在批次边界空转，
    # 书越大越慢；一次性提交能让 8 个线程从头到尾吃满。
    prefetched = _prefetch_images(chapters)
    _build_chapters(book, chapters, spine, toc, prefetched)

    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *spine]

    epub.write_epub(str(output), book, {})

    articles = sum(
        1 for i in book.get_items() if getattr(i, "file_name", "").endswith(".xhtml")
    )
    images = sum(
        1
        for i in book.get_items()
        if str(getattr(i, "media_type", "")).startswith("image/")
        and i.get_name() != "cover.jpg"
    )
    log.info(
        "epub 已生成：%s（%d 个源 / %d 篇文章，%d 张图片）",
        output,
        len(chapters),
        articles,
        images,
    )
    return output


def _prefetch_images(chapters) -> dict[str, list]:
    """把全书所有文章用到的图片并发下载一遍。

    返回 {id(request): 对应的 url->asset 映射} 结构最简单：这里直接返回
    全局 url->asset，重复 URL 只下一次。
    """
    if not any(c.saveimg for c in chapters):
        return {}

    wanted: list[str] = []
    for chapter in chapters:
        if not chapter.saveimg:
            continue
        for post in chapter.posts:
            wanted.extend(
                collect_image_urls(post.body or "", chapter.max_images)
            )
    unique = list(dict.fromkeys(u for u in wanted if u))
    if not unique:
        return {}

    log.info("开始下载图片：共 %d 张（并发 %d）", len(unique), IMAGE_WORKERS)
    started = time.monotonic()

    # 每个源用自己的 referer / 质量设置；同一 URL 可能出现在多个源，先到先得。
    # 注意用 enumerate 拿序号：chapters.index(chapter) 在多个源内容相同时会
    # 返回同一个下标，导致两个源共用同名前缀、图片互相覆盖。
    owner: dict[str, ImageDownloader] = {}
    for idx, chapter in enumerate(chapters):
        if not chapter.saveimg:
            continue
        dl = ImageDownloader(
            chapter.imgquality,
            referer=chapter.site,
            name_prefix=f"g{idx}_",
        )
        for post in chapter.posts:
            for url in collect_image_urls(post.body or "", chapter.max_images):
                if url and url not in owner:
                    owner[url] = dl

    results: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=IMAGE_WORKERS) as pool:
        futures = {u: pool.submit(owner[u].fetch, u) for u in unique}
        deadline = time.monotonic() + BATCH_TIMEOUT
        for url, fut in futures.items():
            remaining = max(1.0, deadline - time.monotonic())
            try:
                results[url] = fut.result(timeout=remaining)
            except FuturesTimeout:
                log.warning("图片下载超时，跳过：%s", url)
                results[url] = None
            except Exception as e:  # noqa: BLE001
                log.warning("图片下载异常 %s：%s", url, e)
                results[url] = None

    ok = sum(1 for v in results.values() if v is not None)
    log.info(
        "图片下载完成：%d/%d 张成功，用时 %.0f 秒",
        ok, len(unique), time.monotonic() - started,
    )
    return results


def _build_chapters(book, chapters, spine, toc, prefetched) -> None:
    """逐个源生成章节、图片和目录结构。"""
    added_images: set[str] = set()
    for group_idx, chapter in enumerate(chapters):
        downloader = ImageDownloader(
            chapter.imgquality,
            referer=chapter.site,
            name_prefix=f"g{group_idx}_",
        )
        article_items: list[epub.EpubHtml] = []

        # 每个源的自定义 css 单独一个文件。不能塞进章节 head（会被 ebooklib
        # 丢掉），只能登记成独立样式表再挂到该源的每一篇上。
        group_css_href = f"css/g{group_idx}.css"
        if chapter.css.strip():
            css_item = epub.EpubItem(
                uid=f"css_g{group_idx}",
                file_name=group_css_href,
                media_type="text/css",
                content=chapter.css.encode("utf-8"),
            )
            book.add_item(css_item)
        else:
            group_css_href = ""

        for art_idx, post in enumerate(chapter.posts):
            body, assets = _article_body(post, chapter, downloader, prefetched)

            # 图片作为独立 item 加入，并把正文里的相对路径改成 images/ 前缀
            for asset in assets:
                # 同一张图可能被多篇文章引用（预下载按 URL 去重，拿到的是
                # 同一个 asset 对象）。只写一次文件，否则 zip 里会出现重名
                # 条目，后写入的覆盖先写入的。
                if asset.name not in added_images:
                    item = epub.EpubItem(
                        uid=f"img_{asset.name}",
                        file_name=f"images/{asset.name}",
                        media_type=asset.media_type,
                        content=asset.data,
                    )
                    book.add_item(item)
                    added_images.add(asset.name)
                body = body.replace(f'src="{asset.name}"', f'src="images/{asset.name}"')

            when = post.time.astimezone().strftime("%Y-%m-%d %H:%M")
            # 标题已在 h2 里，不再重复显示；来源与时间放小字
            meta_bits = [b for b in (post.blog, when) if b]
            html = _xhtml(
                post.title,
                f'<h2 class="article-title">{_esc(post.title)}</h2>'
                f'<p class="article-meta">{_esc(" · ".join(meta_bits))}</p>'
                f'<div class="article-body">{body}</div>',
            )

            item = epub.EpubHtml(
                title=post.title,
                file_name=f"g{group_idx}_a{art_idx}.xhtml",
                lang="zh",
            )
            item.content = html
            if group_css_href:
                _link_css(item, group_css_href)
            book.add_item(item)
            article_items.append(item)

        if not article_items:
            continue

        spine.extend(article_items)

        # 目录：始终套一层源分组。多源合并成一本书时，如果某个源只有一
        # 篇文章就平铺，它的文章会和别的源的分组并列，从目录上根本看不出
        # 来自哪个源。只有全书真的只有一个源、且该源只有一篇时才省略分组。
        only_one_source = len(chapters) == 1
        if only_one_source and len(article_items) == 1:
            toc.append(article_items[0])
        else:
            section = epub.Section(chapter.title, href=f"g{group_idx}.xhtml")
            # 分组本身需要一个落脚页，否则部分阅读器点击分组无反应
            group_head = epub.EpubHtml(
                title=chapter.title,
                file_name=f"g{group_idx}.xhtml",
                lang="zh",
            )
            group_head.content = _xhtml(
                chapter.title,
                f'<h2 class="group-title">{_esc(chapter.title)}</h2>'
                f'<p class="article-meta">共 {len(article_items)} 篇</p>',
            )
            if group_css_href:
                _link_css(group_head, group_css_href)
            book.add_item(group_head)
            spine.insert(len(spine) - len(article_items), group_head)
            toc.append((section, tuple(article_items)))


def group_into_chapters(
    feeds: list[FeedConfig], fetched: list[tuple[FeedConfig, list[Post]]]
) -> list[Chapter]:
    """把抓取结果按源分组，跳过没有更新的源。"""
    chapters: list[Chapter] = []
    for feed, posts in fetched:
        if not posts:
            continue
        chapters.append(
            Chapter(
                title=feed.name,
                posts=posts,
                css=feed.css,
                saveimg=feed.saveimg,
                imgquality=feed.imgquality,
                max_images=feed.max_images,
                site=posts[0].site if posts else "",
            )
        )
    return chapters
