"""
Banco de dados de negócio do condomínio (SQLite via SQLAlchemy síncrono).

Tabelas:
  - reservas  : estado corrente das reservas (ativas + canceladas)
  - visitantes: autorizações de visita

Na primeira subida (ou após reset.sh), o banco é criado e populado a partir
dos arquivos imutáveis em dados/.
"""

import json
import os
from pathlib import Path

from sqlalchemy import (
    Column,
    Index,
    String,
    Float,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DADOS_DIR = BASE_DIR / "dados"
DATA_DIR = BASE_DIR / "data"
DB_URL = f"sqlite:///{DATA_DIR / 'condominio.db'}"


def _enable_wal(dbapi_connection, connection_record):  # noqa: ARG001
    """Ativa WAL mode para melhor concorrência com SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
event.listen(engine, "connect", _enable_wal)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


class Reserva(Base):
    __tablename__ = "reservas"

    codigo = Column(String, primary_key=True)
    apartamento = Column(String, nullable=False, index=True)
    area = Column(String, nullable=False)
    data = Column(String, nullable=False)  # YYYY-MM-DD
    status = Column(String, nullable=False, default="ativa")  # ativa | cancelada


class Visitante(Base):
    __tablename__ = "visitantes"

    id = Column(String, primary_key=True)  # uuid
    apartamento = Column(String, nullable=False, index=True)
    nome = Column(String, nullable=False)
    data = Column(String, nullable=False)  # YYYY-MM-DD


# Índice único parcial: apenas uma reserva ativa por (area, data).
# Isso é a Garantia 5 — a exclusividade é garantida no momento do INSERT.
Index(
    "uq_reserva_ativa_area_data",
    Reserva.area,
    Reserva.data,
    unique=True,
    sqlite_where=text("status = 'ativa'"),
)


def _seed(session: Session) -> None:
    """Popula o banco a partir dos arquivos de dados/ se estiver vazio."""
    if session.query(Reserva).count() == 0:
        reservas = json.loads((DADOS_DIR / "reservas.json").read_text())
        for r in reservas:
            session.add(
                Reserva(
                    codigo=r["codigo"],
                    apartamento=r["apartamento"],
                    area=r["area"],
                    data=r["data"],
                    status="ativa",
                )
            )

    if session.query(Visitante).count() == 0:
        import uuid

        visitantes = json.loads((DADOS_DIR / "visitantes.json").read_text())
        for v in visitantes:
            session.add(
                Visitante(
                    id=str(uuid.uuid4()),
                    apartamento=v["apartamento"],
                    nome=v["nome"],
                    data=v["data"],
                )
            )

    session.commit()


def init_db() -> None:
    """Cria as tabelas e faz seed inicial. Chamado no startup do FastAPI."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        _seed(session)


def get_db():
    """Dependency do FastAPI para obter uma sessão de banco."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
