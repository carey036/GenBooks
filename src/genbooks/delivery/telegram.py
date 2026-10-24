"""Telegram Bot 投递。"""

from __future__ import annotations

from pathlib import Path

import requests

from .base import Channel

TG_TIMEOUT = 300  # 上传文件可能较慢
TG_MAX_BYTES = 50 * 1024 * 1024  # Bot API 上传上限


class TelegramChannel(Channel):
    name = "telegram"

    def send(self, files: dict[str, Path]) -> str:
        cfg = self.config.extras
        token = cfg["token"]
        chat_id = cfg["chat_id"]
        api = cfg.get("api_base") or "https://api.telegram.org"

        sent = 0
        for path in self.wanted_files(files):
            size = path.stat().st_size
            if size > TG_MAX_BYTES:
                raise RuntimeError(
                    f"{path.name} 有 {size / 1024 / 1024:.1f}MB，超过 Telegram 50MB 上限"
                )
            with open(path, "rb") as f:
                resp = requests.post(
                    f"{api}/bot{token}/sendDocument",
                    data={"chat_id": chat_id},
                    files={"document": (path.name, f)},
                    timeout=TG_TIMEOUT,
                )
            payload = resp.json() if resp.content else {}
            if not payload.get("ok"):
                raise RuntimeError(
                    f"发送 {path.name} 失败：{payload.get('description', resp.status_code)}"
                )
            sent += 1
        return f"已发送 {sent} 个文件到 {chat_id}"
