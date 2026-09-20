# Plano de implementação — Assistente do Residencial Aurora (Google ADK)

Este plano mapeia os passos de construção aos itens do checklist de aceite do enunciado (cada seção abaixo é o "passo N" citado nos critérios). Serve como roteiro de execução e como contexto para outra instância de Claude (ex: Claude Code) continuar o trabalho.

## Decisões de arquitetura (fixar antes de codar)

- **Framework**: FastAPI + Uvicorn.
- **Persistência de sessão**: `DatabaseSessionService` do ADK sobre SQLite (`sqlite:///./data/sessions.db`). **Atenção**: em várias versões do ADK, o fluxo de *Tool Confirmation* (HITL) não funciona com `DatabaseSessionService`/`VertexAiSessionService` — só com sessão em memória (`InMemorySessionService`). Isso bate exatamente com a "dica final" do enunciado. Trate isso como o maior risco técnico do projeto (ver Passo 13) e valide cedo, não no fim.
- **Persistência de dados de negócio** (reservas/visitantes): não usar o `state` da sessão do ADK para isso — usar um armazenamento próprio (SQLite separado, ex: `data/condominio.db`, com `sqlite3`/SQLAlchemy), porque:
  - precisa sobreviver ao restart independente da sessão (Garantia 3);
  - precisa de uma constraint atômica de unicidade (Garantia 5);
  - o `session.state` é por sessão/apartamento, não é o lugar certo para o estado global do condomínio.
- **Apartamento da sessão**: gravado em `session.state["apartamento"]` no momento do `create_session`, nunca lido do texto do usuário. Toda tool recebe `tool_context: ToolContext` e lê `tool_context.state["apartamento"]` — nunca um parâmetro `apartamento` vindo do modelo. Isso é a Garantia 2.
- **Confirmação (Garantia 1)**: implementada com `tool_context.request_confirmation(hint=..., payload={...})` dentro das tools que geram cobrança (reservar em área com taxa) ou liberam acesso (autorizar visitante). Isso emite um evento `adk_request_confirmation`. Sua API expõe esse pedido em `confirmacoes_pendentes` e, ao receber `POST /sessoes/{id}/confirmacoes`, monta um `FunctionResponse` com `{"confirmed": true/false}` casado pelo `function_call_id` original e o envia de volta ao Runner (via `run_async`/`newMessage`) para retomar a execução — não via mensagem de chat solta.
- **Agentes**: 1 agente principal (orquestrador, sem o regulamento nas instruções, sem acesso direto às tools de escrita) + no mínimo 2 especialistas:
  - **Especialista de Reservas e Visitantes**: tools de consulta/gravação de reservas, cancelamento, autorização de visitantes.
  - **Especialista de Regulamento**: uma tool de busca (grep/RAG simples) sobre `dados/regulamento.md`, devolve só o trecho relevante — nunca o arquivo inteiro (Garantia 4).
  - Acionamento sugerido: `sub_agents` do ADK com transferência automática (`transfer_to_agent`), ou `AgentTool` explícito — decidir e documentar o motivo no README.

---

## Passo 1 — Bootstrap do projeto e ambiente

1. Fork público de `https://github.com/devfullcycle/mba-ia-desafio-criacao-agente`, clonar localmente.
2. `uv init --python 3.12` (ou ajustar `pyproject.toml` existente).
3. `uv add "google-adk>=2.2.0,<3" fastapi "uvicorn[standard]" pydantic python-dotenv sqlalchemy aiosqlite` (ajustar conforme necessidade real).
4. Fixar a versão exata do ADK usada no `uv.lock` (rodar `uv lock` e conferir).
5. Criar `.env.example` com `GOOGLE_API_KEY=` (e outras variáveis que decidir usar, ex: `GEMINI_MODEL=`). Confirmar que `.env` está no `.gitignore`.
6. Criar `Makefile` ou scripts (`scripts/up.sh`, `scripts/reset.sh`) para:
   - **subir**: `uv run uvicorn app.main:app --port 8000`
   - **restaurar dados**: script que recopia `dados/*.json` (read-only, do repo base) para o storage de runtime (`data/condominio.db` ou JSON de trabalho) e, opcionalmente, apaga `data/sessions.db`.
7. Estrutura de pastas sugerida:
   ```
   app/
     main.py              # FastAPI app, rotas
     agents/
       principal.py
       especialista_reservas.py
       especialista_regulamento.py
     tools/
       reservas.py
       visitantes.py
       regulamento.py
     storage/
       db.py               # conexão SQLite, schema
       repo_reservas.py
       repo_visitantes.py
     services/
       runner.py           # wrap do Runner/App do ADK
   dados/                  # imutável, do enunciado
   data/                   # gerado em runtime (git-ignored)
   ```

