"""epub -> mobi 转换（依赖 calibre 的 ebook-convert）。

关键修正：旧实现用 ``if ".mobi" in str(out)`` 判断成功 —— 看的是
``communicate()`` 返回的 ``(b'', None)`` 里有没有 ".mobi" 字样，和转换
是否成功毫无关系，而且失败后仍继续往下跑，拿不存在的文件去投递。
这里改成检查 returncode + 产物是否真实存在，失败就抛异常。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

CONVERT_TIMEOUT = 600  # 秒


class ConversionError(Exception):
    pass


def _check_calibre() -> str:
    exe = shutil.which("ebook-convert")
    if not exe:
        raise ConversionError(
            "找不到 ebook-convert 命令。请先安装 calibre："
            "https://calibre-ebook.com/download_linux"
        )
    return exe


def epub_to_mobi(epub_path: Path, mobi_path: Path) -> Path:
    """把 epub 转成 mobi。失败抛 ConversionError。"""
    exe = _check_calibre()
    if not epub_path.exists():
        raise ConversionError(f"源文件不存在：{epub_path}")

    cmd = [exe, str(epub_path), str(mobi_path)]
    log.info("开始转换：%s -> %s", epub_path.name, mobi_path.name)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=CONVERT_TIMEOUT,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise ConversionError(f"转换超时（>{CONVERT_TIMEOUT}s）：{epub_path.name}") from e

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise ConversionError(
            f"ebook-convert 返回 {proc.returncode}：{epub_path.name}\n{tail}"
        )
    if not mobi_path.exists() or mobi_path.stat().st_size == 0:
        raise ConversionError(
            f"ebook-convert 报告成功但未产生有效文件：{mobi_path}"
        )

    log.info("转换完成：%s（%.1f MB）", mobi_path.name, mobi_path.stat().st_size / 1024 / 1024)
    return mobi_path


def is_available() -> bool:
    return shutil.which("ebook-convert") is not None
