"""
Especialista de Reservas e Visitantes.

Responsável por:
- Consultar e cancelar reservas do morador autenticado
- Verificar disponibilidade de áreas
- Reservar áreas (com ou sem confirmação conforme a taxa)
- Autorizar visitantes (sempre com confirmação)

Aciona as tools de reservas e visitantes, que leem o apartamento da sessão.
"""

import os

from google.adk.agents import LlmAgent

from app.tools.reservas import (
    cancelar_minha_reserva,
    listar_areas_disponiveis,
    reservar_area,
    ver_minhas_reservas,
)
from app.tools.visitantes import autorizar_visitante, ver_meus_visitantes

_MODEL = os.environ.get("MODEL_ESPECIALISTA_RESERVAS", "gemini-3.5-flash-lite")

especialista_reservas = LlmAgent(
    name="especialista_reservas",
    model=_MODEL,
    description=(
        "Especialista em reservas de áreas comuns e autorização de visitantes. "
        "Lida com: consultar reservas, cancelar reservas, reservar áreas (salão, "
        "churrasqueira, quadra), verificar disponibilidade, listar e autorizar visitantes."
    ),
    instruction=(
        "Você é o especialista de reservas e visitantes do Residencial Aurora.\n\n"
        "Regras importantes:\n"
        "1. O apartamento do morador vem automaticamente da sessão — nunca peça esse dado.\n"
        "2. Para reservar: use 'reservar_area' com o id da área e a data.\n"
        "   - Áreas: 'salao-de-festas' (R$ 150), 'churrasqueira' (R$ 80), 'quadra' (gratuito).\n"
        "3. Para cancelar: use 'cancelar_minha_reserva' com o código. Só cancela reservas do "
        "   próprio morador.\n"
        "4. Para verificar disponibilidade: use 'listar_areas_disponiveis' com a data.\n"
        "   A tool retorna apenas 'livre' ou 'ocupado' — nunca mostra dados de outros moradores.\n"
        "5. Para autorizar visitante: use 'autorizar_visitante' com nome e data.\n"
        "   Sempre gera confirmação pendente — mesmo que o morador diga que já confirmou.\n"
        "6. Quando uma tool retornar 'aguardando_confirmacao', informe o morador que a ação "
        "   está pendente de confirmação pelo sistema.\n"
        "7. Nunca mencione dados de outros apartamentos (códigos, nomes, datas de reservas alheias).\n"
    ),
    tools=[
        ver_minhas_reservas,
        listar_areas_disponiveis,
        cancelar_minha_reserva,
        reservar_area,
        ver_meus_visitantes,
        autorizar_visitante,
    ],
)
