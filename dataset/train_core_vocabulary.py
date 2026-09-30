from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from backend.main import create_landmarker, cv2, extract_landmarks

METADATA_PATH = ROOT / "WLASL_v0.3.json"
LANDMARKS_PATH = ROOT / "core20_landmarks.jsonl"
MODEL_PATH = ROOT.parent / "backend" / "gesture_model.joblib"
REPORT_PATH = ROOT.parent / "backend" / "gesture_model_metadata.json"
VOCABULARY = (
    "hello", "you", "want", "need", "go", "eat", "drink", "water", "help",
    "please", "thank you", "yes", "no", "what", "where", "who", "good",
    "home", "today", "more",
)
FRAMES_PER_VIDEO = 12
EPOCHS = 150
SPLITS = {"train", "val", "test"}


def video_candidates(raw_dir: Path, metadata: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_by_stem: dict[str, list[Path]] = defaultdict(list)
    for path in raw_dir.rglob("*"):
        if path.is_file() and path.stat().st_size > 1024:
            raw_by_stem[path.stem.lower()].append(path)
    for paths in raw_by_stem.values():
        paths.sort(key=lambda path: (path.suffix.lower() != ".mp4", -path.stat().st_size))

    candidates = []
    seen: set[tuple[str, str]] = set()
    for entry in metadata:
        gloss = entry["gloss"].lower().replace("_", " ")
        if gloss not in VOCABULARY:
            continue
        for instance in entry.get("instances", []):
            video_id = str(instance["video_id"])
            key = (gloss, video_id)
            if key in seen:
                continue
            seen.add(key)
            split = instance.get("split")
            if split not in SPLITS:
                continue
            matches = raw_by_stem.get(video_id.lower()) or raw_by_stem.get(video_id.zfill(5))
            if matches:
                candidates.append({
                    "gloss": gloss,
                    "video_id": video_id,
                    "split": split,
                    "path": matches[0],
                })
    return candidates


def extract_video_samples(candidate: dict[str, Any], detector: Any) -> list[dict[str, Any]]:
    capture = cv2.VideoCapture(str(candidate["path"]))
    if not capture.isOpened():
        capture.release()
        print(f"Skipping unreadable clip {candidate['path'].name}.")
        return []
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count < 1:
        capture.release()
        print(f"Skipping empty clip {candidate['path'].name}.")
        return []

    frame_indices = np.unique(
        np.linspace(0, frame_count - 1, min(FRAMES_PER_VIDEO, frame_count), dtype=int)
    )
    samples = []
    for frame_index in frame_indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        success, frame = capture.read()
        if not success:
            continue
        landmarks = extract_landmarks(frame, detector)
        if landmarks is not None:
            samples.append({
                "gloss": candidate["gloss"],
                "video_id": candidate["video_id"],
                "split": candidate["split"],
                "landmarks": landmarks,
            })
    capture.release()
    return samples


def build_classifier() -> Any:
    return make_pipeline(
        StandardScaler(),
        MLPClassifier(
            hidden_layer_sizes=(128, 64),
            activation="relu",
            solver="adam",
            alpha=0.01,
            learning_rate_init=0.001,
            max_iter=EPOCHS,
            tol=0.0,
            early_stopping=False,
            random_state=42,
        ),
    )


def evaluate_by_video(model: Any, samples: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[list[float]]] = defaultdict(list)
    for sample in samples:
        if sample["split"] not in {"val", "test"}:
            continue
        grouped[(sample["gloss"], sample["video_id"])].append(sample["landmarks"])

    expected = []
    predicted = []
    for (gloss, _), frames in sorted(grouped.items()):
        probabilities = model.predict_proba(frames)
        mean_probabilities = probabilities.mean(axis=0)
        expected.append(gloss)
        predicted.append(str(model.classes_[int(mean_probabilities.argmax())]))

    if not expected:
        raise SystemExit("No held-out WLASL validation/test clips yielded hand landmarks.")
    return {
        "clips": len(expected),
        "accuracy": accuracy_score(expected, predicted),
        "report": classification_report(
            expected,
            predicted,
            labels=list(VOCABULARY),
            zero_division=0,
            output_dict=True,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract WLASL hand landmarks and train the 20-sign Gesturelink model."
    )
    parser.add_argument("--raw-videos", required=True, type=Path)
    args = parser.parse_args()
    if not args.raw_videos.is_dir():
        parser.error(f"Raw-video directory does not exist: {args.raw_videos}")
    if cv2 is None:
        raise SystemExit("OpenCV is required to read the training videos.")

    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    candidates = video_candidates(args.raw_videos, metadata)
    clip_counts = Counter(candidate["gloss"] for candidate in candidates)
    missing = [gloss for gloss in VOCABULARY if clip_counts[gloss] == 0]
    if missing:
        raise SystemExit(f"No backup videos matched these signs: {', '.join(missing)}")

    print(
        f"Extracting up to {FRAMES_PER_VIDEO} frames from {len(candidates)} labelled clips "
        f"across {len(VOCABULARY)} signs."
    )
    all_samples: list[dict[str, Any]] = []
    with create_landmarker() as detector:
        for index, candidate in enumerate(candidates, start=1):
            extracted = extract_video_samples(candidate, detector)
            all_samples.extend(extracted)
            print(
                f"[{index}/{len(candidates)}] {candidate['gloss']} "
                f"{candidate['video_id']} ({candidate['split']}): {len(extracted)} hand frames"
            )

    if not all_samples:
        raise SystemExit("No training frames contained a detectable hand.")
    frames_by_split = Counter(sample["split"] for sample in all_samples)
    clips_by_split = Counter(
        (sample["split"], sample["gloss"], sample["video_id"])
        for sample in all_samples
    )
    train_samples = [sample for sample in all_samples if sample["split"] == "train"]
    train_labels = {sample["gloss"] for sample in train_samples}
    if train_labels != set(VOCABULARY):
        absent = sorted(set(VOCABULARY) - train_labels)
        raise SystemExit(f"No training hand frames for: {', '.join(absent)}")

    validation_model = build_classifier()
    validation_model.fit(
        [sample["landmarks"] for sample in train_samples],
        [sample["gloss"] for sample in train_samples],
    )
    evaluation = evaluate_by_video(validation_model, all_samples)

    final_model = build_classifier()
    final_model.fit(
        [sample["landmarks"] for sample in all_samples],
        [sample["gloss"] for sample in all_samples],
    )
    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(final_model, MODEL_PATH)
    with LANDMARKS_PATH.open("w", encoding="utf-8") as output:
        for sample in all_samples:
            output.write(json.dumps(sample, separators=(",", ":")) + "\n")

    per_sign = {
        gloss: {
            split: len({
                (sample["gloss"], sample["video_id"])
                for sample in all_samples
                if sample["gloss"] == gloss and sample["split"] == split
            })
            for split in ("train", "val", "test")
        }
        for gloss in VOCABULARY
    }
    report = {
        "source": "WLASL backup videos",
        "vocabulary": list(VOCABULARY),
        "clip_counts_by_sign_and_split": per_sign,
        "clips_with_hand_landmarks_by_split": {
            split: sum(1 for key in clips_by_split if key[0] == split)
            for split in ("train", "val", "test")
        },
        "frames_with_hand_landmarks_by_split": dict(frames_by_split),
        "held_out_video_evaluation": {
            "clips": evaluation["clips"],
            "accuracy": evaluation["accuracy"],
            "classification_report": evaluation["report"],
            "training_split_only": True,
        },
        "final_model_fit": "all available labelled clips after held-out evaluation",
        "feature_schema": "two handedness slots, 21 landmarks per hand, xyz (126 values)",
        "classifier": "StandardScaler + MLPClassifier (128, 64)",
        "epochs_requested": EPOCHS,
        "held_out_model_epochs": validation_model.named_steps["mlpclassifier"].n_iter_,
        "final_model_epochs": final_model.named_steps["mlpclassifier"].n_iter_,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"Trained {len(final_model.classes_)} signs on {len(all_samples)} frames "
        f"from {len(clips_by_split)} clips for {EPOCHS} epochs."
    )
    print(
        f"Held-out video accuracy (train split only): "
        f"{evaluation['accuracy']:.1%} across {evaluation['clips']} val/test clips."
    )
    print(f"Saved model: {MODEL_PATH}")
    print(f"Saved landmark corpus: {LANDMARKS_PATH}")
    print(f"Saved evaluation report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