Critérios cobertos aqui: `uv sync` funcional, versão do ADK fixada, `.env` fora do git.

---

## Passo 2 — Rotas básicas de sessão e mensagem (esqueleto)

1. `POST /sessoes` — recebe `{"apartamento": "101"}`, valida que o apartamento existe em `dados/apartamentos.json`, cria sessão ADK (`session_service.create_session(...)`) com `state={"apartamento": "101"}`, devolve `{"session_id": ...}` com 201.
2. `POST /sessoes/{session_id}/mensagens` — 404 se sessão não existe; monta `Content(role="user", parts=[Part(text=...)])`, chama `runner.run_async(...)`, agrega eventos de texto final em `resposta`, coleta pendências de confirmação abertas na sessão em `confirmacoes_pendentes`.
3. `GET /sessoes/{session_id}/eventos` — lista eventos crus da sessão (via `session_service.get_session`), na ordem.

---

## Passo 3 — Garantia 2 (parte 1): isolamento de leitura por apartamento

1. Tool de consulta de reservas do próprio apartamento lê `tool_context.state["apartamento"]`, nunca argumento livre do modelo.
2. Testar manualmente: sessão criada para "101" perguntando pelos dados do "302" não deve trazer `RSV-4821` (reserva de exemplo do 302) nem em `resposta` nem em `eventos`.
3. Regra dura no código: se alguma tool aceitar um parâmetro `apartamento`, ele deve ser ignorado/validado contra o da sessão — nunca usado diretamente.

---

## Passo 4 — Cancelamento entre apartamentos (validação negativa)

1. Tool `cancelar_reserva(codigo)` busca a reserva pelo código, compara `reserva.apartamento == tool_context.state["apartamento"]`; se não bater, recusa (resposta normal, não erro 500) e não altera nada.
2. Testar: pedir cancelamento de reserva do 302 numa sessão do 101 não altera o 302 e não vaza `RSV-4821` para a resposta/eventos.

---

## Passo 5 — Cancelamento do próprio apartamento (sem confirmação)

1. Mesma tool acima: quando `reserva.apartamento == apartamento da sessão`, cancela direto (regra de negócio 4: sem confirmação).
2. Efeito deve aparecer imediatamente em `GET /apartamentos/{n}/reservas`.

---

## Passo 6 — Reserva em área sem taxa (fluxo direto, sem confirmação)

1. Tool `reservar(area_id, data)`: consulta `dados/areas.json` pela taxa; se `taxa == 0`, grava direto (sem `request_confirmation`), respeitando a unicidade por área+data (ver Passo 14 para a trava real).
2. Testar que nenhuma pendência aparece em `confirmacoes_pendentes`.

---

## Passo 7 — Garantia 1: reserva com taxa gera confirmação pendente

1. Se `taxa > 0`, a tool chama `tool_context.request_confirmation(hint="Cobrança de R$X para reservar Y em Z", payload={"area": area_id, "data": data, "valor": taxa})` e retorna sem gravar nada.
2. API expõe isso em `confirmacoes_pendentes` com um `id` estável (o `function_call_id` do evento `adk_request_confirmation`, ou um id seu que mapeia para ele).
3. Testar: negar (rota de confirmações com `confirmado: false`) não grava nada, mesmo que o usuário reafirme por texto ("já estou confirmando aqui") — o texto nunca substitui a chamada da rota.

---

## Passo 8 — Aprovar confirmação executa exatamente uma vez

1. `POST /sessoes/{id}/confirmacoes` monta o `FunctionResponse` de aprovação, reenvia ao Runner (retomando a mesma invocação/sessão), a tool volta a rodar e grava a reserva.
2. Marcar a confirmação como "respondida" no seu controle (tabela própria de confirmações, chaveada por sessão+id) assim que processada.
3. Reenviar a mesma resposta de novo deve dar **409**, sem executar de novo — porque o id já não está mais "pendente".

---

## Passo 9 — Id de confirmação inválido/errado

1. Qualquer `id` que não esteja na lista de pendências daquela sessão específica → 409, nada é alterado. Isso vale mesmo para um id de outra sessão.

---

## Passo 10 — Conflito de data já ocupada (validação síncrona simples)

1. Antes mesmo de chegar à trava de concorrência, uma tentativa de reservar uma data já ocupada (ex: pelo 302) deve ser recusada com resposta normal.
2. A resposta e os eventos da sessão do 101 não podem conter `RSV-4821` nem "302" isolado — a tool deve devolver só "ocupado/livre", nunca o dono da reserva concorrente (ligado à Garantia 2, "checar agenda... só se livre ou ocupada").

---

## Passo 11 — Especialista de visitantes + confirmação

