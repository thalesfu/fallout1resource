"""Parse and disassemble classic Fallout INT bytecode without executing it."""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import struct
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace
from .msg import MsgDocument
from .safe_io import write_file_atomic

STARTUP_SIZE = 42
PROCEDURE_SIZE = 24
MAX_FILE_SIZE = 64 * 1024 * 1024
MAX_PROCEDURES = 100_000
EMPTY_POOL = 0xFFFFFFFF
CONSTANT_OPCODES = {0x9001, 0xA001, 0xC001}
MAX_FALLOUT1_OPCODE = 0x8155


class IntFormatError(ValueError):
    """Raised when an INT file is malformed or outside the supported format."""


CORE_OPCODE_NAMES = (
    "noop",
    "push",
    "critical_start",
    "critical_done",
    "jump",
    "call",
    "call_at",
    "call_condition",
    "callstart",
    "exec",
    "spawn",
    "fork",
    "a_to_d",
    "d_to_a",
    "exit",
    "detach",
    "exit_program",
    "stop_program",
    "fetch_global",
    "store_global",
    "fetch_external",
    "store_external",
    "export_variable",
    "export_procedure",
    "swap",
    "swapa",
    "pop",
    "dup",
    "pop_return",
    "pop_exit",
    "pop_address",
    "pop_flags",
    "pop_flags_return",
    "pop_flags_exit",
    "pop_flags_return_extern",
    "pop_flags_exit_extern",
    "pop_flags_return_val_extern",
    "pop_flags_return_val_exit",
    "pop_flags_return_val_exit_extern",
    "check_procedure_argument_count",
    "lookup_procedure_by_name",
    "pop_base",
    "pop_to_base",
    "push_base",
    "set_global",
    "fetch_procedure_address",
    "dump",
    "if",
    "while",
    "store",
    "fetch",
    "equal",
    "not_equal",
    "less_equal",
    "greater_equal",
    "less",
    "greater",
    "add",
    "sub",
    "mul",
    "div",
    "mod",
    "and",
    "or",
    "bitwise_and",
    "bitwise_or",
    "bitwise_xor",
    "bitwise_not",
    "floor",
    "not",
    "negate",
    "wait",
    "cancel",
    "cancel_all",
    "start_critical",
    "end_critical",
)

OPCODE_NAMES = {0x8000 + index: name for index, name in enumerate(CORE_OPCODE_NAMES)}
OPCODE_NAMES.update(
    {
        0x80B4: "random",
        0x80B8: "display_msg",
        0x80B9: "script_overrides",
        0x80BC: "self_obj",
        0x80BD: "source_obj",
        0x80BF: "dude_obj",
        0x80C1: "local_var",
        0x80C2: "set_local_var",
        0x80C5: "global_var",
        0x80C6: "set_global_var",
        0x80C7: "script_action",
        0x80CA: "get_critter_stat",
        0x80D0: "attack",
        0x80DE: "start_gdialog",
        0x80DF: "end_dialogue",
        0x80EA: "game_time",
        0x80F3: "has_trait",
        0x8102: "critter_add_trait",
        0x8105: "message_str",
        0x811C: "gsay_start",
        0x811D: "gsay_end",
        0x811E: "gsay_reply",
        0x811F: "gsay_option",
        0x8120: "gsay_message",
        0x8121: "giq_option",
        0x8138: "item_caps_total",
        0x8139: "item_caps_adjust",
    }
)

DIALOGUE_CALLS: dict[int, tuple[str, tuple[str, ...]]] = {
    0x8105: ("message_lookup", ("message_list_id", "message_number")),
    0x811E: ("reply", ("message_list_id", "message_number")),
    0x811F: ("option", ("message_list_id", "message_number", "target_procedure", "reaction")),
    0x8120: ("message", ("message_list_id", "message_number", "reaction")),
    0x8121: (
        "intelligence_option",
        ("intelligence", "message_list_id", "message_number", "target_procedure", "reaction"),
    ),
}

