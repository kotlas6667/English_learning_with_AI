#!/usr/bin/env bash
# Replace EngLearning v1 with v2 on HAOS (same container/port/data).
# Usage:
#   bash scripts/haos-full-deploy.sh
# Or bootstrap:
#   curl …/haos-full-deploy.sh && bash ./haos-full-deploy.sh

set -euo pipefail

BRANCH="${BRANCH:-main}"
PROJECT_DIR="${PROJECT_DIR:-/share/English_learning_with_AI}"
CONTAINER="${CONTAINER:-englearning}"
IMAGE="${IMAGE:-englearning:latest}"
HOST_DATA="${HOST_DATA:-/mnt/data/supervisor/share/English_learning_with_AI/data}"
HOST_PORT="${HOST_PORT:-8080}"
REPO_TGZ_URL="${REPO_TGZ_URL:-https://codeload.github.com/kotlas6667/English_learning_with_AI_v2/tar.gz/${BRANCH}}"

# Old v1 leftovers to remove when replacing.
OLD_CONTAINERS=(englearning englearning-v2)
OLD_PROJECT_V2="${OLD_PROJECT_V2:-/share/English_learning_with_AI_v2}"

echo "==> EngLearning: REPLACE v1 → v2"
echo "==> Branch: ${BRANCH}"
echo "==> Project: ${PROJECT_DIR}"
echo "==> Data volume (host): ${HOST_DATA}"
echo "==> Container: ${CONTAINER}  port: ${HOST_PORT}"

WORKDIR="$(mktemp -d /tmp/englearning-v2-deploy.XXXXXX)"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

echo "==> Stop & remove old containers (v1 / side-by-side v2)"
for c in "${OLD_CONTAINERS[@]}"; do
  docker rm -f "${c}" 2>/dev/null || true
done

echo "==> Download ${REPO_TGZ_URL}"
curl -fsSL -L -o "${WORKDIR}/eng.tgz" "${REPO_TGZ_URL}"
tar -xzf "${WORKDIR}/eng.tgz" -C "${WORKDIR}"
NEW="$(find "${WORKDIR}" -maxdepth 1 -type d \( \
  -name 'English_learning_with_AI_v2-*' \
  -o -name 'kotlas6667-English_learning_with_AI_v2-*' \
  -o -name 'English_learning_with_AI-*' \
\) | head -1)"
if [[ -z "${NEW}" || ! -d "${NEW}/app" ]]; then
  echo "ERROR: unpack failed (no app/)." >&2
  exit 1
fi
echo "==> Unpacked: ${NEW}"

mkdir -p "${PROJECT_DIR}"

# Prefer existing .env from current project, else from side-by-side v2 dir.
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  cp -a "${PROJECT_DIR}/.env" "${WORKDIR}/.env.keep"
elif [[ -f "${OLD_PROJECT_V2}/.env" ]]; then
  cp -a "${OLD_PROJECT_V2}/.env" "${WORKDIR}/.env.keep"
fi

# Preserve project-local data copy if present (volume below is authoritative).
if [[ -d "${PROJECT_DIR}/data" ]]; then
  mkdir -p "${WORKDIR}/data.keep"
  cp -a "${PROJECT_DIR}/data/." "${WORKDIR}/data.keep/"
fi

echo "==> Sync v2 code into ${PROJECT_DIR} (replaces previous code tree)"
find "${PROJECT_DIR}" -mindepth 1 -maxdepth 1 ! -name data ! -name .env -exec rm -rf {} +
cp -a "${NEW}/." "${PROJECT_DIR}/"

if [[ -f "${WORKDIR}/.env.keep" ]]; then
  cp -a "${WORKDIR}/.env.keep" "${PROJECT_DIR}/.env"
fi
mkdir -p "${PROJECT_DIR}/data"
if [[ -d "${WORKDIR}/data.keep" ]]; then
  cp -a "${WORKDIR}/data.keep/." "${PROJECT_DIR}/data/"
fi

mkdir -p "${HOST_DATA}"
if [[ -d "${PROJECT_DIR}/data" ]] && [[ -z "$(ls -A "${HOST_DATA}" 2>/dev/null || true)" ]]; then
  echo "==> Seeding empty host data from project data/"
  cp -a "${PROJECT_DIR}/data/." "${HOST_DATA}/"
fi

cd "${PROJECT_DIR}"
echo "==> docker build ${IMAGE}"
docker build -t "${IMAGE}" .

echo "==> Start ${CONTAINER} on :${HOST_PORT}"
docker rm -f "${CONTAINER}" 2>/dev/null || true

ENV_FILE_ARGS=()
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  ENV_FILE_ARGS=(--env-file "${PROJECT_DIR}/.env")
fi

docker run -d \
  --name "${CONTAINER}" \
  --restart unless-stopped \
  -p "${HOST_PORT}:8080" \
  -v "${HOST_DATA}:/app/data" \
  "${ENV_FILE_ARGS[@]}" \
  "${IMAGE}"

sleep 2
echo "==> Health"
docker exec "${CONTAINER}" grep -E "app.js\\?v=|bottom-nav|viewHome" /app/app/static/index.html || true
docker exec "${CONTAINER}" test -f /app/app/scenarios.py && echo "scenarios OK"
docker exec "${CONTAINER}" test -f /app/app/static/v2-shell.js && echo "v2-shell OK"
curl -fsS "http://127.0.0.1:${HOST_PORT}/api/health" || true
echo
echo "==> Hotovo: v2 beží ako ${CONTAINER} na porte ${HOST_PORT}."
echo "    Data (settings/stats/learning) ostávajú vo volume: ${HOST_DATA}"
echo "    Starý kód v1 bol nahradený. Ctrl+Shift+R v prehliadači."
