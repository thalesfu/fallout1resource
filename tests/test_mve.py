from __future__ import annotations

import json
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fallout1resource.mve import (
    MVE_HEADER_CONSTANTS,
    MVE_SIGNATURE,
    ExternalTool,
    MveFormatError,
    inspect_ffmpeg,
    mve_output_paths,
    mve_summary,
    parse_mve,
    write_mve_export,
)


def _segment(opcode: int, version: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HBB", len(payload), opcode, version) + payload


def _chunk(chunk_type: int, *segments: bytes) -> bytes:
    payload = b"".join(segments)
    return struct.pack("<HH", len(payload), chunk_type) + payload


def _mve_bytes(*, audio: bool = True) -> bytes:
    header = MVE_SIGNATURE + struct.pack("<3H", *MVE_HEADER_CONSTANTS)
    init_video = _chunk(
        2,
        _segment(0x02, 0, struct.pack("<IH", 10_000, 10)),
        _segment(0x05, 2, struct.pack("<4H", 2, 1, 1, 0)),
        _segment(0x0A, 0, struct.pack("<2H", 640, 480)),
        _segment(0x0C, 0, struct.pack("<HHBBB", 0, 1, 1, 2, 3)),
        _segment(0x01, 0),
    )
    chunks = [init_video]
    if audio:
        chunks.append(
            _chunk(
                0,
                _segment(0x03, 1, struct.pack("<HHHI", 0, 7, 22_050, 4096)),
                _segment(0x01, 0),
            )
        )
    video_segments = [
        _segment(0x0F, 0, b"\x0E"),
        _segment(0x11, 3, bytes(14)),
    ]
    if audio:
        video_segments.append(_segment(0x08, 0, bytes(10)))
    video_segments.extend((_segment(0x07, 1, bytes(6)), _segment(0x01, 0)))
    chunks.extend(
        (
            _chunk(3, *video_segments),
            _chunk(4, _segment(0x00, 0), _segment(0x01, 0)),
            _chunk(5),
        )
    )
    return header + b"".join(chunks)


class MveParsingTests(unittest.TestCase):
    def test_parses_container_timing_video_audio_and_counts(self) -> None:
        document = parse_mve(_mve_bytes())
        summary = mve_summary(document)

        self.assertEqual((16, 8), (document.video.width, document.video.height))
        self.assertEqual(10.0, summary["frames_per_second"])
        self.assertEqual(1, document.frame_count)
        self.assertEqual((0x11,), document.video_data_formats)
        self.assertIsNotNone(document.audio)
        self.assertEqual("interplay_dpcm", document.audio.codec)
        self.assertEqual(22_050, document.audio.sample_rate)
        self.assertEqual(2, document.audio.channels)
        self.assertEqual(1, document.palette_update_count)

    def test_parses_silent_movie(self) -> None:
        document = parse_mve(_mve_bytes(audio=False))
        self.assertIsNone(document.audio)
        self.assertFalse(mve_summary(document)["has_audio"])

    def test_rejects_truncated_and_wrong_header(self) -> None:
        with self.assertRaisesRegex(MveFormatError, "header is truncated"):
            parse_mve(bytes(25))
        wrong = bytearray(_mve_bytes())
        wrong[0] = 0
        with self.assertRaisesRegex(MveFormatError, "signature"):
            parse_mve(bytes(wrong))
        wrong = bytearray(_mve_bytes())
        wrong[20:22] = struct.pack("<H", 25)
        with self.assertRaisesRegex(MveFormatError, "header constants"):
            parse_mve(bytes(wrong))

    def test_rejects_chunk_and_segment_overrun(self) -> None:
        truncated_chunk = bytearray(_mve_bytes())
        struct.pack_into("<H", truncated_chunk, 26, 0xFFFF)
        with self.assertRaisesRegex(MveFormatError, "extends beyond"):
            parse_mve(bytes(truncated_chunk))

        segment_overrun = bytearray(_mve_bytes())
        struct.pack_into("<H", segment_overrun, 30, 0xFFFF)
        with self.assertRaisesRegex(MveFormatError, "exceeds its chunk"):
            parse_mve(bytes(segment_overrun))

    def test_rejects_invalid_palette(self) -> None:
        data = bytearray(_mve_bytes())
        palette_payload = data.find(struct.pack("<HHBBB", 0, 1, 1, 2, 3))
        struct.pack_into("<H", data, palette_payload + 2, 257)
        with self.assertRaisesRegex(MveFormatError, "palette"):
            parse_mve(bytes(data))

    def test_rejects_missing_frames_and_end_chunk(self) -> None:
        no_frames = _mve_bytes().replace(_segment(0x07, 1, bytes(6)), _segment(0x04, 0, bytes(6)))
        with self.assertRaisesRegex(MveFormatError, "no displayable"):
            parse_mve(no_frames)
        with self.assertRaisesRegex(MveFormatError, "end with"):
            parse_mve(_mve_bytes()[:-4])


class MveOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.document = parse_mve(_mve_bytes())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_builds_expected_audio_preview_and_metadata_paths(self) -> None:
        paths = mve_output_paths(
            self.workspace, Path("output/video/sample/sample.json"), self.document
        )
        self.assertEqual("sample.segments.csv", paths[1].name)
        self.assertEqual("sample.poster.png", paths[2].name)
        self.assertEqual("sample.audio.wav", paths[3].name)
        self.assertEqual("sample.preview.mp4", paths[4].name)

    def test_omits_wav_path_for_silent_movie(self) -> None:
        document = parse_mve(_mve_bytes(audio=False))
        paths = mve_output_paths(self.workspace, Path("output/sample.json"), document)
        self.assertIsNone(paths[3])

    def test_rejects_absolute_and_parent_escape(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            mve_output_paths(self.workspace, self.root / "outside.json", self.document)
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            mve_output_paths(self.workspace, Path("../escape.json"), self.document)

    def test_rejects_symlink_escape_when_supported(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        link = self.workspace / "output"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            mve_output_paths(self.workspace, Path("output/escape.json"), self.document)


class MveExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "sample.mve"
        self.source.write_bytes(_mve_bytes())
        self.document = parse_mve(self.source.read_bytes(), self.source)
        self.output = Path("output/video/sample/sample.json")
        self.tool = ExternalTool(
            ffmpeg_path=self.root / "ffmpeg.exe",
            ffprobe_path=self.root / "ffprobe.exe",
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

    def _fake_run(self, command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
        target = Path(command[-1])
        if target.suffix.casefold() in (".png", ".wav", ".mp4"):
            target.write_bytes(f"synthetic {target.suffix}".encode("ascii"))
        return subprocess.CompletedProcess(command, 0, "", "")

    def _write(self, *, overwrite: bool = False) -> tuple[Path, ...]:
        with (
            patch("fallout1resource.mve.inspect_ffmpeg", return_value=self.tool),
            patch("fallout1resource.mve._probe", side_effect=[self.source_probe, self.preview_probe]),
            patch("fallout1resource.mve._run", side_effect=self._fake_run),
            patch("fallout1resource.mve._validate_png"),
            patch(
                "fallout1resource.mve._validate_wav",
                return_value={"channels": 2, "sample_rate": 22050, "sample_width": 2, "frame_count": 1},
            ),
        ):
            return write_mve_export(
                self.document,
                self.workspace,
                self.output,
                self.tool.ffmpeg_path,
                overwrite=overwrite,
            )

    def test_writes_all_audited_outputs(self) -> None:
        paths = self._write()
        for path in paths:
            if path is not None:
                self.assertTrue(path.is_file())
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        self.assertEqual("A" * 64, payload["external_tool"]["ffmpeg_sha256"])
        self.assertEqual(1, payload["summary"]["frame_count"])
        self.assertIn("preview_mp4", payload["derived"])

    def test_refuses_overwrite_and_allows_explicit_overwrite(self) -> None:
        paths = self._write()
        with self.assertRaises(FileExistsError):
            self._write()
        paths[0].write_text("broken", encoding="utf-8")
        self._write(overwrite=True)
        self.assertIn("Interplay MVE", paths[0].read_text(encoding="utf-8"))

    def test_refuses_to_replace_source(self) -> None:
        source = self.workspace / "output" / "sample.json"
        source.parent.mkdir(parents=True)
        source.write_bytes(_mve_bytes())
        document = parse_mve(source.read_bytes(), source)
        with self.assertRaisesRegex(ValueError, "replace a source"):
            write_mve_export(document, self.workspace, source, self.tool.ffmpeg_path, overwrite=True)

    def test_rejects_missing_ffmpeg_before_execution(self) -> None:
        with self.assertRaisesRegex(MveFormatError, "not found"):
            inspect_ffmpeg(self.root / "missing.exe")


if __name__ == "__main__":
    unittest.main()
