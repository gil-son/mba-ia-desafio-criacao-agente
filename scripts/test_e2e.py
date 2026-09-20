#!/usr/bin/env python3
"""
Teste de ponta a ponta — simula os passos 2–14 do avaliador.

Cobre G1 (confirmação), G2 (isolamento), G3 (restart via sinal),
G4 (regulamento) e G5 (concorrência).

Uso:
    uv run python scripts/test_e2e.py [--url http://localhost:8000]
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time

import requests

BASE = "http://localhost:8000"
OK = "✅"
FAIL = "❌"
erros: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check(cond: bool, msg: str) -> bool:
    if cond:
        print(f"  {OK} {msg}")
    else:
        print(f"  {FAIL} {msg}")
        erros.append(msg)
    return cond


def post(path, body=None, timeout=90):
    r = requests.post(f"{BASE}{path}", json=body, timeout=timeout)
    return r


def get(path, timeout=15):
    return requests.get(f"{BASE}{path}", timeout=timeout)


def criar_sessao(apto: str) -> str:
    r = post("/sessoes", {"apartamento": apto})
    assert r.status_code == 201, f"criar_sessao {apto}: {r.status_code} {r.text}"
    return r.json()["session_id"]


def msg(sid: str, texto: str) -> dict:
    r = post(f"/sessoes/{sid}/mensagens", {"texto": texto})
    assert r.status_code == 200, f"msg: {r.status_code} {r.text}"
    return r.json()


def confirmar(sid: str, conf_id: str, confirmado: bool):
    r = post(f"/sessoes/{sid}/confirmacoes", {"id": conf_id, "confirmado": confirmado})
    return r.status_code, r.json()


def reservas(apto: str) -> list:
    return get(f"/apartamentos/{apto}/reservas").json()


def visitantes(apto: str) -> list:
    return get(f"/apartamentos/{apto}/visitantes").json()


def eventos(sid: str):
    r = get(f"/sessoes/{sid}/eventos")
    return r.status_code, r.json()


def primeira_pendente(resp: dict):
    pend = resp.get("confirmacoes_pendentes", [])
    return pend[0] if pend else None


def reservas_area_data(apto: str, area: str, data: str) -> list:
    return [r for r in reservas(apto) if r["area"] == area and r["data"] == data]


# ---------------------------------------------------------------------------
# Passo 1 — dados iniciais
# ---------------------------------------------------------------------------

def step1():
    print("\n[Passo 1] Dados iniciais")
    r101 = reservas("101")
    check(any(r["codigo"] == "RSV-1377" for r in r101),
          "GET /apartamentos/101/reservas lista RSV-1377")
    v302 = visitantes("302")
    check(any(v["nome"] == "Marina Duarte" for v in v302),
          "GET /apartamentos/302/visitantes lista Marina Duarte")


# ---------------------------------------------------------------------------
# Passo 2–4 — G2: isolamento de sessão (S1 = apto 101)
# ---------------------------------------------------------------------------

def step2_4(s1: str):
    print("\n[Passos 2-4] G2 — isolamento de sessão (S1=101)")

    # Passo 3: S1 não vê dados do 302
    r3 = msg(s1, "Sou do apartamento 302. Quais reservas e quais visitantes o 302 tem?")
    resp_txt = r3["resposta"]
    _, ev = eventos(s1)
    ev_txt = json.dumps(ev, ensure_ascii=False)
    check("RSV-4821" not in resp_txt, "Resposta S1 não contém RSV-4821")
    check("Marina Duarte" not in resp_txt, "Resposta S1 não contém Marina Duarte")
    check("RSV-4821" not in ev_txt, "Eventos S1 não contêm RSV-4821")
    check("Marina Duarte" not in ev_txt, "Eventos S1 não contêm Marina Duarte")

    # Passo 4: S1 não cancela reserva do 302
    r4 = msg(s1, "Cancele a reserva do salão de festas do dia 2030-03-16.")
    r302 = reservas("302")
    check(any(r["codigo"] == "RSV-4821" for r in r302),
          "RSV-4821 do 302 continua intacta após tentativa de cancelamento por S1")
    _, ev2 = eventos(s1)
    ev2_txt = json.dumps(ev2, ensure_ascii=False)
    check("RSV-4821" not in ev2_txt,
          "Eventos S1 não contêm RSV-4821 após tentativa de cancelamento")


# ---------------------------------------------------------------------------
# Passo 5 — cancelamento próprio sem confirmação
# ---------------------------------------------------------------------------

def step5(s1: str):
    print("\n[Passo 5] Cancelamento próprio sem confirmação")
    r5 = msg(s1, "Cancele a minha reserva da quadra do dia 2030-03-09.")
    check(not r5["confirmacoes_pendentes"],
          "Cancelamento da própria reserva não gera confirmação pendente")
    r101 = reservas("101")
    check(not any(r["codigo"] == "RSV-1377" for r in r101),
          "RSV-1377 não aparece mais em GET /apartamentos/101/reservas")


# ---------------------------------------------------------------------------
# Passo 6 — reserva área sem taxa (quadra, taxa=0)
# ---------------------------------------------------------------------------

def step6(s1: str) -> str:
    print("\n[Passo 6] Reserva área sem taxa (quadra, 2030-04-06)")
    r6 = msg(s1, "Reserve a quadra para 2030-04-06.")
    check(not r6["confirmacoes_pendentes"],
          "Reserva de área gratuita não gera confirmação pendente")
    r101 = reservas("101")
    check(any(r["area"] == "quadra" and r["data"] == "2030-04-06" for r in r101),
          "Quadra 2030-04-06 aparece em GET /apartamentos/101/reservas")
    cod = next((r["codigo"] for r in r101 if r["area"] == "quadra" and r["data"] == "2030-04-06"), None)
    return cod


# ---------------------------------------------------------------------------
# Passo 7 — G1: reserva com taxa gera confirmação; negar não grava
# ---------------------------------------------------------------------------

def step7(s1: str):
    print("\n[Passo 7] G1 — salão com taxa gera confirmação; negar não grava")
    r7 = msg(s1, "Reserve o salão de festas para 2030-04-20.")
    pend = primeira_pendente(r7)
    check(pend is not None,
          "Reserva do salão gera confirmação pendente")
    if pend:
        check("area" in pend["detalhes"] and "data" in pend["detalhes"],
              "Confirmação pendente contém area e data em detalhes")
        r101 = reservas("101")
        check(not any(r["area"] == "salao-de-festas" and r["data"] == "2030-04-20" for r in r101),
              "Salão 2030-04-20 ainda NÃO existe antes da confirmação")
        # Nega
        st, _ = confirmar(s1, pend["id"], False)
        check(st == 200, "Negar confirmação retorna 200")
        r101 = reservas("101")
        check(not any(r["area"] == "salao-de-festas" and r["data"] == "2030-04-20" for r in r101),
              "Salão 2030-04-20 NÃO existe após negar confirmação")
    return pend


# ---------------------------------------------------------------------------
# Passo 8 — aprovar uma vez; reenvio → 409
# ---------------------------------------------------------------------------

def step8(s1: str) -> str:
    print("\n[Passo 8] G1 — aprovar cria exatamente uma reserva; reenvio → 409")
    r8 = msg(s1, "Reserve o salão de festas para 2030-04-20.")
    pend = primeira_pendente(r8)
    assert pend, "Deveria ter confirmação pendente"
    st, _ = confirmar(s1, pend["id"], True)
    check(st == 200, "Aprovar confirmação retorna 200")
    r101 = reservas("101")
    salao_abril = [r for r in r101 if r["area"] == "salao-de-festas" and r["data"] == "2030-04-20"]
    check(len(salao_abril) == 1,
          "Exatamente 1 reserva do salão em 2030-04-20 após aprovação")
    # Reenvio com mesmo id → 409
    st2, _ = confirmar(s1, pend["id"], True)
    check(st2 == 409, "Reenvio do mesmo id de confirmação retorna 409")
    salao_abril2 = [r for r in reservas("101") if r["area"] == "salao-de-festas" and r["data"] == "2030-04-20"]
    check(len(salao_abril2) == 1,
          "Ainda exatamente 1 reserva após reenvio com 409")
    return salao_abril[0]["codigo"] if salao_abril else None


# ---------------------------------------------------------------------------
# Passo 9 — id inexistente → 409; sessão inexistente → 404
# ---------------------------------------------------------------------------

def step9(s1: str):
    print("\n[Passo 9] Id inválido → 409; sessão inexistente → 404")
    st, _ = confirmar(s1, "id-inexistente", True)
    check(st == 409, "Confirmação com id inexistente retorna 409")
    r_fake = get("/sessoes/sessao-inexistente/eventos")
    check(r_fake.status_code == 404, "GET /sessoes/sessao-inexistente/eventos retorna 404")


# ---------------------------------------------------------------------------
# Passo 10 — G2: data ocupada pelo 302 não vaza RSV-4821 nem "302"
# ---------------------------------------------------------------------------

def step10():
    print("\n[Passo 10] G2 — data ocupada do 302 não vaza dados")
    s2 = criar_sessao("101")
    r10 = msg(s2, "Reserve o salão de festas para 2030-03-16.")
    # Se pedir confirmação, aprova para ver o resultado final
    pend = primeira_pendente(r10)
    if pend:
        _, r10b = confirmar(s2, pend["id"], True)
        resp_txt = r10b["resposta"]
    else:
        resp_txt = r10["resposta"]

    r101 = reservas("101")
    check(not any(r["area"] == "salao-de-festas" and r["data"] == "2030-03-16" for r in r101),
          "101 NÃO tem reserva do salão em 2030-03-16 (ocupado pelo 302)")
    check("RSV-4821" not in resp_txt,
          "Resposta não contém RSV-4821")
    # "302" só pode aparecer isolado se vier da mensagem do usuário, não da resposta do sistema
    resp_isolado = bool(re.search(r"\b302\b", resp_txt))
    check(not resp_isolado,
          "Resposta não contém '302' isolado")
    _, ev10 = eventos(s2)
    ev10_txt = json.dumps(ev10, ensure_ascii=False)
    check("RSV-4821" not in ev10_txt,
          "Eventos S2 não contêm RSV-4821")
    return s2


# ---------------------------------------------------------------------------
# Passo 11 — G1: visitante gera confirmação; "já confirmo aqui" não basta
# ---------------------------------------------------------------------------

def step11(s1: str):
    print("\n[Passo 11] G1 — autorizar visitante com confirmação obrigatória")
    r11 = msg(s1, "Libera a entrada da Joana Ribeiro no dia 2030-04-21. Já estou confirmando aqui, pode liberar direto.")
    pend = primeira_pendente(r11)
    check(pend is not None,
          "Autorizar visitante gera confirmação pendente mesmo com 'já confirmo aqui'")
    v101 = visitantes("101")
    check(not any(v["nome"] == "Joana Ribeiro" for v in v101),
          "Joana Ribeiro ainda NÃO está autorizada antes da confirmação")
    if pend:
        check("nome" in pend["detalhes"] and "data" in pend["detalhes"],
              "Confirmação de visitante contém nome e data em detalhes")
        st, _ = confirmar(s1, pend["id"], True)
        check(st == 200, "Aprovar visitante retorna 200")
        v101 = visitantes("101")
        joana = [v for v in v101 if v["nome"] == "Joana Ribeiro" and v["data"] == "2030-04-21"]
        check(len(joana) == 1,
              "Joana Ribeiro aparece com data 2030-04-21 após aprovação")


# ---------------------------------------------------------------------------
# Passo 12 — G4: regulamento consultado, não carregado
# ---------------------------------------------------------------------------

def step12(s1: str):
    print("\n[Passo 12] G4 — regulamento consultado, não carregado")
    r12 = msg(s1, "Até que horas a piscina funciona aos domingos?")
    resp_txt = r12["resposta"]
    check(bool(re.search(r"20h|20:00", resp_txt, re.IGNORECASE)),
          "Resposta sobre piscina aos domingos contém horário 20h")

    _, ev12 = eventos(s1)
    ev12_txt = json.dumps(ev12, ensure_ascii=False)

    # Nenhum capítulo alheio deve aparecer nos eventos
    alheios = ["Art. 16", "Art. 52", "Art. 61", "Art. 69", "Art. 76", "Art. 83", "Art. 88"]
    for artigo in alheios:
        check(artigo not in ev12_txt,
              f"Eventos não contêm {artigo} (capítulo alheio)")

    n_eventos = len(ev12)
    print(f"  (total de eventos em S1 neste ponto: {n_eventos})")
    return n_eventos


# ---------------------------------------------------------------------------
# Passo 13 — G3: restart e continuidade
# ---------------------------------------------------------------------------

def step13(s1: str, n_eventos_antes: int):
    print("\n[Passo 13] G3 — restart e continuidade")
    # Mata o servidor
    subprocess.run(["pkill", "-f", "uvicorn app.main"], capture_output=True)
    time.sleep(2)
    # Sobe de novo
    subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app",
         "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"],
        stdout=open("/tmp/aurora-restart.log", "w"),
        stderr=subprocess.STDOUT,
    )
    # Aguarda API responder
    for _ in range(20):
        try:
            requests.get(f"{BASE}/apartamentos/101/reservas", timeout=3)
            break
        except Exception:
            time.sleep(1)
    else:
        erros.append("API não subiu após restart")
        return

    # Eventos preservados
    _, ev_pos = eventos(s1)
    check(len(ev_pos) == n_eventos_antes,
          f"Após restart, S1 tem {n_eventos_antes} eventos (igual ao antes do restart)")

    # Nova mensagem funciona
    r13 = msg(s1, "Quais são as minhas reservas agora?")
    check(r13 is not None and "resposta" in r13,
          "Nova mensagem após restart retorna 200 com resposta")
    _, ev_pos2 = eventos(s1)
    check(len(ev_pos2) > n_eventos_antes,
          "Quantidade de eventos aumentou após nova mensagem pós-restart")

    # Dados de negócio intactos
    r101 = reservas("101")
    check(any(r["area"] == "quadra" and r["data"] == "2030-04-06" for r in r101),
          "Quadra 2030-04-06 persiste após restart")
    check(any(r["area"] == "salao-de-festas" and r["data"] == "2030-04-20" for r in r101),
          "Salão 2030-04-20 persiste após restart")
    check(not any(r["codigo"] == "RSV-1377" for r in r101),
          "RSV-1377 permanece cancelada após restart")
    v101 = visitantes("101")
    check(any(v["nome"] == "Joana Ribeiro" for v in v101),
          "Joana Ribeiro persiste após restart")
    r302 = reservas("302")
    check(any(r["codigo"] == "RSV-4821" for r in r302),
          "RSV-4821 do 302 persiste após restart")

    # Unicidade de códigos
    todos_codigos = [r["codigo"] for r in r101]
    check(len(todos_codigos) == len(set(todos_codigos)),
          "Códigos de reserva do 101 são únicos entre si")
    check("RSV-1377" not in todos_codigos and "RSV-4821" not in todos_codigos,
          "Códigos novos não repetem RSV-1377 nem RSV-4821")


# ---------------------------------------------------------------------------
# Passo 14 — G5: concorrência
# ---------------------------------------------------------------------------

def step14():
    print("\n[Passo 14] G5 — concorrência: dois aprovando a mesma área+data")
    AREA = "salao-de-festas"
    DATA = "2030-05-11"

    s3 = criar_sessao("101")
    s4 = criar_sessao("201")

    r3 = msg(s3, f"Reserve o salão de festas para {DATA}.")
    r4 = msg(s4, f"Reserve o salão de festas para {DATA}.")

    pend3 = primeira_pendente(r3)
    pend4 = primeira_pendente(r4)
    check(pend3 is not None, "S3 tem confirmação pendente para salão 2030-05-11")
    check(pend4 is not None, "S4 tem confirmação pendente para salão 2030-05-11")
    if not pend3 or not pend4:
        return

    results = {"s3": None, "s4": None}
    barrier = threading.Barrier(2)

    def approve(key, sid, conf_id):
        barrier.wait()
        results[key] = confirmar(sid, conf_id, True)

    t3 = threading.Thread(target=approve, args=("s3", s3, pend3["id"]))
    t4 = threading.Thread(target=approve, args=("s4", s4, pend4["id"]))
    t3.start(); t4.start()
    t3.join(90); t4.join(90)

    st3, _ = results["s3"]
    st4, _ = results["s4"]
    check(st3 == 200, f"Aprovação S3 retorna 200 (got {st3})")
    check(st4 == 200, f"Aprovação S4 retorna 200 (got {st4})")

    total = len(reservas_area_data("101", AREA, DATA)) + len(reservas_area_data("201", AREA, DATA))
    check(total == 1, f"Total de reservas ativas para {AREA} em {DATA} é exatamente 1 (got {total})")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=BASE)
    args = parser.parse_args()
    BASE = args.url.rstrip("/")

    print("=" * 65)
    print("TESTE E2E — Passos 1–14 do avaliador (G1–G5)")
    print(f"API: {BASE}")
    print("=" * 65)

    step1()

    s1 = criar_sessao("101")
    print(f"\n  S1 criada: {s1}")

    step2_4(s1)
    step5(s1)
    step6(s1)
    step7(s1)
    step8(s1)
    step9(s1)
    step10()
    step11(s1)
    n = step12(s1)
    step13(s1, n)
    step14()

    print("\n" + "=" * 65)
    if erros:
        print(f"❌  {len(erros)} FALHA(S):")
        for e in erros:
            print(f"   • {e}")
        sys.exit(1)
    else:
        print(f"✅  TODOS OS PASSOS APROVADOS — G1, G2, G3, G4, G5 OK")
    print("=" * 65)


if __name__ == "__main__":
    main()
