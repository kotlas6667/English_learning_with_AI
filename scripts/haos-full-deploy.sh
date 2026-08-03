#!/usr/bin/env bash
# Durable HAOS update for EngLearning v2 (separate from v1).
# Usage (on HAOS):
#   bash scripts/haos-full-deploy.sh
# Or bootstrap from /tmp after curl download.

set -euo pipefail

BRANCH="${BRANCH:-master}"
PROJECT_DIR="${PROJECT_DIR:-/share/English_learning_with_AI_v2}"
CONTAINER="${CONTAINER:-englearning-v2}"
IMAGE="${IMAGE:-englearning-v2:latest}"
HOST_DATA="${HOST_DATA:-/mnt/data/supervisor/share/English_learning_with_AI_v2/data}"
HOST_PORT="${HOST_PORT:-8081}"
REPO_TGZ_URL="${REPO_TGZ_URL:-https://codeload.github.com/kotlas6667/English_learning_with_AI_v2/tar.gz/${BRANCH}}"

echo "==> EngLearning v2 deploy"
echo "==> Branch: ${BRANCH}"
echo "==> Project: ${PROJECT_DIR}"
echo "==> Data volume (host): ${HOST_DATA}"
echo "==> Container: ${CONTAINER}  port: ${HOST_PORT}"

WORKDIR="$(mktemp -d /tmp/englearning-v2-deploy.XXXXXX)"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

echo "==> Download ${REPO_TGZ_URL}"
curl -fsSL -L -o "${WORKDIR}/eng.tgz" "${REPO_TGZ_URL}"
tar -xzf "${WORKDIR}/eng.tgz" -C "${WORKDIR}"
NEW="$(find "${WORKDIR}" -maxdepth 1 -type d \( -name 'English_learning_with_AI_v2-*' -o -name 'kotlas6667-English_learning_with_AI_v2-*' \) | head -1)"
if [[ -z "${NEW}" || ! -d "${NEW}/app" ]]; then
  echo "ERROR: unpack failed (no app/)." >&2
  exit 1
fi
echo "==> Unpacked: ${NEW}"

mkdir -p "${PROJECT_DIR}"
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  cp -a "${PROJECT_DIR}/.env" "${WORKDIR}/.env.keep"
fi
if [[ -d "${PROJECT_DIR}/data" ]]; then
  mkdir -p "${WORKDIR}/data.keep"
  cp -a "${PROJECT_DIR}/data/." "${WORKDIR}/data.keep/"
fi

echo "==> Sync code into ${PROJECT_DIR}"
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

echo "==> Replace container ${CONTAINER}"
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
echo "==> Hotovo (v2). Data: ${HOST_DATA}"
echo "    v1 kontajner englearning (ak beží) ostáva nedotknutý."
