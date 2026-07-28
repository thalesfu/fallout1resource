from __future__ import annotations

import codecs
import json
import struct
import tempfile
import unittest
from pathlib import Path

from fallout1resource.int_script import (
    IntFormatError,
    int_output_paths,
    link_messages,
    load_int,
    parse_int,
    write_int_export,
)
from fallout1resource.msg import load_msg


def _opcode(value: int, argument: int | None = None) -> bytes:
    encoded = struct.pack(">H", value)
    if argument is not None:
        encoded += struct.pack(">i", argument)
    return encoded


def _pool(values: list[str]) -> tuple[bytes, dict[str, int]]:
    content = bytearray()
    offsets: dict[str, int] = {}
    for value in values:
        raw = value.encode("ascii") + b"\x00"
        if len(raw) % 2:
            raw += b"\x00"
        offsets[value] = 4 + len(content) + 2
        content.extend(struct.pack(">H", len(raw)))
        content.extend(raw)
    return struct.pack(">I", len(content)) + bytes(content) + b"\xff\xff\xff\xff", offsets


def build_int(path: Path) -> int:
    namespace, offsets = _pool(["start"])
    stringspace = b"\xff\xff\xff\xff"
    procedure_count = 1
    namespace_offset = 42 + 4 + procedure_count * 24
    code_start = namespace_offset + len(namespace) + len(stringspace)
    startup_tail = _opcode(0x802C) + _opcode(0xC001, code_start + 10) + _opcode(0x8004)
    body_offset = code_start + len(startup_tail)
    body = b"".join(
        (
            _opcode(0x802B),
            _opcode(0xC001, 45),
            _opcode(0xC001, 100),
            _opcode(0x811E),
            _opcode(0x802A),
            _opcode(0x8029),
            _opcode(0x801C),
        )
    )
    startup = b"".join(
        (
            _opcode(0x8002),
            _opcode(0xC001, 18),
            _opcode(0x800D),
            _opcode(0xC001, code_start),
            _opcode(0x8004),
            _opcode(0x8010),
            _opcode(0x801A),
            _opcode(0x8020),
            _opcode(0x801A),
            _opcode(0x8021),
            _opcode(0x801A),
            _opcode(0x8022),
            _opcode(0x801A),
            _opcode(0x8023),
            _opcode(0x8024),
            _opcode(0x8025),
            _opcode(0x8026),
        )
    )
    procedure = struct.pack(">6I", offsets["start"], 0, 0, 0, body_offset, 0)
    path.write_bytes(
        startup
        + struct.pack(">I", procedure_count)
        + procedure
        + namespace
        + stringspace
        + startup_tail
        + body
    )
    return body_offset


class IntParsingTests(unittest.TestCase):
    def test_parses_layout_procedure_and_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "TEST.INT"
            body_offset = build_int(path)
            program = load_int(path)
            self.assertEqual(len(program.procedures), 1)
            self.assertEqual(program.procedures[0].name, "start")
            self.assertEqual(program.procedures[0].body_offset, body_offset)
            self.assertEqual(program.procedures[0].instructions[2].argument, 100)
            self.assertEqual(program.procedures[0].instructions[3].mnemonic, "gsay_reply")
            self.assertEqual(program.unknown_opcodes, ())

    def test_rejects_bad_startup_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "TEST.INT"
            build_int(path)
            data = bytearray(path.read_bytes())
            data[1] = 0x03
            with self.assertRaises(IntFormatError):
                parse_int(bytes(data))

    def test_rejects_truncated_procedure_table(self) -> None:
        with self.assertRaises(IntFormatError):
            parse_int(b"\x00" * 42 + struct.pack(">I", 100))

    def test_rejects_invalid_opcode_in_procedure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "TEST.INT"
            body_offset = build_int(path)
            data = bytearray(path.read_bytes())
            data[body_offset : body_offset + 2] = b"\x00\x00"
            with self.assertRaises(IntFormatError):
                parse_int(bytes(data))

    def test_rejects_metadata_jump_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "TEST.INT"
            build_int(path)
            data = bytearray(path.read_bytes())
            data[12:16] = struct.pack(">I", 1)
            with self.assertRaises(IntFormatError):
                parse_int(bytes(data))


class IntMessageLinkTests(unittest.TestCase):
    def test_links_literal_message_to_effective_msg_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            int_path = root / "TEST.INT"
            msg_path = root / "TEST.MSG"
            build_int(int_path)
            msg_path.write_bytes(b"{100}{}{old}\n{100}{}{linked text}")
            references, inferred = link_messages(load_int(int_path), load_msg(msg_path))
            self.assertEqual(inferred, 45)
            self.assertEqual(len(references), 1)
            self.assertEqual(references[0].link_status, "linked")
            self.assertEqual(references[0].msg_text, "linked text")


class IntExportTests(unittest.TestCase):
    def _inputs(self, root: Path):
        int_path = root / "TEST.INT"
        msg_path = root / "TEST.MSG"
        build_int(int_path)
        msg_path.write_bytes(b"{100}{}{linked text}")
        program = load_int(int_path)
        msg = load_msg(msg_path)
        references, inferred = link_messages(program, msg)
        return program, msg, references, inferred

    def test_writes_json_disassembly_links_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            program, msg, references, inferred = self._inputs(root)
            paths = write_int_export(
                program, references, inferred, msg, workspace, "output/TEST.json"
            )
            payload = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["message_link"]["inferred_message_list_id"], 45)
            self.assertEqual(payload["generator"]["component"], "int")
            self.assertEqual(payload["derived"]["disassembly"]["size"], paths[1].stat().st_size)
            self.assertIn("gsay_reply", paths[1].read_text(encoding="utf-8"))
            self.assertTrue(paths[2].read_bytes().startswith(codecs.BOM_UTF8))
            self.assertIn(paths[0].name, paths[3].read_text(encoding="ascii"))

    def test_refuses_overwrite_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            program, msg, references, inferred = self._inputs(root)
            paths = write_int_export(
                program, references, inferred, msg, workspace, "output/TEST.json"
            )
            paths[0].write_text("user content", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_int_export(program, references, inferred, msg, workspace, "output/TEST.json")
            self.assertEqual(paths[0].read_text(encoding="utf-8"), "user content")

    def test_explicit_overwrite_replaces_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            program, msg, references, inferred = self._inputs(root)
            paths = write_int_export(
                program, references, inferred, msg, workspace, "output/TEST.json"
            )
            paths[1].write_text("old", encoding="utf-8")
            write_int_export(
                program,
                references,
                inferred,
                msg,
                workspace,
                "output/TEST.json",
                overwrite=True,
            )
            self.assertIn("gsay_reply", paths[1].read_text(encoding="utf-8"))

    def test_rejects_outputs_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            with self.assertRaises(ValueError):
                int_output_paths(workspace, "../outside.json")
            with self.assertRaises(ValueError):
                int_output_paths(workspace, root / "absolute.json")

    def test_refuses_to_replace_a_source_via_sibling_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            int_source = workspace / "TEST.disasm.txt"
            build_int(int_source)
            program = load_int(int_source)
            references, inferred = link_messages(program)
            with self.assertRaises(ValueError):
                write_int_export(
                    program,
                    references,
                    inferred,
                    None,
                    workspace,
                    "TEST.json",
                    overwrite=True,
                )

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
                int_output_paths(workspace, "output/TEST.json")


if __name__ == "__main__":
    unittest.main()
