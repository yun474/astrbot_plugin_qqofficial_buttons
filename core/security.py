from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Any


def create_action_token(
    secret: str,
    preset_id: str,
    button_id: str,
    button: dict | None = None,
    *,
    user: str = "",
) -> str:
    data = {"p": preset_id, "b": button_id}
    if button is not None:
        specification = json.dumps(
            {"action": button["action"], "permission": button["permission"]},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data["v"] = hashlib.sha256(specification.encode()).hexdigest()[:16]
    if user:
        # 仅触发者按钮把触发者写进签名，换人点击或篡改都无法通过校验。
        data["u"] = str(user)
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    )
    digest = (
        base64.urlsafe_b64encode(signature.digest()[:16]).decode("ascii").rstrip("=")
    )
    return f"{encoded}.{digest}"


def _decode_action_token(secret: str, token: str) -> dict[str, Any] | None:
    if not isinstance(token, str) or len(token) > 512:
        return None
    try:
        encoded, supplied = token.strip().split(".", 1)
        signature = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        )
        expected = (
            base64.urlsafe_b64encode(signature.digest()[:16])
            .decode("ascii")
            .rstrip("=")
        )
        if not hmac.compare_digest(supplied, expected):
            return None
        padding = "=" * (-len(encoded) % 4)
        data: Any = json.loads(base64.urlsafe_b64decode(encoded + padding))
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
        return None


def parse_action_token(secret: str, token: str) -> tuple[str, str] | None:
    data = _decode_action_token(secret, token)
    if data is None:
        return None
    preset_id = str(data.get("p") or "")
    button_id = str(data.get("b") or "")
    if not preset_id or not button_id:
        return None
    return preset_id, button_id


def action_token_user(secret: str, token: str) -> str:
    """读取签名里绑定的触发者；未绑定或签名无效时返回空字符串。"""
    data = _decode_action_token(secret, token)
    return str(data.get("u") or "") if data else ""


def button_token_matches(secret: str, token: str, preset_id: str, button: dict) -> bool:
    """Old messages cannot inherit a newly configured action or permission."""
    expected = create_action_token(
        secret,
        preset_id,
        button["id"],
        button,
        user=action_token_user(secret, token),
    )
    return hmac.compare_digest(token, expected)
