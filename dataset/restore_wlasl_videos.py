from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"
METADATA_PATH = ROOT / "WLASL_v0.3.json"
VIDEO_DIR = ROOT / "videos"
SPLIT_ORDER = {"train": 0, "val": 1, "test": 2}


def normalize_gloss(gloss: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", gloss.lower())).strip()


def has_video_stream(path: Path, ffprobe: str) -> bool:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "video"


def convert_video(source: Path, target: Path, ffmpeg: str, ffprobe: str) -> bool:
    temporary = target.with_name(f".{target.stem}.restoring.mp4")
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                "scale=640:480:force_original_aspect_ratio=decrease",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "27",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
        )
        if not has_video_stream(temporary, ffprobe):
            raise RuntimeError(f"Converted video is invalid: {temporary}")
        temporary.replace(target)
        return True
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        if temporary.exists():
            temporary.unlink()
        print(f"Could not restore from {source.name}: {error}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore playable sign-reference clips from a local WLASL video backup."
    )
    parser.add_argument(
        "--raw-videos",
        required=True,
        type=Path,
        help="Folder containing the downloaded WLASL videos named by video ID.",
    )
    args = parser.parse_args()

    if not args.raw_videos.is_dir():
        parser.error(f"Raw-video folder does not exist: {args.raw_videos}")

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit("Install FFmpeg and ensure both ffmpeg and ffprobe are on PATH.")

    previous_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    raw_by_stem: dict[str, list[Path]] = defaultdict(list)
    for path in args.raw_videos.rglob("*"):
        if path.is_file() and path.stat().st_size > 1024:
            raw_by_stem[path.stem.lower()].append(path)
    for paths in raw_by_stem.values():
        paths.sort(key=lambda path: (path.suffix.lower() != ".mp4", -path.stat().st_size))

    instances_by_gloss: dict[str, list[dict[str, Any]]] = defaultdict(list)
    original_gloss_by_normalized: dict[str, str] = {}
    for item in metadata:
        gloss = normalize_gloss(item["gloss"])
        original_gloss_by_normalized.setdefault(gloss, item["gloss"])
        instances_by_gloss[gloss].extend(item.get("instances", []))

    VIDEO_DIR.mkdir(exist_ok=True)
    probe_cache: dict[Path, bool] = {}
    restored = 0
    selected_manifest: list[dict[str, Any]] = []
    previous_id_by_gloss = {
        normalize_gloss(sample["gloss"]): str(sample["video_id"])
        for sample in previous_manifest
    }

    for gloss, raw_instances in sorted(instances_by_gloss.items()):
        instances = sorted(
            raw_instances,
            key=lambda instance: (
                str(instance["video_id"]) != previous_id_by_gloss.get(gloss),
                SPLIT_ORDER.get(instance.get("split", ""), 3),
                str(instance["video_id"]),
            ),
        )
        chosen: tuple[dict[str, Any], str] | None = None

        for instance in instances:
            video_id = str(instance["video_id"])
            output = VIDEO_DIR / f"{gloss}_{video_id}.mp4"
            if output.is_file() and output not in probe_cache:
                probe_cache[output] = has_video_stream(output, ffprobe)
            if output.is_file() and probe_cache[output]:
                chosen = (instance, video_id)
                break

        candidates: list[tuple[dict[str, Any], Path]] = []
        seen_paths: set[Path] = set()
        for instance in instances:
            video_id = str(instance["video_id"])
            for stem in (video_id.lower(), video_id.zfill(5).lower()):
                for source in raw_by_stem.get(stem, []):
                    if source not in seen_paths:
                        seen_paths.add(source)
                        candidates.append((instance, source))

        if chosen is None:
            for instance, source in candidates:
                valid = probe_cache.get(source)
                if valid is None:
                    valid = has_video_stream(source, ffprobe)
                    probe_cache[source] = valid
                if not valid:
                    continue

                video_id = str(instance["video_id"])
                target = VIDEO_DIR / f"{gloss}_{video_id}.mp4"
                if target.exists() and has_video_stream(target, ffprobe):
                    chosen = (instance, video_id)
                    break
                if convert_video(source, target, ffmpeg, ffprobe):
                    chosen = (instance, video_id)
                    restored += 1
                    break

        if chosen is not None:
            instance, video_id = chosen
            selected_manifest.append({
                **instance,
                "gloss": original_gloss_by_normalized[gloss],
                "video_id": video_id,
            })

    MANIFEST_PATH.write_text(
        json.dumps(selected_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Catalogued {len(selected_manifest)} signs from available video IDs; "
        f"restored {restored} clips. "
        f"{len(instances_by_gloss) - len(selected_manifest)} signs had no playable local source."
    )
    return 0 if selected_manifest else 1


if __name__ == "__main__":
    raise SystemExit(main())
