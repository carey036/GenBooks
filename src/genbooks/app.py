"""整条流水线的编排。

    feeds -> builder -> convert -> delivery

设计原则：
  1. 任何阶段失败都给出**明确的退出码和可读原因**，不静默。
  2. 投递阶段单渠道失败不影响其它渠道，也不影响已生成的文件。
  3. "没有更新"是正常退出（退出码 0），不是错误。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import convert as conv
from . import feeds as feed_mod
from .builder import build_epub, group_into_chapters
from .config import Config, ConfigError, load, validate_channels
from .delivery import build_channels, send_all

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_RUNTIME = 1


class RunSummary:
    def __init__(self):
        self.post_count = 0
        self.files: dict[str, Path] = {}
        self.delivery_results: list = []
        self.skipped_channels: set[str] = set()

    def delivery_failed(self) -> list:
        """真正失败（排除「已禁用」这种正常跳过）。"""
        return [r for r in self.delivery_results if not r.ok and "已禁用" not in r.detail]


def _workdir(config_path: str) -> Path:
    """输出目录：优先用 ./output，保证 workflow 里 git add 能拿到。"""
    out = Path("./output")
    out.mkdir(parents=True, exist_ok=True)
    return out


def run(
    config_path: str = "./config/rss.conf",
    *,
    state_path: str = "./config/last_run.txt",
    cover_path: str = "./config/cover.jpg",
    workdir: str = "./output",
    dry_run: bool = False,
    lookback_override: int | None = None,
) -> RunSummary:
    """执行一轮完整流程。"""
    summary = RunSummary()

    # ---------------------------------------------------- 1. 配置
    cfg = load(config_path)
    if lookback_override:
        cfg.lookback_hours = lookback_override
        log.info("命令行指定回溯 %d 小时", lookback_override)

    problems = validate_channels(cfg)
    if problems:
        for p in problems:
            log.error("配置问题：%s", p)
        for p in problems:
            summary.skipped_channels.add(p.split(":")[0].strip())
        log.error("以下渠道因配置不完整被跳过：%s", ", ".join(summary.skipped_channels))

    # ---------------------------------------------------- 2. 抓取
    state = feed_mod.StateFile(state_path)
    since = feed_mod.resolve_since(cfg.lookback_hours, state)
    started_at = feed_mod.datetime.now(feed_mod.timezone.utc)

    log.info("开始抓取 %d 个 RSS 源", len(cfg.feeds))
    fetched = feed_mod.fetch_all(cfg.feeds, since)
    summary.post_count = sum(len(posts) for _, posts in fetched)

    if summary.post_count == 0:
        log.info("RSS 无更新，本轮不生成书籍")
        return summary

    log.info("共 %d 篇新文章，开始生成 epub", summary.post_count)

    # ---------------------------------------------------- 3. 构建
    chapters = group_into_chapters(cfg.feeds, fetched)
    outdir = Path(workdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%y%m%d%H", time.localtime())
    safe_title = _safe_filename(cfg.title)
    epub_path = outdir / f"{safe_title}{stamp}.epub"

    build_epub(
        cfg.title,
        chapters,
        epub_path,
        cover=Path(cover_path),
        css=cfg.css,
    )
    summary.files["epub"] = epub_path

    # ---------------------------------------------------- 4. 转换 mobi
    needs_mobi = any(ch.mobi and ch.enable for ch in cfg.channels().values())
    if needs_mobi:
        mobi_path = outdir / f"{safe_title}{stamp}.mobi"
        try:
            conv.epub_to_mobi(epub_path, mobi_path)
            summary.files["mobi"] = mobi_path
        except conv.ConversionError as e:
            log.error("mobi 转换失败：%s", e)
            log.error("将只投递 epub；依赖 mobi 的渠道会被自动跳过")
    # 连 epub 都没人要时其实不需要 mobi，这里保持简单：只要有人要就转

    if dry_run:
        log.info("--dry-run：跳过投递。产物：%s", {k: str(v) for k, v in summary.files.items()})
        return summary

    # ---------------------------------------------------- 5. 投递
    channels = build_channels(cfg, skip=summary.skipped_channels)
    summary.delivery_results = send_all(channels, summary.files)

    log.info("=" * 50)
    log.info("投递结果汇总：")
    for r in summary.delivery_results:
        log.info("  %s", r)
    log.info("=" * 50)

    # ---------------------------------------------------- 6. 状态回写
    if summary.files:
        state.write(started_at)

    # 清理不被任何渠道需要的文件
    _cleanup(summary, cfg)

    return summary


def _safe_filename(name: str) -> str:
    """把书名变成安全的文件名。"""
    bad = '<>:"/\\|?*\n\r\t'
    out = "".join("_" if c in bad else c for c in name).strip() or "RSS"
    return out[:80]


def _cleanup(summary: RunSummary, cfg: Config) -> None:
    """删掉没有任何已启用渠道需要的文件，避免仓库里堆垃圾。"""
    wanted: set[str] = set()
    for ch in cfg.channels().values():
        if ch.enable:
            wanted.update(ch.formats())
    for fmt, path in summary.files.items():
        if fmt not in wanted:
            try:
                path.unlink(missing_ok=True)
                log.info("清理未使用的文件：%s", path.name)
            except OSError as e:
                log.warning("清理 %s 失败：%s", path.name, e)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="genbooks", description="把 RSS 打包成 epub/mobi 并投递"
    )
    parser.add_argument("-c", "--config", default="./config/rss.conf", help="配置文件路径")
    parser.add_argument("--state", default="./config/last_run.txt", help="增量状态文件")
    parser.add_argument("--cover", default="./config/cover.jpg", help="封面图片路径")
    parser.add_argument("-o", "--output", default="./output", help="输出目录")
    parser.add_argument("--dry-run", action="store_true", help="只生成不投递")
    parser.add_argument(
        "--lookback",
        type=int,
        default=None,
        help="强制回溯 N 小时（覆盖配置文件与状态文件）",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        summary = run(
            args.config,
            state_path=args.state,
            cover_path=args.cover,
            workdir=args.output,
            dry_run=args.dry_run,
            lookback_override=args.lookback,
        )
    except ConfigError as e:
        log.error("配置错误：%s", e)
        return EXIT_CONFIG
    except Exception as e:  # noqa: BLE001
        log.exception("运行失败：%s", e)
        return EXIT_RUNTIME

    failed = summary.delivery_failed()
    if failed:
        log.error("有 %d 个渠道投递失败：%s", len(failed), ", ".join(r.channel for r in failed))
        return EXIT_RUNTIME

    if summary.post_count == 0:
        log.info("本轮无新内容，正常结束")
    else:
        log.info("完成")
    return EXIT_OK
