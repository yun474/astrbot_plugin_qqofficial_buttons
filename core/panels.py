"""QQ 官方指令面板接口：输入 / 唤起的指令列表，按场景和生效对象配置。

面板数据以 QQ 服务器为准，插件本地不保存副本。
"""

from __future__ import annotations

from typing import Any

SCOPES = ("c2c", "group", "channel", "dm")
# 只有单聊和群聊能指定生效对象，频道和频道私信只能对所有人生效。
TARGET_FIELDS = {"c2c": "user_openids", "group": "group_openids"}
ITEM_TYPES = ("command", "link")

MAX_PANELS = 20
MAX_ITEMS = 20
NAME_WIDTH = 14
DESC_WIDTH = 30
REMARK_WIDTH = 255
LINK_LENGTH = 1000
# 创建和修改关联对象时一次最多传 20 个，详情接口最多返回 1000 个。
TARGET_BATCH = 20
MAX_TARGETS = 1000
TARGET_ID_LENGTH = 128
LIST_LIMIT = 50
MAX_LIST_PAGES = 5

# 官方 2026-08-10 起统一使用 api.bot.qq.com。
PANEL_DOMAIN = "api.bot.qq.com"

# botpy 只把 QQ 返回的 message 放进异常；消息里带错误码时补一句中文提示。
ERROR_HINTS = {
    "40030006": "面板不存在，可能已被删除，请刷新列表",
    "40030008": "链接格式不对，需要以 https:// 开头",
    "40030009": "QQ 那边还在处理上一次操作，稍等几秒再试",
    "40030011": "生效场景不合法",
    "40030012": "频道和频道私信只能对所有人生效",
    "40030013": "超出 QQ 的数量限制",
    "40030015": "指令类型不合法",
    "40030016": "缺少必填内容",
    "40030018": "当前场景不支持这个操作",
    "40030020": "内容被 QQ 判定有安全风险，换个说法试试",
    "40030021": "对所有人生效的面板不能指定对象",
}


class PanelError(RuntimeError):
    """指令面板操作失败，信息可直接展示给后台用户。"""


def text_width(text: str) -> int:
    """按 QQ 的规则计算长度：ASCII 字符算 1，汉字等其他字符算 2。"""
    return sum(1 if ord(char) < 128 else 2 for char in text)


def explain_error(exc: Exception) -> str:
    message = str(exc) or type(exc).__name__
    for code, hint in ERROR_HINTS.items():
        if code in message:
            return f"{hint}（QQ 返回：{message}）"
    return f"QQ 返回：{message}"


