from __future__ import annotations

import copy
import re
from html import escape
from typing import Any


class InteractionHttp:
    """Keep callback reply credentials local to this event's API instance."""

    def __init__(self, http: Any, path: str, event_id: str) -> None:
        self.http = http
        self.path = path
        self.event_id = event_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self.http, name)

    async def request(self, route: Any, **kwargs: Any) -> Any:
        path = route.path.format_map(route.parameters)
        if route.method == "POST" and path == self.path and "json" in kwargs:
            payload = dict(kwargs["json"])
            payload.pop("msg_id", None)
            payload["event_id"] = self.event_id
            kwargs["json"] = payload
        return await self.http.request(route, **kwargs)


class InteractionClient:
    def __init__(self, client: Any, api: Any) -> None:
        self.client = client
        self.api = api

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)


def build_interaction_event(platform: Any, interaction: Any, value: str = ""):
    """把一次按钮点击包装成 AstrBot 的 QQ 消息事件，回复会带上这次点击的 event_id。"""
    from botpy.message import C2CMessage, GroupMessage, Message

    from astrbot.api.message_components import At, Plain
    from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType
    from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import (
        QQOfficialMessageEvent,
    )
    from astrbot.core.platform.sources.qqofficial_webhook.qo_webhook_event import (
        QQOfficialWebhookMessageEvent,
    )

    resolved = interaction.data.resolved
    group = getattr(interaction, "group_openid", None)
    channel = getattr(interaction, "channel_id", None)
    user = (
        getattr(interaction, "group_member_openid", None)
        or getattr(interaction, "user_openid", None)
        or getattr(resolved, "user_id", None)
    )
    if not user or not (group or channel or getattr(interaction, "user_openid", None)):
        raise ValueError("回调缺少用户或会话信息，无法执行指令。")

    event_id = str(getattr(interaction, "event_id", None) or interaction.id)
    client = (
        platform.get_client() if hasattr(platform, "get_client") else platform.client
    )
    path = (
        f"/v2/groups/{group}/messages"
        if group
        else f"/channels/{channel}/messages"
        if channel
        else f"/v2/users/{user}/messages"
    )
    api = copy.copy(client.api)
    api._http = InteractionHttp(client.api._http, path, event_id)
    payload = {"id": str(interaction.id), "content": value}
    if group:
        raw = GroupMessage(
            api,
            event_id,
            payload
            | {
                "group_openid": group,
                "author": {"member_openid": user},
            },
        )
    elif channel:
        raw = Message(
            api,
            event_id,
            payload
            | {
                "channel_id": channel,
                "guild_id": getattr(interaction, "guild_id", None),
                "author": {"id": user},
            },
        )
    else:
        raw = C2CMessage(api, event_id, payload | {"author": {"user_openid": user}})

    message = AstrBotMessage()
    message.type = (
        MessageType.GROUP_MESSAGE if group or channel else MessageType.FRIEND_MESSAGE
    )
    message.self_id = "qq_official"
    message.group_id = str(group or channel or "")
    message.session_id = message.group_id or str(user)
    message.sender = MessageMember(user_id=str(user), nickname=str(user))
    message.message_id = str(interaction.id)
    message.raw_message = raw
    message.message_str = value
    message.message = [At(qq=message.self_id), Plain(value)]
    event_class = (
        QQOfficialWebhookMessageEvent
        if platform.meta().name == "qq_official_webhook"
        else QQOfficialMessageEvent
    )
    event = event_class(
        value,
        message,
        platform.meta(),
        message.session_id,
        InteractionClient(client, api),
    )
    return event


async def send_interaction_reply(
    platform: Any, interaction: Any, segments: list[str | None]
) -> None:
    """借 AstrBot 原生事件回复点击，与普通消息回复走同一条发送路径。

    segments 中的 None 表示艾特点击者；AstrBot 默认按 Markdown 发送，未开通 Markdown 时
    由框架自动回退为纯文本。艾特直接写成 QQ 的 Markdown 标签而不交给 At 组件转换：
    AstrBot 4.27～4.28 会丢弃 At，4.26 会转成群聊不识别的 <@id>。
    """
    from astrbot.api.event import MessageChain
    from astrbot.api.message_components import Plain

    event = build_interaction_event(platform, interaction)
    user = event.get_sender_id()
    chain: list[Any] = []
    for segment in segments:
        if segment is None:
            if user:
                chain.append(Plain(f'<qqbot-at-user id="{escape(user, quote=True)}" />'))
        elif segment:
            chain.append(Plain(segment))
    await event.send(MessageChain(chain))


