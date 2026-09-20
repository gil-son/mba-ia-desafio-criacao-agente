# Assistente do Residencial Aurora

API em Python com Google ADK que expõe um assistente virtual para o aplicativo de moradores do Residencial Aurora. Pelo chat, cada morador reserva áreas comuns, cancela reservas, autoriza visitantes e tira dúvidas sobre o regulamento interno. As cinco garantias descritas no enunciado estão implementadas em código e não dependem do que o modelo decide.

## Arquitetura

O assistente é composto por um agente principal e dois especialistas, conectados via `sub_agents` do ADK. O agente principal nunca acessa tools diretamente — ele orquestra e delega; os especialistas executam.

```
agente_principal
├── especialista_reservas    (sub-agente)
└── especialista_regulamento (sub-agente)
```

### agente_principal — [`app/agents/principal.py`](app/agents/principal.py)

Ponto de entrada de toda conversa. Recebe a mensagem do morador, identifica a intenção e transfere ao especialista adequado. Suas `instruction` descrevem quando acionar cada especialista mas **não contêm nenhum trecho do regulamento** (Garantia 4). Não possui tools próprias.

**Acionamento:** toda mensagem enviada à API chega ao `agente_principal` via `Runner.run_async`.

**Por quê sub-agentes?** O ADK trata a transferência como uma chamada de tool interna, o que preserva o ciclo de confirmação (`request_confirmation`) dentro do contexto correto da sessão — pré-requisito para a Garantia 1 funcionar com `DatabaseSessionService`.

### especialista_reservas — [`app/agents/especialista_reservas.py`](app/agents/especialista_reservas.py)

Trata reservas de áreas comuns, cancelamentos e autorização de visitantes. Possui as tools:

| Tool | Arquivo | O que faz |
|---|---|---|
| `ver_minhas_reservas` | [`app/tools/reservas.py`](app/tools/reservas.py) | Lista reservas ativas do apartamento da sessão |
| `listar_areas_disponiveis` | [`app/tools/reservas.py`](app/tools/reservas.py) | Mostra disponibilidade por data (sem revelar o dono) |
| `cancelar_minha_reserva` | [`app/tools/reservas.py`](app/tools/reservas.py) | Cancela reserva do próprio apartamento, sem confirmação |
| `reservar_area` | [`app/tools/reservas.py`](app/tools/reservas.py) | Reserva área: taxa=0 grava direto; taxa>0 pede confirmação |
| `ver_meus_visitantes` | [`app/tools/visitantes.py`](app/tools/visitantes.py) | Lista visitantes autorizados do apartamento da sessão |
| `autorizar_visitante` | [`app/tools/visitantes.py`](app/tools/visitantes.py) | Autoriza visitante: sempre pede confirmação |

**Acionamento:** `agente_principal` transfere para ele quando a intenção envolve reservas ou visitantes.

**Por quê um único especialista para reservas e visitantes?** Ambas as operações compartilham o mesmo ciclo de confirmação e o mesmo dado de sessão (`apartamento`). Mantê-las num único agente evita transferências desnecessárias e garante que o contexto de confirmação não se perca.

### especialista_regulamento — [`app/agents/especialista_regulamento.py`](app/agents/especialista_regulamento.py)

Responde dúvidas sobre o regulamento interno. Possui uma única tool:

| Tool | Arquivo | O que faz |
|---|---|---|
| `consultar_regulamento` | [`app/tools/regulamento.py`](app/tools/regulamento.py) | Busca trecho relevante em `dados/regulamento.md` por pontuação de palavras-chave; retorna no máximo 2 seções |

**Acionamento:** `agente_principal` transfere para ele quando a intenção envolve regras, horários ou normas.

**Por quê especialista separado?** Isola completamente o acesso ao regulamento: só este agente tem a tool de consulta, e o `agente_principal` nunca recebe o texto do regulamento nas suas instruções (Garantia 4).

---

## Garantias

### Garantia 1 — Cobrança ou acesso só com confirmação

**Onde está:** [`app/tools/reservas.py:reservar_area`](app/tools/reservas.py) e [`app/tools/visitantes.py:autorizar_visitante`](app/tools/visitantes.py).