EXPRESSION_ARITIES = {
    **{opcode: 2 for opcode in range(0x8033, 0x8043)},
    0x8043: 1,
    0x8044: 1,
    0x8045: 1,
    0x8046: 1,
    0x8012: 1,
    0x8014: 1,
    0x8032: 1,
    0x80B4: 2,
    0x80BC: 0,
    0x80BD: 0,
    0x80BF: 0,
    0x80C1: 1,
    0x80C5: 1,
    0x80CA: 2,
    0x80EA: 0,
    0x80F3: 3,
    0x8105: 2,
}

STARTUP_OPCODES = (
    0x8002,
    0xC001,
    0x800D,
    0xC001,
    0x8004,
    0x8010,
    0x801A,
    0x8020,
    0x801A,
    0x8021,
    0x801A,
    0x8022,
    0x801A,
    0x8023,
    0x8024,
    0x8025,
    0x8026,
)


@dataclass(frozen=True, slots=True)
class IntString:
    offset: int
    text: str
    encoded_length: int


@dataclass(frozen=True, slots=True)
class IntInstruction:
    offset: int
    opcode: int
    mnemonic: str
    size: int
    argument_raw: int | None = None
    argument: int | float | str | None = None


@dataclass(frozen=True, slots=True)
class IntProcedure:
    index: int
    name: str
    name_offset: int
    flags: int
    time: int
    condition_offset: int
    body_offset: int
    argument_count: int
    body_size: int
    instructions: tuple[IntInstruction, ...]


@dataclass(frozen=True, slots=True)
class IntProgram:
    source_path: Path
    source_size: int
    source_sha256: str
    procedure_table_offset: int
    namespace_offset: int
    stringspace_offset: int
    code_after_metadata_offset: int
    startup: tuple[IntInstruction, ...]
    startup_tail: tuple[IntInstruction, ...]
    identifiers: tuple[IntString, ...]
    strings: tuple[IntString, ...]
    procedures: tuple[IntProcedure, ...]
    unknown_opcodes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MessageReference:
    procedure_index: int
    procedure_name: str
    instruction_offset: int
    call: str
    message_list_id: int | None
    message_number: int | None
    message_expression: str
    intelligence: int | None
    target_procedure_index: int | None
    target_procedure_name: str | None
    reaction: int | None
    link_status: str
    msg_text: str | None
    msg_audio: str | None


@dataclass(frozen=True, slots=True)
class _Pool:
    offset: int
    end: int
    strings: tuple[IntString, ...]


@dataclass(frozen=True, slots=True)
class _Expression:
    text: str
    constant: int | None


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise IntFormatError(f"truncated 16-bit value at 0x{offset:X}")
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise IntFormatError(f"truncated 32-bit value at 0x{offset:X}")
    return struct.unpack_from(">I", data, offset)[0]


def _decode_script_string(value: bytes, offset: int) -> str:
    raw = value.split(b"\x00", 1)[0]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            return raw.decode("latin-1")


def _parse_pool(data: bytes, offset: int, label: str) -> _Pool:
    length = _u32(data, offset)
    if length == EMPTY_POOL:
        return _Pool(offset, offset + 4, ())
    content_start = offset + 4
    content_end = content_start + length
    if content_end + 4 > len(data):
        raise IntFormatError(f"{label} exceeds file bounds")

    strings: list[IntString] = []
    cursor = content_start
    while cursor < content_end:
        record_start = cursor
        encoded_length = _u16(data, cursor)
        cursor += 2
        if encoded_length < 2 or encoded_length % 2:
            raise IntFormatError(f"invalid {label} string length at 0x{record_start:X}")
        record_end = cursor + encoded_length
        if record_end > content_end:
            raise IntFormatError(f"truncated {label} string at 0x{record_start:X}")
        value = data[cursor:record_end]
        if value[-1] != 0 and value[-2] != 0:
            raise IntFormatError(f"unterminated {label} string at 0x{record_start:X}")
        strings.append(
            IntString(
                offset=cursor - offset,
                text=_decode_script_string(value, cursor),
                encoded_length=encoded_length,
            )
        )
        cursor = record_end
    if cursor != content_end:
        raise IntFormatError(f"misaligned {label}")
    if _u32(data, content_end) != EMPTY_POOL:
        raise IntFormatError(f"invalid {label} terminator at 0x{content_end:X}")
    return _Pool(offset, content_end + 4, tuple(strings))


