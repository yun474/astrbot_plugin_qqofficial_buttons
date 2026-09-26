from __future__ import annotations

import copy
import re
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


def build_command_event(context: Any, platform: Any, interaction: Any, value: str):
    """Create a normal QQ event; the pipeline retains all command permission checks."""
    from botpy.message import C2CMessage, GroupMessage, Message

    from astrbot.api.message_components import At, Plain
    from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType
    from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import (
        QQOfficialMessageEvent,
    )
    from astrbot.core.platform.sources.qqofficial_webhook.qo_webhook_event import (
        QQOfficialWebhookMessageEvent,
    )
    from astrbot.core.star.filter.command import CommandFilter
    from astrbot.core.star.filter.command_group import CommandGroupFilter
    from astrbot.core.star.star_handler import EventType, star_handlers_registry

    command = value[1:].strip()
    normalized = re.sub(r"\s+", " ", command)
    registered = any(
        normalized == name
        or (isinstance(command_filter, CommandFilter) and normalized.startswith(name + " "))
        for handler in star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent
        )
        for command_filter in handler.event_filters
        if isinstance(command_filter, (CommandFilter, CommandGroupFilter))
        for name in command_filter.get_complete_command_names()
    )
    if not registered:
        raise ValueError("回调指令不存在或已停用，请检查按钮中的指令。")

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
    # Use the session's configured wake prefix, while the editor always accepts /command.
    config = context.get_config(event.unified_msg_origin)
    prefixes = config.get("wake_prefix", ["/"])
    text = (prefixes[0] if prefixes else "") + command
    event.message_str = message.message_str = raw.content = text
    message.message[-1] = Plain(text)
    # In AstrBot this flag suppresses the default LLM fallback, not explicit plugin calls.
    event.should_call_llm(True)
    event.set_extra("qqofficial_button_callback", True)
    return event
