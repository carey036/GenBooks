#!/usr/bin/env python3
"""入口脚本（兼容旧调用方式）。

用法：
    python3 src/genBook.py                # 正常跑一轮
    python3 src/genBook.py --dry-run      # 只生成不投递
    python3 src/genBook.py -v             # 调试日志

环境变量 ``config`` 优先于 ``config/rss.conf``（兼容 GitHub Actions secret）。
"""

import sys
from pathlib import Path

# 允许直接 `python3 src/genBook.py` 运行，而不用先安装成包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from genbooks.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
