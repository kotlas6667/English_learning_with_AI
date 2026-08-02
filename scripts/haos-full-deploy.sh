#!/usr/bin/env bash
# Durable HAOS update: sync code into project dir, keep .env + data/, full image rebuild.
# Usage (on HAOS):
#   BRANCH=cursor/fix-mobile-mic-tts-4a94 bash scripts/haos-full-deploy.sh
# Or from /tmp after download — set PROJECT_DIR if needed.

set -euo pipefail

BRANCH="${BRANCH:-cursor/fix-mobile-mic-tts-4a94}"
PROJECT_DIR="${PROJECT_DIR:-/share/English_learning_with_AI}"
CONTAINER="${CONTAINER:-englearning}"
IMAGE="${IMAGE:-englearning:latest}"
HOST_DATA="${HOST_DATA:-/mnt/data/supervisor/share/English_learning_with_AI/data}"
REPO_TGZ_URL="${REPO_TGZ_URL:-https://codeload.github.com/kotlas6667/English_learning_with_AI/tar.gz/${BRANCH}}"

echo "==> Branch: ${BRANCH}"
echo "==> Project: ${PROJECT_DIR}"
echo "==> Data volume (host): ${HOST_DATA}"

WORKDIR="$(mktemp -d /tmp/englearning-deploy.XXXXXX)"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

echo "==> Download ${REPO_TGZ_URL}"
curl -fsSL -L -o "${WORKDIR}/eng.tgz" "${REPO_TGZ_URL}"
tar -xzf "${WORKDIR}/eng.tgz" -C "${WORKDIR}"
NEW="$(find "${WORKDIR}" -maxdepth 1 -type d \( -name 'English_learning_with_AI-*' -o -name 'kotlas6667-English_learning_with_AI-*' \) | head -1)"
if [[ -z "${NEW}" || ! -d "${NEW}/app" ]]; then
  echo "ERROR: unpack failed (no app/)." >&2
  exit 1
fi
echo "==> Unpacked: ${NEW}"

mkdir -p "${PROJECT_DIR}"
# Preserve secrets + learner data across code updates.
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  cp -a "${PROJECT_DIR}/.env" "${WORKDIR}/.env.keep"
fi
if [[ -d "${PROJECT_DIR}/data" ]]; then
  mkdir -p "${WORKDIR}/data.keep"
  cp -a "${PROJECT_DIR}/data/." "${WORKDIR}/data.keep/"
fi

echo "==> Sync code into ${PROJECT_DIR}"
# Remove old code tree but keep directory; then copy fresh tree.
find "${PROJECT_DIR}" -mindepth 1 -maxdepth 1 ! -name data ! -name .env -exec rm -rf {} +
cp -a "${NEW}/." "${PROJECT_DIR}/"

if [[ -f "${WORKDIR}/.env.keep" ]]; then
  cp -a "${WORKDIR}/.env.keep" "${PROJECT_DIR}/.env"
fi
mkdir -p "${PROJECT_DIR}/data"
if [[ -d "${WORKDIR}/data.keep" ]]; then
  cp -a "${WORKDIR}/data.keep/." "${PROJECT_DIR}/data/"
fi

# Ensure host data mount path exists (HAOS Supervised path).
mkdir -p "${HOST_DATA}"
# If project data has content and host volume is empty-ish, seed once.
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
  -p 8080:8080 \
  -v "${HOST_DATA}:/app/data" \
  "${ENV_FILE_ARGS[@]}" \
  "${IMAGE}"

sleep 2
echo "==> Health"
docker exec "${CONTAINER}" grep -E "Ťukni a hovor|app.js\\?v=" /app/app/static/index.html || true
docker exec "${CONTAINER}" test -f /app/app/user_settings.py && echo "user_settings OK"
curl -fsS "http://127.0.0.1:8080/api/health" || true
echo
echo "==> Hotovo. Nastavenia lekcie sú v volume: ${HOST_DATA}/users/<id>/settings.json"
echo "    Full rebuild mení len kód/image — data (settings, slovíčka, profil) ostanú."
