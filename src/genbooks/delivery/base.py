"""投递渠道的公共抽象。

核心设计：**每个渠道必须自己报告成功或失败，但任何一个渠道失败都不
允许影响其它渠道，也不允许让整次运行前功尽弃**。

旧实现的问题正是这一点反过来了：任何一个渠道里抛异常（包括配置缺键
导致的 KeyError、``"str" + e`` 导致的 TypeError），整个 do_one_round
就崩了，后面所有渠道全部跳过、产物丢失、action 报红但看不出原因。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..config import ChannelConfig

log = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    channel: str
    ok: bool
    detail: str = ""

    def __str__(self) -> str:
        mark = "✓" if self.ok else "✗"
        return f"{mark} {self.channel}: {self.detail}"


class Channel(ABC):
    """一个投递渠道。"""

    #: 渠道名，用于日志与结果汇总
    name: str = "base"

    def __init__(self, config: ChannelConfig):
        self.config = config

    def wanted_files(self, files: dict[str, Path]) -> list[Path]:
        """按配置里选择的格式挑出要发送的文件。"""
        wanted = self.config.formats()
        return [files[fmt] for fmt in wanted if fmt in files]

    @abstractmethod
    def send(self, files: dict[str, Path]) -> str:
        """执行投递，成功返回说明文字；失败直接抛异常（由 send_all 兜底）。"""


def send_all(channels: list[Channel], files: dict[str, Path]) -> list[DeliveryResult]:
    """依次执行所有渠道，逐条收集结果，**永不抛出**。

    这是整个投递环节唯一的入口，保证隔离性。
    """
    results: list[DeliveryResult] = []
    for channel in channels:
        targets = channel.wanted_files(files)
        if not channel.config.enable:
            results.append(DeliveryResult(channel.name, True, "已禁用，跳过"))
            continue
        if not targets:
            results.append(DeliveryResult(channel.name, False, "已启用但没有可发送的文件"))
            log.warning("[%s] 已启用但没有可发送的文件", channel.name)
            continue

        try:
            detail = _run_with_timeout(channel, files)
            log.info("[%s] 发送成功：%s", channel.name, detail)
            results.append(DeliveryResult(channel.name, True, detail))
        except Exception as e:  # noqa: BLE001 - 这里就是要兜住一切
            log.exception("[%s] 发送失败", channel.name)
            results.append(DeliveryResult(channel.name, False, f"{type(e).__name__}: {e}"))
    return results


#: 单个渠道的最长等待时间。超时就判定该渠道失败、继续下一个，
#: 避免某个渠道卡住（例如 SMTP 服务器无响应）把整轮运行拖死。
CHANNEL_TIMEOUT = 600


def _run_with_timeout(channel: "Channel", files: dict[str, Path]) -> str:
    """在后台线程执行投递并限制总时长。"""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(channel.send, files)
        try:
            return future.result(timeout=CHANNEL_TIMEOUT)
        except FutureTimeout as e:
            raise TimeoutError(
                f"{channel.name} 超过 {CHANNEL_TIMEOUT}s 未完成，已放弃"
            ) from e
