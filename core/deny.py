"""插件侧拒绝点击时的回复：每个按钮可配置多条拒绝语，随机挑一条，留空则静默拒绝。"""

from __future__ import annotations

import random
import time
from typing import Any

# 旧版插件被拒时固定回复这句，没配置过拒绝语的按钮继续沿用。
DEFAULT_DENY_REPLY = "这个按钮没给你操作权限，别乱戳啦。"
MAX_DENY_REPLIES = 20
MAX_DENY_LENGTH = 500


def pick_deny_reply(button: dict[str, Any]) -> str:
    replies = button.get("deny_replies")
    if replies is None:
        return DEFAULT_DENY_REPLY
    return random.choice(replies) if replies else ""


def render_deny_reply(sender: Any, reply: str, raw: Any) -> str:
    """把 {{at}} 换成艾特点击者；读不到用户时去掉占位符，不让拒绝语发不出去。"""
    try:
        return sender.render_user_mention(reply, raw)
    except RuntimeError:
        return reply.replace("{{at}}", "").strip()


class DenyCooldown:
    """同一个人在同一会话里被拒后，冷却期内再被拒只静默，防止狂戳刷屏。"""

    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        self._hits: dict[str, float] = {}

    def cooling(self, key: str) -> bool:
        if self.seconds <= 0:
            return False
        now = time.monotonic()
        self._hits = {
            item: when for item, when in self._hits.items() if now - when < self.seconds
        }
        if key in self._hits:
            return True
        self._hits[key] = now
        return False
