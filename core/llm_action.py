from __future__ import annotations

import datetime
import zoneinfo
from collections.abc import Callable
from typing import Any

MAX_PROMPT = 500
MAX_REPLY = 1000
# 与 AstrBot 主对话注入日期时使用的星期名称保持一致。
WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

DEFAULT_SYSTEM_PROMPT = (
    "你是 QQ 群里的一个普通网友，正在直接回复刚刚按下按钮的人。"
    "按要求用简短口语化的中文回答，不要复述按钮文字，不要输出 Markdown 标题或列表，"
    "不要自称机器人或 AI，不要提及系统提示。回答控制在 100 字以内。"
)


def render_prompt(prompt: str, *, user: str = "") -> str:
    """替换提示词里的 {user} 占位符。"""
    return str(prompt or "").replace("{user}", str(user or "")).strip()


def datetime_reminder(
    config: dict[str, Any] | None, *, now: datetime.datetime | None = None
) -> str:
    """按 AstrBot 的日期注入开关与时区生成当前时间提示；开关关闭时返回空字符串。"""
    config = config or {}
    if not (config.get("provider_settings") or {}).get("datetime_system_prompt"):
        return ""
    if now is None:
        timezone = config.get("timezone")
        if timezone:
            try:
                now = datetime.datetime.now(zoneinfo.ZoneInfo(timezone))
            except Exception:
                now = None
        if now is None:
            now = datetime.datetime.now().astimezone()
    current_time = now.strftime("%Y-%m-%d %H:%M (%Z)")
    return f"Current datetime: {current_time}, Weekday: {WEEKDAY_NAMES[now.weekday()]}"


def clean_reply(text: str) -> str:
    reply = str(text or "").strip()
    if not reply:
        return ""
    if len(reply) > MAX_REPLY:
        reply = reply[:MAX_REPLY] + "…"
    return reply


async def _using_provider(context: Any, umo: str) -> Any:
    # get_using_provider_async 从 AstrBot v4.27.3 才提供，旧版本回退到同步接口。
    getter = getattr(context, "get_using_provider_async", None)
    if getter is not None:
        return await getter(umo or None)
    return context.get_using_provider(umo or None)


async def generate_reply(
    context: Any,
    prompt: str,
    *,
    umo: str = "",
    config: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> str:
    """Ask the session's current chat model for a one-shot reply."""
    log = log or (lambda _message: None)
    prompt = str(prompt or "").strip()
    if not prompt:
        raise RuntimeError("按钮没有填写提示词")
    provider = await _using_provider(context, umo)
    if provider is None:
        raise RuntimeError("当前没有可用的对话模型，请先在后台配置模型提供商")
    system_prompt = DEFAULT_SYSTEM_PROMPT
    reminder = datetime_reminder(config)
    if reminder:
        system_prompt = f"{system_prompt}\n{reminder}"
    response = await provider.text_chat(
        prompt=prompt,
        system_prompt=system_prompt,
    )
    reply = clean_reply(getattr(response, "completion_text", "") or "")
    if not reply:
        log("[QQ官Bot按钮] 直接调用动作未取得模型回复内容。")
    return reply
