from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_acm import _acm_bytes

from fallout1resource.acm_batch import build_acm_batch_plan, execute_acm_batch


class AcmBatchTests(unittest.TestCase):
    def _audio(self, workspace: Path, name: str = "TEST.ACM") -> Path:
        path = workspace / "raw/master/SOUND/SFX" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_acm_bytes())
        return path

    def test_plan_is_write_free_and_isolates_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._audio(workspace)

            plan = build_acm_batch_plan(workspace, sources=["master"])

            self.assertEqual(len(plan), 1)
            self.assertTrue(plan[0].output.as_posix().endswith("master/SOUND/SFX/TEST/TEST.json"))
            self.assertFalse((workspace / "output").exists())

    def test_continues_after_failure_and_rerun_verifies_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._audio(workspace)
            bad = workspace / "raw/master/SOUND/SFX/BAD.ACM"
            bad.write_bytes(b"invalid")
            plan = build_acm_batch_plan(workspace)

            first = execute_acm_batch(plan, workspace)
            second = execute_acm_batch(plan, workspace)

            self.assertEqual((first.converted, first.failed), (1, 1))
            self.assertEqual((second.skipped_verified, second.failed), (1, 1))

    def test_tampered_wav_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._audio(workspace)
            plan = build_acm_batch_plan(workspace)
            execute_acm_batch(plan, workspace)
            wav_path = next((workspace / "output").rglob("*.wav"))
            wav_path.write_bytes(b"tampered")

            failed = execute_acm_batch(plan, workspace)
            recovered = execute_acm_batch(plan, workspace, overwrite=True)

            self.assertEqual((failed.converted, failed.failed), (0, 1))
            self.assertEqual((recovered.converted, recovered.failed), (1, 0))
            self.assertNotEqual(wav_path.read_bytes(), b"tampered")

    def test_loose_data_is_read_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            game_dir = root / "Fallout"
            source = game_dir / "DATA/SOUND/MUSIC/LOOSE.ACM"
            source.parent.mkdir(parents=True)
            source.write_bytes(_acm_bytes())

            plan = build_acm_batch_plan(workspace, sources=["data"], game_dir=game_dir)

            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0].source_path, source.resolve())


if __name__ == "__main__":
    unittest.main()
