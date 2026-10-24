"""RSS 抓取与文章解析。

相比旧实现的关键修正：
  * 时间统一用 ``calendar.timegm`` 处理 ``struct_time``。旧代码用
    ``time.mktime``，它把入参当**本地时间**，在非 UTC 环境下会整体偏移
    时区差（实测 TZ=Asia/Shanghai 时误差 8 小时），导致漏抓或重复抓。
  * 单个 feed 抓取失败不影响其它 feed（旧实现里一个源超时会拖垮整轮）。
  * 每个源用独立 session + 超时，不会无限挂起。
"""

from __future__ import annotations

import calendar
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser

from .config import FeedConfig

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30  # 秒


@dataclass
class Post:
    """一篇文章。时间统一用带时区的 UTC datetime。"""

    time: datetime
    blog: str
    title: str
    author: str
    link: str
    body: str
    site: str = ""


def _entry_time(entry) -> datetime | None:
    """取出文章时间并转成 UTC aware datetime；取不到返回 None。"""
    for key in ("updated_parsed", "published_parsed", "created_parsed"):
        struct = entry.get(key)
        if not struct:
            continue
        # struct_time 是 UTC 的，必须用 timegm 而不是 mktime
        return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    return None


def _entry_author(entry) -> str:
    author = entry.get("author")
    if author:
        return author
    names = [a.get("name") for a in entry.get("authors", []) if a.get("name")]
    return ", ".join(names) if names else "Anonymous"


def _entry_body(entry) -> str:
    content = entry.get("content")
    if content:
        try:
            return content[0].get("value", "")
        except (IndexError, KeyError, TypeError):
            pass
    return entry.get("summary", "")


def to_post(entry, blog: str, since: datetime, site: str = "") -> Post | None:
    """把 feedparser 的 entry 转成 Post。

    ``site`` 是文章所属站点的根地址，主要用于图片请求的 Referer。

    关于无日期条目：很多源（典型如知乎日报）只有第一条带 pubDate，其余
    条目完全没有时间字段。旧实现遇到这种情况直接丢弃，导致 30 篇只抓到
    1 篇。这里改为**用当前时间兜底**——没有时间信息说明我们无法判断它
    是不是旧的，宁可多收一篇也不要静默漏掉。
    """
    when = _entry_time(entry)
    if when is None:
        log.debug("条目没有时间字段，按当前时间处理：%s", entry.get("title"))
        when = datetime.now(timezone.utc)
    elif when < since:
        return None
    return Post(
        time=when,
        blog=blog,
        title=entry.get("title", "Null"),
        author=_entry_author(entry),
        link=entry.get("link", ""),
        body=_entry_body(entry),
        site=site,
    )


def fetch_feed(feed: FeedConfig, since: datetime, timeout: int = DEFAULT_TIMEOUT) -> list[Post]:
    """抓取单个 feed 并返回 since 之后的文章。

    任何网络/解析异常都在这里被吃掉并返回空列表 —— 一个源挂掉不应该影响别的源。
    """
    try:
        parsed = feedparser.parse(
            feed.url,
            request_headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            },
            # feedparser 透传给 urllib 的超时
            request_timeout=timeout,
        )
    except TypeError:
        # 老版本 feedparser 不支持 request_timeout
        try:
            parsed = feedparser.parse(feed.url)
        except Exception as e:  # noqa: BLE001 - 网络异常种类太多，统一兜底
            log.warning("[%s] 抓取失败：%s", feed.name, e)
            return []
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] 抓取失败：%s", feed.name, e)
        return []

    if getattr(parsed, "bozo", False) and not parsed.get("entries"):
        log.warning("[%s] 解析异常且无条目：%s", feed.name, getattr(parsed, "bozo_exception", ""))

    blog = feed.name or parsed.get("feed", {}).get("title", "") or feed.url
    site = _site_of(feed.url, parsed)

    posts: list[Post] = []
    for entry in parsed.get("entries", []):
        try:
            post = to_post(entry, blog, since, site)
        except Exception as e:  # noqa: BLE001
            log.warning("[%s] 条目解析失败，已跳过：%s", feed.name, e)
            continue
        if post:
            posts.append(post)

    posts.sort(key=lambda p: p.time)
    log.info("[%s] 抓到 %d 篇", feed.name, len(posts))
    return posts


def _site_of(feed_url: str, parsed) -> str:
    """推断文章所属站点，用于图片请求的 Referer。

    优先级：feed 里声明的站点主页 > feed 自身域名。知乎图床这类服务会
    校验 Referer，不带会直接 403。
    """
    link = ""
    try:
        link = (parsed.get("feed") or {}).get("link") or ""
    except Exception:  # noqa: BLE001
        link = ""
    base = link or feed_url
    from urllib.parse import urlparse

    parsed_url = urlparse(base)
    if parsed_url.scheme and parsed_url.netloc:
        return f"{parsed_url.scheme}://{parsed_url.netloc}/"
    return ""


def fetch_all(
    feeds: list[FeedConfig], since: datetime, max_workers: int = 5, timeout: int = DEFAULT_TIMEOUT
) -> list[tuple[FeedConfig, list[Post]]]:
    """并发抓取所有 feed，按 feeds 的原始顺序返回，保证书本目录顺序稳定。"""
    results: dict[int, list[Post]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(feeds) or 1))) as pool:
        future_map = {
            pool.submit(fetch_feed, feed, since, timeout): idx
            for idx, feed in enumerate(feeds)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception as e:  # noqa: BLE001 - 兜底：线程里逃逸出来的异常
                log.warning("[%s] 抓取线程异常：%s", feeds[idx].name, e)
                results[idx] = []

    return [(feed, results.get(i, [])) for i, feed in enumerate(feeds)]


def resolve_since(lookback_hours: int | None, state_file=None) -> datetime:
    """决定「从什么时候开始算新文章」。

    优先级：
      1. 配置里显式给了 lookback_hours -> now - N 小时
      2. 有状态文件（记录上次成功运行时间）-> 用上次的时间
      3. 都没有 -> 回溯 24 小时

    旧实现用 ``config/time.txt`` 里「小于 10000 就当小时数」的隐式约定，
    而且这种模式下**从不回写**，导致同一批文章反复推送。这里改成显式的
    state 文件，成功后回写，语义明确。
    """
    now = datetime.now(timezone.utc)

    if lookback_hours:
        since = now - timedelta(hours=lookback_hours)
        log.info("按配置回溯 %d 小时，起点 %s", lookback_hours, since.isoformat())
        return since

    if state_file:
        saved = state_file.read_since()
        if saved:
            log.info("沿用上次成功运行时间，起点 %s", saved.isoformat())
            return saved

    since = now - timedelta(hours=24)
    log.info("无历史记录，默认回溯 24 小时，起点 %s", since.isoformat())
    return since


class StateFile:
    """记录上次成功运行的时间戳，实现跨次运行的增量抓取。"""

    def __init__(self, path: str = "./config/last_run.txt"):
        self.path = path

    def read_since(self) -> datetime | None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except FileNotFoundError:
            return None
        if not text:
            return None
        try:
            return datetime.fromtimestamp(int(float(text)), tz=timezone.utc)
        except ValueError:
            log.warning("状态文件 %s 内容无法解析：%r，忽略", self.path, text[:40])
            return None

    def write(self, when: datetime) -> None:
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(str(int(when.timestamp())))
        except OSError as e:
            log.warning("写入状态文件失败（不影响本次结果）：%s", e)
