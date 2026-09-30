import unittest
from types import SimpleNamespace

from backend.main import ConferenceRooms, MAX_ROOM_PARTICIPANTS, PROJECT_ROOT, health, sign_videos


class FakeWebSocket:
    def __init__(self, hostname="localhost", origin="http://localhost:8000"):
        self.url = SimpleNamespace(hostname=hostname)
        self.headers = {"origin": origin}
        self.messages = []
        self.accepted = False
        self.closed = None

    async def accept(self):
        self.accepted = True

    async def close(self, code, reason):
        self.closed = (code, reason)

    async def send_json(self, message):
        self.messages.append(message)


class ConferenceRoomsTests(unittest.IsolatedAsyncioTestCase):
    async def test_join_relay_and_leave(self):
        rooms = ConferenceRooms()
        alice_socket = FakeWebSocket()
        alice = await rooms.join(alice_socket, "room-1", "Alice")
        bob_socket = FakeWebSocket()
        bob = await rooms.join(bob_socket, "room-1", "Bob")

        self.assertEqual(bob_socket.messages[0]["type"], "joined")
        self.assertEqual(bob_socket.messages[0]["peers"][0]["name"], "Alice")
        self.assertEqual(alice_socket.messages[-1]["type"], "peer-joined")

        await rooms.relay("room-1", alice, {
            "to": bob.id,
            "signal": {"type": "offer", "sdp": "offer-sdp"},
        })
        self.assertEqual(bob_socket.messages[-1]["signal"]["sdp"], "offer-sdp")

        await rooms.leave("room-1", bob)
        self.assertEqual(alice_socket.messages[-1], {"type": "peer-left", "peerId": bob.id})
        await rooms.leave("room-1", alice)
        self.assertNotIn("room-1", rooms.rooms)

    async def test_rejects_cross_origin_room_and_excess_participants(self):
        rooms = ConferenceRooms()
        cross_origin = FakeWebSocket(origin="http://attacker.test")
        self.assertIsNone(await rooms.join(cross_origin, "room-1", "Guest"))
        self.assertEqual(cross_origin.closed[0], 1008)

        sockets = []
        participants = []
        for _ in range(MAX_ROOM_PARTICIPANTS):
            socket = FakeWebSocket()
            sockets.append(socket)
            participants.append(await rooms.join(socket, "room-2", "Guest"))

        full_room_socket = FakeWebSocket()
        self.assertIsNone(await rooms.join(full_room_socket, "room-2", "Guest"))
        self.assertEqual(full_room_socket.closed[0], 1013)

        for participant in participants:
            await rooms.leave("room-2", participant)


class SignVideoCatalogTests(unittest.TestCase):
    def test_catalog_lists_playable_local_hello_video_and_all_sign_glosses(self):
        catalog = sign_videos()
        local_videos = list((PROJECT_ROOT / "dataset" / "videos").glob("*.mp4"))
        hello = next(item for item in catalog if item["gloss"].lower() == "hello")
        catalog_glosses = {item["gloss"].lower() for item in catalog}
        local_glosses = {
            path.stem.rpartition("_")[0].replace("_", " ").lower()
            for path in local_videos
        }

        self.assertEqual(catalog_glosses, local_glosses)
        self.assertEqual(len(catalog), len(catalog_glosses))
        self.assertTrue(PROJECT_ROOT.joinpath(*hello["url"].strip("/").split("/")).is_file())


class HealthTests(unittest.TestCase):
    def test_health_reports_loaded_vision_and_model(self):
        status = health()
        self.assertTrue(status["ok"])
        self.assertTrue(status["vision_ready"])
        self.assertTrue(status["model_ready"])


if __name__ == "__main__":
    unittest.main()
