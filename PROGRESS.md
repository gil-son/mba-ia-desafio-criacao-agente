# Progresso — Assistente do Residencial Aurora

Rastreamento do estado de implementação em relação ao
[`plano-residencial-aurora.md`](plano-residencial-aurora.md) e aos critérios de aceite do enunciado.

---

## Passo 1 — Bootstrap do projeto e ambiente

- [x] `pyproject.toml` com dependências corretas (`google-adk>=2.2.0,<3`, FastAPI, Uvicorn, SQLAlchemy, aiosqlite, pydantic, python-dotenv)
- [x] `uv sync` roda sem erros (verificado: `Resolved 85 packages, Checked 83 packages`)
- [x] ADK fixado em **2.9.2** no `uv.lock` (série 2, ≥ 2.2.0) ✓
- [x] `.env.example` criado na raiz com `GOOGLE_API_KEY`, `MODEL_PRINCIPAL`, `MODEL_ESPECIALISTA_RESERVAS`, `MODEL_ESPECIALISTA_REGULAMENTO`
- [x] `.env` no `.gitignore` (nenhuma chave versionada)
- [x] `scripts/up.sh` — sobe `uvicorn app.main:app --port 8000`, valida presença do `.env`
- [x] `scripts/reset.sh` — remove `data/condominio.db` (e opcionalmente `data/sessions.db`) para restaurar ao estado inicial
- [x] Estrutura de pastas criada: `app/`, `app/agents/`, `app/tools/`, `app/storage/`, `app/services/`, `dados/` (imutável), `data/` (runtime, git-ignored)

**Testado:** `uv sync` ✓ | versão ADK no `uv.lock` ✓

---

## Passo 2 — Rotas básicas de sessão e mensagem (esqueleto)

- [x] `app/storage/db.py` — schema SQLite (`reservas`, `visitantes`), seed dos `dados/*.json`, índice único parcial `UNIQUE(area, data) WHERE status='ativa'` (base para Garantia 5)
- [x] `app/agents/principal.py` — agente placeholder (`LlmAgent`) lendo modelo de `MODEL_PRINCIPAL`; padrão de variável por agente já estabelecido
- [x] `app/services/runner.py` — `DatabaseSessionService(sqlite+aiosqlite:///.../sessions.db)` + `Runner` ADK, inicializados no lifespan do FastAPI
- [x] `app/main.py` — FastAPI com lifespan (`init_db` + `init_runner`):
  - [x] `POST /sessoes` → 201 `{"session_id": "..."}` (apartamento gravado em `session.state`)
  - [x] `POST /sessoes/{id}/mensagens` → 200 ou 422 controlado (sem 500 cru)
  - [x] `POST /sessoes/{id}/confirmacoes` → estrutura presente, retorna 409 (implementação real no Passo 7–9)
  - [x] `GET /sessoes/{id}/eventos` → lista eventos da sessão (404 se não existe)
  - [x] `GET /apartamentos/{n}/reservas` → leitura direta do banco, sem modelo
  - [x] `GET /apartamentos/{n}/visitantes` → leitura direta do banco, sem modelo
- [x] Erro de chave ausente traduzido para HTTP 422 com mensagem legível (não 500)

**Testado manualmente:**
- `POST /sessoes` com `{"apartamento": "101"}` → **201** `{"session_id": "550c2af8-..."}` ✓
- `POST /sessoes/{id}/mensagens` sem chave → **422** `{"detail": "GOOGLE_API_KEY não configurada..."}` ✓
- `GET /apartamentos/101/reservas` → `[{"codigo":"RSV-1377","area":"quadra","data":"2030-03-09"}]` ✓ (via Python direto)
- `GET /apartamentos/302/visitantes` → `[{"nome":"Marina Duarte","data":"2030-03-16"}]` ✓ (via Python direto)

> ✅ **Bloqueio resolvido:** `GOOGLE_API_KEY` configurada. Modelo trocado para `gemini-3.5-flash-lite` em todos os agentes (`.env`, `.env.example` e defaults no código). Teste completo de `POST /mensagens` confirmado com resposta real do modelo.