**Como funciona:** cada tool usa um fluxo de dois passos:

1. **Primeira execução** (`tool_context.tool_confirmation is None`): chama `tool_context.request_confirmation(hint, payload)` e retorna sem gravar nada. O ADK grava um evento `adk_request_confirmation` na sessão.
2. **Re-execução pós-confirmação** (`tool_context.tool_confirmation` preenchido): verifica `tool_context.tool_confirmation.confirmed`. Se `True`, executa a ação; se `False`, descarta.

A rota `POST /sessoes/{id}/confirmacoes` em [`app/main.py`](app/main.py) monta um `FunctionResponse` com o `id` da confirmação e `{"confirmed": bool}` e o entrega ao Runner, que retoma a execução exatamente no ponto onde parou.

**Por que não depende do modelo:** a verificação de `tool_confirmation` está no código Python da tool, não no prompt. A mensagem `"já estou confirmando aqui"` do morador nunca atinge a lógica da tool — ela só avança quando `POST /confirmacoes` é chamado com o `id` correto.

**Proteção contra reenvio:** `_extrair_confirmacoes_pendentes` em [`app/main.py`](app/main.py) cruza os eventos de `adk_request_confirmation` com os de `FunctionResponse` correspondentes. Se o `id` já foi respondido, não aparece mais na lista de pendentes e a rota retorna `409`.

---

### Garantia 2 — Cada sessão pertence a um apartamento

**Onde está:** todas as tools em [`app/tools/reservas.py`](app/tools/reservas.py) e [`app/tools/visitantes.py`](app/tools/visitantes.py).

**Como funciona:** o apartamento é gravado em `session.state["apartamento"]` na criação da sessão (`POST /sessoes`) e lido exclusivamente de `tool_context.state["apartamento"]` dentro de cada tool. Nenhuma tool aceita `apartamento` como parâmetro vindo do modelo.

```python
# Exemplo em reservar_area (app/tools/reservas.py)
apartamento = tool_context.state["apartamento"]   # sempre da sessão
# ...nunca: def reservar_area(apartamento: str, ...)
```

A tool `cancelar_minha_reserva` valida `reserva.apartamento == apartamento_da_sessão` antes de cancelar, e a `listar_areas_disponiveis` retorna apenas `"livre"` ou `"ocupado"` — nunca o apartamento que está reservando.

**Por que não depende do modelo:** o `apartamento` nunca passa pelo prompt; o modelo não tem como alterá-lo. A validação acontece em Python antes de qualquer leitura ou escrita no banco.

---

### Garantia 3 — Nada se perde no reinício

**Onde está:** [`app/services/runner.py`](app/services/runner.py) e [`app/storage/db.py`](app/storage/db.py).

**Como funciona:**

- **Sessões ADK:** `DatabaseSessionService` persiste todos os eventos, estados e confirmações pendentes em SQLite. Ao reiniciar, o Runner recarrega a sessão do banco e continua de onde parou — inclusive confirmações que ainda não foram respondidas.
- **Dados de negócio:** `reservas` e `visitantes` ficam em `data/condominio.db` (SQLite separado, gerenciado pelo SQLAlchemy síncrono).
- **Resumabilidade:** o `App` é criado com `ResumabilityConfig(is_resumable=True)` para que o Runner saiba retomar sessões interrompidas.

```python
# app/services/runner.py
_session_service = DatabaseSessionService(db_url="sqlite+aiosqlite:///data/sessions.db")

app = App(
    name=_APP_NAME,
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
)

_runner = Runner(
    app=app,
    session_service=_session_service,
)
```

**Por que não depende do modelo:** é configuração de infraestrutura — banco de dados persiste independentemente de o processo estar no ar ou não.

---

### Garantia 4 — O regulamento é consultado, não carregado

**Onde está:** [`app/tools/regulamento.py:consultar_regulamento`](app/tools/regulamento.py) e [`app/agents/principal.py`](app/agents/principal.py).

**Como funciona:** a tool `consultar_regulamento` divide `dados/regulamento.md` em seções (capítulos e artigos), pontua cada seção pela relevância à pergunta usando palavras-chave e retorna **no máximo 2 seções**. O documento inteiro nunca entra num único evento de sessão.

