import json
import tempfile
import unittest
from pathlib import Path

from core.models import default_preset
from core.storage import ButtonStorage


class StorageTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
