"""
Serviço ADK: encapsula o Runner e o DatabaseSessionService.

- Sessões persistidas em SQLite (data/sessions.db) para Garantia 3.
- Apartamento gravado em session.state["apartamento"] no momento da criação.
- ResumabilityConfig(is_resumable=True) para suporte ao fluxo de confirmação
  (Garantia 1 — retomada após request_confirmation).
"""

import os
from pathlib import Path

from google.adk.apps import App
from google.adk.apps._configs import ResumabilityConfig
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

from app.agents.principal import root_agent

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"

_APP_NAME = "residencial-aurora"

# Instâncias únicas reutilizadas pelo FastAPI (inicializadas no startup)
_session_service: DatabaseSessionService | None = None
_runner: Runner | None = None


def get_session_service() -> DatabaseSessionService:
    global _session_service
    if _session_service is None:
        raise RuntimeError("SessionService não inicializado. Chame init_runner() primeiro.")
    return _session_service


def get_runner() -> Runner:
    global _runner
    if _runner is None:
        raise RuntimeError("Runner não inicializado. Chame init_runner() primeiro.")
    return _runner


def init_runner() -> None:
    """Inicializa o DatabaseSessionService e o Runner. Chamado no startup do FastAPI."""
    global _session_service, _runner

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite+aiosqlite:///{DATA_DIR / 'sessions.db'}"

    _session_service = DatabaseSessionService(db_url=db_url)

    app = App(
        name=_APP_NAME,
        root_agent=root_agent,
        # ResumabilityConfig(is_resumable=True) habilita a retomada de invocações
        # interrompidas por request_confirmation (Garantia 1).
        resumability_config=ResumabilityConfig(is_resumable=True),
    )

    _runner = Runner(
        app=app,
        session_service=_session_service,
    )


def app_name() -> str:
    return _APP_NAME
