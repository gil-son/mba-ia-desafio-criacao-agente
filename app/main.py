"""
API do Residencial Aurora — FastAPI.

Rotas:
  POST /sessoes                          — cria sessão ADK (201)
  POST /sessoes/{session_id}/mensagens   — envia mensagem ao agente (200)
  POST /sessoes/{session_id}/confirmacoes — responde confirmação pendente (200/409)
  GET  /sessoes/{session_id}/eventos     — lista eventos da sessão (200/404)

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


def _extrair_confirmacoes_pendentes(session) -> list[ConfirmacaoPendente]:
    """
    Varre os eventos da sessão em busca de pedidos de confirmação pendentes.

    Um pedido de confirmação é representado por um evento com `long_running_tool_ids`
    que contém chamadas de função com nome 'adk_request_confirmation'. Um pedido
    é considerado RESPONDIDO quando há um evento de resposta (role='user') com uma
    FunctionResponse cujo id bate com o da chamada de confirmação.

    Garantia 1: coleta apenas pedidos que ainda não foram respondidos.
    """
    events = session.events or []

    # IDs de adk_request_confirmation que já foram respondidos
    responded_ids: set[str] = set()
    for ev in events:
        if ev.content and ev.content.role == "user":
            for part in (ev.content.parts or []):
                if part.function_response and part.function_response.name == "adk_request_confirmation":
                    responded_ids.add(part.function_response.id)

    # Coleta pedidos de confirmação ainda pendentes
    pending: list[ConfirmacaoPendente] = []
    for ev in events:
        if not ev.long_running_tool_ids:
            continue
        for part in (ev.content.parts or [] if ev.content else []):
            fc = part.function_call
            if not fc or fc.name != "adk_request_confirmation":
                continue
            if fc.id not in ev.long_running_tool_ids:
                continue
            if fc.id in responded_ids:
                continue

            # Extrai payload do ToolConfirmation
            args = fc.args or {}
            tool_confirmation = args.get("toolConfirmation", {})
            payload = tool_confirmation.get("payload") or {}
            hint = tool_confirmation.get("hint", "")

            # Determina ação e detalhes a partir do payload
            if "area" in payload and "data" in payload:
                acao = "reservar_area"
                detalhes = {
                    "area": payload.get("area"),
                    "data": payload.get("data"),
                }
                if "valor" in payload:
                    detalhes["valor"] = payload["valor"]
            elif "nome" in payload and "data" in payload:
                acao = "autorizar_visitante"
                detalhes = {
                    "nome": payload.get("nome"),
                    "data": payload.get("data"),
                }
            else:
                acao = "confirmar_acao"
                detalhes = payload if isinstance(payload, dict) else {"hint": hint}

            pending.append(ConfirmacaoPendente(
                id=fc.id,
                acao=acao,
                detalhes=detalhes,
            ))

    return pending


async def _run_agent(
    session_id: str,
    new_message: genai_types.Content,
) -> MensagemResponse:
    """Executa o agente para uma nova mensagem e coleta resposta + pendências."""
    runner = get_runner()
    _app_name = app_name()

    # Valida a chave antes de chamar o modelo
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(
            status_code=422,
            detail="GOOGLE_API_KEY não configurada. Preencha o arquivo .env e reinicie a API.",
        )

    resposta_texto = ""
    try:
        async for event in runner.run_async(
            user_id="morador",
            session_id=session_id,
            new_message=new_message,
        ):
            if event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            resposta_texto += part.text
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Recarrega sessão para coletar pendências atualizadas
    svc = get_session_service()
    session = await svc.get_session(
        app_name=_app_name, user_id="morador", session_id=session_id
    )
    confirmacoes = _extrair_confirmacoes_pendentes(session) if session else []

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

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=req.texto)],
    )
    return await _run_agent(session_id=session_id, new_message=content)


@app.post("/sessoes/{session_id}/confirmacoes", response_model=MensagemResponse)
async def responder_confirmacao(session_id: str, req: ResponderConfirmacaoRequest):
    """
    Responde uma confirmação pendente.

    - 200: confirmação processada (aprovada ou negada)
    - 409: o id não está entre as confirmações pendentes desta sessão
    - 404: sessão não existe

    Garantia 1: a ação só é executada (ou descartada) por esta rota,
    nunca por mensagem de texto do morador.
    """
    svc = get_session_service()
    _app_name = app_name()

    session = await svc.get_session(
        app_name=_app_name, user_id="morador", session_id=session_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    # Verifica se o id está pendente nesta sessão
    pendentes = _extrair_confirmacoes_pendentes(session)
    ids_pendentes = {p.id for p in pendentes}

    if req.id not in ids_pendentes:
        raise HTTPException(
            status_code=409,
            detail="Nenhuma confirmação pendente com esse id nesta sessão.",
        )

    # Monta o FunctionResponse de confirmação para retomar o Runner
    # O id deve ser o mesmo da chamada adk_request_confirmation
    confirmation_response = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(
                function_response=genai_types.FunctionResponse(
                    id=req.id,
                    name="adk_request_confirmation",
                    response={"confirmed": req.confirmado},
                )
            )
        ],
    )

    return await _run_agent(session_id=session_id, new_message=confirmation_response)


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