def _mnemonic(opcode: int) -> str:
    if opcode == 0x9001:
        return "push_string"
    if opcode == 0xA001:
        return "push_float"
    if opcode == 0xC001:
        return "push_int"
    return OPCODE_NAMES.get(opcode, f"op_{opcode:04x}")


def _disassemble_range(
    data: bytes,
    start: int,
    end: int,
    strings: dict[int, str],
) -> tuple[IntInstruction, ...]:
    if start < 0 or end < start or end > len(data):
        raise IntFormatError(f"invalid code range 0x{start:X}-0x{end:X}")
    result: list[IntInstruction] = []
    cursor = start
    while cursor < end:
        opcode = _u16(data, cursor)
        if opcode not in CONSTANT_OPCODES and not (0x8000 <= opcode <= MAX_FALLOUT1_OPCODE):
            raise IntFormatError(f"invalid opcode 0x{opcode:04X} at 0x{cursor:X}")
        if opcode in CONSTANT_OPCODES:
            if cursor + 6 > end:
                raise IntFormatError(f"constant at 0x{cursor:X} crosses code boundary")
            raw = _u32(data, cursor + 2)
            if opcode == 0xC001:
                argument: int | float | str = struct.unpack_from(">i", data, cursor + 2)[0]
            elif opcode == 0xA001:
                argument = struct.unpack_from(">f", data, cursor + 2)[0]
            else:
                argument = strings.get(raw, f"<unresolved-string:0x{raw:X}>")
            result.append(IntInstruction(cursor, opcode, _mnemonic(opcode), 6, raw, argument))
            cursor += 6
        else:
            result.append(IntInstruction(cursor, opcode, _mnemonic(opcode), 2))
            cursor += 2
    return tuple(result)


def _validate_startup(instructions: tuple[IntInstruction, ...]) -> None:
    actual = tuple(instruction.opcode for instruction in instructions)
    if actual != STARTUP_OPCODES:
        raise IntFormatError("INT startup signature does not match Fallout bytecode")
    if instructions[1].argument != 18:
        raise IntFormatError("INT startup constant is not 18")


