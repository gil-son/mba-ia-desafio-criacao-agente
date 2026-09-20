"""
Repositório de reservas — operações de leitura e escrita sobre a tabela `reservas`.

Todas as operações que envolvem o apartamento do solicitante recebem esse
valor direto do banco/sessão ADK, nunca de um parâmetro escolhido pelo modelo.
"""

import json
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.storage.db import Reserva

DADOS_DIR = Path(__file__).resolve().parent.parent.parent / "dados"


def _load_areas() -> dict[str, dict]:
    areas = json.loads((DADOS_DIR / "areas.json").read_text())
    return {a["id"]: a for a in areas}


# Cache em memória para evitar releitura repetida (dados imutáveis)
_AREAS: dict[str, dict] = {}


def get_area(area_id: str) -> Optional[dict]:
    global _AREAS
    if not _AREAS:
        _AREAS = _load_areas()
    return _AREAS.get(area_id)


def list_areas() -> list[dict]:
    global _AREAS
    if not _AREAS:
        _AREAS = _load_areas()
    return list(_AREAS.values())


def listar_reservas_apartamento(db: Session, apartamento: str) -> list[Reserva]:
    """Retorna as reservas ativas do apartamento informado."""
    return (
        db.query(Reserva)
        .filter(Reserva.apartamento == apartamento, Reserva.status == "ativa")
        .all()
    )


def verificar_disponibilidade(db: Session, area: str, data: str) -> bool:
    """Retorna True se a data está livre para a área (sem reserva ativa)."""
    existente = (
        db.query(Reserva)
        .filter(
            Reserva.area == area,
            Reserva.data == data,
            Reserva.status == "ativa",
        )
        .first()
    )
    return existente is None


def cancelar_reserva(
    db: Session, codigo: str, apartamento: str
) -> tuple[bool, str]:
    """
    Cancela uma reserva pelo código, validando que pertence ao apartamento.

    Retorna (sucesso, mensagem).
    """
    reserva = db.query(Reserva).filter(Reserva.codigo == codigo).first()
    if reserva is None:
        return False, f"Reserva {codigo} não encontrada."
    if reserva.status != "ativa":
        return False, f"Reserva {codigo} já está cancelada."
    if reserva.apartamento != apartamento:
        # Nunca revelar a quem pertence — Garantia 2
        return False, f"Reserva {codigo} não pertence ao seu apartamento."
    reserva.status = "cancelada"
    db.commit()
    return True, f"Reserva {codigo} cancelada com sucesso."


def criar_reserva(
    db: Session, apartamento: str, area: str, data: str
) -> tuple[bool, str, Optional[str]]:
    """
    Cria uma reserva ativa. Usa INSERT atômico para Garantia 5.

    Retorna (sucesso, mensagem, codigo_da_reserva|None).
    """
    area_info = get_area(area)
    if area_info is None:
        return False, f"Área '{area}' não encontrada.", None

    codigo = f"RSV-{uuid.uuid4().hex[:8].upper()}"
    reserva = Reserva(
        codigo=codigo,
        apartamento=apartamento,
        area=area,
        data=data,
        status="ativa",
    )
    try:
        db.add(reserva)
        db.commit()
        return True, f"Reserva {codigo} criada para {area_info['nome']} em {data}.", codigo
    except IntegrityError:
        db.rollback()
        return (
            False,
            f"Não foi possível reservar: a data {data} já está ocupada para {area_info['nome']}.",
            None,
        )
