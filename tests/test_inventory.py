from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fallout1resource.inventory import build_inventory, ensure_within_workspace, write_inventory
from test_dat1 import build_dat1


class InventoryTests(unittest.TestCase):
    def test_output_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            with self.assertRaises(ValueError):
                ensure_within_workspace(workspace, workspace.parent / "outside.json")

    def test_inventory_excludes_savegames_and_writes_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_dir = root / "Fallout"
            data_dir = game_dir / "DATA"
            save_dir = data_dir / "SAVEGAME" / "SLOT01"
            dialog_dir = data_dir / "TEXT" / "ENGLISH" / "DIALOG"
            save_dir.mkdir(parents=True)
            dialog_dir.mkdir(parents=True)
            build_dat1(game_dir / "MASTER.DAT")
            build_dat1(game_dir / "CRITTER.DAT")
            (save_dir / "SAVE.DAT").write_bytes(b"save")
            (dialog_dir / "HAROLD.MSG").write_text("message", encoding="ascii")
            workspace = root / "workspace"

            manifest = build_inventory(game_dir, hash_sources=False)
            paths = [entry["internal_path"] for entry in manifest["entries"]]
            self.assertFalse(any("SAVEGAME" in path for path in paths))
            self.assertIn("TEXT/ENGLISH/DIALOG/HAROLD.MSG", paths)

            json_path, csv_path, hash_path = write_inventory(manifest, workspace, "manifests/inventory.json")
            self.assertTrue(json_path.is_file())
            self.assertTrue(csv_path.is_file())
            self.assertTrue(hash_path.is_file())
            self.assertGreater(manifest["summary"]["duplicate_path_count"], 0)


if __name__ == "__main__":
    unittest.main()
