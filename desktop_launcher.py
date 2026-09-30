from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn
from backend.main import app


def main() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    address = f"http://127.0.0.1:{port}"

    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()

    try:
        for _ in range(100):
            if not thread.is_alive():
                raise RuntimeError("Gesturelink's local server stopped unexpectedly.")
            try:
                with urllib.request.urlopen(f"{address}/health", timeout=1) as response:
                    health = json.load(response)
                    if health.get("ok") and health.get("vision_ready") and health.get("model_ready"):
                        break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Gesturelink's local server did not become ready.")

        print(f"Gesturelink is ready at {address}")
        webbrowser.open(address)
        input("Keep this window open while using Gesturelink. Press Enter to close it.\n")
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()


if __name__ == "__main__":
    main()
