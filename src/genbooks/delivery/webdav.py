"""WebDAV 投递（坚果云等）。"""

from __future__ import annotations

from pathlib import Path

import requests

from .base import Channel

WEBDAV_TIMEOUT = 120  # 上传大文件需要时间


class WebdavChannel(Channel):
    name = "webdav"

    def send(self, files: dict[str, Path]) -> str:
        cfg = self.config.extras
        server = cfg["server"]
        if not server.endswith("/"):
            server += "/"

        auth = (cfg["user"], cfg["pwd"])
        sent = 0
        for path in self.wanted_files(files):
            url = server + path.name
            with open(path, "rb") as f:
                resp = requests.put(
                    url,
                    data=f,
                    auth=auth,
                    timeout=WEBDAV_TIMEOUT,
                    headers={"Content-Type": "application/octet-stream"},
                )
            # WebDAV 成功通常是 200/201/204
            if resp.status_code not in (200, 201, 204):
                raise RuntimeError(
                    f"上传 {path.name} 失败：HTTP {resp.status_code} {resp.text[:200]}"
                )
            sent += 1
        return f"已上传 {sent} 个文件"
