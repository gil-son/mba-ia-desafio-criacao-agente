"""
API do Residencial Aurora — FastAPI.

Rotas implementadas neste esqueleto (Passo 2):
  POST /sessoes                          — cria sessão ADK
  POST /sessoes/{session_id}/mensagens   — envia mensagem ao agente
  GET  /sessoes/{session_id}/eventos     — lista eventos da sessão

Rotas de verificação (sem modelo):
  GET /apartamentos/{numero}/reservas
  GET /apartamentos/{numero}/visitantes
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from google.adk.events import Event
from google.genai import types as genai_types
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.runner import app_name, get_runner, get_session_service, init_runner
from app.storage.db import Reserva, Visitante, get_db, init_db

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = BASE_DIR / "dados"


# ---------------------------------------------------------------------------
# Lifespan: inicializa banco e runner ao subir
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_runner()
    # Inicializa o serviço de sessão (cria tabelas do ADK se necessário)
    svc = get_session_service()
    await svc.__aenter__()
    yield
    await svc.__aexit__(None, None, None)


app = FastAPI(title="Residencial Aurora", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Schemas Pydantic
# ---------------------------------------------------------------------------

class CriarSessaoRequest(BaseModel):
    apartamento: str


class CriarSessaoResponse(BaseModel):
    session_id: str


class EnviarMensagemRequest(BaseModel):
    texto: str


class ConfirmacaoPendente(BaseModel):
    id: str
    acao: str
    detalhes: dict[str, Any]


class MensagemResponse(BaseModel):
    resposta: str
    confirmacoes_pendentes: list[ConfirmacaoPendente]


class ResponderConfirmacaoRequest(BaseModel):
    id: str
    confirmado: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_apartamentos() -> list[dict]:
    return json.loads((DADOS_DIR / "apartamentos.json").read_text())


def _apartamento_existe(numero: str) -> bool:
    return any(a["numero"] == numero for a in _load_apartamentos())


def _eventos_para_lista(session) -> list[dict]:
    """Serializa os eventos do ADK para dicionários JSON-safe."""
    eventos = []
    for ev in (session.events or []):
        if isinstance(ev, Event):
            try:
                eventos.append(ev.model_dump(mode="json"))
            except Exception:
                eventos.append({"raw": str(ev)})
        else:
            eventos.append(ev)
    return eventos


async def _run_agent(session_id: str, user_message: str) -> MensagemResponse:
    """Executa o agente para uma mensagem e coleta resposta + pendências."""
    runner = get_runner()
    _app_name = app_name()

    # Valida a chave antes de chamar o modelo, para evitar 500 cru.
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(
            status_code=422,
            detail="GOOGLE_API_KEY não configurada. Preencha o arquivo .env e reinicie a API.",
        )

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_message)],
    )

    resposta_texto = ""
    try:
        async for event in runner.run_async(
            user_id="morador",
            session_id=session_id,
            new_message=content,
        ):
            # Captura a resposta final de texto do agente
            if event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            resposta_texto += part.text
    except HTTPException:
        raise
    except Exception as exc:
        # Traduz qualquer erro do ADK/modelo em resposta HTTP controlada.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Pendências de confirmação ficam para implementação nos Passos 7-9
    confirmacoes: list[ConfirmacaoPendente] = []

    return MensagemResponse(
        resposta=resposta_texto,
        confirmacoes_pendentes=confirmacoes,
    )


# ---------------------------------------------------------------------------
# Rotas de sessão
# ---------------------------------------------------------------------------

@app.post("/sessoes", status_code=201, response_model=CriarSessaoResponse)
async def criar_sessao(req: CriarSessaoRequest):
    """Cria uma sessão ADK para o apartamento informado (201)."""
    svc = get_session_service()
    _app_name = app_name()

    session = await svc.create_session(
        app_name=_app_name,
        user_id="morador",
        state={"apartamento": req.apartamento},
    )
    return CriarSessaoResponse(session_id=session.id)


@app.post("/sessoes/{session_id}/mensagens", response_model=MensagemResponse)
async def enviar_mensagem(session_id: str, req: EnviarMensagemRequest):
    """Envia uma mensagem ao agente e devolve resposta + confirmações pendentes."""
    svc = get_session_service()
    _app_name = app_name()

    existing = await svc.get_session(
        app_name=_app_name, user_id="morador", session_id=session_id
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    return await _run_agent(session_id=session_id, user_message=req.texto)


@app.post("/sessoes/{session_id}/confirmacoes", response_model=MensagemResponse)
async def responder_confirmacao(session_id: str, req: ResponderConfirmacaoRequest):
    """Responde uma confirmação pendente (409 se o id não estiver pendente)."""
    svc = get_session_service()
    _app_name = app_name()

    existing = await svc.get_session(
        app_name=_app_name, user_id="morador", session_id=session_id
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    # Implementação real nos Passos 7-9; por ora retorna 409 para qualquer id
    raise HTTPException(
        status_code=409,
        detail="Nenhuma confirmação pendente com esse id nesta sessão.",
    )


@app.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str):
    """Lista todos os eventos gravados na sessão, em ordem."""
    svc = get_session_service()
    _app_name = app_name()

    session = await svc.get_session(
        app_name=_app_name, user_id="morador", session_id=session_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    return _eventos_para_lista(session)


# ---------------------------------------------------------------------------
# Rotas de verificação (leitura direta do banco, sem modelo)
# ---------------------------------------------------------------------------

@app.get("/apartamentos/{numero}/reservas")
def listar_reservas(numero: str, db: Session = Depends(get_db)):
    """Lista as reservas ativas de um apartamento."""
    reservas = (
        db.query(Reserva)
        .filter(Reserva.apartamento == numero, Reserva.status == "ativa")
        .all()
    )
    return [
        {"codigo": r.codigo, "area": r.area, "data": r.data} for r in reservas
    ]


@app.get("/apartamentos/{numero}/visitantes")
def listar_visitantes(numero: str, db: Session = Depends(get_db)):
    """Lista as autorizações de visita de um apartamento."""
    visitantes = (
        db.query(Visitante)
        .filter(Visitante.apartamento == numero)
        .all()
    )
    return [{"nome": v.nome, "data": v.data} for v in visitantes]
