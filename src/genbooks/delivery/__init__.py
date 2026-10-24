"""投递渠道集合。"""

from __future__ import annotations

import logging

from ..config import Config
from .base import Channel, DeliveryResult, send_all
from .boox import BooxChannel
from .email import EmailChannel
from .github import GithubChannel
from .telegram import TelegramChannel
from .webdav import WebdavChannel

log = logging.getLogger(__name__)

_REGISTRY = {
    "email": EmailChannel,
    "webdav": WebdavChannel,
    "telegram": TelegramChannel,
    "boox": BooxChannel,
    "github": GithubChannel,
}


def build_channels(cfg: Config, skip: set[str] | None = None) -> list[Channel]:
    """根据配置构造所有渠道（含未启用的，由 send_all 统一判断跳过）。

    ``skip`` 用于禁用配置有问题的渠道，避免它们反复报错。
    """
    skip = skip or set()
    channels: list[Channel] = []
    for name, channel_cfg in cfg.channels().items():
        if name in skip:
            log.warning("[%s] 配置不完整，本次跳过", name)
            continue
        channels.append(_REGISTRY[name](channel_cfg))
    return channels


__all__ = [
    "Channel",
    "DeliveryResult",
    "send_all",
    "build_channels",
    "EmailChannel",
    "WebdavChannel",
    "TelegramChannel",
    "BooxChannel",
    "GithubChannel",
]
