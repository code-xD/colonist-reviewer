#!/usr/bin/env python3
"""Turn one or more Colonist Review Recorder WebM files into an AI-readable JSON report."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
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

VISIBLE_PLAYER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "username": {"type": "string"},
        "color": {"type": "string"},
        "public_points": {"type": ["integer", "null"]},
        "resource_count": {"type": ["integer", "null"]},
    },
    "required": ["username", "color", "public_points", "resource_count"],
}

VISIBLE_TILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "x": {"type": "number", "minimum": 0, "maximum": 1},
        "y": {"type": "number", "minimum": 0, "maximum": 1},
        "resource": {"type": "string"},
        "dice_number": {"type": ["integer", "null"]},
    },
    "required": ["x", "y", "resource", "dice_number"],
}

VISIBLE_BUILDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "x": {"type": "number", "minimum": 0, "maximum": 1},
        "y": {"type": "number", "minimum": 0, "maximum": 1},
        "owner": {"type": "string"},
        "color": {"type": "string"},
        "kind": {"type": "string", "enum": ["settlement", "city"]},
    },
    "required": ["x", "y", "owner", "color", "kind"],
}

VISIBLE_ROAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "start_x": {"type": "number", "minimum": 0, "maximum": 1},
        "start_y": {"type": "number", "minimum": 0, "maximum": 1},
        "end_x": {"type": "number", "minimum": 0, "maximum": 1},
        "end_y": {"type": "number", "minimum": 0, "maximum": 1},
        "owner": {"type": "string"},
        "color": {"type": "string"},
    },
    "required": ["start_x", "start_y", "end_x", "end_y", "owner", "color"],
}

BOARD_SNAPSHOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "timestamp_seconds": {"type": "number", "minimum": 0},
        "active_player": {"type": "string"},
        "players": {"type": "array", "items": VISIBLE_PLAYER_SCHEMA},
        "tiles": {"type": "array", "items": VISIBLE_TILE_SCHEMA},
        "buildings": {"type": "array", "items": VISIBLE_BUILDING_SCHEMA},
        "roads": {"type": "array", "items": VISIBLE_ROAD_SCHEMA},
        "robber_x": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "robber_y": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "timestamp_seconds", "active_player", "players", "tiles", "buildings",
        "roads", "robber_x", "robber_y", "confidence",
    ],
}

BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "events": {"type": "array", "items": EVENT_SCHEMA},
        "board_snapshots": {"type": "array", "items": BOARD_SNAPSHOT_SCHEMA},
        "visible_state": {"type": "string"},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["events", "board_snapshots", "visible_state", "uncertainties"],
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


def canonical_topology() -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[tuple[int, int]]]:
    row_lengths = [3, 4, 5, 4, 3]
    centers: list[tuple[float, float]] = []
    for row, length in enumerate(row_lengths):
        offset = abs(2 - row) * 0.5
        for column in range(length):
            centers.append(((offset + column) * 3**0.5, row * 1.5))

    corner_lookup: dict[tuple[float, float], int] = {}
    edges: set[tuple[int, int]] = set()
    for center_x, center_y in centers:
        tile_corners: list[int] = []
        for corner in range(6):
            angle = (60 * corner - 30) * 3.141592653589793 / 180
            point = (round(center_x + math.cos(angle), 4), round(center_y + math.sin(angle), 4))
            if point not in corner_lookup:
                corner_lookup[point] = len(corner_lookup)
            tile_corners.append(corner_lookup[point])
        for corner in range(6):
            edges.add(tuple(sorted((tile_corners[corner], tile_corners[(corner + 1) % 6]))))

    ordered_corners = sorted(corner_lookup, key=lambda point: (point[1], point[0]))
    corner_remap = {corner_lookup[point]: index for index, point in enumerate(ordered_corners)}
    ordered_edges = sorted(
        ((corner_remap[start], corner_remap[end]) for start, end in edges),
        key=lambda edge: (
            (ordered_corners[edge[0]][1] + ordered_corners[edge[1]][1]) / 2,
            (ordered_corners[edge[0]][0] + ordered_corners[edge[1]][0]) / 2,
        ),
    )
    return centers, ordered_corners, ordered_edges


def canonicalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    tiles = snapshot.get("tiles", [])
    if len(tiles) != 19:
        return None

    row_lengths = [3, 4, 5, 4, 3]
    ordered_tiles: list[dict[str, Any]] = []
    by_y = sorted(tiles, key=lambda tile: (tile["y"], tile["x"]))
    position = 0
    for length in row_lengths:
        ordered_tiles.extend(sorted(by_y[position : position + length], key=lambda tile: tile["x"]))
        position += length

    centers, corners, edges = canonical_topology()
    observed_x = [tile["x"] for tile in ordered_tiles]
    observed_y = [tile["y"] for tile in ordered_tiles]
    canonical_x = [point[0] for point in centers]
    canonical_y = [point[1] for point in centers]

    def transform(x: float, y: float) -> tuple[float, float]:
        mapped_x = min(canonical_x) + (x - min(observed_x)) * (max(canonical_x) - min(canonical_x)) / (max(observed_x) - min(observed_x))
        mapped_y = min(canonical_y) + (y - min(observed_y)) * (max(canonical_y) - min(canonical_y)) / (max(observed_y) - min(observed_y))
        return mapped_x, mapped_y

    def nearest_index(point: tuple[float, float], candidates: list[tuple[float, float]]) -> int:
        return min(range(len(candidates)), key=lambda index: (candidates[index][0] - point[0]) ** 2 + (candidates[index][1] - point[1]) ** 2)

    edge_midpoints = [
        ((corners[start][0] + corners[end][0]) / 2, (corners[start][1] + corners[end][1]) / 2)
        for start, end in edges
    ]
    buildings = [
        {
            "corner_index": nearest_index(transform(building["x"], building["y"]), corners),
            "owner": building["owner"],
            "color": building["color"],
            "kind": building["kind"],
        }
        for building in snapshot.get("buildings", [])
    ]
    roads = [
        {
            "edge_index": nearest_index(
                transform(
                    (road["start_x"] + road["end_x"]) / 2,
                    (road["start_y"] + road["end_y"]) / 2,
                ),
                edge_midpoints,
            ),
            "owner": road["owner"],
            "color": road["color"],
        }
        for road in snapshot.get("roads", [])
    ]
    robber_tile_index = None
    if snapshot.get("robber_x") is not None and snapshot.get("robber_y") is not None:
        robber_tile_index = nearest_index(transform(snapshot["robber_x"], snapshot["robber_y"]), centers)

    return {
        "timestamp_seconds": snapshot["timestamp_seconds"],
        "active_player": snapshot["active_player"],
        "players": snapshot["players"],
        "tiles": [
            {"tile_index": index, "resource": tile["resource"], "dice_number": tile["dice_number"]}
            for index, tile in enumerate(ordered_tiles)
        ],
        "buildings": buildings,
        "roads": roads,
        "robber_tile_index": robber_tile_index,
        "confidence": snapshot["confidence"],
    }


def stabilize_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots = sorted(snapshots, key=lambda snapshot: snapshot["timestamp_seconds"])

    def most_common(values: Iterable[Any]) -> Any:
        counts = Counter(values)
        return counts.most_common(1)[0][0] if counts else None

    name_counts = Counter(
        player["username"] for snapshot in snapshots for player in snapshot["players"]
    )
    raw_player_colors = {
        username: most_common(
            player["color"]
            for snapshot in snapshots
            for player in snapshot["players"]
            if player["username"] == username
        )
        for username in name_counts
    }
    name_aliases: dict[str, str] = {}
    canonical_names: list[str] = []
    for username, _ in name_counts.most_common():
        match = next(
            (
                canonical
                for canonical in canonical_names
                if raw_player_colors[canonical] == raw_player_colors[username]
                and SequenceMatcher(None, canonical.lower(), username.lower()).ratio() >= 0.82
            ),
            None,
        )
        name_aliases[username] = match or username
        if not match:
            canonical_names.append(username)

    def normalized_name(username: str) -> str:
        return name_aliases.get(username, username)

    tile_resources = {
        index: most_common(
            tile["resource"]
            for snapshot in snapshots
            for tile in snapshot["tiles"]
            if tile["tile_index"] == index
        )
        for index in range(19)
    }
    tile_numbers = {
        index: most_common(
            tile["dice_number"]
            for snapshot in snapshots
            for tile in snapshot["tiles"]
            if tile["tile_index"] == index
        )
        for index in range(19)
    }
    usernames = set(name_aliases.values())
    player_colors = {
        username: most_common(
            player["color"]
            for snapshot in snapshots
            for player in snapshot["players"]
            if normalized_name(player["username"]) == username
        )
        for username in usernames
    }
    road_owners = {
        index: most_common(
            normalized_name(road["owner"])
            for snapshot in snapshots
            for road in snapshot["roads"]
            if road["edge_index"] == index
        )
        for index in range(72)
    }
    building_owners = {
        index: most_common(
            normalized_name(building["owner"])
            for snapshot in snapshots
            for building in snapshot["buildings"]
            if building["corner_index"] == index
        )
        for index in range(54)
    }

    known_roads: dict[int, dict[str, Any]] = {}
    known_buildings: dict[int, dict[str, Any]] = {}
    stabilized: list[dict[str, Any]] = []
    for snapshot in snapshots:
        for road in snapshot["roads"]:
            owner = road_owners[road["edge_index"]] or normalized_name(road["owner"])
            known_roads[road["edge_index"]] = {
                **road,
                "owner": owner,
                "color": player_colors.get(owner) or road["color"],
            }
        for building in snapshot["buildings"]:
            owner = building_owners[building["corner_index"]] or normalized_name(building["owner"])
            previous = known_buildings.get(building["corner_index"])
            known_buildings[building["corner_index"]] = {
                **building,
                "owner": owner,
                "color": player_colors.get(owner) or building["color"],
                "kind": "city" if previous and previous["kind"] == "city" else building["kind"],
            }
        stabilized.append(
            {
                **snapshot,
                "active_player": normalized_name(snapshot["active_player"]),
                "players": [
                    {
                        **player,
                        "username": normalized_name(player["username"]),
                        "color": player_colors.get(normalized_name(player["username"])) or player["color"],
                    }
                    for player in snapshot["players"]
                ],
                "tiles": [
                    {
                        **tile,
                        "resource": tile_resources[tile["tile_index"]],
                        "dice_number": tile_numbers[tile["tile_index"]],
                    }
                    for tile in snapshot["tiles"]
                ],
                "roads": list(known_roads.values()),
                "buildings": list(known_buildings.values()),
            }
        )
    return stabilized


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
    frames: list[Frame], *, api_url: str, api_key: str, model: str, player: str
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "These are chronological screenshots from a completed Colonist.io game. "
                "Extract only events supported by visible evidence. A screenshot can show "
                "the state after an action rather than the action itself. Put guesses in "
                "inference, lower confidence, and use the supplied timestamps. Do not infer "
                "hidden cards or hidden resources. Duplicate or unclear events may be omitted. "
                f"The reviewed player's username is {player!r}. An exact visible username is "
                "authoritative. When that label is obscured, the largest or expanded player "
                "container represents the local reviewed player in this recording; treat that "
                "layout cue as an inference and do not override a clearly visible different name."
                " For each supplied frame, add one board snapshot when the game board is visible. "
                "Use x/y values relative to the board area: 0,0 is its top-left and 1,1 is its "
                "bottom-right. Record all clearly visible tiles and pieces in that frame, not only "
                "the new move. Road endpoints and settlement centers must share the same coordinate "
                "system. Leave arrays empty and lower confidence when the board is obscured."
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
    batch_results: list[dict[str, Any]],
    *,
    api_url: str,
    api_key: str,
    model: str,
    player: str,
) -> dict[str, Any]:
    content = [
        {
            "type": "input_text",
            "text": (
                "Consolidate the following chronological visual observations into one "
                "post-game review. Deduplicate repeated state observations. Keep uncertain "
                "claims uncertain. Suggestions must be retrospective and cite visible "
                "evidence; do not invent resource counts, hidden cards, or legal alternatives "
                f"that cannot be supported. The reviewed player is {player!r}. Attribute "
                "player-specific coaching to that username. The largest or expanded player "
                "container is a fallback local-player cue only when its name is unreadable.\n\n"
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
    parser.add_argument(
        "--player",
        default=os.getenv("COLONIST_USERNAME", ""),
        help="username to assess (or set COLONIST_USERNAME in analyzer/.env)",
    )
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
    if not args.extract_only and not args.player.strip():
        fail("set COLONIST_USERNAME in analyzer/.env or pass --player")

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
            # MediaRecorder WebM files may omit container duration metadata. The
            # sampled frame count still gives a stable offset for the next part.
            offset += len(paths) * args.sample_every

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
                    player=args.player,
                )
            )

        print("Building final review…", file=sys.stderr)
        report = consolidate_report(
            batch_results,
            api_url=args.api_url,
            api_key=api_key,
            model=args.model,
            player=args.player,
        )
        output = {
            "schema_version": "1.2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_videos": [str(video.resolve()) for video in args.videos],
            "model": args.model,
            "reviewed_player": args.player,
            "sample_every_seconds": args.sample_every,
            "sampled_frame_count": len(all_frames),
            "analyzed_frame_count": len(selected),
            "board_topology": "hex19-row-major-v1",
            "board_snapshots": stabilize_snapshots(
                list(filter(
                    None,
                    (
                        canonicalize_snapshot(snapshot)
                        for batch in batch_results
                        for snapshot in batch.get("board_snapshots", [])
                    ),
                )),
            ),
            "review": report,
        }
        write_json(args.output, output)
        print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