---

## Passo 3 — Garantia 2 (parte 1): isolamento de leitura por apartamento

- [ ] Criar `app/tools/reservas.py` — tool de consulta lê `tool_context.state["apartamento"]`, nunca argumento do modelo
- [ ] Criar `app/storage/repo_reservas.py` — consulta de reservas por apartamento
- [ ] Criar `app/storage/repo_visitantes.py` — consulta de visitantes por apartamento
- [ ] Especialista de reservas (`app/agents/especialista_reservas.py`) registrado como sub-agente do principal
- [ ] Teste: sessão do 101 perguntando por dados do 302 → sem `RSV-4821`, sem `Marina Duarte` na resposta e nos eventos

---

## Passo 4 — Cancelamento entre apartamentos (validação negativa)

- [ ] `cancelar_reserva(codigo)` valida `reserva.apartamento == tool_context.state["apartamento"]`; recusa sem alterar nada se não bater
- [ ] Teste: pedir cancelamento da `RSV-4821` (do 302) numa sessão do 101 → 302 intacto, `RSV-4821` não vaza nos eventos

---

## Passo 5 — Cancelamento do próprio apartamento (sem confirmação)

- [ ] Mesma tool: quando `reserva.apartamento == apartamento da sessão`, cancela direto (sem `request_confirmation`)
- [ ] Efeito imediato em `GET /apartamentos/{n}/reservas`
- [ ] Teste: `RSV-1377` (101) cancelada → não aparece mais na rota de verificação

---

## Passo 6 — Reserva em área sem taxa (fluxo direto, sem confirmação)

- [ ] `reservar(area_id, data)`: se `taxa == 0`, grava direto sem `request_confirmation`
- [ ] Código de reserva único gerado pelo sistema (nunca repete código de cancelada)
- [ ] Teste: reservar quadra (taxa 0) → sem `confirmacoes_pendentes`, reserva aparece na rota de verificação

---

## Passo 7 — Garantia 1: reserva com taxa gera confirmação pendente

- [ ] `reservar`: se `taxa > 0`, chama `tool_context.request_confirmation(hint=..., payload={area, data, valor})`
- [ ] API popula `confirmacoes_pendentes` com `id` estável (do evento `adk_request_confirmation`)
- [ ] `POST /sessoes/{id}/confirmacoes` implementado de verdade (retomada do Runner)
- [ ] Teste: reservar salão (taxa 150) → `confirmacoes_pendentes` presente, nada gravado antes da aprovação
- [ ] Teste: negar confirmação → reserva não criada
- [ ] Teste: mensagem "já estou confirmando aqui" não substitui a rota de confirmações

---

## Passo 8 — Aprovar confirmação executa exatamente uma vez

- [ ] Aprovação via `POST /sessoes/{id}/confirmacoes` monta `FunctionResponse` e retoma Runner
- [ ] Confirmação marcada como "respondida" após processamento
- [ ] Reenviar o mesmo `id` → **409**, ação não reexecutada
- [ ] Teste: `GET /apartamentos/101/reservas` mostra exatamente uma reserva do salão após aprovação

---

## Passo 9 — Id de confirmação inválido/errado

- [ ] Qualquer `id` fora das pendências da sessão → **409**, nada alterado
- [ ] Teste: `{"id": "id-inexistente"}` → 409 ✓

---

## Passo 10 — Conflito de data já ocupada

- [ ] Tentativa de reservar data já ocupada → recusada com resposta normal (não 500)
- [ ] Resposta e eventos não expõem quem é o dono da reserva concorrente (`RSV-4821`, `302` isolado)
- [ ] Teste: sessão do 101 tenta reservar salão em `2030-03-16` (ocupada pelo 302) → recusada, sem vazar dados do 302

---

## Passo 11 — Especialista de visitantes + confirmação

