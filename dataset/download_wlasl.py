from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

METADATA_URL = "https://raw.githubusercontent.com/dxli94/WLASL/master/start_kit/WLASL_v0.3.json"
ROOT = Path(__file__).resolve().parent
METADATA_PATH = ROOT / "WLASL_v0.3.json"
VIDEO_DIR = ROOT / "videos"
MAX_BYTES = 800 * 1024 * 1024


def download_metadata() -> list[dict]:
    if not METADATA_PATH.exists():
        print("Downloading WLASL metadata...")
        with urlopen(METADATA_URL) as response:
            METADATA_PATH.write_bytes(response.read())
    return json.loads(METADATA_PATH.read_text(encoding="utf-8"))


def choose_samples(entries: list[dict], labels: set[str], count: int, max_total: int, direct_only: bool) -> list[dict]:
    chosen = []
    for entry in entries:
        if labels and entry["gloss"].lower() not in labels:
            continue
        for instance in entry["instances"]:
            if instance.get("split") not in {"train", "val"}:
                continue
            if direct_only and ("youtube.com" in instance.get("url", "") or "youtu.be" in instance.get("url", "")):
                continue
            if len(chosen) >= max_total:
                return chosen
            chosen.append({"gloss": entry["gloss"], **instance})
            if len([item for item in chosen if item["gloss"] == entry["gloss"]]) >= count:
                break
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a small academic WLASL video subset.")
    parser.add_argument("--labels", default="hello,thank_you,yes,no", help="Comma-separated WLASL glosses")
    parser.add_argument("--per-label", type=int, default=5, help="Maximum videos per label")
    parser.add_argument("--max-total", type=int, default=500, help="Maximum total videos")
    parser.add_argument("--direct-only", action="store_true", help="Skip YouTube links that commonly return 403")
    parser.add_argument("--all-labels", action="store_true", help="Use every label in the metadata")
    parser.add_argument("--max-gb", type=float, default=0.8, help="Hard download storage limit in GB")
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()

    entries = download_metadata()
    labels = set() if args.all_labels else {label.strip().lower() for label in args.labels.split(",") if label.strip()}
    samples = choose_samples(entries, labels, args.per_label, args.max_total, args.direct_only)
    manifest_path = ROOT / "manifest.json"
    manifest_path.write_text(json.dumps(samples, indent=2), encoding="utf-8")
    print(f"Selected {len(samples)} samples across {len({item['gloss'] for item in samples})} labels.")
    if args.metadata_only:
        return

    try:
        subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("yt-dlp is required for video downloads. Install it with: python -m pip install yt-dlp") from error
    VIDEO_DIR.mkdir(exist_ok=True)
    max_bytes = int(args.max_gb * 1024 * 1024 * 1024)
    for sample in samples:
        output = VIDEO_DIR / f"{sample['gloss']}_{sample['video_id']}.mp4"
        if output.exists():
            continue
        used_bytes = sum(path.stat().st_size for path in VIDEO_DIR.glob("*.mp4"))
        if used_bytes >= max_bytes:
            print(f"Storage limit reached: {used_bytes / (1024 * 1024):.1f} MB")
            break
        print(f"Downloading {sample['gloss']} ({sample['video_id']})")
        subprocess.run([sys.executable, "-m", "yt_dlp", "--no-playlist", "--max-filesize", f"{max_bytes - used_bytes}", "-f", "mp4[height<=480]/mp4", "-o", str(output), sample["url"]], check=False)


if __name__ == "__main__":
    main()
