#!/usr/bin/env python3
"""
Teste da Garantia 4 — regulamento consultado, não carregado.

Passos:
  1. Cria sessão nova (apto 101).
  2. Pergunta sobre horário da piscina aos domingos.
  3. Verifica que a resposta contém o horário correto (20h).
  4. Puxa GET /sessoes/{id}/eventos e:
     a. Confirma que nenhum evento contém trechos de capítulos NÃO relacionados.
     b. Mostra o trecho exato retornado pela tool para conferência.
  5. Confirma (por grep no código) que app/agents/principal.py NÃO menciona o regulamento
     nas instructions (texto do prompt).
"""

import json
import re
import sys

import requests

BASE_URL = "http://localhost:8000"
APTO = "101"

# Palavras/frases de capítulos NÃO relacionados à piscina que NÃO devem aparecer nos eventos
CAPITULOS_ALHEIOS = [
    # Capítulo III — Silêncio
    "período de silêncio",
    "Art. 16",
    "Art. 17",
    # Capítulo VI — Salão/Churrasqueira/Quadra
    "salão de festas",
    "churrasqueira",
    "quadra poliesportiva",
    "Art. 36",
    "Art. 37",
    # Capítulo VIII — Animais
    "animais domésticos",
    "Art. 52",
    "Art. 53",
    "espaço pet",
    # Capítulo IX — Mudanças
    "Art. 61",
    "elevador de serviço",
    # Capítulo X — Obras
    "Art. 69",
    "Art. 70",
    # Capítulo XI — Garagem
    "Art. 76",
    "Art. 77",
    # Capítulo XII — Lixo
    "Art. 83",
    "coleta seletiva",
    # Capítulo XIII — Penalidades
    "Art. 88",
    "Art. 89",
    "cota condominial",
]

# Horário correto (Art. 22, II): domingos e feriados das 9h às 20h
HORARIO_CORRETO_REGEX = re.compile(r"20h|20:00|vinte horas", re.IGNORECASE)


def criar_sessao(apto: str) -> str:
    r = requests.post(f"{BASE_URL}/sessoes", json={"apartamento": apto}, timeout=30)
    assert r.status_code == 201, f"Esperado 201, got {r.status_code}"
    return r.json()["session_id"]


def enviar_mensagem(sid: str, texto: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/sessoes/{sid}/mensagens",
        json={"texto": texto},
        timeout=90,
    )
    assert r.status_code == 200, f"Esperado 200, got {r.status_code}: {r.text}"
    return r.json()


def get_eventos(sid: str) -> list:
    r = requests.get(f"{BASE_URL}/sessoes/{sid}/eventos", timeout=30)
    assert r.status_code == 200
    return r.json()


def eventos_para_texto(eventos: list) -> str:
    """Serializa todos os eventos para string para busca de padrões."""
    return json.dumps(eventos, ensure_ascii=False)


