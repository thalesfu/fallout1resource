from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_map_file import build_map
from test_proto import build_catalog

from fallout1resource.map_batch import build_map_batch_plan, execute_map_batch


class MapBatchTests(unittest.TestCase):
    def _dependencies(self, workspace: Path) -> tuple[Path, Path]:
        prototype_root = workspace / "raw/master/PROTO"
        build_catalog(prototype_root)
        scripts = workspace / "raw/master/SCRIPTS/SCRIPTS.LST"
        scripts.parent.mkdir(parents=True, exist_ok=True)
        scripts.write_bytes(b"OTHER.INT\r\nHAROLD.INT\r\n")
        return prototype_root, scripts

    def _map(self, workspace: Path, name: str = "TEST.MAP") -> Path:
        path = workspace / "raw/master/MAPS" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(build_map())
        return path

    def test_plan_is_write_free_and_resolves_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            prototype_root, scripts = self._dependencies(workspace)
            self._map(workspace)

            plan, actual_proto, actual_scripts = build_map_batch_plan(workspace, sources=["master"])

            self.assertEqual(len(plan), 1)
            self.assertEqual(actual_proto, prototype_root.resolve())
            self.assertEqual(actual_scripts, scripts.resolve())
            self.assertTrue(plan[0].output.as_posix().endswith("master/MAPS/TEST/TEST.json"))
            self.assertFalse((workspace / "output").exists())

    def test_continues_after_failure_and_rerun_verifies_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            prototype_root, scripts = self._dependencies(workspace)
            self._map(workspace)
            bad = workspace / "raw/master/MAPS/BAD.MAP"
            bad.write_bytes(b"invalid")
            plan, _, _ = build_map_batch_plan(workspace)

            first = execute_map_batch(plan, prototype_root, scripts, workspace)
            second = execute_map_batch(plan, prototype_root, scripts, workspace)

            self.assertEqual((first.converted, first.failed), (1, 1))
            self.assertEqual((second.skipped_verified, second.failed), (1, 1))

    def test_tampered_csv_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            prototype_root, scripts = self._dependencies(workspace)
            self._map(workspace)
            plan, _, _ = build_map_batch_plan(workspace)
            execute_map_batch(plan, prototype_root, scripts, workspace)
            csv_path = next((workspace / "output").rglob("*.objects.csv"))
            csv_path.write_bytes(b"tampered")

            failed = execute_map_batch(plan, prototype_root, scripts, workspace)
            recovered = execute_map_batch(plan, prototype_root, scripts, workspace, overwrite=True)

            self.assertEqual((failed.converted, failed.failed), (0, 1))
            self.assertEqual((recovered.converted, recovered.failed), (1, 0))
            self.assertNotEqual(csv_path.read_bytes(), b"tampered")

    def test_loose_data_is_read_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            self._dependencies(workspace)
            game_dir = root / "Fallout"
            source = game_dir / "DATA/MAPS/LOOSE.MAP"
            source.parent.mkdir(parents=True)
            source.write_bytes(build_map())

            plan, _, _ = build_map_batch_plan(workspace, sources=["data"], game_dir=game_dir)

            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0].source_path, source.resolve())


if __name__ == "__main__":
    unittest.main()
