"""send2boox 投递。

接口来源：send2boox.com 网页版「推送」功能，用账号 cookie 里的 token
调用其内部 API。这是非公开接口，随时可能变；因此这里的每一步都做显式
校验并给出可读的报错，而不是像旧实现那样用裸 ``except`` 静默返回 False
（用户只会看到"没收到书"，不知道哪一步挂了）。

旧实现的两个具体缺陷已修正：
  * ``fileName.split(".")[1]`` 在文件名有多个点时取到错误段、没有点时
    直接 IndexError —— 改用 os.path.splitext。
  * 全裸 except + 静默 return，失败无任何日志。
"""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path

import oss2
import requests

from .base import Channel

log = logging.getLogger(__name__)

TIMEOUT = 60
BASE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class BooxChannel(Channel):
    name = "boox"

    def __init__(self, config):
        super().__init__(config)
        self.token = config.extras.get("token", "")
        self.session = requests.Session()

    # ------------------------------------------------------ 内部工具

    @staticmethod
    def _rand_hex() -> str:
        return format(random.randint(0, 0xFFFF), "x")

    def _remote_key(self, filename: str, uid: str) -> str:
        """生成远端对象名，保留真实扩展名。"""
        _, ext = os.path.splitext(filename)
        if not ext:
            raise RuntimeError(f"文件名没有扩展名，无法判断类型：{filename}")
        stamp = "".join(self._rand_hex() for _ in range(8))
        return f"{uid}/push/{stamp}{ext}"

    def _headers(self, push: bool = False) -> dict:
        h = {
            "Host": "send2boox.com",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": BASE_UA,
            "Referer": "https://send2boox.com/",
            "Cookie": f"locale=zh-cn; token={self.token}; language=zh",
        }
        if push:
            h["Content-Type"] = "application/json;charset=UTF-8"
            h["Origin"] = "https://send2boox.com"
        return h

    def _get_json(self, url: str, push: bool = False) -> dict:
        resp = self.session.get(url, headers=self._headers(push), timeout=TIMEOUT)
        if resp.status_code == 401:
            raise RuntimeError("boox token 已失效，请重新从浏览器 cookie 中获取")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------ 主流程

    def _send_one(self, path: Path) -> None:
        me = self._get_json("https://send2boox.com/api/1/users/me")
        uid = me.get("data", {}).get("uid")
        if not uid:
            raise RuntimeError(f"获取 boox uid 失败：{me}")

        sts = self._get_json("https://send2boox.com/api/1/config/stss")
        sts_data = sts.get("data", {})
        if "AccessKeyId" not in sts_data:
            raise RuntimeError(f"获取 boox 临时凭证失败：{sts}")

        bucket_info = self._get_json("https://send2boox.com/api/1/push/bucket")
        bucket_name = bucket_info.get("data", {}).get("bucket")
        if not bucket_name:
            raise RuntimeError(f"获取 boox bucket 失败：{bucket_info}")

        key = self._remote_key(path.name, uid)
        auth = oss2.StsAuth(
            sts_data["AccessKeyId"],
            sts_data["AccessKeySecret"],
            sts_data["SecurityToken"],
            auth_version="AUTH_VERSION_1",
        )
        bucket = oss2.Bucket(
            auth, "http://oss-cn-shenzhen.aliyuncs.com", bucket_name, connect_timeout=TIMEOUT
        )
        bucket.put_object_from_file(key, str(path))
        log.info("已上传到临时存储：%s", key)

        _, ext = os.path.splitext(path.name)
        payload = {
            "data": {
                "name": path.name,
                "resourceDisplayName": path.name,
                "resourceKey": key,
                "bucket": "onyx-cloud",
                "resourceType": ext.lstrip(".").lower(),
                "title": path.stem,
                "parent": None,
            }
        }
        resp = self.session.post(
            "https://send2boox.com/api/1/push/saveAndPush",
            headers=self._headers(push=True),
            json=payload,
            timeout=TIMEOUT,
        )
        body = resp.json() if resp.content else {}
        if "SUCCESS" not in str(body.get("message", "")).upper():
            raise RuntimeError(f"boox 推送失败：{body}")

    def send(self, files: dict[str, Path]) -> str:
        sent = 0
        for path in self.wanted_files(files):
            self._send_one(path)
            sent += 1
        return f"已推送 {sent} 个文件到 Boox"
