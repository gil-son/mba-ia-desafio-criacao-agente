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

- [x] `app/tools/reservas.py` — `ver_minhas_reservas` lê `tool_context.state["apartamento"]`, nunca argumento do modelo
- [x] `app/storage/repo_reservas.py` — `listar_reservas_apartamento(db, apartamento)` filtra por apartamento
- [x] `app/storage/repo_visitantes.py` — `listar_visitantes_apartamento(db, apartamento)` filtra por apartamento
- [x] `app/agents/especialista_reservas.py` registrado como sub-agente do principal em `app/agents/principal.py`
- [x] Teste G2-A (Passo 10): sessão do 101 perguntando por dados do 302 → sem `RSV-4821`, sem `Marina Duarte` na resposta e nos eventos ✓

---

## Passo 4 — Cancelamento entre apartamentos (validação negativa)

- [x] `cancelar_minha_reserva(codigo)` em `app/tools/reservas.py` chama `_cancelar(db, codigo, apartamento)` — valida `reserva.apartamento == tool_context.state["apartamento"]`; recusa sem alterar nada se não bater
- [x] Teste G2-B (Passo 10): pedir cancelamento da `RSV-4821` (do 302) numa sessão do 101 → 302 intacto, `RSV-4821` não vaza nos eventos ✓

---

## Passo 5 — Cancelamento do próprio apartamento (sem confirmação)

- [x] Mesma tool: quando `reserva.apartamento == apartamento da sessão`, `cancelar_reserva` em `repo_reservas.py` cancela direto (sem `request_confirmation`)
- [x] Efeito imediato em `GET /apartamentos/{n}/reservas`
- [x] Teste G2-C (validado nos Passos 7/8): `RSV-1377` (101) cancelada → não aparece mais na rota de verificação ✓

---

## Passo 6 — Reserva em área sem taxa (fluxo direto, sem confirmação)

- [x] `reservar_area(area, data)`: se `taxa == 0`, grava direto sem `request_confirmation`
- [x] Código de reserva único gerado pelo sistema com `uuid4` hex (ex: `RSV-D47AE62B`) — nunca repete
- [x] Teste: reservar quadra (taxa 0) → `confirmacoes_pendentes: []`, reserva aparece imediatamente ✓

---

## Passo 7 — Garantia 1: reserva com taxa gera confirmação pendente

- [x] `reservar_area`: se `taxa > 0`, chama `tool_context.request_confirmation(hint=..., payload={area, data, valor})`
- [x] API popula `confirmacoes_pendentes` com `id` estável (do evento `adk_request_confirmation`)
- [x] `POST /sessoes/{id}/confirmacoes` implementado com retomada do Runner
- [x] Teste: reservar salão (taxa 150) → `confirmacoes_pendentes` com `area`, `data`, `valor` — nada gravado ✓
- [x] Teste: negar confirmação → reserva não criada ✓
- [x] Teste: mensagem "já estou confirmando aqui" → não substitui a rota (tool verifica `tool_confirmation`, não o texto) ✓

---

## Passo 8 — Aprovar confirmação executa exatamente uma vez

- [x] Aprovação via `POST /sessoes/{id}/confirmacoes` monta `FunctionResponse` e retoma Runner
- [x] Confirmação marcada como "respondida" pelo ADK após processamento
- [x] Reenviar o mesmo `id` → **409**, ação não reexecutada ✓
- [x] Teste: `GET /apartamentos/101/reservas` mostra exatamente uma reserva do salão após aprovação ✓

---

## Passo 9 — Id de confirmação inválido/errado

- [x] Qualquer `id` fora das pendências da sessão → **409**, nada alterado ✓
- [x] Teste: reenvio de `id` já respondido → 409 ✓ (coberto nos testes de Passo 7/8)

---

## Passo 10 — Conflito de data já ocupada

- [x] Tentativa de reservar data já ocupada → recusada com resposta normal (não 500) ✓
- [x] Resposta e eventos de OUTPUT não expõem `RSV-4821` nem `302` isolado ✓
- [x] Teste: sessão 101 tenta reservar salão em `2030-03-16` (ocupada pelo 302) → recusada ✓
  - `RSV-4821` ausente na resposta e nos eventos de output ✓
  - `302` isolado ausente na resposta e nos eventos de output ✓
  - `302` presente **apenas** no evento `author=user` (a própria mensagem digitada pelo avaliador) — inevitável e esperado

---

## Passo 11 — Especialista de visitantes + confirmação

- [x] `app/tools/visitantes.py` — `autorizar_visitante(nome, data)` implementada com fluxo de dois passos:
  - Primeira execução: chama `request_confirmation`, retorna sem gravar
  - Re-execução pós-confirmação: verifica `tool_context.tool_confirmation.confirmed`, grava se aprovado
