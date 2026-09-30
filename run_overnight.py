from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
log_path = ROOT / "overnight_report.txt"

commands = [
    [PYTHON, "dataset/download_wlasl.py", "--all-labels", "--per-label", "1", "--max-total", "500", "--direct-only", "--max-gb", "0.8"],
    [PYTHON, "dataset/prepare_wlasl.py"],
    [PYTHON, "backend/train_model.py"],
]

with log_path.open("w", encoding="utf-8") as report:
    report.write(f"Gesturelink overnight run started: {datetime.now().isoformat()}\n")
    for command in commands:
        report.write(f"\n$ {' '.join(command)}\n")
        report.flush()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        report.write(result.stdout)
        report.write(result.stderr)
        report.write(f"Exit code: {result.returncode}\n")
        if result.returncode:
            report.write("Pipeline stopped after this failure.\n")
            break
    report.write(f"\nFinished: {datetime.now().isoformat()}\n")
print(f"Overnight pipeline complete. Read {log_path}")