def parse_int(data: bytes, *, source_path: Path | None = None) -> IntProgram:
    if len(data) > MAX_FILE_SIZE:
        raise IntFormatError(f"INT exceeds {MAX_FILE_SIZE} byte safety limit")
    if len(data) < STARTUP_SIZE + 4:
        raise IntFormatError("INT file is truncated")

    procedure_count = _u32(data, STARTUP_SIZE)
    if procedure_count == 0 or procedure_count > MAX_PROCEDURES:
        raise IntFormatError(f"invalid procedure count: {procedure_count}")
    table_start = STARTUP_SIZE + 4
    namespace_offset = table_start + procedure_count * PROCEDURE_SIZE
    if namespace_offset > len(data):
        raise IntFormatError("procedure table exceeds file bounds")

    namespace = _parse_pool(data, namespace_offset, "namespace")
    stringspace_offset = namespace.end
    stringspace = _parse_pool(data, stringspace_offset, "stringspace")
    code_start = stringspace.end
    identifier_map = {item.offset: item.text for item in namespace.strings}
    string_map = {item.offset: item.text for item in stringspace.strings}

    raw_procedures: list[tuple[int, int, int, int, int, int]] = []
    for index in range(procedure_count):
        offset = table_start + index * PROCEDURE_SIZE
        values = struct.unpack_from(">6I", data, offset)
        name_offset, flags, time, condition_offset, body_offset, argument_count = values
        if name_offset not in identifier_map:
            raise IntFormatError(f"procedure {index} has unknown name offset 0x{name_offset:X}")
        if body_offset > len(data):
            raise IntFormatError(f"procedure {index} body is outside the file")
        raw_procedures.append(values)

    body_items = sorted(
        (values[4], index)
        for index, values in enumerate(raw_procedures)
        if values[4] not in (0, len(data)) and not (values[1] & 0x04)
    )
    if not body_items:
        raise IntFormatError("INT contains no procedure bodies")
    if body_items[0][0] < code_start:
        raise IntFormatError("procedure body overlaps metadata")
    body_sizes: dict[int, int] = {}
    for position, (body_offset, index) in enumerate(body_items):
        next_offset = body_items[position + 1][0] if position + 1 < len(body_items) else len(data)
        if next_offset < body_offset:
            raise IntFormatError("procedure bodies are not ordered")
        body_sizes[index] = next_offset - body_offset

    startup = _disassemble_range(data, 0, STARTUP_SIZE, string_map)
    _validate_startup(startup)
    if startup[3].argument != code_start:
        raise IntFormatError(
            f"startup metadata jump 0x{startup[3].argument:X} does not match 0x{code_start:X}"
        )
    startup_tail = _disassemble_range(data, code_start, body_items[0][0], string_map)

    procedures: list[IntProcedure] = []
    unknown: Counter[int] = Counter()
    for index, values in enumerate(raw_procedures):
        name_offset, flags, time, condition_offset, body_offset, argument_count = values
        body_size = body_sizes.get(index, 0)
        instructions = (
            _disassemble_range(data, body_offset, body_offset + body_size, string_map)
            if body_size
            else ()
        )
        for instruction in instructions:
            if (
                instruction.opcode not in OPCODE_NAMES
                and instruction.opcode not in CONSTANT_OPCODES
            ):
                unknown[instruction.opcode] += 1
        procedures.append(
            IntProcedure(
                index=index,
                name=identifier_map[name_offset],
                name_offset=name_offset,
                flags=flags,
                time=time,
                condition_offset=condition_offset,
                body_offset=body_offset,
                argument_count=argument_count,
                body_size=body_size,
                instructions=instructions,
            )
        )

    source = (source_path or Path("<memory>")).resolve() if source_path else Path("<memory>")
    return IntProgram(
        source_path=source,
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        procedure_table_offset=STARTUP_SIZE,
        namespace_offset=namespace_offset,
        stringspace_offset=stringspace_offset,
        code_after_metadata_offset=code_start,
        startup=startup,
        startup_tail=startup_tail,
        identifiers=namespace.strings,
        strings=stringspace.strings,
        procedures=tuple(procedures),
        unknown_opcodes=tuple(sorted(unknown)),
    )


def load_int(path: Path | str) -> IntProgram:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise IntFormatError(f"source changed while reading: {source}")
    return parse_int(data, source_path=source)


def _expression_before(
    instructions: tuple[IntInstruction, ...],
    index: int,
) -> tuple[_Expression, int]:
    if index < 0:
        raise IntFormatError("expression extends before procedure start")
    instruction = instructions[index]
    if instruction.opcode == 0xC001:
        return _Expression(str(instruction.argument), int(instruction.argument)), index - 1
    if instruction.opcode == 0x9001:
        return _Expression(json.dumps(instruction.argument, ensure_ascii=False), None), index - 1
    if instruction.opcode == 0xA001:
        return _Expression(str(instruction.argument), None), index - 1
    arity = EXPRESSION_ARITIES.get(instruction.opcode)
    if arity is None:
        raise IntFormatError(f"cannot determine expression arity for 0x{instruction.opcode:04X}")
    children: list[_Expression] = []
    cursor = index - 1
    for _ in range(arity):
        child, cursor = _expression_before(instructions, cursor)
        children.append(child)
    children.reverse()
    constant: int | None = None
    if instruction.opcode == 0x8046 and children[0].constant is not None:
        constant = -children[0].constant
    rendered = f"{instruction.mnemonic}({', '.join(child.text for child in children)})"
    return _Expression(rendered, constant), cursor


def _call_arguments(
    instructions: tuple[IntInstruction, ...],
    index: int,
    names: tuple[str, ...],
) -> dict[str, _Expression] | None:
    expressions: list[_Expression] = []
    cursor = index - 1
    try:
        for _ in names:
            expression, cursor = _expression_before(instructions, cursor)
            expressions.append(expression)
    except IntFormatError:
        return None
    expressions.reverse()
    return dict(zip(names, expressions, strict=True))


