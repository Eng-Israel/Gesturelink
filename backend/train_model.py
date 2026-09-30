from __future__ import annotations

import json
from pathlib import Path

import joblib
from sklearn.neighbors import KNeighborsClassifier

DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_PATH = Path(__file__).resolve().parent / "gesture_model.joblib"

features: list[list[float]] = []
labels: list[str] = []
for file in DATA_DIR.glob("*/*.jsonl"):
    for line in file.read_text(encoding="utf-8").splitlines():
        sample = json.loads(line)
        features.append(sample["landmarks"])
        labels.append(sample["label"])

if len(set(labels)) < 2:
    raise SystemExit("Collect at least two gesture labels before training.")

model = KNeighborsClassifier(n_neighbors=min(5, len(features)))
model.fit(features, labels)
joblib.dump(model, MODEL_PATH)
print(f"Saved {len(features)} samples across {len(set(labels))} labels to {MODEL_PATH}")
