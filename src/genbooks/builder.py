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
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ebooklib import epub

from .config import FeedConfig
from .feeds import Post
from .images import ImageDownloader, rewrite_body, strip_images

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
    site: str = ""


def _esc(text: str) -> str:
    """最小化 HTML 转义，防止标题里的 < & 破坏结构。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _xhtml(title: str, body: str, extra_css: str = "") -> str:
    """包一层完整的 XHTML 外壳。

    注意：这里**不能**带 ``<?xml version="1.0" encoding="utf-8"?>`` 声明。
    ebooklib 内部用 lxml 的 HTML 解析器处理 content 字符串，遇到带
    encoding 声明的 unicode 字符串会直接抛 ValueError，导致该章节
    （以及连带依赖它的 nav.xhtml）静默丢失。
    """
    css_tag = f'<style type="text/css">{extra_css}</style>' if extra_css else ""
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>{_esc(title)}</title>"
        '<link rel="stylesheet" href="style.css" type="text/css"/>'
        f"{css_tag}</head><body>{body}</body></html>"
    )


def _article_body(
    post: Post, chapter: Chapter, downloader: ImageDownloader
) -> tuple[str, list]:
    """处理一篇正文：图片下载/剥离，返回 (html, 图片资源列表)。"""
    body = post.body or ""
    assets = []
    if chapter.saveimg:
        body, assets = rewrite_body(body, downloader)
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
    article_count = 0
    image_count = 0

    for group_idx, chapter in enumerate(chapters):
        downloader = ImageDownloader(chapter.imgquality, referer=chapter.site)
        article_items: list[epub.EpubHtml] = []

        for art_idx, post in enumerate(chapter.posts):
            body, assets = _article_body(post, chapter, downloader)

            # 图片作为独立 item 加入，并把正文里的相对路径改成 images/ 前缀
            for asset in assets:
                item = epub.EpubItem(
                    uid=f"g{group_idx}a{art_idx}_{asset.name}",
                    file_name=f"images/{asset.name}",
                    media_type=asset.media_type,
                    content=asset.data,
                )
                book.add_item(item)
                image_count += 1
                body = body.replace(f'src="{asset.name}"', f'src="images/{asset.name}"')

            when = post.time.astimezone().strftime("%Y-%m-%d %H:%M")
            # 标题已在 h2 里，不再重复显示；来源与时间放小字
            meta_bits = [b for b in (post.blog, when) if b]
            html = _xhtml(
                post.title,
                f'<h2 class="article-title">{_esc(post.title)}</h2>'
                f'<p class="article-meta">{_esc(" · ".join(meta_bits))}</p>'
                f'<div class="article-body">{body}</div>',
                chapter.css,
            )

            item = epub.EpubHtml(
                title=post.title,
                file_name=f"g{group_idx}_a{art_idx}.xhtml",
                lang="zh",
            )
            item.content = html
            book.add_item(item)
            article_items.append(item)
            article_count += 1

        if not article_items:
            continue

        spine.extend(article_items)

        # 目录：多篇文章时套一层源分组；只有一篇就直接平铺
        if len(article_items) == 1:
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
            book.add_item(group_head)
            spine.insert(len(spine) - len(article_items), group_head)
            toc.append((section, tuple(article_items)))

    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *spine]

    output.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output), book)
    log.info(
        "epub 已生成：%s（%d 个源 / %d 篇文章，%d 张图片）",
        output,
        len(chapters),
        article_count,
        image_count,
    )
    return output


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
                site=posts[0].site if posts else "",
            )
        )
    return chapters
