#!/usr/bin/env python3
"""Extract and synchronize Fallout 1 "Tell Me About" character topics."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


TOPIC_TITLE = "可以谈论的主题"
NEGATIVE_HELP_MARKERS = (
    "不能告诉你什么",
    "无法告诉你什么",
    "can't tell you",
    "cannot tell you",
)
NORMALIZED_ENGLISH = {
    "Vault13": "Vault 13",
    "Vault-13": "Vault 13",
    "Waterchip": "Water Chip",
}


@dataclass(frozen=True)
class Topic:
    keyword: str
    full_name: str
    answer: str
    message_number: int


def _load_effective(path: Path) -> dict[int, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    messages: dict[int, str] = {}
    for entry in data.get("entries", []):
        if entry.get("effective", True):
            messages[int(entry["number"])] = str(entry.get("text") or "").strip()
    return messages


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _negative_help(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in NEGATIVE_HELP_MARKERS)


def _help_topics(help_text: str, candidates: list[str] | None = None) -> list[tuple[str, str]]:
    parts = re.split(r"[:：]", help_text, maxsplit=1)
    if len(parts) != 2:
        return []
    values = [part.strip().rstrip("。.") for part in re.split(r"[、，,]", parts[1])]
    topics: list[tuple[str, str]] = []
    candidates = sorted((value for value in (candidates or []) if value), key=len, reverse=True)
    for part in values:
        if not part:
            continue
        prefix = ""
        translation = ""
        for candidate in candidates:
            if not part.casefold().startswith(candidate.casefold()):
                continue
            following = part[len(candidate) : len(candidate) + 1]
            if following and (following.isascii() and following.isalnum()):
                continue
            prefix = candidate
            translation = part[len(candidate) :].lstrip("-－—–:： ‘'\"“” ").strip()
            break
        if not prefix:
            cjk = re.search(r"[\u3400-\u9fff]", part)
            if cjk:
                prefix = part[: cjk.start()].rstrip("-－—–:： ‘'\"“” ")
                translation = part[cjk.start() :].strip()
            elif "-" in part:
                prefix, translation = (value.strip() for value in part.rsplit("-", 1))
            else:
                prefix, translation = part, ""
        if prefix:
            topics.append((prefix, translation))
    return topics


def _localized_answer(
    number: int,
    keyword: str,
    translation: str,
    current: dict[int, str],
    master_answer: str,
) -> str:
    answer_slot = current.get(number + 100, "")
    keyword_slot = current.get(number, "")
    if _has_cjk(answer_slot):
        return answer_slot
    # Some Chinese MSG files accidentally put localized answers in 1000-series
    # keyword slots while leaving an English duplicate in the 1100-series.
    # Prefer that localized text only when it is not merely the translated label.
    if _has_cjk(keyword_slot):
        compact = keyword_slot.strip().rstrip("。.")
        translated = translation.strip().rstrip("。.")
        if compact != translated:
            return keyword_slot
    if answer_slot:
        return answer_slot
    if keyword_slot and keyword_slot.casefold() != keyword.casefold() and not translation:
        return keyword_slot
    return master_answer


def topic_records(resource_root: Path, script_name: str) -> list[Topic]:
    """Return complete effective keyword/answer records for one character script."""
    stem = Path(script_name).stem.upper()
    if not stem:
        return []
    current_path = resource_root / f"workspace/output/text/data/TEXT/ENGLISH/DIALOG/{stem}.json"
    master_path = resource_root / f"workspace/output/text/master/TEXT/ENGLISH/DIALOG/{stem}.json"
    current = _load_effective(current_path)
    master = _load_effective(master_path)
    if not current and not master:
        return []
    help_text = current.get(1199) or master.get(1199, "")
    if not help_text or _negative_help(help_text):
        return []

    canonical = master or current
    candidate_keywords = [canonical.get(number, "") for number in range(1000, 1099)]
    listed_topics = _help_topics(help_text, candidate_keywords)
    if not listed_topics:
        return []
    topics = []
    for offset, (keyword, translation) in enumerate(listed_topics):
        number = 1000 + offset
        master_keyword = canonical.get(number, "")
        master_answer = canonical.get(number + 100, "")
        # A few original MSG files (notably GARL) place the first answer in
        # the 1000-series and omit the corresponding keyword/1100 entry. The
        # ordered 1199 help list still supplies the missing keyword.
        if not master_answer and master_keyword.casefold() != keyword.casefold():
            master_answer = master_keyword
        if not master_answer:
            continue
        english = NORMALIZED_ENGLISH.get(keyword, keyword)
        full_name = f"{english}（{translation}）" if translation else english
        topics.append(
            Topic(
                keyword=keyword,
                full_name=full_name,
                answer=_localized_answer(number, keyword, translation, current, master_answer),
                message_number=number,
            )
        )
    return topics


def _cell(value: str) -> str:
    return value.replace("\r\n", "<br>").replace("\n", "<br>").replace("|", "\\|")


def render_topic_section(topics: list[Topic], level: int = 1, names: dict[str, str] | None = None) -> str:
    if not topics:
        return ""
    names = names or {}
    lines = [
        f"{'#' * level} {TOPIC_TITLE}",
        "",
        "| 关键字 | 关键字实际的全名（中英文） | 内容 |",
        "|---|---|---|",
    ]
    for topic in topics:
        full_name = names.get(topic.keyword, topic.full_name)
        lines.append(f"| {_cell(topic.keyword)} | {_cell(full_name)} | {_cell(topic.answer)} |")
    return "\n".join(lines)


def _split_table_row(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", body)]


def parse_topic_table(text: str) -> tuple[int | None, list[tuple[str, str, str]], dict[str, str]]:
    heading = re.search(rf"(?m)^(#{{1,6}}) {re.escape(TOPIC_TITLE)}\s*$", text)
    if not heading:
        return None, [], {}
    level = len(heading.group(1))
    tail = text[heading.end():]
    end = re.search(rf"(?m)^#{{1,{level}}} ", tail)
    body = tail[: end.start()] if end else tail
    rows: list[tuple[str, str, str]] = []
    names: dict[str, str] = {}
    for line in body.splitlines():
        if not line.startswith("|") or re.match(r"^\|\s*:?-", line):
            continue
        cells = _split_table_row(line)
        if len(cells) != 3 or cells[0] == "关键字":
            continue
        rows.append((cells[0], cells[1], cells[2]))
        names[cells[0]] = cells[1]
    return level, rows, names


def _topic_bounds(text: str) -> tuple[int, int, int] | None:
    heading = re.search(rf"(?m)^(#{{1,6}}) {re.escape(TOPIC_TITLE)}\s*$", text)
    if not heading:
        return None
    level = len(heading.group(1))
    tail = text[heading.end():]
    next_heading = re.search(rf"(?m)^#{{1,{level}}} ", tail)
    end = heading.end() + (next_heading.start() if next_heading else len(tail))
    while end > heading.start() and text[end - 1] == "\n":
        end -= 1
    return heading.start(), end, level


def _document_section_level(text: str) -> int:
    if re.search(r"(?m)^# 名称\s*$", text):
        return 1
    if re.search(r"(?m)^## 名称\s*$", text):
        return 2
    return 1


def synchronize_note(text: str, topics: list[Topic]) -> tuple[str, bool]:
    """Insert or replace one note's topic table while preserving valid curated names."""
    if not topics:
        return text, False
    level, rows, names = parse_topic_table(text)
    expected = {(topic.keyword, topic.answer) for topic in topics}
    actual = {(keyword, answer) for keyword, _, answer in rows}
    if len(rows) == len(topics) and actual == expected:
        return text, False
    level = level or _document_section_level(text)
    replacement = render_topic_section(topics, level=level, names=names)
    bounds = _topic_bounds(text)
    if bounds:
        start, end, _ = bounds
        updated = text[:start].rstrip() + "\n\n" + replacement + "\n\n" + text[end:].lstrip()
        return updated.rstrip() + "\n", True

    later_titles = (
        "对话",
        "身份与处境",
        "生平",
        "性格与言行",
        "他人评价",
        "掌握的信息",
        "任务关联",
        "未确定的信息",
    )
    anchor = None
    for title in later_titles:
        found = re.search(rf"(?m)^{'#' * level} {re.escape(title)}\s*$", text)
        if found and (anchor is None or found.start() < anchor):
            anchor = found.start()
    if anchor is None:
        return text.rstrip() + "\n\n" + replacement + "\n", True
    updated = text[:anchor].rstrip() + "\n\n" + replacement + "\n\n" + text[anchor:].lstrip()
    return updated.rstrip() + "\n", True


