"""In-memory session store for the Aria HTTP API.

Each session owns one ``Chatbot`` instance and a per-session lock, so
concurrent requests for the same session never interleave inside the
chatbot's stateful pieces (context manager, unknown streak). The store
itself is protected by a single lock for map mutations.

Not suitable for multi-process deployments (multiple uvicorn workers).
A Redis-backed store would be the production upgrade; single-worker
uvicorn is the deployment target for the capstone.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from aria.chatbot import Chatbot, ChatbotReply
from aria.context_manager import DEFAULT_MAX_TURNS
from aria.logger_config import get_logger
from aria.models import Intent

_LOGGER = get_logger("web.session_store")

DEFAULT_IDLE_TIMEOUT = timedelta(minutes=30)
"""Sessions idle longer than this are removed on the next access."""


@dataclass
class _SessionRecord:
    """Internal per-session state."""

    chatbot: Chatbot
    created_at: datetime
    last_used_at: datetime
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    """Thread-safe session_id -> Chatbot map with idle expiry."""

    def __init__(
        self,
        intents: Iterable[Intent],
        idle_timeout: timedelta = DEFAULT_IDLE_TIMEOUT,
        max_turns: int = DEFAULT_MAX_TURNS,
        clock: Callable[[], datetime] | None = None,
        transcript_dir: Path | None = None,
    ) -> None:
        """Create a store.

        Args:
            intents: Parsed intents to give each new ``Chatbot``.
            idle_timeout: Sessions idle longer than this are removed
                on the next access.
            max_turns: Sliding-window size passed to each ``Chatbot``.
            clock: Injectable clock for the store's own idle-expiry
                bookkeeping. Defaults to ``datetime.now(timezone.utc)``.
            transcript_dir: Optional transcript directory for each bot.

        Raises:
            ValueError: If ``idle_timeout`` is not positive.
        """
        if idle_timeout <= timedelta(0):
            raise ValueError("idle_timeout must be positive.")

        self._intents = tuple(intents)
        self._idle_timeout = idle_timeout
        self._max_turns = max_turns
        self._clock: Callable[[], datetime] = (
            clock or (lambda: datetime.now(timezone.utc))
        )
        self._transcript_dir = transcript_dir
        self._records: dict[str, _SessionRecord] = {}
        self._lock = threading.Lock()
        _LOGGER.debug(
            "SessionStore initialised (idle_timeout=%s, max_turns=%d)",
            idle_timeout,
            max_turns,
        )

    def __len__(self) -> int:
        """Return the number of active sessions."""
        with self._lock:
            return len(self._records)

    def create(self) -> str:
        """Create a new session and return its opaque ID."""
        session_id = str(uuid.uuid4())
        now = self._clock()
        bot = Chatbot(
            self._intents,
            max_turns=self._max_turns,
            transcript_dir=self._transcript_dir,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._records[session_id] = _SessionRecord(
                chatbot=bot, created_at=now, last_used_at=now
            )
        _LOGGER.info("Session created: %s", session_id)
        return session_id

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        with self._lock:
            existed = self._records.pop(session_id, None) is not None
        if existed:
            _LOGGER.info("Session deleted: %s", session_id)
        return existed

    def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns number removed."""
        now = self._clock()
        with self._lock:
            return self._purge_expired_locked(now)

    def get(self, session_id: str) -> Chatbot | None:
        """Return the bot for ``session_id``, or None if unknown/expired.

        Refreshes ``last_used_at`` on hit so a chatty session does not
        expire mid-conversation.
        """
        now = self._clock()
        with self._lock:
            self._purge_expired_locked(now)
            record = self._records.get(session_id)
            if record is None:
                return None
            record.last_used_at = now
            return record.chatbot

    def respond(
        self, session_id: str, message: str
    ) -> ChatbotReply | None:
        """Submit a user message under the per-session lock.

        Returns ``None`` if the session is unknown or expired. Raises
        ``SessionError`` if the underlying bot has already ended (a
        farewell has been sent); the API layer maps that to HTTP 409.
        """
        now = self._clock()
        with self._lock:
            self._purge_expired_locked(now)
            record = self._records.get(session_id)
            if record is None:
                return None
            record.last_used_at = now
        with record.lock:
            return record.chatbot.respond(message)

    def _purge_expired_locked(self, now: datetime) -> int:
        """Remove expired sessions. Caller must hold ``self._lock``."""
        cutoff = now - self._idle_timeout
        expired = [
            sid
            for sid, rec in self._records.items()
            if rec.last_used_at < cutoff
        ]
        for sid in expired:
            del self._records[sid]
        if expired:
            _LOGGER.info("Purged %d expired sessions", len(expired))
        return len(expired)
