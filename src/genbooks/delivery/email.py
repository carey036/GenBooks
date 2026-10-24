"""邮件投递（Kindle 等）。"""

from __future__ import annotations

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path

from .base import Channel

log = logging.getLogger(__name__)

SMTP_TIMEOUT = 60
# 常见邮箱的标准端口，用户漏填 port 时用来推断
_SSL_PORTS = {465, 994}
_STARTTLS_PORTS = {25, 587, 2525}


class EmailChannel(Channel):
    name = "email"

    def send(self, files: dict[str, Path]) -> str:
        cfg = self.config.extras
        sender = cfg["from"]
        to = cfg["to"]
        host = cfg["smtp"]
        port = int(cfg["port"])
        password = cfg["pwd"]
        use_ssl = bool(cfg.get("ssl", port in _SSL_PORTS))

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = to
        msg["Date"] = formatdate(localtime=True)
        msg["Subject"] = cfg.get("subject") or "RSS 订阅更新"

        text = cfg.get("text") or "由 GenBooks 自动推送。"
        msg.attach(MIMEText(text, "plain", "utf-8"))

        for path in self.wanted_files(files):
            with open(path, "rb") as f:
                part = MIMEApplication(f.read())
            part.add_header(
                "Content-Disposition", "attachment", filename=path.name
            )
            msg.attach(part)

        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT)
        else:
            server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)

        try:
            server.ehlo()
            if not use_ssl and cfg.get("starttls", port in _STARTTLS_PORTS):
                server.starttls()
                server.ehlo()
            server.login(sender, password)
            server.sendmail(sender, [to], msg.as_string())
        finally:
            try:
                server.quit()
            except smtplib.SMTPException:
                pass

        return f"已发送至 {to}"
