#!/usr/bin/env python3
"""冒烟测试：不依赖网络、不依赖 calibre，覆盖本次重构修掉的关键缺陷。

运行：
    python3 tests/smoke_test.py

任何一个用例失败都会以非零退出码结束，方便塞进 CI。
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from genbooks import config as C  # noqa: E402
from genbooks import feeds as F  # noqa: E402
from genbooks.builder import Chapter, build_epub  # noqa: E402
from genbooks.delivery import send_all  # noqa: E402
from genbooks.delivery.base import Channel  # noqa: E402
from genbooks.feeds import Post  # noqa: E402

FAILED: list[str] = []
PASSED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  ✓ {name}")
    else:
        FAILED.append(name)
        print(f"  ✗ {name} {detail}")


# ------------------------------------------------------------------ 配置层


def test_config() -> None:
    print("\n[配置层]")

    # 最小配置：只写 title + feeds，其余全缺 —— 旧版会 KeyError 崩溃
    try:
        cfg = C.parse({"title": "T", "feeds": [{"name": "a", "url": "http://x"}]})
        check("最小配置不崩溃", True)
        check("缺失渠道默认关闭", not cfg.telegram.enable and not cfg.boox.enable)
    except Exception as e:  # noqa: BLE001
        check("最小配置不崩溃", False, repr(e))

    # 旧格式（emailinfo 等旧名）必须兼容
    old = {
        "title": "Old",
        "feeds": [{"name": "a", "url": "http://x", "saveimg": False, "imgquality": 100}],
        "emailinfo": {"enable": True, "to": "a@b.c", "from": "a@b.c", "smtp": "s", "port": 25, "pwd": "p", "epub": False, "mobi": True},
        "webdav": {"enable": False},
        "telegram": {"enable": False},
        "boox": {"enable": False},
        "github": {"enable": True, "epub": True, "mobi": True},
    }
    cfg_old = C.parse(old)
    check("旧格式 emailinfo 兼容", cfg_old.email.enable and cfg_old.email.formats() == ["mobi"])

    # 字符串布尔
    cfg_str = C.parse({"title": "S", "feeds": [{"name": "a", "url": "http://x", "saveimg": "true"}],
                       "github": {"enable": "false", "epub": "1"}})
    check("字符串布尔解析", cfg_str.feeds[0].saveimg is True and cfg_str.github.enable is False)

    # 启用但缺必填项 -> 返回问题而不是抛异常
    cfg_bad = C.parse({"title": "B", "feeds": [{"name": "a", "url": "http://x"}],
                       "telegram": {"enable": True, "epub": True}})
    problems = C.validate_channels(cfg_bad)
    check("缺必填项被报告而非崩溃", any("token" in p for p in problems))

    # 非法配置给出明确错误
    for bad_input, hint in [("{oops", "JSON"), ('{"title":"x"}', "feeds")]:
        try:
            C.parse(bad_input)
            check(f"非法配置报错({hint})", False, "没有抛异常")
        except C.ConfigError:
            check(f"非法配置报错({hint})", True)


# ------------------------------------------------------------------ 抓取层


def test_time() -> None:
    print("\n[抓取层-时间]")
    import time as _time

    struct = _time.struct_time((2026, 10, 21, 7, 28, 0, 0, 0, 0))

    class E(dict):
        pass

    got = F._entry_time(E(published_parsed=struct))
    expect = datetime(2026, 10, 21, 7, 28, tzinfo=timezone.utc)
    check("UTC 时间解析正确", got == expect, f"got={got}")

    # 旧实现 time.mktime 在非 UTC 时区会偏移；确认新实现不受 TZ 影响
    old_ts = _time.mktime(struct)
    old_val = datetime.fromtimestamp(old_ts, tz=timezone.utc)
    check(
        "不再使用 mktime（避免时区偏移）",
        got == expect,
        f"旧实现会得到 {old_val}",
    )

    # 无日期的条目不再丢弃（知乎日报等源 30 条里只有 1 条带日期，
    # 旧实现会把另外 29 条全丢掉），改为用当前时间兜底
    no_date_post = F.to_post(E(title="x", link="http://x"), "b", expect)
    check("无日期条目不再被丢弃", no_date_post is not None)
    if no_date_post is not None:
        check(
            "无日期条目用当前时间兜底",
            no_date_post.time >= expect,
            f"got={no_date_post.time}",
        )


# ------------------------------------------------------------------ 构建层


def test_builder() -> None:
    print("\n[构建层]")
    with tempfile.TemporaryDirectory() as td:
        posts = [
            Post(datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc), "源A", "标题一", "作者", "http://x/1", "<p>正文</p>"),
            Post(datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc), "源A", "标题<2>", "作者", "http://x/2", "<p>含&lt;尖括号&gt;</p>"),
            Post(datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc), "源A", "标题三", "作者", "http://x/3", "<p>正文三</p>"),
        ]
        chapters = [Chapter(title="源A", posts=posts)]
        out = build_epub("测试书", chapters, Path(td) / "t.epub")

        check("epub 文件生成", out.exists() and out.stat().st_size > 0)
        z = zipfile.ZipFile(out)
        first = z.infolist()[0]
        check("mimetype 是第一个 entry", first.filename == "mimetype", first.filename)
        check("mimetype 未被压缩(符合 OCF)", first.compress_type == zipfile.ZIP_STORED, str(first.compress_type))
        check("含 EPUB3 nav.xhtml", any(n.endswith("nav.xhtml") for n in z.namelist()))
        opf = [n for n in z.namelist() if n.endswith(".opf")]
        check("含 content.opf", len(opf) == 1)

        # 每篇文章必须是独立文件（不能全挤在一个 chapter 里）
        import re as _re

        article_files = [
            n for n in z.namelist() if _re.search(r"_a\d+\.xhtml$", n)
        ]
        check("每篇文章独立成文件", len(article_files) == 3, f"实际 {len(article_files)} 个: {article_files}")

        for name in article_files:
            html = z.read(name).decode()
            n_title = html.count('class="article-title"')
            check(f"{name} 只含 1 篇", n_title == 1, f"含 {n_title} 篇")

        # 目录必须是两层：源分组下面挂文章
        nav = z.read([n for n in z.namelist() if n.endswith("nav.xhtml")][0]).decode()
        check("nav 含源分组标题", "源A" in nav)
        check("nav 含每篇文章标题", all(t in nav for t in ("标题一", "标题&lt;2&gt;", "标题三")))
        check("nav 是嵌套结构(<ol> 出现两次)", nav.count("<ol") >= 2, f"<ol 出现 {nav.count('<ol')} 次")


def test_single_article_no_group() -> None:
    """一个源只有一篇文章时，不应再套一层分组。"""
    print("\n[构建层-单篇不分组]")
    with tempfile.TemporaryDirectory() as td:
        posts = [Post(datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc), "源B", "唯一一篇", "a", "l", "<p>x</p>")]
        out = build_epub("书", [Chapter(title="源B", posts=posts)], Path(td) / "s.epub")
        z = zipfile.ZipFile(out)
        nav = z.read([n for n in z.namelist() if n.endswith("nav.xhtml")][0]).decode()
        check("单篇时文章直接挂在目录下", "唯一一篇" in nav)
        check("单篇时不额外生成分组页", not any(n.endswith("g0.xhtml") for n in z.namelist()))


# ------------------------------------------------------------------ 投递层


class _OkChannel(Channel):
    name = "ok"

    def send(self, files):
        return "done"


class _BoomChannel(Channel):
    name = "boom"

    def send(self, files):
        raise RuntimeError("模拟失败")


class _BareChannel(Channel):
    name = "bare"

    def send(self, files):
        raise KeyError("telegram")  # 这正是旧版配置缺键时的异常类型


def test_delivery() -> None:
    print("\n[投递层-失败隔离]")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "a.epub"
        f.write_bytes(b"x")
        files = {"epub": f}
        cfg = C.parse({"title": "T", "feeds": [{"name": "a", "url": "http://x"}]})

        ok = _OkChannel(cfg.github)
        ok.config.enable = True
        ok.config.epub = True
        boom = _BoomChannel(cfg.github)
        boom.config.enable = True
        boom.config.epub = True
        bare = _BareChannel(cfg.github)
        bare.config.enable = True
        bare.config.epub = True

        results = send_all([boom, bare, ok], files)
        check("不向外抛异常", True)
        check("失败渠道被标记", len([r for r in results if not r.ok]) == 2)
        check("成功渠道仍成功", [r for r in results if r.ok][0].channel == "ok")
        check("产物未被删除", f.exists())
        check("KeyError 也被兜住", any("KeyError" in r.detail for r in results))


# ------------------------------------------------------------------ 运行


def main() -> int:
    print("=" * 60)
    print("GenBooks 冒烟测试")
    print("=" * 60)
    for fn in (test_config, test_time, test_builder, test_single_article_no_group, test_delivery):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            FAILED.append(fn.__name__)

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print(f"  失败：{name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
