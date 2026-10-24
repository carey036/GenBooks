"""配置归一化。

设计目标：**配置文件里少写任何段落都不应该让程序崩溃**，也不应该让
某个渠道的配置错误牵连到其它渠道。所有可选段落在这里统一定义默认值，
业务代码只读归一化之后的结构，永远不需要写 ``config["xxx"]["yyy"]``。

同时保留旧的配置格式（``rss.conf`` / secret ``CONFIG``）完全兼容，
老用户不需要改任何东西。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """配置本身不可用（无法解析 / 缺少必需字段）。"""


# ---------------------------------------------------------------- 数据结构


@dataclass
class FeedConfig:
    name: str
    url: str
    saveimg: bool = False
    imgquality: int = 100
    css: str = ""


@dataclass
class ChannelConfig:
    """一个投递渠道的开关与参数。

    ``enable`` 为 False 时整个渠道跳过；``epub``/``mobi`` 决定推送哪些格式。
    每个渠道的 extras 存放各自需要的凭据等字段。
    """

    enable: bool = False
    epub: bool = False
    mobi: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def formats(self) -> list[str]:
        out = []
        if self.epub:
            out.append("epub")
        if self.mobi:
            out.append("mobi")
        return out


@dataclass
class Config:
    title: str
    feeds: list[FeedConfig]
    email: ChannelConfig
    webdav: ChannelConfig
    telegram: ChannelConfig
    boox: ChannelConfig
    github: ChannelConfig
    lookback_hours: int | None = None
    css: str = ""

    def channels(self) -> dict[str, ChannelConfig]:
        return {
            "email": self.email,
            "webdav": self.webdav,
            "telegram": self.telegram,
            "boox": self.boox,
            "github": self.github,
        }


# ---------------------------------------------------------------- 解析工具

# 每个渠道的默认开关：与 README 的示例保持一致
_CHANNEL_DEFAULTS = {
    "email": {"enable": False, "epub": False, "mobi": True},
    "webdav": {"enable": False, "epub": False, "mobi": True},
    "telegram": {"enable": False, "epub": True, "mobi": True},
    "boox": {"enable": False, "epub": False, "mobi": True},
    "github": {"enable": False, "epub": False, "mobi": False},
}

# 渠道需要的必填字段（仅在该渠道 enable 时才校验）
_CHANNEL_REQUIRED = {
    "email": ("to", "from", "smtp", "port", "pwd"),
    "webdav": ("server", "user", "pwd"),
    "telegram": ("token", "chat_id"),
    "boox": ("token",),
    "github": (),
}

_TRUE = {"true", "1", "yes", "on", "y", "t"}


def _as_bool(value: Any, default: bool = False) -> bool:
    """把各种写法（True/False/"true"/"false"/1/0）统一成 bool。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_channel(name: str, raw: Any) -> ChannelConfig:
    """解析一个渠道段落。raw 缺失 / 为 None / 不是 dict 时全部走默认值。"""
    defaults = _CHANNEL_DEFAULTS[name]
    if not isinstance(raw, dict):
        raw = {}

    extras = {k: v for k, v in raw.items() if k not in ("enable", "epub", "mobi")}
    return ChannelConfig(
        enable=_as_bool(raw.get("enable"), defaults["enable"]),
        epub=_as_bool(raw.get("epub"), defaults["epub"]),
        mobi=_as_bool(raw.get("mobi"), defaults["mobi"]),
        extras=extras,
    )


def _parse_feed(raw: dict) -> FeedConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"feeds 中的条目必须是对象，实际是 {type(raw).__name__}")
    url = raw.get("url")
    if not url:
        raise ConfigError(f"feeds 条目缺少 url：{raw!r}")
    return FeedConfig(
        name=str(raw.get("name") or url),
        url=str(url),
        saveimg=_as_bool(raw.get("saveimg"), False),
        imgquality=max(0, min(100, _as_int(raw.get("imgquality"), 100))),
        css=str(raw.get("css") or ""),
    )


# 旧版配置里这些段落的名称与新名字的对应关系，用于向后兼容
_LEGACY_ALIASES = {
    "emailinfo": "email",
}


def _get_channel_raw(raw: dict, name: str) -> Any:
    """取渠道原始配置，兼容旧版字段名（enabled 优先于旧名）。"""
    if name in raw:
        return raw[name]
    for legacy, new in _LEGACY_ALIASES.items():
        if new == name and legacy in raw:
            log.info("检测到旧版配置字段 %r，已按 %r 处理", legacy, name)
            return raw[legacy]
    return None


def parse(raw: dict | str) -> Config:
    """把原始配置（dict 或 JSON 字符串）解析成强类型 Config。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ConfigError(f"配置不是合法 JSON：{e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("配置根节点必须是 JSON 对象")

    feeds_raw = raw.get("feeds")
    if not feeds_raw:
        raise ConfigError("配置缺少 feeds（至少要订阅一个 RSS 源）")
    if not isinstance(feeds_raw, list):
        raise ConfigError("feeds 必须是数组")

    feeds = [_parse_feed(f) for f in feeds_raw]

    channels = {
        name: _parse_channel(name, _get_channel_raw(raw, name))
        for name in _CHANNEL_DEFAULTS
    }

    title = str(raw.get("title") or "RSS Daily")

    # 回溯时长：兼容旧版 time.txt 的两种语义
    lookback = raw.get("lookback_hours")
    lookback_hours = _as_int(lookback, -1) if lookback is not None else None
    if lookback_hours is not None and lookback_hours <= 0:
        lookback_hours = None

    return Config(
        title=title,
        feeds=feeds,
        email=channels["email"],
        webdav=channels["webdav"],
        telegram=channels["telegram"],
        boox=channels["boox"],
        github=channels["github"],
        lookback_hours=lookback_hours,
        css=str(raw.get("css") or ""),
    )


def validate_channels(cfg: Config) -> list[str]:
    """校验已启用的渠道是否填全了必填项。

    返回「问题描述」列表。**不抛异常、不阻断其它渠道** —— 调用方负责
    把有问题的渠道单独禁用，其它渠道继续工作。
    """
    problems: list[str] = []
    for name, channel in cfg.channels().items():
        if not channel.enable:
            continue
        if not channel.formats():
            problems.append(f"{name}: 已启用但没有选择任何格式（epub/mobi 都为 false）")
            continue
        for key in _CHANNEL_REQUIRED[name]:
            value = channel.extras.get(key)
            if value in (None, "", 0):
                problems.append(f"{name}: 缺少必填字段 {key!r}")
    return problems


def load(path: str = "./config/rss.conf", env_var: str = "config") -> Config:
    """按「环境变量优先、配置文件兜底」的顺序加载配置。

    环境变量是为了兼容 GitHub Actions 的 secret 用法。
    """
    raw_text = os.environ.get(env_var)
    source = f"环境变量 {env_var}"
    if raw_text:
        log.info("从环境变量读取配置")
    else:
        log.info("环境变量为空，回退到配置文件 %s", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_text = f.read()
        except FileNotFoundError as e:
            raise ConfigError(f"找不到配置文件 {path}，且环境变量 {env_var} 未设置") from e
        source = path

    try:
        return parse(raw_text)
    except ConfigError as e:
        raise ConfigError(f"配置解析失败（来源：{source}）：{e}") from e
