"""FastAPI application for the Aria chatbot HTTP API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import (
    FastAPI,
    HTTPException,
    Path as ApiPath,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from aria import __version__
from aria.exceptions import (
    InputValidationError,
    ResponseGenerationError,
    SessionError,
)
from aria.logger_config import configure_logging, get_logger
from aria.pattern_matcher import load_intents_from_json

from .schemas import (
    ChatRequest,
    ChatResponse,
    CreateSessionResponse,
    HealthResponse,
    HistoryResponse,
    MessageEntry,
)
from .session_store import SessionStore

_LOGGER = get_logger("web.api")

_DEFAULT_CONFIG_PATH = Path("config/intents.json")
_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _config_path() -> Path:
    env = os.environ.get("ARIA_CONFIG")
    return Path(env) if env else _DEFAULT_CONFIG_PATH


def _cors_origins() -> list[str]:
    raw = os.environ.get("ARIA_CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    intents = load_intents_from_json(_config_path())
    app.state.session_store = SessionStore(intents)
    _LOGGER.info(
        "Aria API ready with %d intents, %d active sessions",
        len(intents),
        len(app.state.session_store),
    )
    yield
    _LOGGER.info("Aria API shutting down")


def create_app() -> FastAPI:
    """Construct the FastAPI application."""
    app = FastAPI(
        title="Aria Chatbot API",
        version=__version__,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Return service status and the active-session count."""
        return HealthResponse(
            status="ok",
            version=__version__,
            active_sessions=len(app.state.session_store),
        )

    @app.post(
        "/api/session",
        response_model=CreateSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_session() -> CreateSessionResponse:
        """Create a new chat session and return its ID."""
        return CreateSessionResponse(
            session_id=app.state.session_store.create()
        )

    @app.delete(
        "/api/session/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def end_session(
        session_id: str = ApiPath(..., min_length=1, max_length=64),
    ) -> Response:
        """Delete a session; 404 if unknown or already expired."""
        if not app.state.session_store.delete(session_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or expired.",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(body: ChatRequest) -> ChatResponse:
        """Send a message to a session and return the bot reply."""
        try:
            reply = app.state.session_store.respond(
                body.session_id, body.message
            )
        except SessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        except InputValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except ResponseGenerationError as exc:
            _LOGGER.exception("Response generation failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The server could not generate a reply.",
            ) from exc

        if reply is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or expired.",
            )

        return ChatResponse(
            reply=reply.text,
            category=reply.category.value,
            intent=reply.intent,
            timestamp=reply.timestamp,
        )

    @app.get(
        "/api/history/{session_id}", response_model=HistoryResponse
    )
    def history(
        session_id: str = ApiPath(..., min_length=1, max_length=64),
    ) -> HistoryResponse:
        """Return the transcript of a session; 404 if unknown."""
        bot = app.state.session_store.get(session_id)
        if bot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or expired.",
            )
        return HistoryResponse(
            session_id=session_id,
            messages=[
                MessageEntry(
                    role=msg.role.value,
                    text=msg.text,
                    timestamp=msg.timestamp,
                    category=(
                        msg.category.value if msg.category else None
                    ),
                    intent=msg.intent,
                )
                for msg in bot.context.messages
            ],
            facts=dict(bot.context.facts),
        )

    # Static mount LAST so /api/* routes match first.
    if _STATIC_DIR.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=_STATIC_DIR, html=True),
            name="static",
        )

    return app


app = create_app()