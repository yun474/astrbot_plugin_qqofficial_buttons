from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


def create_action_token(secret: str, preset_id: str, button_id: str) -> str:
    payload = json.dumps(
        {"p": preset_id, "b": button_id},
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


def parse_action_token(secret: str, token: str) -> tuple[str, str] | None:
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
        preset_id = str(data.get("p") or "")
        button_id = str(data.get("b") or "")
        if not preset_id or not button_id:
            return None
        return preset_id, button_id
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