O `agente_principal` não tem o regulamento nas suas `instruction` — apenas a instrução de delegar ao `especialista_regulamento`. O texto do regulamento só aparece nos eventos de `function_response` da tool, limitado ao trecho retornado.

**Por que não depende do modelo:** a seleção de trechos é feita em Python pela tool (pontuação por palavras-chave + mapeamento de sinônimos). O modelo recebe apenas o resultado da tool, não o documento completo.

---

### Garantia 5 — Dois moradores, uma reserva

**Onde está:** [`app/storage/db.py`](app/storage/db.py) (índice) e [`app/storage/repo_reservas.py:criar_reserva`](app/storage/repo_reservas.py).

**Como funciona:**

1. **Índice único parcial** no SQLite:
   ```python
   # app/storage/db.py
   Index(
       "uq_reserva_ativa_area_data",
       Reserva.area, Reserva.data,
       unique=True,
       sqlite_where=text("status = 'ativa'"),
   )
   ```
   Garante que nunca existam duas linhas com `status='ativa'` para o mesmo `(area, data)`.

2. **INSERT atômico com captura de `IntegrityError`**:
   ```python
   # app/storage/repo_reservas.py
   try:
       db.add(reserva)
       db.commit()
       return True, f"Reserva {codigo} criada ...", codigo
   except IntegrityError:
       db.rollback()
       return False, f"A data {data} já está ocupada para ...", None
   ```

3. **WAL mode** ativado em todas as conexões (`PRAGMA journal_mode=WAL`) para suportar leituras concorrentes enquanto uma escrita está em andamento.

**Por que não depende do modelo:** a exclusividade é garantida pelo banco no momento do `COMMIT`, não por uma verificação prévia feita pelo modelo. Mesmo que dois INSERTs cheguem simultaneamente, o banco rejeita o segundo com `IntegrityError`, que a tool converte em resposta de negócio normal (sem erro de servidor).

---

## Como rodar

### Pré-requisitos

- Python 3.12 ou superior
- [`uv`](https://docs.astral.sh/uv/) instalado (`pip install uv` ou `curl -Ls https://astral.sh/uv/install.sh | sh`)
- Chave de API do Google AI Studio ([aistudio.google.com](https://aistudio.google.com))

### Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

```
GOOGLE_API_KEY=sua-chave-aqui

# Modelos Gemini — ajuste conforme os limites do seu projeto no AI Studio
MODEL_PRINCIPAL=gemini-3.5-flash-lite
MODEL_ESPECIALISTA_RESERVAS=gemini-3.5-flash-lite
MODEL_ESPECIALISTA_REGULAMENTO=gemini-3.5-flash-lite
```

### Instalar dependências

```bash
uv sync
```

### Restaurar dados iniciais

Remove os bancos de runtime (`data/condominio.db` e `data/sessions.db`) para que sejam recriados a partir dos arquivos imutáveis em `dados/` na próxima subida:

```bash
bash scripts/reset.sh
```

Para restaurar só os dados de negócio mantendo as sessões ativas:

```bash
bash scripts/reset.sh --keep-sessions
```

### Subir a API

```bash
bash scripts/up.sh
```

A API fica disponível em `http://localhost:8000`. Na primeira subida após o reset, o banco é criado e populado automaticamente com os dados de `dados/*.json`.

### Verificar funcionamento

```bash
# Dados iniciais — deve listar RSV-1377
curl http://localhost:8000/apartamentos/101/reservas

# Dados iniciais — deve listar Marina Duarte
curl http://localhost:8000/apartamentos/302/visitantes
```

### Teste automatizado (opcional)

O repositório inclui scripts de validação usados durante o desenvolvimento:

```bash
# Teste de ponta a ponta (passos 1–14 do avaliador, inclui restart automático)
uv run python scripts/test_e2e.py

# Teste isolado de concorrência (Garantia 5)
uv run python scripts/test_concorrencia.py

# Teste isolado da Garantia 4 (regulamento)
uv run python scripts/test_garantia4.py
```
