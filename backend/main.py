from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
MODEL_PATH = ROOT / "gesture_model.joblib"
ROOM_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
MAX_ROOM_PARTICIPANTS = 6
model = None
try:
    import joblib
    if MODEL_PATH.exists():
        model = joblib.load(MODEL_PATH)
except Exception:
    model = None

app = FastAPI(title="Gesturelink conference", version="0.2.0")

try:
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
except ImportError:
    cv2 = None
    np = None
    mp = None
    python = None
    vision = None


class FrameRequest(BaseModel):
    image: str
    label: str | None = None


class Participant:
    def __init__(self, websocket: WebSocket, name: str):
        self.id = uuid.uuid4().hex
        self.websocket = websocket
        self.name = name
        self.send_lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_json(message)


class ConferenceRooms:
    def __init__(self) -> None:
        self.rooms: dict[str, dict[str, Participant]] = {}
        self.lock = asyncio.Lock()

    async def join(self, websocket: WebSocket, room_id: str, name: str) -> Participant | None:
        if not ROOM_CODE_PATTERN.fullmatch(room_id):
            await websocket.close(code=1008, reason="Invalid room code")
            return None

        origin = websocket.headers.get("origin")
        if origin and urlsplit(origin).hostname != websocket.url.hostname:
            await websocket.close(code=1008, reason="Conference origin does not match")
            return None

        await websocket.accept()
        participant = Participant(websocket, name[:30].strip() or "Guest")
        async with self.lock:
            room = self.rooms.setdefault(room_id, {})
            if len(room) >= MAX_ROOM_PARTICIPANTS:
                await websocket.close(code=1013, reason="This room is full")
                return None
            existing = list(room.values())
            room[participant.id] = participant

        try:
            await participant.send({
                "type": "joined",
                "peerId": participant.id,
                "peers": [{"id": peer.id, "name": peer.name} for peer in existing],
            })
            await self.broadcast(
                existing,
                {"type": "peer-joined", "peer": {"id": participant.id, "name": participant.name}},
            )
        except (RuntimeError, WebSocketDisconnect):
            await self.leave(room_id, participant)
            return None
        return participant

    async def relay(self, room_id: str, sender: Participant, message: dict[str, Any]) -> None:
        target_id = message.get("to")
        signal = message.get("signal")
        if not isinstance(target_id, str) or not isinstance(signal, dict):
            return
        if signal.get("type") not in {"offer", "answer"}:
            return

        async with self.lock:
            target = self.rooms.get(room_id, {}).get(target_id)
        if target is None or target.id == sender.id:
            return
        await target.send({
            "type": "signal",
            "from": sender.id,
            "name": sender.name,
            "signal": signal,
        })

    async def leave(self, room_id: str, participant: Participant) -> None:
        async with self.lock:
            room = self.rooms.get(room_id)
            if room is None or room.pop(participant.id, None) is None:
                return
            remaining = list(room.values())
            if not room:
                self.rooms.pop(room_id, None)
        await self.broadcast(remaining, {"type": "peer-left", "peerId": participant.id})

    @staticmethod
    async def broadcast(participants: list[Participant], message: dict[str, Any]) -> None:
        for participant in participants:
            try:
                await participant.send(message)
            except (RuntimeError, WebSocketDisconnect):
                continue


conference_rooms = ConferenceRooms()


def decode_image(data_url: str) -> Any:
    if "," not in data_url:
        raise HTTPException(status_code=400, detail="Expected a data URL image")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception as error:
        raise HTTPException(status_code=400, detail="Could not decode image") from error
    if image is None:
        raise HTTPException(status_code=400, detail="Image was empty")
    return image


def create_landmarker() -> Any:
    if vision is None:
        raise RuntimeError("MediaPipe is required to extract hand landmarks.")
    model_path = ROOT / "hand_landmarker.task"
    if not model_path.exists():
        model_path = ROOT.parent / "dataset" / "hand_landmarker.task"
    if not model_path.exists():
        raise FileNotFoundError(f"Hand landmarker asset not found: {model_path}")
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model_path)),
        num_hands=2,
    )
    return vision.HandLandmarker.create_from_options(options)


