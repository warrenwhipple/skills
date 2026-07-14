#!/usr/bin/env python3
"""Convert yt-dlp YouTube metadata and json3 captions to Markdown."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import textwrap
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert yt-dlp .info.json and YouTube json3 captions to Markdown."
    )
    parser.add_argument("info_json", type=Path, help="Path to yt-dlp .info.json")
    parser.add_argument("captions_json3", type=Path, help="Path to YouTube .json3 captions")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output Markdown path. Defaults beside info_json using the video ID.",
    )
    parser.add_argument(
        "--target-seconds",
        type=int,
        default=30,
        help="Approximate transcript paragraph size in seconds.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=0,
        help="Wrap transcript paragraphs to this width. 0 disables wrapping.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def clean_filename(value: str) -> str:
    value = re.sub(r"[^\w\s.,'&()\\[\\]-]", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "youtube transcript"


def default_output_path(info_json: Path, info: dict[str, Any]) -> Path:
    video_id = info.get("id")
    if isinstance(video_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{6,32}", video_id):
        return info_json.with_name(f"{video_id}.youtube-transcript.md")
    title = clean_filename(info.get("title") or info_json.stem)
    return info_json.with_name(f"{title} YouTube transcript.md")


def format_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.strptime(value, "%Y%m%d")
        return f"{parsed:%b} {parsed.day}, {parsed:%Y}"
    except ValueError:
        return value


def format_duration(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_timestamp(ms: int | float | None) -> str:
    total_seconds = int((ms or 0) // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_count(value: int | None) -> str | None:
    if value is None:
        return None
    return f"{value:,}"


def event_text(event: dict[str, Any]) -> str:
    segs = event.get("segs") or []
    text = join_fragments([str(seg.get("utf8", "")) for seg in segs])
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left.endswith((" ", "\n", "(", "[")):
        return False
    if right.startswith((" ", "\n", ".", ",", "?", "!", ":", ";", ")", "]")):
        return False
    return True


def join_fragments(fragments: list[str]) -> str:
    text = ""
    for fragment in fragments:
        if not fragment:
            continue
        if needs_space(text, fragment):
            text += " "
        text += fragment
    return text.strip()


def caption_rows(captions: dict[str, Any]) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for event in captions.get("events", []):
        text = event_text(event)
        if not text:
            continue
        rows.append((int(event.get("tStartMs") or 0), text))
    return rows


def paragraphize(rows: list[tuple[int, str]], target_seconds: int) -> list[tuple[int, str]]:
    paragraphs: list[tuple[int, str]] = []
    current_start: int | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_start, current_parts
        if current_start is not None and current_parts:
            paragraphs.append((current_start, join_fragments(current_parts)))
        current_start = None
        current_parts = []

    for start_ms, text in rows:
        if current_start is None:
            current_start = start_ms

        elapsed_seconds = (start_ms - current_start) / 1000
        current_parts.append(text)
        current_text = join_fragments(current_parts)

        ends_sentence = bool(re.search(r'[.!?]["\')\]]?$', current_text))
        long_enough = elapsed_seconds >= target_seconds
        quite_long = elapsed_seconds >= target_seconds * 1.8
        enough_words = len(current_text.split()) >= 45

        if (long_enough and ends_sentence and enough_words) or quite_long:
            flush()

    flush()
    return paragraphs


def markdown_for(info: dict[str, Any], paragraphs: list[tuple[int, str]], width: int) -> str:
    title = info.get("title") or info.get("fulltitle") or "Untitled YouTube video"
    url = info.get("webpage_url") or info.get("original_url") or ""
    uploader = info.get("uploader") or info.get("channel")
    upload_date = format_date(info.get("upload_date"))
    duration = format_duration(info.get("duration"))
    view_count = format_count(info.get("view_count"))
    like_count = format_count(info.get("like_count"))
    description = (info.get("description") or "").strip()

    metadata_lines = []
    if uploader:
        metadata_lines.append(str(uploader))
    if upload_date:
        metadata_lines.append(f"Published {upload_date}")
    if duration:
        metadata_lines.append(f"Duration {duration}")
    if view_count:
        metadata_lines.append(f"{view_count} views")
    if like_count:
        metadata_lines.append(f"{like_count} likes")

    out: list[str] = []
    if url:
        out.extend([f"[{title}]({url})", ""])
    out.extend(["## Title", "", str(title), "", "## Metadata", ""])
    out.extend(metadata_lines or ["No metadata extracted."])
    out.extend(["", "## Creator Description", "", description or "No description extracted."])
    out.extend(["", "## Extracted Transcript", ""])

    for start_ms, text in paragraphs:
        out.append(format_timestamp(start_ms))
        out.append("")
        if width > 0:
            out.append(textwrap.fill(text, width=width))
        else:
            out.append(text)
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    args = parse_args()
    info = load_json(args.info_json)
    captions = load_json(args.captions_json3)
    paragraphs = paragraphize(caption_rows(captions), args.target_seconds)

    output = args.output
    if output is None:
        output = default_output_path(args.info_json, info)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown_for(info, paragraphs, args.width), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
