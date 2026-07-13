from __future__ import annotations

from collections import defaultdict
from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from .models import ButtonValidationError, new_id, normalize_preset


class QQOfficialButtonsTool(FunctionTool[AstrAgentContext]):
    def __init__(self, plugin: Any) -> None:
        super().__init__(
            name="send_qq_official_buttons",
            description=(
                "Send an interactive button menu in the current QQ Official Bot conversation. "
                "Prefer an exposed preset_id. Only use dynamic buttons when the user explicitly "
                "needs choices and the plugin permits dynamic mode. Never invent administrator commands."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "preset_id": {
                        "type": "string",
                        "description": "ID of a WebUI preset exposed to the LLM.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Optional message text. For presets this overrides its text for this send only.",
                    },
                    "buttons": {
                        "type": "array",
                        "description": "Optional dynamic buttons. Disabled by default in plugin config.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "row": {"type": "integer", "minimum": 1, "maximum": 5},
                                "label": {"type": "string"},
                                "action_type": {
                                    "type": "string",
                                    "enum": ["command", "input", "link"],
                                },
                                "value": {"type": "string"},
                            },
                            "required": ["row", "label", "action_type", "value"],
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
        )
        self.plugin = plugin

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs: Any
    ) -> ToolExecResult:
        event = context.context.event
        preset_id = str(kwargs.get("preset_id") or "").strip()
        content_override = str(kwargs.get("content") or "").strip()
        if preset_id:
            preset = self.plugin.storage.get(preset_id)
            if not preset or not preset["enabled"] or not preset["expose_to_llm"]:
                available = ", ".join(
                    f"{item['id']} ({item['name']})"
                    for item in self.plugin.storage.list(exposed_only=True)
                )
                return f"error: preset is unavailable. Exposed presets: {available or 'none'}"
        else:
            if not self.plugin.enable_dynamic_buttons:
                available = ", ".join(
                    f"{item['id']} ({item['name']})"
                    for item in self.plugin.storage.list(exposed_only=True)
                )
                return f"error: dynamic buttons are disabled. Use a preset: {available or 'none'}"
            raw_buttons = kwargs.get("buttons")
            if not isinstance(raw_buttons, list) or not raw_buttons:
                return "error: provide preset_id or a non-empty buttons array."
            grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for item in raw_buttons:
                if not isinstance(item, dict):
                    return "error: each dynamic button must be an object."
                try:
                    row = int(item.get("row", 1))
                except (TypeError, ValueError):
                    return "error: dynamic button row must be an integer."
                grouped[row].append(
                    {
                        "id": new_id("llm"),
                        "label": item.get("label"),
                        "style": 0,
                        "action": {
                            "type": item.get("action_type"),
                            "value": item.get("value"),
                        },
                        "permission": {"type": 2},
                    }
                )
            raw_preset = {
                "id": new_id("llm_menu"),
                "name": "LLM 临时按钮",
                "content": content_override or "请选择：",
                "enabled": True,
                "expose_to_llm": False,
                "rows": [grouped[key] for key in sorted(grouped)],
            }
            try:
                preset = normalize_preset(
                    raw_preset,
                    max_rows=self.plugin.max_rows,
                    max_per_row=self.plugin.max_per_row,
                    allow_http_links=self.plugin.allow_http_links,
                    allow_functions=False,
                )
            except ButtonValidationError as exc:
                return f"error: invalid dynamic buttons: {exc}"
        if content_override:
            preset["content"] = content_override[:2000]
        try:
            scene = await self.plugin.sender.send(event, preset)
        except Exception as exc:
            return f"error: failed to send QQ buttons: {exc}"
        return f"Buttons sent successfully in the current {scene}. Do not repeat the choices as text."
