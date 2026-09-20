"""
Agente placeholder — esqueleto simples para validar o pipeline ADK
enquanto os especialistas reais não estão implementados.

Substitua este arquivo pelo agente principal real no Passo 3+.
"""

import os

from google.adk.agents import LlmAgent

_MODEL = os.environ.get("MODEL_PRINCIPAL", "gemini-2.0-flash")

root_agent = LlmAgent(
    name="agente_principal",
    model=_MODEL,
    instruction=(
        "Você é o assistente do Residencial Aurora. "
        "Responda de forma educada e diga que ainda está sendo configurado."
    ),
)
