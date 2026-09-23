from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from .models import ButtonValidationError, clone_preset, default_preset, normalize_preset


class ButtonStorage:
    """Small atomic JSON store used by chat commands and the plugin page."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_rows: int = 5,
        max_per_row: int = 5,
        allow_http_links: bool = False,
        allow_functions: bool = True,
    ) -> None:
        self.path = Path(path)
        self.max_rows = max_rows
        self.max_per_row = max_per_row
        self.allow_http_links = allow_http_links
        self.allow_functions = allow_functions
        self._lock = asyncio.Lock()
        self._data = self._load()

    def _empty_data(self) -> dict[str, Any]:
        return {
            "version": 1,
            "signing_secret": secrets.token_urlsafe(32),
            "presets": [self._starter_preset()],
        }

    def _starter_preset(self) -> dict[str, Any]:
        preset = default_preset()
        if not self.allow_functions:
            hello = preset["rows"][1][0]
            hello["action"] = {"type": "input", "value": "你好，云云"}
        return self.validate(preset)

    def _load(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            data = self._empty_data()
            self._write(data)
            return data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            backup = self.path.with_suffix(".broken.json")
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            data = self._empty_data()
            self._write(data)
            return data
        presets = []
        for item in raw.get("presets", []):
            try:
                presets.append(self.validate(item))
            except ValueError:
                continue
        return {
            "version": 1,
            "signing_secret": str(
                raw.get("signing_secret") or secrets.token_urlsafe(32)
            ),
            "presets": presets or [self._starter_preset()],
        }

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def validate(self, preset: Any) -> dict[str, Any]:
        return normalize_preset(
            preset,
            max_rows=self.max_rows,
            max_per_row=self.max_per_row,
            allow_http_links=self.allow_http_links,
            allow_functions=self.allow_functions,
        )

    @property
    def signing_secret(self) -> str:
        return self._data["signing_secret"]

    def list(self, *, exposed_only: bool = False) -> list[dict[str, Any]]:
        presets = self._data["presets"]
        if exposed_only:
            presets = [p for p in presets if p["enabled"] and p["expose_to_llm"]]
        return json.loads(json.dumps(presets, ensure_ascii=False))

    def get(self, preset_id: str) -> dict[str, Any] | None:
        for preset in self._data["presets"]:
            if preset["id"] == preset_id:
                return json.loads(json.dumps(preset, ensure_ascii=False))
        return None

    async def save(self, raw: Any) -> dict[str, Any]:
        preset = self.validate(raw)
        async with self._lock:
            used = {
                trigger
                for current in self._data["presets"]
                if current["id"] != preset["id"]
                for trigger in current.get("triggers", [])
            }
            overlap = used.intersection(preset["triggers"])
            if overlap:
                raise ButtonValidationError(f"自定义指令已被其他菜单使用：{sorted(overlap)[0]}")
            for index, current in enumerate(self._data["presets"]):
                if current["id"] == preset["id"]:
                    self._data["presets"][index] = preset
                    break
            else:
                self._data["presets"].append(preset)
            self._write(self._data)
        return self.get(preset["id"]) or preset

    async def delete(self, preset_id: str) -> bool:
        async with self._lock:
            before = len(self._data["presets"])
            self._data["presets"] = [
                p for p in self._data["presets"] if p["id"] != preset_id
            ]
            changed = len(self._data["presets"]) != before
            if changed:
                self._write(self._data)
            return changed

    async def duplicate(self, preset_id: str) -> dict[str, Any] | None:
        source = self.get(preset_id)
        if source is None:
            return None
        return await self.save(clone_preset(source))

    async def replace_all(self, raw_presets: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_presets, list) or not raw_presets:
            raise ValueError("导入数据至少需要一个按钮组")
        presets = [self.validate(item) for item in raw_presets]
        ids = [item["id"] for item in presets]
        if len(ids) != len(set(ids)):
            raise ValueError("导入数据包含重复的按钮组 ID")
        triggers = [trigger for item in presets for trigger in item["triggers"]]
        if len(triggers) != len(set(triggers)):
            raise ValueError("导入数据包含重复的自定义指令")
        async with self._lock:
            self._data["presets"] = presets
            self._write(self._data)
        return self.list()
