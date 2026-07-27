from __future__ import annotations

import codecs
import json
import tempfile
import unittest
from pathlib import Path

from fallout1resource.msg import (
    MsgFormatError,
    decode_msg,
    load_msg,
    msg_output_paths,
    parse_msg,
    write_msg_export,
)


class MsgParsingTests(unittest.TestCase):
    def test_parses_records_and_ignores_outside_text(self) -> None:
        entries = parse_msg("comment\n{100}{}{Hello}\nignored\n{101}{VOICE}{World}")
        self.assertEqual(
            [(entry.number, entry.audio, entry.text) for entry in entries],
            [
                (100, "", "Hello"),
                (101, "VOICE", "World"),
            ],
        )
        self.assertEqual(entries[0].source_line_start, 2)
        self.assertEqual(entries[1].source_line_end, 4)

    def test_removes_field_newlines_like_game_loader_but_preserves_source_text(self) -> None:
        entry = parse_msg("{1}{}{first\nsecond}")[0]
        self.assertEqual(entry.text, "firstsecond")
        self.assertEqual(entry.source_text, "first\nsecond")

    def test_preserves_duplicates_and_marks_last_effective(self) -> None:
        entries = parse_msg("{7}{}{old}\n{7}{}{new}")
        self.assertEqual(len(entries), 2)
        self.assertFalse(entries[0].effective)
        self.assertTrue(entries[1].effective)
        self.assertEqual(entries[1].number_occurrence, 2)
        self.assertEqual(entries[1].number_occurrence_count, 2)

    def test_matches_original_sign_only_number_behavior(self) -> None:
        self.assertEqual(parse_msg("{+}{}{text}")[0].number, 0)

    def test_rejects_malformed_records(self) -> None:
        cases = (
            "stray }",
            "{1}{}{unterminated",
            "{1}{}",
            "{x}{}{text}",
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(MsgFormatError):
                parse_msg(value)

    def test_enforces_game_field_limit_in_source_encoding_bytes(self) -> None:
        parse_msg("{1}{}{中" + "文" * 510 + "}", encoding="gbk")
        with self.assertRaises(MsgFormatError):
            parse_msg("{1}{}{中" + "文" * 511 + "}", encoding="gbk")


class MsgEncodingTests(unittest.TestCase):
    def test_detects_ascii(self) -> None:
        decoded = decode_msg(b"{1}{}{hello}")
        self.assertEqual(decoded.encoding, "ascii")
        self.assertEqual(decoded.detection_method, "ascii-only")

    def test_detects_utf8(self) -> None:
        decoded = decode_msg("{1}{}{哈罗德}".encode())
        self.assertEqual(decoded.encoding, "utf-8")
        self.assertEqual(decoded.confidence, "high")

    def test_prefers_gbk_for_simplified_chinese(self) -> None:
        decoded = decode_msg("{1}{}{哈罗德在旧镇。}".encode("gbk"))
        self.assertEqual(decoded.encoding, "gbk")
        self.assertIn(decoded.confidence, {"low", "medium"})
        self.assertEqual(parse_msg(decoded.text, decoded.encoding)[0].text, "哈罗德在旧镇。")

    def test_explicit_encoding_is_strict(self) -> None:
        decoded = decode_msg("{1}{}{中文}".encode("gbk"), encoding="cp936")
        self.assertEqual(decoded.detection_method, "explicit")
        with self.assertRaises(MsgFormatError):
            decode_msg(b"\xff", encoding="utf-8")


class MsgExportTests(unittest.TestCase):
    def _document(self, root: Path):
        source = root / "HAROLD.MSG"
        source.write_bytes("{100}{}{哈罗德}".encode("gbk"))
        return load_msg(source)

    def test_writes_utf8_json_csv_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            paths = write_msg_export(self._document(root), workspace, "output/HAROLD.json")
            json_path, csv_path, hash_path = paths
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["entries"][0]["text"], "哈罗德")
            self.assertTrue(csv_path.read_bytes().startswith(codecs.BOM_UTF8))
            self.assertIn(json_path.name, hash_path.read_text(encoding="ascii"))

    def test_refuses_overwrite_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            document = self._document(root)
            paths = write_msg_export(document, workspace, "output/HAROLD.json")
            paths[0].write_text("user content", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_msg_export(document, workspace, "output/HAROLD.json")
            self.assertEqual(paths[0].read_text(encoding="utf-8"), "user content")

    def test_explicit_overwrite_replaces_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            document = self._document(root)
            paths = write_msg_export(document, workspace, "output/HAROLD.json")
            paths[0].write_text("old", encoding="utf-8")
            write_msg_export(document, workspace, "output/HAROLD.json", overwrite=True)
            self.assertEqual(
                json.loads(paths[0].read_text(encoding="utf-8"))["entries"][0]["number"], 100
            )

    def test_rejects_outputs_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            with self.assertRaises(ValueError):
                msg_output_paths(workspace, "../outside.json")
            with self.assertRaises(ValueError):
                msg_output_paths(workspace, root / "absolute.json")

    def test_refuses_to_replace_source_via_sibling_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "HAROLD.csv"
            source.write_bytes(b"{100}{}{source}")
            document = load_msg(source)
            with self.assertRaises(ValueError):
                write_msg_export(document, workspace, "HAROLD.json", overwrite=True)
            self.assertEqual(source.read_bytes(), b"{100}{}{source}")

    def test_rejects_symlink_escape_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside"
            outside.mkdir()
            try:
                (workspace / "output").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            with self.assertRaises(ValueError):
                msg_output_paths(workspace, "output/HAROLD.json")


if __name__ == "__main__":
    unittest.main()
