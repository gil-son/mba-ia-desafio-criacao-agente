#!/usr/bin/env bash
# Restaura os dados do condomínio ao estado inicial do repositório.
# Remove o banco de negócio (condominio.db) para que seja recriado a partir
# dos arquivos de dados/. Opcionalmente apaga também as sessões ADK.
# Uso: bash scripts/reset.sh [--keep-sessions]
set -euo pipefail

cd "$(dirname "$0")/.."

KEEP_SESSIONS=false
for arg in "$@"; do
  case $arg in
    --keep-sessions) KEEP_SESSIONS=true ;;
  esac
done

echo "Restaurando dados do condomínio..."

# Apaga o banco de negócio — será recriado e populado na próxima subida
rm -f data/condominio.db

if [ "$KEEP_SESSIONS" = false ]; then
  echo "Removendo sessões ADK..."
  rm -f data/sessions.db
fi

echo "Restauração concluída. Suba a API com: bash scripts/up.sh"