1. Tool `autorizar_visitante(nome, data)` sempre chama `request_confirmation` (libera acesso = Garantia 1), grava só após aprovação.
2. Testar isolamento (Garantia 2) e o texto "pode liberar, eu confirmo por aqui" não pulando a rota.

---

## Passo 12 — Garantia 4: regulamento consultado, não carregado

1. Tool `consultar_regulamento(pergunta)` faz busca (por seção/heading, ou embeddings simples, ou grep por palavras-chave) em `dados/regulamento.md` e devolve **só o trecho relevante** como resultado da tool.
2. O especialista de regulamento recebe essa tool; o agente principal não tem o arquivo nas instruções e não chama a tool diretamente.
3. Testar pergunta "posso usar a piscina domingo à noite?" — resposta deve trazer o horário de fechamento correto, e os eventos da sessão não devem conter trechos de capítulos que não são sobre piscina/horário.

---

## Passo 13 — Garantia 3: persistência entre restarts (o ponto de maior risco)

1. Trocar `InMemorySessionService` por `DatabaseSessionService(db_url="sqlite:///./data/sessions.db")` (ou equivalente da versão do ADK escolhida).
2. **Testar isoladamente e cedo** se o fluxo de confirmação (Passos 7–9) continua funcionando com sessão persistida — várias versões do ADK têm bugs/limitações aqui (é a "armadilha silenciosa" citada no enunciado: a rota aceita, mas a tool nunca retoma). Se a combinação atual não funcionar, testar variações de topologia dos agentes (subagents vs `AgentTool`), configuração de `App`/`Runner`, e — se necessário — documentar uma solução alternativa (ex: guardar você mesmo o payload da confirmação pendente fora do ADK e reconstruir o `FunctionResponse` manualmente antes de chamar `run_async`).
3. Reiniciar a API manualmente (matar o processo, subir de novo) e conferir: `GET /sessoes/{id}/eventos` devolve o histórico anterior, novas mensagens funcionam, e as reservas/visitantes gravados antes continuam nas rotas de verificação.
4. Garantir que a geração de código de reserva nunca reutiliza um código já usado (inclusive cancelado) — usar contador/uuid persistido no seu próprio storage, não em memória.

---

## Passo 14 — Garantia 5: concorrência real (idempotência/atomicidade)

1. Modelar a tabela de reservas com uma **constraint UNIQUE(area_id, data) WHERE status = 'ativa'** (ou índice único parcial), e fazer o `INSERT` de gravação dentro de uma transação que dependa dessa constraint para falhar — não confiar em "consultar antes de gravar" (há race condition).
2. Capturar a violação de unicidade no momento do `INSERT` e traduzir para uma resposta de negócio normal ("essa data já foi reservada por outra confirmação"), nunca 500.
3. Testar simulando duas aprovações simultâneas para a mesma área/data (duas threads/requests concorrentes ao `POST /sessoes/{id}/confirmacoes` de duas sessões diferentes): as duas respostas HTTP devem ser 200, mas só uma reserva deve existir ao final — some 1 reserva no total entre os dois apartamentos.

---

## Passo 15 — Fechamento: validação cruzada, README e revisão final

1. Conferir que `dados/*.json` e `dados/regulamento.md` continuam idênticos aos do repositório base (nada foi editado neles).
2. Revisar cada tool: nenhuma aceita `apartamento` do modelo sem validar contra `tool_context.state`; nenhuma tool inventa dado (tudo lido/gravado via storage próprio).
3. Confirmar que o agente principal não tem o regulamento nas instruções (grep no prompt dele).
4. Escrever `README.md` com as três seções obrigatórias:
   - **Arquitetura**: cada agente, responsabilidade, como é acionado, por quê.
   - **Garantias**: para cada uma das 5, apontar arquivo + trecho de código e explicar por que não depende do que o modelo decide.
   - **Como rodar**: pré-requisitos, variáveis do `.env`, comando de subida, comando de restauração.
5. Rodar de ponta a ponta os testes 1–14 acima numa sequência limpa (restaurar → subir → repetir cada cenário) antes de considerar pronto.

---

## Riscos a monitorar durante o desenvolvimento (usar `adk web` para depurar)

- Confirmação + sessão persistida (Passo 13) é o ponto mais instável entre versões do ADK — validar isso primeiro, não por último, mesmo que a lista de passos sugira o contrário.
- Corrida entre "consultar agenda" e "gravar reserva" (Passo 14) só se resolve com constraint no storage, não com lock em memória do processo Python (o enunciado não garante um único worker).
- Vazamento de dados entre apartamentos pode acontecer de forma sutil via *eventos* da sessão (ex: a tool de consulta de agenda devolvendo o apartamento do dono junto), não só na resposta final — revisar o payload retornado por cada tool, não só o texto do agente.
