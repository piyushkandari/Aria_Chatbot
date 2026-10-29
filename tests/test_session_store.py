"""Unit tests for the web SessionStore."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aria.exceptions import SessionError
from aria.pattern_matcher import load_intents_from_json

from web.session_store import DEFAULT_IDLE_TIMEOUT, SessionStore

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "intents.json"
)


class _Clock:
    """Controllable clock for idle-expiry tests."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _make_store(
    clock=None, idle_timeout: timedelta = DEFAULT_IDLE_TIMEOUT
) -> SessionStore:
    intents = load_intents_from_json(_CONFIG_PATH)
    return SessionStore(
        intents,
        idle_timeout=idle_timeout,
        clock=clock,
    )


class ConstructionTests(unittest.TestCase):
    """Tests for SessionStore construction."""

    def test_reject_zero_timeout(self) -> None:
        with self.assertRaises(ValueError):
            SessionStore([], idle_timeout=timedelta(0))

    def test_reject_negative_timeout(self) -> None:
        with self.assertRaises(ValueError):
            SessionStore([], idle_timeout=timedelta(seconds=-1))

    def test_empty_store(self) -> None:
        store = _make_store()
        self.assertEqual(len(store), 0)


class CreationTests(unittest.TestCase):
    """Tests for SessionStore.create."""

    def test_create_returns_unique_ids(self) -> None:
        store = _make_store()
        ids = {store.create() for _ in range(10)}
        self.assertEqual(len(ids), 10)

    def test_len_tracks_active_sessions(self) -> None:
        store = _make_store()
        store.create()
        store.create()
        self.assertEqual(len(store), 2)


class GetRespondTests(unittest.TestCase):
    """Tests for get() and respond()."""

    def test_get_unknown_returns_none(self) -> None:
        self.assertIsNone(_make_store().get("nope"))

    def test_get_returns_bot(self) -> None:
        store = _make_store()
        sid = store.create()
        self.assertIsNotNone(store.get(sid))

    def test_respond_unknown_returns_none(self) -> None:
        self.assertIsNone(_make_store().respond("nope", "hi"))

    def test_respond_returns_reply(self) -> None:
        store = _make_store()
        sid = store.create()
        reply = store.respond(sid, "hello")
        assert reply is not None
        self.assertEqual(reply.category.value, "greeting")

    def test_respond_after_farewell_raises(self) -> None:
        store = _make_store()
        sid = store.create()
        store.respond(sid, "bye")
        with self.assertRaises(SessionError):
            store.respond(sid, "hello")


class DeleteTests(unittest.TestCase):
    """Tests for SessionStore.delete."""

    def test_delete_existing_returns_true(self) -> None:
        store = _make_store()
        sid = store.create()
        self.assertTrue(store.delete(sid))

    def test_delete_unknown_returns_false(self) -> None:
        self.assertFalse(_make_store().delete("nope"))

    def test_after_delete_get_returns_none(self) -> None:
        store = _make_store()
        sid = store.create()
        store.delete(sid)
        self.assertIsNone(store.get(sid))


class ExpiryTests(unittest.TestCase):
    """Tests for idle-session expiry."""

    def test_idle_session_expires(self) -> None:
        clock = _Clock(datetime(2025, 1, 1, tzinfo=timezone.utc))
        store = _make_store(clock=clock, idle_timeout=timedelta(minutes=5))
        sid = store.create()
        clock.advance(timedelta(minutes=6))
        self.assertIsNone(store.get(sid))

    def test_active_session_survives(self) -> None:
        clock = _Clock(datetime(2025, 1, 1, tzinfo=timezone.utc))
        store = _make_store(clock=clock, idle_timeout=timedelta(minutes=5))
        sid = store.create()
        clock.advance(timedelta(minutes=3))
        store.get(sid)
        clock.advance(timedelta(minutes=3))
        self.assertIsNotNone(store.get(sid))

    def test_cleanup_expired_returns_count(self) -> None:
        clock = _Clock(datetime(2025, 1, 1, tzinfo=timezone.utc))
        store = _make_store(clock=clock, idle_timeout=timedelta(minutes=5))
        store.create()
        store.create()
        clock.advance(timedelta(minutes=6))
        removed = store.cleanup_expired()
        self.assertEqual(removed, 2)
        self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
