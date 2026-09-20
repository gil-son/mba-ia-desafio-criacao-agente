#!/usr/bin/env python3
"""
Teste de concorrência — Garantia 5 (Passo 14).

Simula o fluxo do avaliador:
  1. Cria S3 (apto 101) e S4 (apto 201).
  2. Envia "Reserve o salão de festas para 2030-05-11" em cada sessão.
  3. Coleta as confirmações pendentes de ambas as sessões.
  4. Aprova as duas confirmações SIMULTANEAMENTE via threading.
  5. Verifica:
     - Ambas as respostas HTTP devem ser 200.
     - A soma de reservas ativas para salão em 2030-05-11 deve ser exatamente 1.

Uso:
    python scripts/test_concorrencia.py [--url http://localhost:8000]
"""

import argparse
import json
import sys
import threading
import time
from typing import Optional

import requests

BASE_URL = "http://localhost:8000"
AREA = "salao-de-festas"
DATA = "2030-05-11"
APTO_S3 = "101"
APTO_S4 = "201"


def criar_sessao(apartamento: str) -> str:
    r = requests.post(f"{BASE_URL}/sessoes", json={"apartamento": apartamento}, timeout=30)
    assert r.status_code == 201, f"criar_sessao {apartamento}: esperado 201, got {r.status_code} — {r.text}"
    sid = r.json()["session_id"]
    print(f"  [sessão criada] apto={apartamento} session_id={sid}")
    return sid


def enviar_mensagem(session_id: str, texto: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/sessoes/{session_id}/mensagens",
        json={"texto": texto},
        timeout=60,
    )
    assert r.status_code == 200, f"enviar_mensagem: esperado 200, got {r.status_code} — {r.text}"
    return r.json()


def responder_confirmacao(session_id: str, conf_id: str, confirmado: bool) -> tuple[int, dict]:
    r = requests.post(
        f"{BASE_URL}/sessoes/{session_id}/confirmacoes",
        json={"id": conf_id, "confirmado": confirmado},
        timeout=60,
    )
    return r.status_code, r.json()


def contar_reservas_salao(apto: str) -> list[dict]:
    r = requests.get(f"{BASE_URL}/apartamentos/{apto}/reservas", timeout=10)
    assert r.status_code == 200
    return [rv for rv in r.json() if rv["area"] == AREA and rv["data"] == DATA]


def main():
    global BASE_URL
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=BASE_URL)
    args = parser.parse_args()
    BASE_URL = args.url.rstrip("/")

    print("=" * 60)
    print("TESTE DE CONCORRÊNCIA — Garantia 5")
    print(f"  Área: {AREA}  |  Data: {DATA}")
    print(f"  API:  {BASE_URL}")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Passo 1: criar as sessões
    # ------------------------------------------------------------------
    print("\n[1] Criando sessões S3 (apto 101) e S4 (apto 201)...")
    s3 = criar_sessao(APTO_S3)
    s4 = criar_sessao(APTO_S4)

    # ------------------------------------------------------------------
    # Passo 2: enviar pedidos de reserva em cada sessão
    # ------------------------------------------------------------------
    print(f"\n[2] Enviando pedido de reserva do {AREA} para {DATA} em S3 e S4...")
    msg = f"Reserve o salão de festas para {DATA}."

    resp_s3 = enviar_mensagem(s3, msg)
    resp_s4 = enviar_mensagem(s4, msg)

    print(f"  S3 confirmacoes_pendentes: {resp_s3['confirmacoes_pendentes']}")
    print(f"  S4 confirmacoes_pendentes: {resp_s4['confirmacoes_pendentes']}")

    pend_s3 = resp_s3.get("confirmacoes_pendentes", [])
    pend_s4 = resp_s4.get("confirmacoes_pendentes", [])

    assert pend_s3, f"S3 deveria ter confirmação pendente, mas got: {resp_s3}"
    assert pend_s4, f"S4 deveria ter confirmação pendente, mas got: {resp_s4}"

    conf_id_s3 = pend_s3[0]["id"]
    conf_id_s4 = pend_s4[0]["id"]
    print(f"  conf_id S3={conf_id_s3}")
    print(f"  conf_id S4={conf_id_s4}")

    # ------------------------------------------------------------------
    # Passo 3: aprovar ambas SIMULTANEAMENTE via threading
    # ------------------------------------------------------------------
    print("\n[3] Aprovando as duas confirmações SIMULTANEAMENTE...")
    results: dict[str, Optional[tuple[int, dict]]] = {"s3": None, "s4": None}
    barrier = threading.Barrier(2)

    def approve_s3():
        barrier.wait()  # sincroniza para disparar ao mesmo tempo
        results["s3"] = responder_confirmacao(s3, conf_id_s3, True)

    def approve_s4():
        barrier.wait()
        results["s4"] = responder_confirmacao(s4, conf_id_s4, True)

    t3 = threading.Thread(target=approve_s3)
    t4 = threading.Thread(target=approve_s4)
    t3.start()
    t4.start()
    t3.join(timeout=90)
    t4.join(timeout=90)

    status_s3, body_s3 = results["s3"]
    status_s4, body_s4 = results["s4"]

    print(f"\n  Resposta S3: HTTP {status_s3}")
    print(f"    body: {json.dumps(body_s3, ensure_ascii=False)[:300]}")
    print(f"\n  Resposta S4: HTTP {status_s4}")
    print(f"    body: {json.dumps(body_s4, ensure_ascii=False)[:300]}")

    # ------------------------------------------------------------------
    # Passo 4: verificações
    # ------------------------------------------------------------------
    print("\n[4] Verificando resultados...")

    erros = []

    if status_s3 != 200:
        erros.append(f"S3 deveria ser HTTP 200, got {status_s3}")
    if status_s4 != 200:
        erros.append(f"S4 deveria ser HTTP 200, got {status_s4}")

    reservas_101 = contar_reservas_salao(APTO_S3)
    reservas_201 = contar_reservas_salao(APTO_S4)
    total = len(reservas_101) + len(reservas_201)

    print(f"  Reservas salão {DATA} — apto 101: {reservas_101}")
    print(f"  Reservas salão {DATA} — apto 201: {reservas_201}")
    print(f"  Total ativo: {total}")

    if total != 1:
        erros.append(f"Deveria existir exatamente 1 reserva ativa, mas encontrei {total}")

    print("\n" + "=" * 60)
    if erros:
        print("❌ FALHA:")
        for e in erros:
            print(f"   • {e}")
        sys.exit(1)
    else:
        print("✅ APROVADO — Garantia 5 confirmada:")
        print(f"   • S3 HTTP {status_s3} ✓")
        print(f"   • S4 HTTP {status_s4} ✓")
        print(f"   • Exatamente {total} reserva ativa para {AREA} em {DATA} ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