def _text(value: Any, label: str, limit: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise PanelError(f"{label}不能为空")
    if text_width(text) > limit:
        raise PanelError(
            f"{label}「{text}」太长了，最多 {limit // 2} 个汉字或 {limit} 个英文字符"
        )
    return text


def normalize_item(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PanelError(f"第 {index} 条指令格式不对")
    item_type = str(raw.get("type") or "command")
    if item_type not in ITEM_TYPES:
        raise PanelError(f"第 {index} 条指令的类型不支持")
    label = f"第 {index} 条的指令" if item_type == "command" else f"第 {index} 条的名称"
    item: dict[str, Any] = {
        # QQ 要求每条都带 type，缺了会把整个面板退回。
        "type": item_type,
        "name": _text(raw.get("name"), label, NAME_WIDTH, required=True),
        "only_admin": bool(raw.get("only_admin", False)),
    }
    desc = _text(raw.get("desc"), f"第 {index} 条的说明", DESC_WIDTH)
    if desc:
        item["desc"] = desc
    if item_type == "link":
        link = str(raw.get("link") or "").strip()
        if not link.startswith("https://") or len(link) > LINK_LENGTH:
            raise PanelError(f"第 {index} 条的链接需要以 https:// 开头")
        item["link"] = link
    return item


def normalize_targets(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    targets = list(dict.fromkeys(str(value).strip() for value in raw))
    targets = [value for value in targets if value]
    if len(targets) > MAX_TARGETS:
        raise PanelError(f"指定对象最多 {MAX_TARGETS} 个")
    for value in targets:
        if len(value) > TARGET_ID_LENGTH or any(char.isspace() for char in value):
            raise PanelError(f"对象 ID「{value[:40]}」格式不对")
    return targets


def normalize_panel(payload: dict[str, Any]) -> dict[str, Any]:
    """校验页面提交的面板，返回 scope、target_type、targets 和发给 QQ 的 panel。"""
    scope = str(payload.get("scope") or "")
    if scope not in SCOPES:
        raise PanelError("请选择生效场景")
    target_type = str(payload.get("target_type") or "all")
    if target_type not in ("all", "specific"):
        raise PanelError("生效范围只能是所有人或指定对象")
    if target_type == "specific" and scope not in TARGET_FIELDS:
        raise PanelError("频道和频道私信只能对所有人生效")
    targets = normalize_targets(payload.get("targets"))
    if target_type == "specific" and not targets:
        raise PanelError("指定对象至少添加一个")
    if target_type == "all":
        targets = []

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise PanelError("面板里至少要有一条指令")
    if len(raw_items) > MAX_ITEMS:
        raise PanelError(f"一个面板最多 {MAX_ITEMS} 条指令")
    items = [normalize_item(raw, index) for index, raw in enumerate(raw_items, 1)]
    names = [item["name"] for item in items]
    duplicated = next((name for name in names if names.count(name) > 1), None)
    if duplicated:
        raise PanelError(f"指令「{duplicated}」重复了")

    remark = _text(payload.get("remark"), "备注", REMARK_WIDTH)
    return {
        "scope": scope,
        "target_type": target_type,
        "targets": targets,
        "panel": {"items": items, "remark": remark},
    }


def _route(method: str, path: str, **parameters: Any) -> Any:
    from botpy.http import Route

    class PanelRoute(Route):
        DOMAIN = PANEL_DOMAIN

    return PanelRoute(method, path, **parameters)


async def _request(http: Any, method: str, path: str, **kwargs: Any) -> Any:
    from botpy.errors import HttpErrorDict

    parameters = kwargs.pop("parameters", {})
    try:
        result = await http.request(_route(method, path, **parameters), **kwargs)
    except tuple(set(HttpErrorDict.values())) as exc:
        raise PanelError(explain_error(exc)) from exc
    # botpy 连续超时会返回 None；删除成功时 QQ 也可能不带包体。
    if result is None and method != "DELETE":
        raise PanelError("QQ 指令面板接口没有返回结果，可能是请求超时，请刷新后确认再操作")
    return result


async def list_panels(http: Any, scope: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(MAX_LIST_PAGES):
        params = {"scope": scope, "limit": str(LIST_LIMIT)}
        if cursor:
            params["cursor"] = cursor
        page = await _request(http, "GET", "/v2/panels", params=params)
        for record in page.get("records") or []:
            if isinstance(record, dict):
                record.setdefault("scope", scope)
                records.append(record)
        cursor = str(page.get("next_cursor") or "")
        if page.get("is_end", True) or not cursor:
            break
    return records


async def get_panel(http: Any, panel_id: str) -> dict[str, Any]:
    result = await _request(
        http, "GET", "/v2/panels/{panel_id}", parameters={"panel_id": panel_id}
    )
    if not isinstance(result, dict):
        raise PanelError("QQ 返回的面板详情格式不对")
    return result


async def _change_targets(
    http: Any, panel_id: str, field: str, op: str, targets: list[str]
) -> None:
    for start in range(0, len(targets), TARGET_BATCH):
        await _request(
            http,
            "PUT",
            "/v2/panels/{panel_id}/target",
            parameters={"panel_id": panel_id},
            json={"op": op, field: targets[start : start + TARGET_BATCH]},
        )


async def create_panel(http: Any, data: dict[str, Any]) -> tuple[str, str]:
    """创建面板，返回面板 ID 和提醒。

    指定对象超过 20 个时先带前 20 个创建，剩下的分批追加；追加失败时面板已经存在，
    返回提醒而不是报错，避免页面当成没创建而重复新建。
    """
    scope = data["scope"]
    targets = data["targets"]
    body: dict[str, Any] = {
        "scope": scope,
        "target_type": data["target_type"],
        "panel": data["panel"],
    }
    field = TARGET_FIELDS.get(scope, "")
    if data["target_type"] == "specific":
        body[field] = targets[:TARGET_BATCH]
    result = await _request(http, "POST", "/v2/panels", json=body)
    panel_id = str(result.get("panel_id") or "") if isinstance(result, dict) else ""
    if not panel_id:
        raise PanelError("QQ 没有返回面板 ID，请刷新列表确认是否已创建")
    try:
        await _change_targets(http, panel_id, field, "add", targets[TARGET_BATCH:])
    except PanelError as exc:
        return panel_id, f"面板已创建，但部分指定对象没加上：{exc}"
    return panel_id, ""


async def update_panel(
    http: Any, panel_id: str, data: dict[str, Any], current: dict[str, Any]
) -> str:
    """覆盖面板内容，再按差异增删指定对象，返回提醒；场景和生效范围创建后不能修改。"""
    await _request(
        http,
        "PUT",
        "/v2/panels/{panel_id}",
        parameters={"panel_id": panel_id},
        json={"panel": data["panel"]},
    )
    if data["target_type"] != "specific":
        return ""
    field = TARGET_FIELDS[data["scope"]]
    existing = [str(value) for value in current.get(field) or []]
    wanted = data["targets"]
    existing_set, wanted_set = set(existing), set(wanted)
    added = [value for value in wanted if value not in existing_set]
    removed = [value for value in existing if value not in wanted_set]
    try:
        await _change_targets(http, panel_id, field, "del", removed)
        await _change_targets(http, panel_id, field, "add", added)
    except PanelError as exc:
        return f"指令已保存，但指定对象没改完：{exc}"
    return ""


async def delete_panel(http: Any, panel_id: str) -> None:
    await _request(
        http, "DELETE", "/v2/panels/{panel_id}", parameters={"panel_id": panel_id}
    )