def main():
    print("=" * 65)
    print("TESTE — Garantia 4: regulamento consultado, não carregado")
    print("=" * 65)

    erros = []

    # ------------------------------------------------------------------
    # Passo 1: sessão nova
    # ------------------------------------------------------------------
    print(f"\n[1] Criando sessão (apto {APTO})...")
    sid = criar_sessao(APTO)
    print(f"    session_id = {sid}")

    # ------------------------------------------------------------------
    # Passo 2: pergunta sobre piscina
    # ------------------------------------------------------------------
    pergunta = "Posso usar a piscina aos domingos à noite? Até que horas ela fica aberta?"
    print(f"\n[2] Enviando pergunta: \"{pergunta}\"")
    resp = enviar_mensagem(sid, pergunta)
    resposta = resp.get("resposta", "")
    print(f"\n    Resposta do agente:\n    {resposta}")

    # ------------------------------------------------------------------
    # Passo 3: horário correto na resposta
    # ------------------------------------------------------------------
    print("\n[3] Verificando horário de fechamento na resposta...")
    if HORARIO_CORRETO_REGEX.search(resposta):
        print("    ✅ Horário 20h encontrado na resposta.")
    else:
        erros.append("Resposta NÃO contém o horário correto (20h) para a piscina aos domingos.")
        print("    ❌ Horário 20h NÃO encontrado na resposta!")

    # ------------------------------------------------------------------
    # Passo 4: inspecionar eventos
    # ------------------------------------------------------------------
    print(f"\n[4] Puxando GET /sessoes/{sid}/eventos...")
    eventos = get_eventos(sid)
    print(f"    Total de eventos: {len(eventos)}")

    eventos_texto = eventos_para_texto(eventos)

    # Mostra o trecho retornado pela tool (busca em function_response dos eventos)
    print("\n    --- Trecho retornado pela tool consultar_regulamento ---")
    trecho_encontrado = False
    for ev in eventos:
        content = ev.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            fr = part.get("function_response") or {}
            if fr.get("name") == "consultar_regulamento":
                resultado = fr.get("response", {})
                print(f"    Seções: {resultado.get('secoes', [])}")
                print(f"    Trechos:\n")
                for linha in (resultado.get("trechos_relevantes", "") or "").splitlines():
                    print(f"      {linha}")
                trecho_encontrado = True
    if not trecho_encontrado:
        print("    (tool consultar_regulamento não encontrada nos eventos — verifique se foi chamada)")
        erros.append("Tool consultar_regulamento não aparece nos eventos da sessão.")
    print("    -------------------------------------------------------")

    # Verifica ausência de capítulos alheios nos eventos
    print("\n[4b] Verificando ausência de capítulos não relacionados nos eventos...")
    encontrados_alheios = []
    for frase in CAPITULOS_ALHEIOS:
        if frase.lower() in eventos_texto.lower():
            encontrados_alheios.append(frase)

    if encontrados_alheios:
        erros.append(
            f"Eventos contêm trechos de capítulos NÃO relacionados: {encontrados_alheios}"
        )
        print(f"    ❌ Encontrados trechos alheios: {encontrados_alheios}")
    else:
        print("    ✅ Nenhum trecho de capítulos alheios nos eventos.")

    # ------------------------------------------------------------------
    # Passo 5: principal.py não carrega regulamento nas instructions
    # ------------------------------------------------------------------
    print("\n[5] Verificando app/agents/principal.py (sem regulamento no prompt)...")
    principal_path = "app/agents/principal.py"
    with open(principal_path, encoding="utf-8") as f:
        principal_code = f.read()

    # Verifica que não há texto do regulamento ou carregamento do arquivo
    proibidos_no_principal = [
        "regulamento.md",
        "Art. 22",          # artigo da piscina
        "piscina funciona", # texto literal do regulamento
        "read_text",        # leitura de arquivo de regulamento direto
        "open(",            # abertura de arquivo
    ]
    achou_no_principal = [p for p in proibidos_no_principal if p in principal_code]
    if achou_no_principal:
        erros.append(f"principal.py contém referências proibidas: {achou_no_principal}")
        print(f"    ❌ Referências proibidas em principal.py: {achou_no_principal}")
    else:
        print("    ✅ principal.py não contém regulamento nem leitura direta do arquivo.")

    # Confirma que o regulamento só chega via sub-agente, não na instruction
    if "regulamento" in principal_code.lower():
        # Aceito: mencionar nome do especialista e importação de módulo
        linhas_com_reg = [
            l.strip() for l in principal_code.splitlines()
            if "regulamento" in l.lower()
        ]
        print(f"    (Linhas com 'regulamento' em principal.py: menção ao especialista apenas)")
        for l in linhas_com_reg:
            print(f"      {l}")

    # ------------------------------------------------------------------
    # Resultado final
    # ------------------------------------------------------------------
    print("\n" + "=" * 65)
    if erros:
        print("❌ FALHA:")
        for e in erros:
            print(f"   • {e}")
        sys.exit(1)
    else:
        print("✅ APROVADO — Garantia 4 confirmada:")
        print(f"   • Resposta contém horário 20h ✓")
        print(f"   • Nenhum capítulo alheio nos eventos ✓")
        print(f"   • principal.py não carrega o regulamento ✓")
    print("=" * 65)


if __name__ == "__main__":
    main()
