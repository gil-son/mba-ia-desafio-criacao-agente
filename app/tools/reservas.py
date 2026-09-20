"""
Tools de reservas para o especialista de reservas.

Garantia 2: o apartamento é sempre lido de tool_context.state["apartamento"],
nunca de um argumento fornecido pelo modelo. Nenhuma tool expõe quem é o dono
de uma reserva de outro apartamento.
"""

import json
from pathlib import Path
from typing import Optional

from google.adk.tools import ToolContext

from app.storage.db import SessionLocal
from app.storage.repo_reservas import (
    cancelar_reserva as _cancelar,
    criar_reserva as _criar,
    get_area,
    listar_reservas_apartamento,
    list_areas,
    verificar_disponibilidade,
)

DADOS_DIR = Path(__file__).resolve().parent.parent.parent / "dados"


def _load_apartamentos() -> list[dict]:
    return json.loads((DADOS_DIR / "apartamentos.json").read_text())


# ---------------------------------------------------------------------------
# Tool: listar minhas reservas
# ---------------------------------------------------------------------------

def ver_minhas_reservas(tool_context: ToolContext) -> dict:
    """
    Lista as reservas ativas do morador autenticado.

    Não aceita nenhum parâmetro de apartamento — usa sempre o da sessão.
    """
    apartamento = tool_context.state["apartamento"]
    with SessionLocal() as db:
        reservas = listar_reservas_apartamento(db, apartamento)
    if not reservas:
        return {"reservas": [], "mensagem": "Você não tem reservas ativas no momento."}
    return {
        "reservas": [
            {"codigo": r.codigo, "area": r.area, "data": r.data}
            for r in reservas
        ]
    }


# ---------------------------------------------------------------------------
# Tool: listar áreas disponíveis
# ---------------------------------------------------------------------------

def listar_areas_disponiveis(data: str, tool_context: ToolContext) -> dict:
    """
    Verifica a disponibilidade de todas as áreas comuns em uma data.

    Retorna somente 'livre' ou 'ocupado' por área — nunca o dono da reserva.

    Args:
        data: Data no formato AAAA-MM-DD.
    """
    with SessionLocal() as db:
        result = []
        for area in list_areas():
            livre = verificar_disponibilidade(db, area["id"], data)
            result.append({
                "id": area["id"],
                "nome": area["nome"],
                "taxa": area["taxa"],
                "status": "livre" if livre else "ocupado",
            })
    return {"data": data, "areas": result}


# ---------------------------------------------------------------------------
# Tool: cancelar reserva própria
# ---------------------------------------------------------------------------

def cancelar_minha_reserva(codigo: str, tool_context: ToolContext) -> dict:
    """
    Cancela uma reserva do morador autenticado pelo código.

    Só cancela reservas do próprio apartamento (validação no código).
    Não gera confirmação pendente (regra de negócio 4).

    Args:
        codigo: Código da reserva (ex: RSV-1377).
    """
    apartamento = tool_context.state["apartamento"]
    with SessionLocal() as db:
        sucesso, mensagem = _cancelar(db, codigo, apartamento)
    return {"sucesso": sucesso, "mensagem": mensagem}


# ---------------------------------------------------------------------------
# Tool: reservar área
# ---------------------------------------------------------------------------

def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """
    Reserva uma área comum para o morador autenticado.

    - Área com taxa zero: grava direto, sem confirmação (passo 6).
    - Área com taxa maior que zero: solicita confirmação antes de gravar (Garantia 1).

    Args:
        area: ID da área (ex: 'salao-de-festas', 'churrasqueira', 'quadra').
        data: Data desejada no formato AAAA-MM-DD.
    """
    apartamento = tool_context.state["apartamento"]

    area_info = get_area(area)
    if area_info is None:
        return {"sucesso": False, "mensagem": f"Área '{area}' não encontrada."}

    # Verifica disponibilidade antes de prosseguir (verifica conflito simples)
    with SessionLocal() as db:
        livre = verificar_disponibilidade(db, area, data)

    if not livre:
        # Garantia 2: não revela quem está reservando — apenas informa ocupado
        return {
            "sucesso": False,
            "mensagem": f"A data {data} já está ocupada para {area_info['nome']}.",
        }

    taxa = area_info.get("taxa", 0)

    if taxa > 0:
        # Garantia 1: cobra confirmação para ações com cobrança
        tool_context.request_confirmation(
            hint=(
                f"Confirma a reserva de {area_info['nome']} para {data}? "
                f"Será cobrada uma taxa de R$ {taxa:.2f}."
            ),
            payload={"area": area, "data": data, "valor": taxa},
        )
        # Retorna sem gravar — a tool será re-executada após confirmação
        return {
            "aguardando_confirmacao": True,
            "mensagem": (
                f"Aguardando confirmação para reservar {area_info['nome']} em {data} "
                f"(taxa: R$ {taxa:.2f})."
            ),
        }

    # Área sem taxa: grava direto (passo 6)
    with SessionLocal() as db:
        sucesso, mensagem, codigo = _criar(db, apartamento, area, data)
    return {"sucesso": sucesso, "mensagem": mensagem, "codigo": codigo}