# 直接调用按钮通过插件内部指令进入 AstrBot 流水线，按钮信息放在事件附加数据里。
LLM_COMMAND = "qqbtn_llm"
LLM_TASK_EXTRA = "qqofficial_button_llm_task"
# 勾选“回复时艾特点击者”时写入事件，发送前由插件的结果装饰钩子补上艾特。
LLM_MENTION_EXTRA = "qqofficial_button_llm_mention"
INTERNAL_COMMANDS = {"qqbtn_action", LLM_COMMAND}


def render_prompt(prompt: str, *, user: str = "") -> str:
    """替换提示词里的 {user} 占位符。"""
    return str(prompt or "").replace("{user}", str(user or "")).strip()


def _wake_prefixes(context: Any, event: Any) -> list[str]:
    return context.get_config(event.unified_msg_origin).get("wake_prefix", ["/"])


def build_llm_event(
    context: Any,
    platform: Any,
    interaction: Any,
    prompt: str,
    *,
    label: str,
    mention: bool,
):
    """把直接调用按钮包装成插件内部指令事件，交给 AstrBot 流水线处理。

    插件的内部指令收到后用 event.request_llm 带上当前对话发起请求，人格、对话记忆、
    其他插件的 LLM 钩子与回复设置都按 AstrBot 正常流程生效；提示词不会当作点击者的发言，
    也不受 LLM 唤醒前缀和其他插件的消息处理影响。
    """
    from astrbot.api.message_components import Plain

    if not prompt:
        raise ValueError("按钮没有填写提示词。")
    event = build_interaction_event(platform, interaction, "")
    prefixes = _wake_prefixes(context, event)
    text = (prefixes[0] if prefixes else "") + LLM_COMMAND
    message = event.message_obj
    event.message_str = message.message_str = message.raw_message.content = text
    message.message[-1] = Plain(text)
    # 回复由内部指令发起的请求负责，不再触发 AstrBot 的默认 LLM 请求。
    event.should_call_llm(True)
    event.set_extra("qqofficial_button_callback", True)
    event.set_extra(LLM_TASK_EXTRA, {"prompt": prompt, "label": label})
    if mention:
        event.set_extra(LLM_MENTION_EXTRA, True)
    return event


def build_command_event(context: Any, platform: Any, interaction: Any, value: str):
    """Create a normal QQ event; the pipeline retains all command permission checks."""
    from astrbot.api.message_components import Plain
    from astrbot.core.star.filter.command import CommandFilter
    from astrbot.core.star.filter.command_group import CommandGroupFilter
    from astrbot.core.star.star_handler import EventType, star_handlers_registry

    event = build_interaction_event(platform, interaction, value)
    message = event.message_obj
    raw = message.raw_message
    prefixes = _wake_prefixes(context, event)
    # Accept the session prefix, legacy /command, or a bare command name.
    command = value.strip()
    for prefix in sorted({"/", *prefixes} - {""}, key=len, reverse=True):
        if command.startswith(prefix):
            command = command[len(prefix) :].strip()
            break
    if not command or command.split()[0] in INTERNAL_COMMANDS:
        raise ValueError("请填写已注册的指令，不能调用插件内部动作。")
    normalized = re.sub(r"\s+", " ", command)
    registered = any(
        normalized == name
        or (
            isinstance(command_filter, CommandFilter)
            and normalized.startswith(name + " ")
        )
        for handler in star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent
        )
        for command_filter in handler.event_filters
        if isinstance(command_filter, (CommandFilter, CommandGroupFilter))
        for name in command_filter.get_complete_command_names()
    )
    if not registered:
        raise ValueError("回调指令不存在或已停用，请检查按钮中的指令。")

    text = (prefixes[0] if prefixes else "") + command
    event.message_str = message.message_str = raw.content = text
    message.message[-1] = Plain(text)
    # In AstrBot this flag suppresses the default LLM fallback, not explicit plugin calls.
    event.should_call_llm(True)
    event.set_extra("qqofficial_button_callback", True)
    return event
