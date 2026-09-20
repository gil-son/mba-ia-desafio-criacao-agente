"""
Especialista de Regulamento.

Responsável por responder dúvidas sobre o regulamento interno do condomínio.
Usa a tool 'consultar_regulamento' que retorna APENAS o trecho relevante —
nunca carrega o documento inteiro (Garantia 4).
"""

import os

from google.adk.agents import LlmAgent

from app.tools.regulamento import consultar_regulamento

_MODEL = os.environ.get("MODEL_ESPECIALISTA_REGULAMENTO", "gemini-3.5-flash-lite")

especialista_regulamento = LlmAgent(
    name="especialista_regulamento",
    model=_MODEL,
    description=(
        "Especialista em regulamento interno do condomínio. "
        "Responde dúvidas sobre regras, horários, normas de uso das áreas comuns, "
        "direitos e deveres dos moradores, animais, obras, garagem, lixo e penalidades."
    ),
    instruction=(
        "Você é o especialista de regulamento do Residencial Aurora.\n\n"
        "Ao responder dúvidas sobre o regulamento:\n"
        "1. Use sempre a tool 'consultar_regulamento' para buscar o trecho relevante.\n"
        "2. Baseie sua resposta EXCLUSIVAMENTE no trecho retornado pela tool.\n"
        "3. Seja objetivo e cite o artigo quando possível.\n"
        "4. Não invente regras que não constam no regulamento.\n"
        "5. Se a tool não encontrar informação, diga que não há regra específica e sugira "
        "   contato com a administração.\n"
    ),
    tools=[consultar_regulamento],
)
