#!/usr/bin/env python3
"""Turn one or more Colonist Review Recorder WebM files into an AI-readable JSON report."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops, ImageStat


DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_API_URL = "https://api.openai.com/v1/responses"


EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "timestamp_seconds": {"type": "number", "minimum": 0},
        "actor": {"type": "string"},
        "action": {
            "type": "string",
            "enum": [
                "roll",
                "build_road",
                "build_settlement",
                "upgrade_city",
                "buy_development_card",
                "play_development_card",
                "trade_offer",
                "trade_completed",
                "robber_move",
                "discard",
                "turn_change",
                "game_result",
                "other",
                "unclear",
            ],
        },
        "observation": {"type": "string"},
        "inference": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_timestamps": {
            "type": "array",
            "items": {"type": "number", "minimum": 0},
        },
    },
    "required": [
        "timestamp_seconds",
        "actor",
        "action",
        "observation",
        "inference",
        "confidence",
        "evidence_timestamps",
    ],
}

BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "events": {"type": "array", "items": EVENT_SCHEMA},
        "visible_state": {"type": "string"},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["events", "visible_state", "uncertainties"],
}

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "timestamp_seconds": {"type": "number", "minimum": 0},
        "decision": {"type": "string"},
        "assessment": {"type": "string"},
        "alternative": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "timestamp_seconds",
        "decision",
        "assessment",
        "alternative",
        "confidence",
    ],
}

SUGGESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "priority": {"type": "integer", "minimum": 1, "maximum": 5},
        "topic": {"type": "string"},
        "suggestion": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["priority", "topic", "suggestion", "evidence"],
}

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "game_overview": {"type": "string"},
        "player_assessed": {"type": "string"},
        "timeline": {"type": "array", "items": EVENT_SCHEMA},
        "key_decisions": {"type": "array", "items": DECISION_SCHEMA},
        "suggestions": {"type": "array", "items": SUGGESTION_SCHEMA},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "game_overview",
        "player_assessed",
        "timeline",
        "key_decisions",
        "suggestions",
        "limitations",
    ],
}


@dataclass(frozen=True)
class Frame:
    path: Path
    timestamp_seconds: float
    change_score: float


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs without overriding the process environment."""
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            fail(f"invalid .env entry on line {line_number}: expected KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            fail(f"invalid .env variable name on line {line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def binary_works(binary: str) -> bool:
    try:
        result = subprocess.run(
            [binary, "-version"], capture_output=True, timeout=10, check=False
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def find_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary and not binary_works(binary):
        binary = None

    if not binary and name == "ffmpeg":
        try:
            import imageio_ffmpeg

            bundled = imageio_ffmpeg.get_ffmpeg_exe()
            if binary_works(bundled):
                binary = bundled
        except (ImportError, OSError):
            pass

    if not binary and name == "ffprobe":
        ffmpeg = shutil.which("ffmpeg")
        sibling = Path(ffmpeg).with_name("ffprobe") if ffmpeg else None
        if sibling and sibling.exists() and binary_works(str(sibling)):
            binary = str(sibling)
    if not binary:
        fail(
            f"a working {name} was not found. Run: "
            "python3 -m pip install -r analyzer/requirements.txt"
        )
    return binary


def probe_duration(video: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe and binary_works(ffprobe):
        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())

    ffmpeg = find_binary("ffmpeg")
    result = subprocess.run([ffmpeg, "-i", str(video)], capture_output=True, text=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        fail(f"could not determine duration of {video}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def extract_frames(video: Path, output_dir: Path, every_seconds: float) -> list[Path]:
    ffmpeg = find_binary("ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame-%06d.jpg"
    filter_graph = f"fps=1/{every_seconds},scale='min(1280,iw)':-2"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        filter_graph,
        "-q:v",
        "4",
        str(pattern),
    ]
    subprocess.run(command, check=True)
    return sorted(output_dir.glob("frame-*.jpg"))


def image_change_score(previous: Image.Image, current: Image.Image) -> float:
    previous = previous.convert("RGB").resize((128, 72))
    current = current.convert("RGB").resize((128, 72))
    difference = ImageChops.difference(previous, current)
    means = ImageStat.Stat(difference).mean
    return sum(means) / (len(means) * 255)


def score_frames(paths: list[Path], offset: float, every_seconds: float) -> list[Frame]:
    scored: list[Frame] = []
    previous: Image.Image | None = None

    for index, path in enumerate(paths):
        with Image.open(path) as opened:
            current = opened.copy()
        score = 1.0 if previous is None else image_change_score(previous, current)
        scored.append(Frame(path, offset + index * every_seconds, score))
        previous = current

    return scored


def select_frames(frames: list[Frame], maximum: int, coverage_seconds: float = 45) -> list[Frame]:
    if len(frames) <= maximum:
        return frames

    selected: dict[Path, Frame] = {frames[0].path: frames[0], frames[-1].path: frames[-1]}
    next_coverage = frames[0].timestamp_seconds + coverage_seconds
    for frame in frames:
        if frame.timestamp_seconds >= next_coverage:
            selected[frame.path] = frame
            next_coverage = frame.timestamp_seconds + coverage_seconds

    if len(selected) > maximum:
        ordered = sorted(selected.values(), key=lambda frame: frame.timestamp_seconds)
        step = (len(ordered) - 1) / (maximum - 1)
        return [ordered[round(index * step)] for index in range(maximum)]

    remaining = sorted(
        (frame for frame in frames if frame.path not in selected),
        key=lambda frame: frame.change_score,
        reverse=True,
    )
    for frame in remaining[: maximum - len(selected)]:
        selected[frame.path] = frame

    return sorted(selected.values(), key=lambda frame: frame.timestamp_seconds)


def batched(items: list[Frame], size: int) -> Iterable[list[Frame]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def image_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def response_output_text(response: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                texts.append(content.get("text", ""))
    if not texts:
        raise RuntimeError("the API response did not contain output text")
    return "".join(texts)


def call_responses_api(
    *,
    api_url: str,
    api_key: str,
    model: str,
    instructions: str,
    content: list[dict[str, Any]],
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "model": model,
        "store": False,
        "instructions": instructions,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as result:
            response = json.load(result)
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API returned HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"OpenAI API request failed: {error.reason}") from error

    return json.loads(response_output_text(response))


def analyze_frame_batch(
    frames: list[Frame], *, api_url: str, api_key: str, model: str
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "These are chronological screenshots from a completed Colonist.io game. "
                "Extract only events supported by visible evidence. A screenshot can show "
                "the state after an action rather than the action itself. Put guesses in "
                "inference, lower confidence, and use the supplied timestamps. Do not infer "
                "hidden cards or hidden resources. Duplicate or unclear events may be omitted."
            ),
        }
    ]
    for frame in frames:
        content.append(
            {
                "type": "input_text",
                "text": f"Frame timestamp: {frame.timestamp_seconds:.1f} seconds",
            }
        )
        content.append(
            {
                "type": "input_image",
                "image_url": image_data_url(frame.path),
                "detail": "high",
            }
        )

    return call_responses_api(
        api_url=api_url,
        api_key=api_key,
        model=model,
        instructions=(
            "You are a careful retrospective Catan game observer. Separate visible facts "
            "from inference. Never claim knowledge of face-down development cards, opponents' "
            "resources, or events that the frames do not establish."
        ),
        content=content,
        schema_name="colonist_frame_batch",
        schema=BATCH_SCHEMA,
    )


def consolidate_report(
    batch_results: list[dict[str, Any]], *, api_url: str, api_key: str, model: str
) -> dict[str, Any]:
    content = [
        {
            "type": "input_text",
            "text": (
                "Consolidate the following chronological visual observations into one "
                "post-game review. Deduplicate repeated state observations. Keep uncertain "
                "claims uncertain. Suggestions must be retrospective and cite visible "
                "evidence; do not invent resource counts, hidden cards, or legal alternatives "
                "that cannot be supported. If the user's player color is unclear, say so.\n\n"
                + json.dumps(batch_results, ensure_ascii=False)
            ),
        }
    ]
    return call_responses_api(
        api_url=api_url,
        api_key=api_key,
        model=model,
        instructions=(
            "You are a Catan review coach working only after a game has ended. Produce a "
            "grounded review from the supplied observations, not live assistance."
        ),
        content=content,
        schema_name="colonist_game_review",
        schema=REPORT_SCHEMA,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze completed Colonist.io WebM recordings into structured JSON."
    )
    parser.add_argument("videos", nargs="+", type=Path, help="WebM part(s), in chronological order")
    parser.add_argument("-o", "--output", type=Path, default=Path("colonist-review.json"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--api-url", default=os.getenv("OPENAI_API_URL", DEFAULT_API_URL))
    parser.add_argument("--sample-every", type=float, default=4.0, metavar="SECONDS")
    parser.add_argument("--max-frames", type=int, default=96)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="extract selected frames and a manifest without calling an AI API",
    )
    parser.add_argument(
        "--frames-dir",
        type=Path,
        help="keep selected frames here (required with --extract-only)",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    for video in args.videos:
        if not video.is_file():
            fail(f"video does not exist: {video}")
    if args.sample_every <= 0:
        fail("--sample-every must be greater than zero")
    if args.max_frames < 2:
        fail("--max-frames must be at least 2")
    if not 1 <= args.batch_size <= 10:
        fail("--batch-size must be between 1 and 10")
    if args.extract_only and not args.frames_dir:
        fail("--frames-dir is required with --extract-only")


def copy_selected_frames(frames: list[Frame], destination: Path) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for index, frame in enumerate(frames, start=1):
        filename = f"{index:04d}-{frame.timestamp_seconds:010.1f}s.jpg"
        target = destination / filename
        shutil.copy2(frame.path, target)
        manifest.append(
            {
                "file": filename,
                "timestamp_seconds": round(frame.timestamp_seconds, 3),
                "change_score": round(frame.change_score, 6),
            }
        )
    return manifest


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    args = parse_args()
    validate_args(args)
    find_binary("ffmpeg")

    if not args.extract_only and not os.getenv("OPENAI_API_KEY"):
        fail("set OPENAI_API_KEY, or use --extract-only to test frame selection")

    with tempfile.TemporaryDirectory(prefix="colonist-review-") as temporary:
        temporary_path = Path(temporary)
        all_frames: list[Frame] = []
        offset = 0.0

        for index, video in enumerate(args.videos, start=1):
            print(f"Extracting {video}…", file=sys.stderr)
            paths = extract_frames(
                video.resolve(), temporary_path / f"part-{index:02d}", args.sample_every
            )
            all_frames.extend(score_frames(paths, offset, args.sample_every))
            offset += probe_duration(video.resolve())

        if not all_frames:
            fail("ffmpeg extracted no frames from the supplied video(s)")

        selected = select_frames(all_frames, args.max_frames)
        print(f"Selected {len(selected)} of {len(all_frames)} sampled frames.", file=sys.stderr)

        if args.frames_dir:
            frames_manifest = copy_selected_frames(selected, args.frames_dir)
        else:
            frames_manifest = [
                {
                    "timestamp_seconds": round(frame.timestamp_seconds, 3),
                    "change_score": round(frame.change_score, 6),
                }
                for frame in selected
            ]

        if args.extract_only:
            manifest_path = args.frames_dir / "frames.json"
            write_json(
                manifest_path,
                {
                    "source_videos": [str(video.resolve()) for video in args.videos],
                    "sample_every_seconds": args.sample_every,
                    "frames": frames_manifest,
                },
            )
            print(f"Wrote {manifest_path}", file=sys.stderr)
            return

        api_key = os.environ["OPENAI_API_KEY"]
        batch_results: list[dict[str, Any]] = []
        batches = list(batched(selected, args.batch_size))
        for index, frame_batch in enumerate(batches, start=1):
            print(f"Analyzing frame batch {index}/{len(batches)}…", file=sys.stderr)
            batch_results.append(
                analyze_frame_batch(
                    frame_batch,
                    api_url=args.api_url,
                    api_key=api_key,
                    model=args.model,
                )
            )

        print("Building final review…", file=sys.stderr)
        report = consolidate_report(
            batch_results,
            api_url=args.api_url,
            api_key=api_key,
            model=args.model,
        )
        output = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_videos": [str(video.resolve()) for video in args.videos],
            "model": args.model,
            "sample_every_seconds": args.sample_every,
            "sampled_frame_count": len(all_frames),
            "analyzed_frame_count": len(selected),
            "review": report,
        }
        write_json(args.output, output)
        print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
