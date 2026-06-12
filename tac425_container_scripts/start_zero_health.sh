#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${HOME}/TAC425/external/Zero-Health"
cd "$REPO_DIR"

if [ ! -f .env ] && [ -f .env.example ]; then
  echo '+ cp .env.example .env'
  cp .env.example .env
fi

if command -v docker-compose >/dev/null 2>&1; then
  echo '+ docker-compose -f docker-compose.yml -f docker-compose.tac425.yml up -d --build'
  docker-compose -f docker-compose.yml -f docker-compose.tac425.yml up -d --build
else
  echo '+ docker compose -f docker-compose.yml -f docker-compose.tac425.yml up -d --build'
  docker compose -f docker-compose.yml -f docker-compose.tac425.yml up -d --build
fi
