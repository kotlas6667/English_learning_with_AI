#!/usr/bin/env bash
# Po vytvorení prázdneho repo na GitHube spusti tento skript z koreňa v2 projektu.
# 1) https://github.com/new  →  Name: English_learning_with_AI_v2  (bez README/gitignore)
# 2) bash scripts/publish-to-github.sh

set -euo pipefail

OWNER="${OWNER:-kotlas6667}"
REPO="${REPO:-English_learning_with_AI_v2}"
REMOTE_URL="${REMOTE_URL:-https://github.com/${OWNER}/${REPO}.git}"

cd "$(dirname "$0")/.."

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: nie si v git repo." >&2
  exit 1
fi

echo "==> Remote: ${REMOTE_URL}"
git remote remove origin 2>/dev/null || true
git remote add origin "${REMOTE_URL}"

echo "==> Push master…"
git push -u origin master

echo "==> Hotovo: ${REMOTE_URL}"
