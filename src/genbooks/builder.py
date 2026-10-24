"""把抓取到的文章构建成 epub。

设计取舍：不再手写 content.opf / toc.ncx / toc.html 等 XML 模板（旧实现
keys.py 里那一堆），改用 ebooklib 生成标准 EPUB3。这样：
  * mimetype 由库保证「第一个 entry 且不压缩」，符合 OCF 规范
  * nav.xhtml（EPUB3 目录）和 toc.ncx（兼容旧设备）都自动生成
  * 不用再维护几百行容易漏字段的模板字符串
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ebooklib import epub

from .config import FeedConfig
from .feeds import Post
from .images import ImageDownloader, rewrite_body, strip_images

log = logging.getLogger(__name__)

# 正文基础样式，各 feed 的 css 会追加在后面
BASE_CSS = """
body { font-family: serif; line-height: 1.6; }
h2.feedtitle { font-size: 1.3em; font-weight: bold; margin-top: 1.2em; }
.article-meta { font-size: 0.8em; color: #666; }
img { max-width: 100%; height: auto; }
.chapter-title { font-size: 1.5em; font-weight: bold; }
"""


@dataclass
class Chapter:
    """一个 RSS 源对应书里的一章。"""

    title: str
    posts: list[Post] = field(default_factory=list)
    css: str = ""
    saveimg: bool = False
    imgquality: int = 100


def _esc(text: str) -> str:
    """最小化 HTML 转义，防止标题里的 < & 破坏结构。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


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
    chapter_items: list[epub.EpubHtml] = []
    image_count = 0

    for idx, chapter in enumerate(chapters):
        downloader = ImageDownloader(chapter.imgquality)
        # 图片要先作为独立 item 加入书里，正文才能引用
        html_parts: list[str] = []
        for post in chapter.posts:
            body = post.body or ""
            if chapter.saveimg:
                body, assets = rewrite_body(body, downloader)
                for asset in assets:
                    item = epub.EpubItem(
                        uid=f"ch{idx}_{asset.name}",
                        file_name=f"images/{asset.name}",
                        media_type=asset.media_type,
                        content=asset.data,
                    )
                    book.add_item(item)
                    image_count += 1
                # 正文里引用的路径要和 item 的 file_name 一致
                for asset in assets:
                    body = body.replace(f'src="{asset.name}"', f'src="images/{asset.name}"')
            else:
                body = strip_images(body)

            when = post.time.astimezone().strftime("%Y-%m-%d %H:%M")
            html_parts.append(
                f'<div class="article">'
                f'<h3 class="article-title">{_esc(post.title)}</h3>'
                f'<p class="article-meta">{_esc(post.author)} · {_esc(post.blog)} · {when}</p>'
                f'<div class="article-body">{body}</div>'
                f"</div>"
            )

        item = epub.EpubHtml(
            title=chapter.title,
            file_name=f"chapter_{idx}.xhtml",
            lang="zh",
        )
        item.content = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            f'<title>{_esc(chapter.title)}</title>'
            f'<link rel="stylesheet" href="style.css" type="text/css"/>'
            "</head><body>"
            f'<h2 class="chapter-title">{_esc(chapter.title)}</h2>'
            + (f'<style type="text/css">{chapter.css}</style>' if chapter.css else "")
            + "\n".join(html_parts)
            + "</body></html>"
        )
        book.add_item(item)
        chapter_items.append(item)

    style_item = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=style.encode("utf-8"),
    )
    book.add_item(style_item)

    book.toc = tuple(chapter_items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapter_items]

    output.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output), book)
    log.info("epub 已生成：%s（%d 章，%d 张图片）", output, len(chapters), image_count)
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
            )
        )
    return chapters
