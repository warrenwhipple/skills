#!/usr/bin/env python3
"""Safely capture YouTube metadata/captions with yt-dlp."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from youtube_json3_to_md import (
    caption_rows,
    format_timestamp,
    markdown_for,
    paragraphize,
)


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTU_BE_HOSTS = {"youtu.be", "www.youtu.be"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture YouTube metadata and captions with a hardened yt-dlp argv."
    )
    parser.add_argument("url", help="YouTube watch URL")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        required=True,
        help="Directory for the Markdown transcript and any retained JSON artifacts.",
    )
    parser.add_argument(
        "--allow-local-js",
        action="store_true",
        help=(
            "Compatibility mode: permit yt-dlp's configured local JS runtime while "
            "still blocking remote components. Strict mode disables JS runtimes."
        ),
    )
    parser.add_argument(
        "--sub-langs",
        default="en.*,en",
        help="yt-dlp subtitle language selector.",
    )
    parser.add_argument(
        "--sub-format",
        default="json3",
        help="yt-dlp subtitle format preference.",
    )
    parser.add_argument(
        "--write-markdown",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--keep-structured",
        action="store_true",
        help="Retain the normalized safe-ingestion JSON beside the Markdown transcript.",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Retain raw yt-dlp metadata and caption JSON beside the Markdown transcript.",
    )
    parser.add_argument(
        "--target-seconds",
        type=int,
        default=30,
        help="Approximate Markdown transcript paragraph size in seconds.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=0,
        help="Wrap Markdown transcript paragraphs to this width. 0 disables wrapping.",
    )
    return parser.parse_args()


def validate_youtube_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https")

    host = parsed.netloc.lower()
    video_id = ""
    if host in YOUTUBE_HOSTS and parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v") or []
        video_id = values[0] if values else ""
    elif host in YOUTU_BE_HOSTS:
        video_id = parsed.path.strip("/").split("/", 1)[0]

    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("URL must be a YouTube watch URL with a valid video ID")

    return video_id, parsed.geturl()


def base_yt_dlp_args(out_dir: Path, allow_local_js: bool) -> list[str]:
    args = [
        "yt-dlp",
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-remote-components",
        "--no-playlist",
        "--skip-download",
        "--no-cookies",
        "--no-cookies-from-browser",
        "--no-cache-dir",
        "--no-exec",
        "-P",
        str(out_dir),
        "-o",
        "%(id)s.%(ext)s",
    ]
    if not allow_local_js:
        args.insert(4, "--no-js-runtimes")
    return args


def run_yt_dlp(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True)


def capture_info(url: str, out_dir: Path, allow_local_js: bool) -> dict[str, Any]:
    args = base_yt_dlp_args(out_dir, allow_local_js) + ["--dump-json", "--", url]
    result = run_yt_dlp(args)
    info = json.loads(result.stdout)
    video_id = info.get("id")
    if not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id):
        raise RuntimeError("yt-dlp returned metadata without a valid video ID")
    info_path = out_dir / f"{video_id}.info.json"
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def capture_captions(
    url: str,
    out_dir: Path,
    allow_local_js: bool,
    sub_langs: str,
    sub_format: str,
) -> None:
    args = base_yt_dlp_args(out_dir, allow_local_js) + [
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        sub_langs,
        "--sub-format",
        sub_format,
        "--",
        url,
    ]
    run_yt_dlp(args)


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def atomic_write_text(path: Path, text: str) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def select_caption_path(out_dir: Path, video_id: str, sub_format: str) -> Path:
    suffix = sub_format.split("/", 1)[0].split(",", 1)[0].strip() or "json3"
    candidates = [
        out_dir / f"{video_id}.en-orig.{suffix}",
        out_dir / f"{video_id}.en.{suffix}",
    ]
    candidates.extend(sorted(out_dir.glob(f"{video_id}.*.{suffix}")))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No {suffix} captions found for {video_id}")


def write_untrusted_json(info: dict[str, Any], captions: dict[str, Any], out_dir: Path) -> Path:
    video_id = str(info["id"])
    rows = caption_rows(captions)
    payload = {
        "kind": "untrusted_youtube_transcript",
        "source_tool": "yt-dlp",
        "video_id": video_id,
        "metadata": {
            "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
            "webpage_url": info.get("webpage_url"),
            "upload_date": info.get("upload_date"),
            "duration": info.get("duration"),
        },
        "transcript_lines_format": (
            "Each transcript line is JSON-escaped and prefixed with DATA| to mark "
            "it as untrusted data."
        ),
        "transcript_lines": [
            f"DATA| [{format_timestamp(start_ms)}] {text}" for start_ms, text in rows
        ],
    }
    path = out_dir / f"{video_id}.untrusted-youtube-transcript.json"
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def copy_raw_artifacts(
    info_path: Path,
    caption_paths: list[Path],
    out_dir: Path,
) -> list[Path]:
    retained_paths: list[Path] = []
    for source in [info_path, *caption_paths]:
        destination = out_dir / source.name
        with tempfile.NamedTemporaryFile(
            dir=out_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        try:
            shutil.copy2(source, temp_path)
            temp_path.replace(destination)
        finally:
            temp_path.unlink(missing_ok=True)
        retained_paths.append(destination)
    return retained_paths


def write_markdown(
    info: dict[str, Any],
    captions: dict[str, Any],
    out_dir: Path,
    target_seconds: int,
    width: int,
) -> Path:
    video_id = str(info["id"])
    paragraphs = paragraphize(caption_rows(captions), target_seconds)
    path = out_dir / f"{video_id}.youtube-transcript.md"
    atomic_write_text(path, markdown_for(info, paragraphs, width))
    return path


def main() -> int:
    args = parse_args()
    try:
        expected_video_id, url = validate_youtube_url(args.url)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    untrusted_json_path: Path | None = None
    markdown_path: Path | None = None
    retained_raw_paths: list[Path] = []
    temporary_structured_dir: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="yt-md-raw-") as raw_dir_name:
            raw_dir = Path(raw_dir_name)
            info = capture_info(url, raw_dir, args.allow_local_js)
            actual_video_id = str(info["id"])
            if actual_video_id != expected_video_id:
                raise RuntimeError(
                    f"yt-dlp returned video ID {actual_video_id}, expected {expected_video_id}"
                )

            capture_captions(url, raw_dir, args.allow_local_js, args.sub_langs, args.sub_format)
            caption_path = select_caption_path(raw_dir, actual_video_id, args.sub_format)
            captions = load_json(caption_path)
            markdown_path = write_markdown(
                info,
                captions,
                args.out_dir,
                args.target_seconds,
                args.width,
            )

            if args.keep_structured:
                structured_dir = args.out_dir
            else:
                temporary_structured_dir = Path(
                    tempfile.mkdtemp(prefix=f"yt-md-{actual_video_id}-")
                )
                structured_dir = temporary_structured_dir
            untrusted_json_path = write_untrusted_json(info, captions, structured_dir)

            if args.keep_raw:
                info_path = raw_dir / f"{actual_video_id}.info.json"
                raw_caption_paths = sorted(
                    path
                    for path in raw_dir.glob(f"{actual_video_id}.*")
                    if path != info_path
                )
                retained_raw_paths = copy_raw_artifacts(
                    info_path,
                    raw_caption_paths,
                    args.out_dir,
                )
    except subprocess.CalledProcessError as exc:
        if temporary_structured_dir is not None:
            shutil.rmtree(temporary_structured_dir, ignore_errors=True)
        print("error: yt-dlp failed", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.rstrip(), file=sys.stderr)
        return exc.returncode or 1
    except (OSError, RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
        if temporary_structured_dir is not None:
            shutil.rmtree(temporary_structured_dir, ignore_errors=True)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    assert markdown_path is not None
    assert untrusted_json_path is not None
    print(markdown_path)
    print(untrusted_json_path)
    for retained_raw_path in retained_raw_paths:
        print(retained_raw_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