def link_messages(
    program: IntProgram,
    msg: MsgDocument | None = None,
) -> tuple[tuple[MessageReference, ...], int | None]:
    raw: list[dict[str, Any]] = []
    procedure_names = {procedure.index: procedure.name for procedure in program.procedures}
    for procedure in program.procedures:
        for index, instruction in enumerate(procedure.instructions):
            call_info = DIALOGUE_CALLS.get(instruction.opcode)
            if call_info is None:
                continue
            call, argument_names = call_info
            arguments = _call_arguments(procedure.instructions, index, argument_names)
            values = {
                name: arguments[name].constant if arguments is not None else None
                for name in argument_names
            }
            message_expression = (
                arguments["message_number"].text if arguments is not None else "<unresolved>"
            )
            target_index = values.get("target_procedure")
            raw.append(
                {
                    "procedure_index": procedure.index,
                    "procedure_name": procedure.name,
                    "instruction_offset": instruction.offset,
                    "call": call,
                    "message_list_id": values.get("message_list_id"),
                    "message_number": values.get("message_number"),
                    "message_expression": message_expression,
                    "intelligence": values.get("intelligence"),
                    "target_procedure_index": target_index,
                    "target_procedure_name": procedure_names.get(target_index),
                    "reaction": values.get("reaction"),
                }
            )

    inferred_list: int | None = None
    effective: dict[int, Any] = {}
    if msg is not None:
        effective = {entry.number: entry for entry in msg.entries if entry.effective}
        scores: Counter[int] = Counter(
            item["message_list_id"]
            for item in raw
            if item["message_list_id"] is not None and item["message_number"] in effective
        )
        if scores:
            best = scores.most_common()
            if len(best) == 1 or best[0][1] > best[1][1]:
                inferred_list = best[0][0]

    references: list[MessageReference] = []
    for item in raw:
        entry = None
        if msg is None:
            status = "no-msg"
        elif item["message_number"] is None:
            status = "dynamic-number"
        elif inferred_list is None:
            status = "ambiguous-message-list"
        elif item["message_list_id"] != inferred_list:
            status = "different-message-list"
        else:
            entry = effective.get(item["message_number"])
            status = "linked" if entry is not None else "missing-number"
        references.append(
            MessageReference(
                **item,
                link_status=status,
                msg_text=entry.text if entry is not None else None,
                msg_audio=entry.audio if entry is not None else None,
            )
        )
    return tuple(references), inferred_list


def int_summary(program: IntProgram, references: Iterable[MessageReference] = ()) -> dict[str, Any]:
    refs = tuple(references)
    return {
        "procedures": len(program.procedures),
        "implemented_procedures": sum(procedure.body_size > 0 for procedure in program.procedures),
        "instructions": len(program.startup)
        + len(program.startup_tail)
        + sum(len(procedure.instructions) for procedure in program.procedures),
        "identifiers": len(program.identifiers),
        "static_strings": len(program.strings),
        "unknown_opcodes": [f"0x{opcode:04X}" for opcode in program.unknown_opcodes],
        "message_references": len(refs),
        "linked_message_references": sum(reference.link_status == "linked" for reference in refs),
    }


def _instruction_dict(instruction: IntInstruction) -> dict[str, Any]:
    payload = asdict(instruction)
    payload["offset_hex"] = f"0x{instruction.offset:08X}"
    payload["opcode_hex"] = f"0x{instruction.opcode:04X}"
    return payload


def _json_payload(
    program: IntProgram,
    references: tuple[MessageReference, ...],
    inferred_list: int | None,
    msg: MsgDocument | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout INT",
        "generator": {"name": "fallout1resource", "version": __version__},
        "source": {
            "path": str(program.source_path),
            "size": program.source_size,
            "sha256": program.source_sha256,
        },
        "layout": {
            "procedure_table_offset": program.procedure_table_offset,
            "namespace_offset": program.namespace_offset,
            "stringspace_offset": program.stringspace_offset,
            "code_after_metadata_offset": program.code_after_metadata_offset,
        },
        "summary": int_summary(program, references),
        "identifiers": [asdict(item) for item in program.identifiers],
        "strings": [asdict(item) for item in program.strings],
        "startup": [_instruction_dict(item) for item in program.startup],
        "startup_tail": [_instruction_dict(item) for item in program.startup_tail],
        "procedures": [
            {
                **{key: value for key, value in asdict(procedure).items() if key != "instructions"},
                "body_offset_hex": f"0x{procedure.body_offset:08X}",
                "instructions": [_instruction_dict(item) for item in procedure.instructions],
            }
            for procedure in program.procedures
        ],
        "message_link": {
            "msg_source": str(msg.source_path) if msg is not None else None,
            "msg_sha256": msg.source_sha256 if msg is not None else None,
            "inferred_message_list_id": inferred_list,
            "inference_method": "unique highest count of literal message numbers found in supplied MSG",
            "references": [asdict(reference) for reference in references],
        },
    }


