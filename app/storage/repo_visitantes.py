"""
Repositório de visitantes — operações de leitura e escrita sobre `visitantes`.
"""

import uuid

from sqlalchemy.orm import Session

from app.storage.db import Visitante


def listar_visitantes_apartamento(db: Session, apartamento: str) -> list[Visitante]:
    """Retorna todas as autorizações de visita do apartamento."""
    return (
        db.query(Visitante)
        .filter(Visitante.apartamento == apartamento)
        .all()
    )


def autorizar_visitante(
    db: Session, apartamento: str, nome: str, data: str
) -> tuple[bool, str]:
    """
    Registra uma autorização de visita.

    Retorna (sucesso, mensagem).
    """
    visitante = Visitante(
        id=str(uuid.uuid4()),
        apartamento=apartamento,
        nome=nome,
        data=data,
    )
    db.add(visitante)
    db.commit()
    return True, f"Visitante {nome} autorizado para {data}."
