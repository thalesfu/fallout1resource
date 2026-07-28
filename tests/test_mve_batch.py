from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from test_mve import _mve_bytes

from fallout1resource.mve import ExternalTool
from fallout1resource.mve_batch import build_mve_batch_plan, execute_mve_batch


class MveBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.ffmpeg = (self.root / "ffmpeg.exe").resolve()
        self.tool = ExternalTool(
            ffmpeg_path=self.ffmpeg,
            ffprobe_path=(self.root / "ffprobe.exe").resolve(),
            ffmpeg_sha256="A" * 64,
            ffprobe_sha256="B" * 64,
            version_line="ffmpeg version synthetic",
            runtime_files=(),
            runtime_manifest_sha256="C" * 64,
        )
        self.source_probe = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "interplayvideo",
                    "width": 16,
                    "height": 8,
                    "nb_read_frames": "1",
                },
                {"codec_type": "audio", "channels": 2, "sample_rate": "22050"},
            ]
        }
        self.preview_probe = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "mpeg4",
                    "width": 16,
                    "height": 8,
                    "nb_read_frames": "1",
                }
            ]
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _movie(self, name: str = "TEST.MVE") -> Path:
        path = self.workspace / "raw/master/ART/CUTS" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_mve_bytes())
        return path

    def _fake_run(
        self, command: list[str], *, timeout: int = 600
    ) -> subprocess.CompletedProcess[str]:
        target = Path(command[-1])
        if target.suffix.casefold() in (".png", ".wav", ".mp4"):
            target.write_bytes(f"synthetic {target.suffix}".encode("ascii"))
        return subprocess.CompletedProcess(command, 0, "", "")

    def _patch_export(self, *, probes: bool) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(
            patch("fallout1resource.mve_batch.inspect_ffmpeg", return_value=self.tool)
        )
        if probes:
            stack.enter_context(
                patch(
                    "fallout1resource.mve._probe",
                    side_effect=[self.source_probe, self.preview_probe],
                )
            )
            stack.enter_context(patch("fallout1resource.mve._run", side_effect=self._fake_run))
            stack.enter_context(patch("fallout1resource.mve._validate_png"))
            stack.enter_context(
                patch(
                    "fallout1resource.mve._validate_wav",
                    return_value={
                        "channels": 2,
                        "sample_rate": 22050,
                        "sample_width": 2,
                        "frame_count": 1,
                    },
                )
            )
        return stack

    def test_plan_is_write_free_and_isolates_source(self) -> None:
        self._movie()
        plan = build_mve_batch_plan(self.workspace, sources=["master"])
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0].output.as_posix().endswith("master/ART/CUTS/TEST/TEST.json"))
        self.assertFalse((self.workspace / "output").exists())

    def test_continues_after_failure_and_rerun_verifies_outputs(self) -> None:
        self._movie()
        bad = self.workspace / "raw/master/ART/CUTS/BAD.MVE"
        bad.write_bytes(b"invalid")
        plan = build_mve_batch_plan(self.workspace)
        with self._patch_export(probes=True):
            first = execute_mve_batch(plan, self.workspace, self.ffmpeg)
        with self._patch_export(probes=False):
            second = execute_mve_batch(plan, self.workspace, self.ffmpeg)
        self.assertEqual((first.converted, first.failed), (1, 1))
        self.assertEqual((second.skipped_verified, second.failed), (1, 1))

    def test_tampered_preview_requires_overwrite(self) -> None:
        self._movie()
        plan = build_mve_batch_plan(self.workspace)
        with self._patch_export(probes=True):
            execute_mve_batch(plan, self.workspace, self.ffmpeg)
        preview = next((self.workspace / "output").rglob("*.preview.mp4"))
        preview.write_bytes(b"tampered")
        with self._patch_export(probes=False):
            failed = execute_mve_batch(plan, self.workspace, self.ffmpeg)
        with self._patch_export(probes=True):
            recovered = execute_mve_batch(plan, self.workspace, self.ffmpeg, overwrite=True)
        self.assertEqual((failed.converted, failed.failed), (0, 1))
        self.assertEqual((recovered.converted, recovered.failed), (1, 0))


if __name__ == "__main__":
    unittest.main()