def extract_landmarks(image: Any, detector: Any | None = None) -> list[float] | None:
    if vision is None:
        return None
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    if detector is None:
        with create_landmarker() as local_detector:
            result = local_detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image))
    else:
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image))
    if not result.hand_landmarks:
        return None
    hands: list[list[float] | None] = [None, None]
    for hand_index, points in enumerate(result.hand_landmarks):
        handedness = result.handedness[hand_index][0].category_name.lower()
        slot = 0 if handedness == "left" else 1 if handedness == "right" else -1
        if slot < 0 or hands[slot] is not None:
            slot = next((index for index, hand in enumerate(hands) if hand is None), -1)
        if slot < 0:
            continue
        origin_x, origin_y = points[0].x, points[0].y
        hands[slot] = [
            value
            for point in points
            for value in (point.x - origin_x, point.y - origin_y, point.z)
        ]
    if all(hand is None for hand in hands):
        return None
    return [value for hand in hands for value in (hand or [0.0] * 63)]


@app.get("/health")
def health() -> dict[str, Any]:
    asset_exists = (ROOT / "hand_landmarker.task").exists() or (ROOT.parent / "dataset" / "hand_landmarker.task").exists()
    return {
        "ok": True,
        "vision_ready": vision is not None and asset_exists,
        "model_ready": model is not None,
        "message": "Gesturelink API is online",
    }


@app.get("/")
@app.get("/index.html")
def index() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/app.js")
def app_script() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "app.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/styles.css")
def stylesheet() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "styles.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/collector.html")
def collector_page() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "collector.html")


@app.get("/sign_utils.js")
def sign_utils_script() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "sign_utils.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/dataset/manifest.json")
def sign_manifest() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "dataset" / "manifest.json",
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/dataset/sign-videos")
def sign_videos() -> list[dict[str, str]]:
    videos = []
    seen_glosses: set[str] = set()
    for path in sorted((PROJECT_ROOT / "dataset" / "videos").glob("*.mp4")):
        gloss, separator, video_id = path.stem.rpartition("_")
        if not separator or not video_id:
            continue
        normalized_gloss = re.sub(r"\s+", " ", gloss.replace("_", " ").lower()).strip()
        if not normalized_gloss or normalized_gloss in seen_glosses:
            continue
        seen_glosses.add(normalized_gloss)
        videos.append({
            "gloss": normalized_gloss,
            "video_id": video_id,
            "url": f"/dataset/videos/{quote(path.name)}",
        })
    return videos


app.mount(
    "/dataset/videos",
    StaticFiles(directory=PROJECT_ROOT / "dataset" / "videos"),
    name="sign-videos",
)


@app.websocket("/signal/{room_id}")
async def conference_signal(websocket: WebSocket, room_id: str, name: str = "Guest") -> None:
    participant = await conference_rooms.join(websocket, room_id, name)
    if participant is None:
        return
    try:
        while True:
            await conference_rooms.relay(room_id, participant, await websocket.receive_json())
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        await conference_rooms.leave(room_id, participant)


@app.post("/collect-frame")
def collect_frame(request: FrameRequest) -> dict[str, Any]:
    if not request.label or not request.label.strip():
        raise HTTPException(status_code=400, detail="A gesture label is required")
    image = decode_image(request.image)
    label_dir = DATA_DIR / request.label.strip().lower().replace(" ", "_")
    label_dir.mkdir(exist_ok=True)
    timestamp = f"{time.time_ns()}.jpg"
    cv2.imwrite(str(label_dir / timestamp), image)
    landmarks = extract_landmarks(image)
    if landmarks:
        with (label_dir / "landmarks.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps({"label": request.label.strip(), "landmarks": landmarks}) + "\n")
    return {"saved": True, "landmarks_found": landmarks is not None, "label": request.label.strip()}


@app.post("/infer-posture")
def infer_posture(request: FrameRequest) -> dict[str, Any]:
    image = decode_image(request.image)
    landmarks = extract_landmarks(image)
    if landmarks is None:
        return {"label": None, "confidence": 0, "landmarks_found": False}
    if model is None:
        return {"label": None, "confidence": 0, "landmarks_found": True}
    probabilities = model.predict_proba([landmarks])[0]
    best_index = int(probabilities.argmax())
    return {
        "label": str(model.classes_[best_index]),
        "confidence": round(float(probabilities[best_index]), 3),
        "landmarks_found": True,
    }
