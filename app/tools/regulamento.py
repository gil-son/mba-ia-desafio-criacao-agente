"""
Tool de consulta ao regulamento interno.

Garantia 4: retorna APENAS o trecho relevante à pergunta — nunca o documento inteiro.
O agente principal não tem o regulamento nas instruções.
"""

import re
from pathlib import Path

REGULAMENTO_PATH = Path(__file__).resolve().parent.parent.parent / "dados" / "regulamento.md"

# Cache do conteúdo dividido em seções (capítulos + artigos)
_SECTIONS: list[dict] = []


def _load_sections() -> list[dict]:
    """
    Divide o regulamento em seções (capítulos e artigos).
    Cada seção tem: titulo, conteudo, palavras-chave extraídas do título.
    """
    text = REGULAMENTO_PATH.read_text(encoding="utf-8")
    sections: list[dict] = []

    # Divide por cabeçalhos markdown (## Capítulo) ou artigos (**Art. N.**)
    # Estratégia: capturar blocos de texto por heading/artigo
    current_title = "Introdução"
    current_lines: list[str] = []

    for line in text.splitlines():
        # Novo capítulo (heading ##)
        if line.startswith("## "):
            if current_lines:
                sections.append({
                    "titulo": current_title,
                    "conteudo": "\n".join(current_lines).strip(),
                })
            current_title = line.lstrip("# ").strip()
            current_lines = [line]
        # Novo artigo começa com **Art.
        elif re.match(r"^\*\*Art\.\s+\d+", line):
            if current_lines and not current_lines[0].startswith("## "):
                # Acumula artigos dentro do mesmo capítulo em blocos de ~3 artigos
                # para não granularizar demais
                sections.append({
                    "titulo": current_title,
                    "conteudo": "\n".join(current_lines).strip(),
                })
                current_lines = [line]
            else:
                current_lines.append(line)
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "titulo": current_title,
            "conteudo": "\n".join(current_lines).strip(),
        })

    return sections


def _get_sections() -> list[dict]:
    global _SECTIONS
    if not _SECTIONS:
        _SECTIONS = _load_sections()
    return _SECTIONS


def _score_section(section: dict, query_lower: str, keywords: list[str]) -> int:
    """
    Pontua uma seção com base na relevância para a consulta.
    """
    titulo_lower = section["titulo"].lower()
    conteudo_lower = section["conteudo"].lower()
    score = 0

    for kw in keywords:
        if kw in titulo_lower:
            score += 3
        if kw in conteudo_lower:
            score += 1

    # Bonus para correspondência direta no titulo
    if any(kw in titulo_lower for kw in keywords):
        score += 2

    return score


# Mapeamento de termos comuns às seções relevantes
_KEYWORD_MAP = {
    "piscina": ["piscina", "IV"],
    "academia": ["academia", "V"],
    "salão": ["salão", "festas", "VI"],
    "churrasqueira": ["churrasqueira", "VI"],
    "quadra": ["quadra", "VI"],
    "animal": ["animal", "VIII", "pet"],
    "cachorro": ["animal", "VIII", "pet"],
    "gato": ["animal", "VIII"],
    "mudança": ["mudança", "IX"],
    "obra": ["obra", "X", "reforma"],
    "reforma": ["reforma", "X"],
    "garagem": ["garagem", "XI"],
    "veículo": ["garagem", "XI", "veículo"],
    "lixo": ["lixo", "XII", "reciclagem"],
    "reciclagem": ["reciclagem", "XII"],
    "multa": ["multa", "XIII", "penalidade"],
    "visitante": ["visitante", "portaria", "VII"],
    "portaria": ["portaria", "VII"],
    "barulho": ["silêncio", "III"],
    "silêncio": ["silêncio", "III"],
    "ruído": ["silêncio", "III"],
    "elevador": ["elevador", "XIV"],
    "reserva": ["reserva", "VI"],
    "horário": ["horário", "funcionamento"],
    "domingo": ["piscina", "IV", "domingo"],
    "feriado": ["piscina", "feriado"],
}


def consultar_regulamento(pergunta: str) -> dict:
    """
    Busca no regulamento interno o trecho relevante para a pergunta.

    Retorna apenas o trecho relevante — nunca o documento inteiro.
    O agente principal não tem o regulamento nas instruções; esta tool
    é chamada apenas pelo especialista de regulamento.

    Args:
        pergunta: Dúvida ou assunto a ser consultado no regulamento.
    """
    if not pergunta or not pergunta.strip():
        return {"erro": "Pergunta vazia."}

    query_lower = pergunta.lower()
    sections = _get_sections()

    # Extrai palavras-chave da pergunta
    keywords: list[str] = []
    words = re.findall(r"\w+", query_lower)
    # Adiciona palavras da pergunta com mais de 3 letras
    keywords.extend(w for w in words if len(w) > 3)
    # Expande com mapeamento de sinônimos
    for word in list(words):
        if word in _KEYWORD_MAP:
            keywords.extend(_KEYWORD_MAP[word])

    # Remove duplicatas
    keywords = list(dict.fromkeys(keywords))

    # Pontua cada seção
    scored = [
        (section, _score_section(section, query_lower, keywords))
        for section in sections
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Retorna as 2 seções mais relevantes (ou 1 se só uma tiver pontuação > 0)
    top = [s for s, score in scored if score > 0][:2]

    if not top:
        # Fallback: busca literal das palavras mais longas
        palavras_longas = sorted(words, key=len, reverse=True)[:3]
        for section in sections:
            for palavra in palavras_longas:
                if palavra in section["conteudo"].lower():
                    top.append(section)
                    break
            if top:
                break

    if not top:
        return {
            "resultado": "Não encontrei informação específica sobre esse assunto no regulamento.",
            "dica": "Consulte o zelador ou a administração para obter mais detalhes.",
        }

    trechos = "\n\n---\n\n".join(s["conteudo"] for s in top)
    return {
        "trechos_relevantes": trechos,
        "secoes": [s["titulo"] for s in top],
    }
