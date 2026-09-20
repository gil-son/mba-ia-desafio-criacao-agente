#!/usr/bin/env bash
# Sobe a API do Residencial Aurora na porta 8000.
# Uso: bash scripts/up.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# Garante que o arquivo .env existe
if [ ! -f .env ]; then
  echo "ERRO: arquivo .env não encontrado. Copie .env.example e preencha GOOGLE_API_KEY."
  exit 1
fi

# Cria a pasta de dados de runtime se não existir
mkdir -p data

uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
