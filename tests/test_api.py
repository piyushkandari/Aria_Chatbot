"""API tests using FastAPI TestClient."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web.api import app

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "intents.json"
)


def _client() -> TestClient:
    os.environ["ARIA_CONFIG"] = str(_CONFIG_PATH)
    return TestClient(app)


class ApiTests(unittest.TestCase):
    """Exercises the HTTP endpoints through TestClient."""

    def setUp(self) -> None:
        self._client = _client()
        self._client.__enter__()

    def tearDown(self) -> None:
        self._client.__exit__(None, None, None)

    def test_health(self) -> None:
        r = self._client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("version", body)
        self.assertIn("active_sessions", body)

    def test_create_session_returns_201(self) -> None:
        r = self._client.post("/api/session")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["session_id"])

    def test_chat_returns_reply(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        r = self._client.post(
            "/api/chat", json={"session_id": sid, "message": "hello"}
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["reply"])
        self.assertEqual(body["category"], "greeting")
        self.assertTrue(body["intent"].startswith("greeting."))
        self.assertIn("timestamp", body)

    def test_chat_unknown_session_returns_404(self) -> None:
        r = self._client.post(
            "/api/chat",
            json={"session_id": "does-not-exist", "message": "hi"},
        )
        self.assertEqual(r.status_code, 404)

    def test_chat_empty_message_returns_422(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        r = self._client.post(
            "/api/chat", json={"session_id": sid, "message": ""}
        )
        self.assertEqual(r.status_code, 422)

    def test_chat_too_long_returns_422(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        r = self._client.post(
            "/api/chat",
            json={"session_id": sid, "message": "a" * 501},
        )
        self.assertEqual(r.status_code, 422)

    def test_chat_extra_fields_rejected(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        r = self._client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": "hi",
                "unexpected": "field",
            },
        )
        self.assertEqual(r.status_code, 422)

    def test_chat_after_farewell_returns_409(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        self._client.post(
            "/api/chat", json={"session_id": sid, "message": "bye"}
        )
        r = self._client.post(
            "/api/chat", json={"session_id": sid, "message": "hello"}
        )
        self.assertEqual(r.status_code, 409)

    def test_followup_as_first_message_returns_200(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        r = self._client.post(
            "/api/chat",
            json={"session_id": sid, "message": "what did i just ask"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["reply"])

    def test_history_empty(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        r = self._client.get(f"/api/history/{sid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["messages"], [])
        self.assertEqual(body["facts"], {})

    def test_history_after_turns(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        self._client.post(
            "/api/chat",
            json={"session_id": sid, "message": "my name is Alice"},
        )
        r = self._client.get(f"/api/history/{sid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["facts"].get("name"), "Alice")

    def test_history_unknown_returns_404(self) -> None:
        r = self._client.get("/api/history/nope")
        self.assertEqual(r.status_code, 404)

    def test_delete_session_returns_204(self) -> None:
        sid = self._client.post("/api/session").json()["session_id"]
        r = self._client.delete(f"/api/session/{sid}")
        self.assertEqual(r.status_code, 204)
        r2 = self._client.post(
            "/api/chat", json={"session_id": sid, "message": "hi"}
        )
        self.assertEqual(r2.status_code, 404)

    def test_delete_unknown_returns_404(self) -> None:
        r = self._client.delete("/api/session/nope")
        self.assertEqual(r.status_code, 404)

    def test_cors_header_present(self) -> None:
        r = self._client.get(
            "/api/health", headers={"Origin": "http://example.com"}
        )
        self.assertIn("access-control-allow-origin", r.headers)


class StaticFilesTests(unittest.TestCase):
    """Static frontend served at '/'."""

    def setUp(self) -> None:
        self._client = _client()
        self._client.__enter__()

    def tearDown(self) -> None:
        self._client.__exit__(None, None, None)

    def test_index_html_served_at_root(self) -> None:
        r = self._client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("Aria", r.text)
        self.assertIn("chat-form", r.text)

    def test_styles_css_served(self) -> None:
        r = self._client.get("/styles.css")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/css", r.headers.get("content-type", ""))

    def test_app_js_served(self) -> None:
        r = self._client.get("/app.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers.get("content-type", ""))
        self.assertIn("sendMessage", r.text)

    def test_api_routes_not_shadowed_by_static_mount(self) -> None:
        # /api/health must still hit the API handler, not StaticFiles.
        r = self._client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()