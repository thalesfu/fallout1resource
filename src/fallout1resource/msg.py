"""Decode, parse, and export Fallout message list (MSG) files."""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace
from .safe_io import write_file_atomic


MAX_FIELD_BYTES = 1023


class MsgFormatError(ValueError):
    """Raised when an MSG file cannot be decoded or parsed safely."""


@dataclass(frozen=True, slots=True)
class EncodingCandidate:
    encoding: str
    score: int
    cjk_characters: int
    control_characters: int


@dataclass(frozen=True, slots=True)
class DecodedMsg:
    text: str
    encoding: str
    detection_method: str
    confidence: str
    candidates: tuple[EncodingCandidate, ...]
    newline_style: str


@dataclass(frozen=True, slots=True)
class MsgEntry:
    occurrence: int
    number: int
    number_raw: str
    source_number: str
    audio: str
    source_audio: str
    text: str
    source_text: str
    source_line_start: int
    source_line_end: int
    number_occurrence: int = 1
    number_occurrence_count: int = 1
    effective: bool = True


@dataclass(frozen=True, slots=True)
class MsgDocument:
    source_path: Path
    source_size: int
    source_sha256: str
    decoded: DecodedMsg
    entries: tuple[MsgEntry, ...]


@dataclass(frozen=True, slots=True)
class _Field:
    source_value: str
    engine_value: str
    line_start: int
    line_end: int


