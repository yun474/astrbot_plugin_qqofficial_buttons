import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.models import ButtonValidationError, default_preset
from core.storage import ButtonStorage


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_changes_preserve_saved_menus(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "buttons.json"
            original = ButtonStorage(path)
            saved = original.list()
            reloaded = ButtonStorage(
                path, max_rows=1, max_per_row=1, allow_functions=False
            )
            self.assertEqual(reloaded.list(), saved)
            self.assertEqual(reloaded.signing_secret, original.signing_secret)

    async def test_starter_obeys_small_layout_limits_and_empty_store_stays_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "buttons.json"
            storage = ButtonStorage(path, max_rows=1, max_per_row=1)
            self.assertEqual(len(storage.list()[0]["rows"]), 1)
            self.assertEqual(len(storage.list()[0]["rows"][0]), 1)
            await storage.delete("starter_menu")
            self.assertEqual(ButtonStorage(path).list(), [])

    async def test_write_failure_does_not_change_live_state(self):
        with tempfile.TemporaryDirectory() as temp:
            storage = ButtonStorage(Path(temp) / "buttons.json")
            original = storage.list()
            changed = default_preset() | {"name": "not saved"}
            for operation in (
                lambda: storage.save(changed),
                lambda: storage.delete("starter_menu"),
                lambda: storage.replace_all([changed]),
            ):
                with patch.object(storage, "_write", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        await operation()
                self.assertEqual(storage.list(), original)
                self.assertEqual(ButtonStorage(storage.path).list(), original)

    async def test_invalid_data_is_not_overwritten_or_silently_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "buttons.json"
            for content in (
                "{broken",
                "[]",
                '{"presets": [], "signing_secret": ""}',
                json.dumps({"presets": [{"id": "broken"}], "signing_secret": "secret"}),
            ):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ButtonValidationError):
                    ButtonStorage(path)
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    async def test_save_duplicate_delete_and_persist(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "buttons.json"
            storage = ButtonStorage(path)
            preset = default_preset()
            preset["name"] = "修改后的菜单"
            saved = await storage.save(preset)
            self.assertEqual(saved["name"], "修改后的菜单")

            duplicate = await storage.duplicate("starter_menu")
            self.assertIsNotNone(duplicate)
            self.assertNotEqual(duplicate["id"], "starter_menu")
            self.assertEqual(duplicate["triggers"], [])
            self.assertTrue(await storage.delete(duplicate["id"]))

            reloaded = ButtonStorage(path)
            self.assertEqual(reloaded.get("starter_menu")["name"], "修改后的菜单")
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(raw["signing_secret"])

    async def test_exportable_list_has_no_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            storage = ButtonStorage(Path(temp) / "buttons.json")
            exported = json.dumps(storage.list())
            self.assertNotIn(storage.signing_secret, exported)

    async def test_custom_command_cannot_point_to_two_menus(self):
        with tempfile.TemporaryDirectory() as temp:
            storage = ButtonStorage(Path(temp) / "buttons.json")
            first = default_preset()
            first["triggers"] = ["/导航"]
            await storage.save(first)
            second = default_preset()
            second["id"] = "other"
            second["triggers"] = ["/导航"]
            with self.assertRaisesRegex(ButtonValidationError, "已被其他菜单使用"):
                await storage.save(second)


if __name__ == "__main__":
    unittest.main()