- [x] `app/tools/reservas.py` — `reservar_area` corrigida com mesmo padrão (branch pós-confirmação para não re-chamar `request_confirmation` na re-execução)
- [x] Especialista de reservas (`especialista_reservas`) cobre ambas as tools (reservas + visitantes) — já documentado
- [x] Teste: "Libera a entrada da Joana Ribeiro no dia 2030-04-21" → `confirmacoes_pendentes` com nome e data, nada gravado ✓
- [x] Teste: aprovar via `POST /sessoes/{id}/confirmacoes` → Joana Ribeiro aparece em `GET /apartamentos/101/visitantes` ✓
- [x] Teste: reenviar mesmo `id` → **409**, sem duplicata ✓
- [x] Teste: "Já estou confirmando aqui, pode liberar direto" → confirmação ainda pendente, Ana Paula não gravada ✓

**Testado manualmente** (sessão `de94a8a1`, aptos 101):
- Autorizar Joana Ribeiro 2030-04-21 → pendente ✓ → aprovada → gravada ✓
- Reenvio do mesmo `id` → 409 ✓
- "já estou confirmando aqui" para Ana Paula Souza → pendente (não gravada) ✓

---

## Passo 12 — Garantia 4: regulamento consultado, não carregado

- [x] `app/tools/regulamento.py` — `consultar_regulamento(pergunta)` divide o regulamento em seções por capítulo/artigo, pontua por relevância e retorna no máximo as 2 seções mais relevantes — nunca o documento inteiro
- [x] `app/agents/especialista_regulamento.py` — agente com a tool `consultar_regulamento`; registrado como sub-agente do principal
- [x] Agente principal (`app/agents/principal.py`) **sem** o regulamento nas instruções — confirmado por leitura direta: nenhuma referência ao conteúdo do regulamento, apenas nome do especialista e instrução de delegação
- [x] Teste (sessão `6b9be1ab`): pergunta "Posso usar a piscina aos domingos à noite? Até que horas ela fica aberta?" → resposta: "**aos domingos e feriados, a piscina funciona das 9h às 20h**" ✓
- [x] `GET /sessoes/{id}/eventos`: 8 eventos, tool retornou apenas **Capítulo IV: Piscina** (Art. 21–28) — nenhum trecho de capítulos alheios (silêncio, salão, animais, mudanças, obras, garagem, lixo, penalidades) nos eventos ✓

**Trecho retornado pela tool `consultar_regulamento`** (seções: `['Capítulo IV: Piscina']`):
> Art. 22. A piscina observa os seguintes períodos de uso:
> I. De segunda a sábado, a piscina funciona das 8h às 22h.
> II. **Aos domingos e feriados, a piscina funciona das 9h às 20h.**
> Parágrafo único. Fora desses períodos, o recinto da piscina permanece fechado (…)
> (Art. 21–28 completos, apenas Capítulo IV)

**Testado com `scripts/test_garantia4.py`** (sessão `6b9be1ab`, apto 101):
- Resposta contém horário 20h ✓
- Eventos: 8 no total, nenhum trecho de capítulo alheio ✓
- `principal.py` sem regulamento no prompt ✓

---

## Passo 13 — Garantia 3: persistência entre restarts (maior risco técnico)

- [x] `DatabaseSessionService` configurado com `sqlite+aiosqlite:///.../sessions.db` ✓
- [x] **Validado**: fluxo de confirmação funciona com sessão persistida após restart ✓ — **sem bugs**
- [x] Testar: matar processo → subir de novo → `GET /sessoes/{id}/eventos` devolve 12 eventos (esperado: 12) ✓
- [x] Testar: novas mensagens funcionam após restart ✓ (envio de "Quais são as minhas reservas?" → 200)
- [x] Testar: reservas/visitantes gravados antes do restart continuam nas rotas de verificação ✓
  - RSV-1377 (quadra 2030-03-09) ✓ | RSV-BF3CC504 (quadra 2030-06-01) ✓ | RSV-4821 do 302 ✓
- [x] Testar: confirmação pendente sobrevive ao restart e retoma corretamente ✓
  - `adk-14f03840` pendente antes do restart → aprovada após restart → RSV-B151B015 criada ✓
- [x] Código de reserva gerado por `uuid4` hex no momento do INSERT — nunca em memória ✓

