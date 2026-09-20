"""
Tools de visitantes para o especialista de reservas.

Garantia 1: autorizar visitante SEMPRE gera confirmação pendente (libera acesso).
Garantia 2: o apartamento vem da sessão, nunca de argumento do modelo.
"""

from google.adk.tools import ToolContext

from app.storage.db import SessionLocal
from app.storage.repo_visitantes import (
    autorizar_visitante as _autorizar,
    listar_visitantes_apartamento,
)


# ---------------------------------------------------------------------------
# Tool: listar meus visitantes
# ---------------------------------------------------------------------------

def ver_meus_visitantes(tool_context: ToolContext) -> dict:
    """
    Lista as autorizações de visita do morador autenticado.

    Não aceita parâmetro de apartamento — usa sempre o da sessão.
    """
    apartamento = tool_context.state["apartamento"]
    with SessionLocal() as db:
        visitantes = listar_visitantes_apartamento(db, apartamento)
    if not visitantes:
        return {"visitantes": [], "mensagem": "Nenhum visitante autorizado no momento."}
    return {
        "visitantes": [{"nome": v.nome, "data": v.data} for v in visitantes]
    }


# ---------------------------------------------------------------------------
# Tool: autorizar visitante (com confirmação obrigatória — Garantia 1)
# ---------------------------------------------------------------------------

def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """
    Autoriza a entrada de um visitante no condomínio.

    Sempre requer confirmação antes de gravar (Garantia 1 — libera acesso).
    O morador não pode pular a confirmação dizendo "já confirmo aqui".

    Fluxo de dois passos (mesmo padrão de reservar_area):
      1. Primeira execução: tool_context.tool_confirmation é None →
         chama request_confirmation e retorna sem gravar.
      2. Re-execução após confirmação: tool_context.tool_confirmation está
         preenchido → grava se confirmed=True, recusa se confirmed=False.

    Args:
        nome: Nome completo do visitante.
        data: Data da visita no formato AAAA-MM-DD.
    """
    apartamento = tool_context.state["apartamento"]

    # Re-execução pós-confirmação: tool_confirmation foi preenchido pelo ADK
    if tool_context.tool_confirmation is not None:
        if not tool_context.tool_confirmation.confirmed:
            return {
                "sucesso": False,
                "mensagem": f"Autorização de {nome} em {data} cancelada pelo morador.",
            }
        # Aprovado — grava o visitante
        with SessionLocal() as db:
            sucesso, mensagem = _autorizar(db, apartamento, nome, data)
        return {"sucesso": sucesso, "mensagem": mensagem}

    # Primeira execução: libera acesso → confirmação obrigatória (Garantia 1)
    # Isso garante que "já estou confirmando aqui" no texto nunca substitui
    # a rota POST /sessoes/{id}/confirmacoes.
    tool_context.request_confirmation(
        hint=f"Confirma a autorização de entrada para {nome} em {data}?",
        payload={"nome": nome, "data": data},
    )
    # Retorna sem gravar — a tool será re-executada com tool_confirmation preenchido
    return {
        "aguardando_confirmacao": True,
        "mensagem": f"Aguardando confirmação para autorizar {nome} em {data}.",
    }
