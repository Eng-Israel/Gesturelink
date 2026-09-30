from __future__ import annotations

import json
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
VIDEO_DIR = ROOT / "videos"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "backend" / "data"
MODEL_PATH = ROOT / "hand_landmarker.task"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

def landmarks_for_frame(frame: object, detector: object) -> list[float] | None:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not result.hand_landmarks:
        return None
    points = result.hand_landmarks[0]
    origin_x, origin_y = points[0].x, points[0].y
    return [value for point in points for value in (point.x - origin_x, point.y - origin_y, point.z)]


def main() -> None:
    if not MODEL_PATH.exists():
        print("Downloading official MediaPipe hand landmark model...")
        with urlopen(MODEL_URL) as response:
            MODEL_PATH.write_bytes(response.read())
    processed = 0
    options = vision.HandLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(MODEL_PATH)), num_hands=1)
    with vision.HandLandmarker.create_from_options(options) as detector:
        for video_path in VIDEO_DIR.glob("*.mp4"):
            label = video_path.name.rsplit("_", 1)[0]
            label_dir = OUTPUT_DIR / label
            label_dir.mkdir(parents=True, exist_ok=True)
            output_path = label_dir / f"wlasl_{video_path.stem}.jsonl"
            if output_path.exists():
                continue
            capture = cv2.VideoCapture(str(video_path))
            with output_path.open("w", encoding="utf-8") as output:
                while True:
                    success, frame = capture.read()
                    if not success:
                        break
                    landmarks = landmarks_for_frame(frame, detector)
                    if landmarks:
                        output.write(json.dumps({"label": label, "landmarks": landmarks}) + "\n")
                        processed += 1
            capture.release()
            print(f"Processed {video_path.name}")
    print(f"Saved {processed} landmark frames to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
