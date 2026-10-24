"""放到 GitHub 仓库（用 git 命令推送到当前仓库）。

相比旧实现：旧代码在 genBook.py 里对 ``os.remove(epubFile)`` 做了一堆
"删除还是保留"的分支判断，还依赖 workflow 里 ``git add . && git commit``
一步完成。这里把「哪些文件要进仓库」这件事交给 workflow，本模块只负责
告诉调用方哪些文件应当保留。
"""

from __future__ import annotations

from pathlib import Path

from .base import Channel


class GithubChannel(Channel):
    name = "github"

    def send(self, files: dict[str, Path]) -> str:
        # 不需要真正"上传"：workflow 里的 git add/commit/push 会带上留在
        # 工作区的文件。这里只做一次存在性确认。
        kept = self.wanted_files(files)
        missing = [p.name for p in kept if not p.exists()]
        if missing:
            raise RuntimeError(f"文件不存在：{', '.join(missing)}")
        return f"保留 {len(kept)} 个文件交给 workflow 提交"