def _format_instruction(instruction: IntInstruction) -> str:
    argument = ""
    if instruction.argument is not None:
        argument = f" {json.dumps(instruction.argument, ensure_ascii=False)}"
    return f"{instruction.offset:08X}  {instruction.opcode:04X}  {instruction.mnemonic}{argument}"


def _disassembly_text(program: IntProgram, references: tuple[MessageReference, ...]) -> bytes:
    annotations: dict[int, list[str]] = defaultdict(list)
    for reference in references:
        detail = reference.message_expression
        if reference.msg_text is not None:
            detail += f" | {reference.msg_text}"
        annotations[reference.instruction_offset].append(
            f"{reference.call}: list={reference.message_list_id}, message={detail}, status={reference.link_status}"
        )
    lines = [
        "; Fallout INT disassembly (analysis only; not recompilable source)",
        f"; source: {program.source_path}",
        f"; sha256: {program.source_sha256}",
        "",
        ".startup",
    ]
    lines.extend(_format_instruction(item) for item in program.startup)
    lines.append("")
    lines.append(".startup_tail")
    lines.extend(_format_instruction(item) for item in program.startup_tail)
    for procedure in program.procedures:
        lines.extend(
            [
                "",
                f".procedure {procedure.index} {procedure.name} offset=0x{procedure.body_offset:08X} size={procedure.body_size} args={procedure.argument_count} flags=0x{procedure.flags:08X}",
            ]
        )
        for instruction in procedure.instructions:
            lines.append(_format_instruction(instruction))
            lines.extend(f"          ; {note}" for note in annotations.get(instruction.offset, ()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _message_csv(references: tuple[MessageReference, ...]) -> bytes:
    stream = io.StringIO(newline="")
    fieldnames = (
        list(asdict(references[0]).keys())
        if references
        else [
            "procedure_index",
            "procedure_name",
            "instruction_offset",
            "call",
            "message_list_id",
            "message_number",
            "message_expression",
            "intelligence",
            "target_procedure_index",
            "target_procedure_name",
            "reaction",
            "link_status",
            "msg_text",
            "msg_audio",
        ]
    )
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()
    for reference in references:
        writer.writerow(asdict(reference))
    return codecs.BOM_UTF8 + stream.getvalue().encode("utf-8")


def int_output_paths(workspace: Path | str, output: Path | str) -> tuple[Path, Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise ValueError("INT output must use a .json filename")
    return (
        json_path,
        json_path.with_suffix(".disasm.txt"),
        json_path.with_suffix(".messages.csv"),
        json_path.with_suffix(".json.sha256"),
    )


def write_int_export(
    program: IntProgram,
    references: tuple[MessageReference, ...],
    inferred_list: int | None,
    msg: MsgDocument | None,
    workspace: Path | str,
    output: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path, Path]:
    targets = int_output_paths(workspace, output)
    protected_sources = {program.source_path}
    if msg is not None:
        protected_sources.add(msg.source_path)
    if any(target in protected_sources for target in targets):
        raise ValueError("an INT output would replace a source file")
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"output already exists; refusing to overwrite: {existing[0]}")

    json_bytes = (
        json.dumps(
            _json_payload(program, references, inferred_list, msg), ensure_ascii=False, indent=2
        )
        + "\n"
    ).encode("utf-8")
    disassembly = _disassembly_text(program, references)
    messages = _message_csv(references)
    digest = hashlib.sha256(json_bytes).hexdigest().upper()
    checksum = f"{digest}  {targets[0].name}\n".encode("ascii")
    for target, content in zip(targets, (json_bytes, disassembly, messages, checksum), strict=True):
        write_file_atomic(target, content, overwrite=overwrite)
    return targets