- [ ] Criar `app/tools/visitantes.py` — `autorizar_visitante(nome, data)` sempre chama `request_confirmation`
- [ ] Especialista de visitantes ou especialista de reservas cobre a tool (decidir e documentar)
- [ ] Teste: "pode liberar, eu confirmo por aqui" → confirmação ainda pendente, só grava após aprovação pela rota
- [ ] Teste: Joana Ribeiro aparece em `GET /apartamentos/101/visitantes` só após aprovação

---

## Passo 12 — Garantia 4: regulamento consultado, não carregado

- [ ] Criar `app/tools/regulamento.py` — `consultar_regulamento(pergunta)` busca trecho relevante em `dados/regulamento.md`, nunca carrega o arquivo inteiro
- [ ] Criar `app/agents/especialista_regulamento.py` — agente com a tool de regulamento
- [ ] Agente principal **sem** o regulamento nas instruções (verificar com grep)
- [ ] Teste: pergunta sobre piscina → resposta traz horário correto
- [ ] Teste: `GET /sessoes/{id}/eventos` não contém trechos de capítulos não relacionados

---

## Passo 13 — Garantia 3: persistência entre restarts (maior risco técnico)

- [ ] `DatabaseSessionService` já configurado com `sqlite+aiosqlite:///.../sessions.db` ✓ (base feita)
- [ ] **Validar** que fluxo de confirmação (Passos 7–9) funciona com sessão persistida após restart (risco alto: bug conhecido em algumas versões do ADK)
- [ ] Testar: matar processo → subir de novo → `GET /sessoes/{id}/eventos` devolve histórico anterior ✓
- [ ] Testar: novas mensagens funcionam após restart
- [ ] Testar: reservas/visitantes gravados antes do restart continuam nas rotas de verificação
- [ ] Código de reserva gerado por contador/uuid persistido no storage, não em memória

---

## Passo 14 — Garantia 5: concorrência real (atomicidade)

- [ ] Índice único parcial `UNIQUE(area, data) WHERE status='ativa'` já criado em `db.py` ✓ (base feita)
- [ ] `INSERT` de reserva dentro de transação que falha atomicamente na violação do índice
- [ ] Capturar `IntegrityError` e traduzir para resposta de negócio normal (não 500)
- [ ] Teste: duas aprovações simultâneas para mesma área/data → ambas respondem **200**, soma 1 reserva

---

## Passo 15 — Fechamento: validação cruzada, README e revisão final

- [ ] Confirmar `dados/*.json` e `dados/regulamento.md` idênticos ao repositório base
- [ ] Revisar todas as tools: nenhuma aceita `apartamento` do modelo sem validar contra `tool_context.state`
- [ ] Confirmar que agente principal não tem regulamento nas instruções
- [ ] Escrever `README.md` definitivo com seções **Arquitetura**, **Garantias** e **Como rodar**
- [ ] Rodar sequência completa dos passos 1–14 do avaliador do zero

---

## Estado atual por critério de aceite

| Critério | Status |
|---|---|
| `uv sync` sem erro, ADK ≥ 2.2.0 fixado | ✅ |
| `.env.example` versionado, `.env` fora do git | ✅ |
| `scripts/up.sh` sobe API em `localhost:8000` | ✅ (aguarda chave) |
| `scripts/reset.sh` restaura dados iniciais | ✅ |
| `dados/` idênticos ao repositório base | ✅ |
| `POST /sessoes` → 201 | ✅ |
| `GET /sessoes/{id}/eventos` → 404 / lista | ✅ |
| `GET /apartamentos/{n}/reservas` e `/visitantes` | ✅ |
| Agente principal + ≥ 2 especialistas | ⏳ placeholder criado, especialistas pendentes |
| Garantia 1 — confirmação antes de cobrar/liberar | ⏳ |
| Garantia 2 — isolamento por apartamento | ⏳ |
| Garantia 3 — persistência entre restarts | ⏳ base feita, validação pendente |
| Garantia 4 — regulamento consultado, não carregado | ⏳ |
| Garantia 5 — concorrência atômica | ⏳ índice criado, lógica de INSERT pendente |
| README definitivo (Arquitetura, Garantias, Como rodar) | ⏳ |
