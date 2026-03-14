#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yml"
SERVICE_NAME="frontend"
FRONTEND_PORT="${DRAGONCP_FRONTEND_PORT:-5002}"

log() {
  printf '[deploy-frontend] %s\n' "$*"
}

fail() {
  printf '[deploy-frontend] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

compose() {
  docker compose -f "${COMPOSE_FILE}" "$@"
}

is_service_running() {
  local running_output
  running_output="$(compose ps --services --status running "${SERVICE_NAME}" 2>/dev/null || true)"
  [[ "${running_output}" == "${SERVICE_NAME}" ]]
}

main() {
  require_command docker

  [[ -f "${COMPOSE_FILE}" ]] || fail "Compose file not found at ${COMPOSE_FILE}"

  docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is not available"
  docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable. Start Docker and try again"

  compose config >/dev/null

  log "Docker version: $(docker --version)"
  log "Compose version: $(docker compose version --short)"
  log "Project root: ${PROJECT_ROOT}"

  if is_service_running; then
    log "Stopping running ${SERVICE_NAME} container"
    compose stop "${SERVICE_NAME}"
  else
    log "${SERVICE_NAME} container is not currently running"
  fi

  log "Rebuilding ${SERVICE_NAME} image with latest local changes"
  compose build --pull "${SERVICE_NAME}"

  log "Starting ${SERVICE_NAME} container"
  compose up -d --force-recreate "${SERVICE_NAME}"

  log "Deployment complete"
  log "Frontend URL: http://localhost:${FRONTEND_PORT}"
  compose ps "${SERVICE_NAME}"
}

main "$@"