**Testado manualmente** (sessão `c6f193b0`, apto 101):
- 12 eventos antes do restart → 12 eventos após restart → 21 após aprovação pós-restart ✓
- Dados de negócio intactos após restart ✓
- Confirmação pós-restart retomou e gravou RSV-B151B015 (salão 2030-07-15) ✓
- **Nenhuma das variações de topologia/Runner/App foi necessária** — a configuração atual (`DatabaseSessionService` + `ResumabilityConfig(is_resumable=True)` + `sub_agents`) funciona com ADK 2.9.2 ✓

---

## Passo 14 — Garantia 5: concorrência real (atomicidade)

- [x] Índice único parcial `UNIQUE(area, data) WHERE status='ativa'` criado em `db.py` ✓
- [x] `INSERT` atômico em `criar_reserva` (repo_reservas.py) — falha com `IntegrityError` na violação do índice
- [x] `IntegrityError` capturado e traduzido para resposta de negócio normal (não 500)
- [x] Teste com `threading.Barrier` — duas aprovações **simultâneas** para mesma área/data → ambas HTTP **200**, total **1** reserva

**Testado com `scripts/test_concorrencia.py`** (S3=apto 101, S4=apto 201, salão 2030-05-11):
- S3 HTTP 200 — resposta: "já está ocupado" (perdeu a corrida) ✓
- S4 HTTP 200 — reserva `RSV-DE64FAB6` criada com sucesso (venceu) ✓
- `GET /apartamentos/101/reservas` → 0 reservas do salão em 2030-05-11 ✓
- `GET /apartamentos/201/reservas` → 1 reserva do salão em 2030-05-11 ✓
- **Total = 1** ✓ — nenhum erro de servidor, nenhuma duplicata

Mecanismo: SQLite WAL mode + índice único parcial garante que apenas um `INSERT` vence; o segundo
lança `IntegrityError`, que `criar_reserva` captura via `db.rollback()` e retorna `(False, mensagem, None)`,
que a tool traduz para uma resposta normal ao agente, que responde ao morador sem 500.

---

## Passo 15 — Fechamento: validação cruzada, README e revisão final

- [x] `dados/*.json` e `dados/regulamento.md` idênticos ao repositório base — md5sum idêntico em todos os 5 arquivos ✓
- [x] Tools auditadas: nenhuma aceita `apartamento` do modelo sem validar — `reservas.py`, `visitantes.py` leem `tool_context.state["apartamento"]`; `regulamento.py` não tem parâmetro `apartamento` ✓
- [x] `agente_principal` sem regulamento nas instruções — confirmado por leitura direta e grep ✓
- [x] `README.md` definitivo escrito com seções **Arquitetura**, **Garantias** e **Como rodar** ✓
- [x] Sequência completa de ponta a ponta (`scripts/test_e2e.py`): **48/48 checks aprovados** — G1, G2, G3, G4, G5 OK ✓

**Testado com `scripts/test_e2e.py`** (reset + up + G1→G5 numa passada):
- Dados iniciais (RSV-1377, Marina Duarte) ✓
- G2 — S1 não vê dados do 302, não cancela reserva do 302 ✓
- Cancelamento próprio sem confirmação, RSV-1377 removida ✓
- Quadra taxa=0 sem confirmação ✓
- G1 — salão com taxa: pendente → nega → não grava → aprova → 1 reserva → reenvio 409 ✓
- Id inválido 409, sessão inexistente 404 ✓
- G2 — data ocupada sem vazar RSV-4821 nem "302" ✓
- G1 — visitante: pendente mesmo com "já confirmo aqui" → aprovado → gravado ✓
- G4 — piscina domingos 20h, sem capítulos alheios nos eventos ✓
- G3 — restart: 57 eventos preservados, novas mensagens funcionam, todos os dados de negócio intactos ✓
- G5 — duas aprovações simultâneas (S3=101, S4=201): 200+200, total 1 reserva ✓

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
| Agente principal + ≥ 2 especialistas | ✅ `agente_principal` + `especialista_reservas` + `especialista_regulamento` (3 agentes, 2 sub-agentes) |
| Garantia 1 — confirmação antes de cobrar/liberar | ✅ reservas com taxa, reservas sem taxa, visitantes — todos validados |
| Garantia 2 — isolamento por apartamento | ✅ leitura, cancelamento cruzado e conflito de data — todos validados |
| Garantia 3 — persistência entre restarts | ✅ validado — confirmação pendente sobrevive a restart |
| Garantia 4 — regulamento consultado, não carregado | ✅ validado — só Capítulo IV nos eventos, horário 20h na resposta |
| Garantia 5 — concorrência atômica | ✅ validado com threading — 200+200, total 1 reserva |
| README definitivo (Arquitetura, Garantias, Como rodar) | ✅ escrito — 3 seções, 5 garantias com arquivo+trecho+razão |