def note_script(text: str) -> str:
    match = re.search(r"(?m)^resource_script:\s*`?([^.\s`]+)\.INT`?\s*$", text)
    if match:
        return match.group(1).upper()
    match = re.search(r"(?m)^\| 人物脚本 \|\s*`?([^.\s`]+)\.INT`?\s*\|$", text)
    return match.group(1).upper() if match else ""


def character_notes(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if "人物" in path.parts
        and any(part in {"Named Characters 专名人物", "Generic Characters 普通人物"} for part in path.parts)
    )


def sync_tree(root: Path, resource_root: Path, check: bool = False) -> dict[str, int]:
    stats = {"notes": 0, "topic_notes": 0, "topic_rows": 0, "changed": 0}
    for note in character_notes(root):
        stats["notes"] += 1
        text = note.read_text(encoding="utf-8")
        topics = topic_records(resource_root, note_script(text))
        if not topics:
            continue
        stats["topic_notes"] += 1
        stats["topic_rows"] += len(topics)
        updated, changed = synchronize_note(text, topics)
        if changed:
            stats["changed"] += 1
            if not check:
                note.write_text(updated, encoding="utf-8")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Location package or vault subtree")
    parser.add_argument("--resource-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Report drift without modifying notes")
    args = parser.parse_args()
    stats = sync_tree(args.root.resolve(), args.resource_root.resolve(), check=args.check)
    print(" ".join(f"{key}={value}" for key, value in stats.items()))
    return 1 if args.check and stats["changed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
