#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${HOME}/TAC425/external/Zero-Health"
cd "$REPO_DIR"

if command -v docker-compose >/dev/null 2>&1; then
  echo '+ docker-compose -f docker-compose.yml -f docker-compose.tac425.yml down -v'
  docker-compose -f docker-compose.yml -f docker-compose.tac425.yml down -v
else
  echo '+ docker compose -f docker-compose.yml -f docker-compose.tac425.yml down -v'
  docker compose -f docker-compose.yml -f docker-compose.tac425.yml down -v
fi