def _newline_style(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    present = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    if not present:
        return "none"
    return present[0] if len(present) == 1 else "mixed"


def _candidate_score(text: str) -> tuple[int, int, int]:
    cjk = sum(
        "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff"
        for char in text
    )
    controls = sum(ord(char) < 32 and char not in "\r\n\t" for char in text)
    private_use = sum("\ue000" <= char <= "\uf8ff" for char in text)
    return cjk * 4 - controls * 40 - private_use * 20, cjk, controls


def _decode_strict(data: bytes, encoding: str) -> str | None:
    try:
        return data.decode(encoding, errors="strict")
    except UnicodeDecodeError:
        return None


def decode_msg(data: bytes, *, encoding: str | None = None) -> DecodedMsg:
    """Decode MSG bytes, recording rather than hiding encoding uncertainty."""
    if encoding is not None:
        try:
            canonical = codecs.lookup(encoding).name
            text = data.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            raise MsgFormatError(f"cannot decode MSG with {encoding}: {exc}") from exc
        return DecodedMsg(
            text=text,
            encoding=canonical,
            detection_method="explicit",
            confidence="user-specified",
            candidates=(),
            newline_style=_newline_style(text),
        )

    for bom, codec, label in (
        (codecs.BOM_UTF8, "utf-8-sig", "utf-8-sig"),
        (codecs.BOM_UTF32_LE, "utf-32", "utf-32-le"),
        (codecs.BOM_UTF32_BE, "utf-32", "utf-32-be"),
        (codecs.BOM_UTF16_LE, "utf-16", "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16", "utf-16-be"),
    ):
        if data.startswith(bom):
            text = data.decode(codec, errors="strict")
            return DecodedMsg(text, label, "bom", "high", (), _newline_style(text))

    if all(byte < 0x80 for byte in data):
        text = data.decode("ascii")
        return DecodedMsg(text, "ascii", "ascii-only", "high", (), _newline_style(text))

    utf8 = _decode_strict(data, "utf-8")
    if utf8 is not None:
        return DecodedMsg(utf8, "utf-8", "strict", "high", (), _newline_style(utf8))

    candidates: list[tuple[EncodingCandidate, str]] = []
    for codec in ("gbk", "big5"):
        text = _decode_strict(data, codec)
        if text is None:
            continue
        score, cjk, controls = _candidate_score(text)
        candidates.append((EncodingCandidate(codec, score, cjk, controls), text))
    if not any(candidate.encoding == "gbk" for candidate, _ in candidates):
        text = _decode_strict(data, "gb18030")
        if text is not None:
            score, cjk, controls = _candidate_score(text)
            candidates.append((EncodingCandidate("gb18030", score, cjk, controls), text))
    if candidates:
        candidates.sort(key=lambda item: (item[0].score, item[0].encoding == "gbk"), reverse=True)
        best, text = candidates[0]
        confidence = "medium"
        if len(candidates) > 1 and best.score - candidates[1][0].score < max(20, best.cjk_characters // 10):
            confidence = "low"
        return DecodedMsg(
            text,
            best.encoding,
            "cjk-heuristic",
            confidence,
            tuple(item[0] for item in candidates),
            _newline_style(text),
        )

    text = data.decode("latin-1")
    score, cjk, controls = _candidate_score(text)
    fallback = EncodingCandidate("latin-1", score, cjk, controls)
    return DecodedMsg(text, "latin-1", "lossless-fallback", "low", (fallback,), _newline_style(text))


def _field_byte_length(value: str, encoding: str) -> int:
    codec = "utf-16" if encoding.startswith("utf-16") else encoding
    if codec == "utf-16":
        return len(value.encode(codec)) - len(codecs.BOM_UTF16_LE)
    codec = "utf-32" if encoding.startswith("utf-32") else codec
    if codec == "utf-32":
        return len(value.encode(codec)) - len(codecs.BOM_UTF32_LE)
    return len(value.encode(codec))


def _read_fields(text: str, encoding: str) -> list[_Field]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    fields: list[_Field] = []
    index = 0
    line = 1
    while index < len(normalized):
        while index < len(normalized) and normalized[index] != "{":
            if normalized[index] == "}":
                raise MsgFormatError(f"mismatched closing delimiter at line {line}")
            if normalized[index] == "\n":
                line += 1
            index += 1
        if index == len(normalized):
            break

        line_start = line
        index += 1
        source_chars: list[str] = []
        engine_chars: list[str] = []
        while index < len(normalized) and normalized[index] != "}":
            char = normalized[index]
            if char == "\x00":
                raise MsgFormatError(f"NUL byte in field beginning at line {line_start}")
            source_chars.append(char)
            if char == "\n":
                line += 1
            else:
                engine_chars.append(char)
            index += 1
        if index == len(normalized):
            raise MsgFormatError(f"unterminated field beginning at line {line_start}")

        source_value = "".join(source_chars)
        engine_value = "".join(engine_chars)
        if _field_byte_length(engine_value, encoding) > MAX_FIELD_BYTES:
            raise MsgFormatError(f"field beginning at line {line_start} exceeds {MAX_FIELD_BYTES} bytes")
        fields.append(_Field(source_value, engine_value, line_start, line))
        index += 1
    return fields


def _parse_number(raw: str, line: int) -> int:
    if not raw:
        raise MsgFormatError(f"empty message number at line {line}")
    digits = raw[1:] if raw[0] in "+-" else raw
    if any(char < "0" or char > "9" for char in digits):
        raise MsgFormatError(f"invalid message number {raw!r} at line {line}")
    # The original parser accepts a sign without digits and atoi resolves it to 0.
    return 0 if not digits else int(raw, 10)


def parse_msg(text: str, encoding: str = "utf-8") -> tuple[MsgEntry, ...]:
    fields = _read_fields(text, encoding)
    if len(fields) % 3:
        raise MsgFormatError(f"incomplete MSG record: found {len(fields)} fields")

    entries: list[MsgEntry] = []
    for offset in range(0, len(fields), 3):
        number_field, audio_field, text_field = fields[offset : offset + 3]
        entries.append(
            MsgEntry(
                occurrence=len(entries) + 1,
                number=_parse_number(number_field.engine_value, number_field.line_start),
                number_raw=number_field.engine_value,
                source_number=number_field.source_value,
                audio=audio_field.engine_value,
                source_audio=audio_field.source_value,
                text=text_field.engine_value,
                source_text=text_field.source_value,
                source_line_start=number_field.line_start,
                source_line_end=text_field.line_end,
            )
        )

    totals = Counter(entry.number for entry in entries)
    seen: Counter[int] = Counter()
    annotated: list[MsgEntry] = []
    for entry in entries:
        seen[entry.number] += 1
        annotated.append(
            replace(
                entry,
                number_occurrence=seen[entry.number],
                number_occurrence_count=totals[entry.number],
                effective=seen[entry.number] == totals[entry.number],
            )
        )
    return tuple(annotated)


def load_msg(path: Path | str, *, encoding: str | None = None) -> MsgDocument:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise MsgFormatError(f"source changed while reading: {source}")
    decoded = decode_msg(data, encoding=encoding)
    entries = parse_msg(decoded.text, decoded.encoding)
    return MsgDocument(
        source_path=source,
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        decoded=decoded,
        entries=entries,
    )


def msg_summary(document: MsgDocument) -> dict[str, Any]:
    duplicates = sorted(
        number
        for number, count in Counter(entry.number for entry in document.entries).items()
        if count > 1
    )
    return {
        "entries": len(document.entries),
        "unique_numbers": len({entry.number for entry in document.entries}),
        "duplicate_numbers": duplicates,
        "encoding": document.decoded.encoding,
        "encoding_confidence": document.decoded.confidence,
        "newline_style": document.decoded.newline_style,
    }


def _json_payload(document: MsgDocument) -> dict[str, Any]:
    summary = msg_summary(document)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "format": "Fallout MSG",
        "generator": {"name": "fallout1resource", "version": __version__},
        "source": {
            "path": str(document.source_path),
            "size": document.source_size,
            "sha256": document.source_sha256,
        },
        "decoding": {
            "encoding": document.decoded.encoding,
            "method": document.decoded.detection_method,
            "confidence": document.decoded.confidence,
            "candidates": [asdict(candidate) for candidate in document.decoded.candidates],
            "newline_style": document.decoded.newline_style,
        },
        "summary": summary,
        "semantics": {
            "field_order": ["number", "audio", "text"],
            "newlines_inside_fields": "removed to match the game loader",
            "duplicate_numbers": "all occurrences preserved; the last occurrence is effective",
        },
        "entries": [asdict(entry) for entry in document.entries],
    }


def _csv_bytes(document: MsgDocument) -> bytes:
    stream = io.StringIO(newline="")
    fieldnames = [
        "occurrence",
        "number",
        "number_raw",
        "source_number",
        "audio",
        "source_audio",
        "text",
        "source_text",
        "source_line_start",
        "source_line_end",
        "number_occurrence",
        "number_occurrence_count",
        "effective",
    ]
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()
    for entry in document.entries:
        writer.writerow(asdict(entry))
    return codecs.BOM_UTF8 + stream.getvalue().encode("utf-8")


def msg_output_paths(workspace: Path | str, output: Path | str) -> tuple[Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise ValueError("MSG output must use a .json filename")
    return json_path, json_path.with_suffix(".csv"), json_path.with_suffix(".json.sha256")


def write_msg_export(
    document: MsgDocument,
    workspace: Path | str,
    output: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    json_path, csv_path, hash_path = msg_output_paths(workspace, output)
    targets = (json_path, csv_path, hash_path)
    if any(target == document.source_path for target in targets):
        raise ValueError(f"output would replace the source MSG: {document.source_path}")
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"output already exists; refusing to overwrite: {existing[0]}")

    json_bytes = (json.dumps(_json_payload(document), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    csv_bytes = _csv_bytes(document)
    digest = hashlib.sha256(json_bytes).hexdigest().upper()
    hash_bytes = f"{digest}  {json_path.name}\n".encode("ascii")
    for target, data in zip(targets, (json_bytes, csv_bytes, hash_bytes), strict=True):
        write_file_atomic(target, data, overwrite=overwrite)
    return targets
