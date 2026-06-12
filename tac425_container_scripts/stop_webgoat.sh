#!/usr/bin/env bash
set -euo pipefail

echo '+ docker rm -f webgoat >/dev/null 2>&1 || true'
docker rm -f webgoat >/dev/null 2>&1 || true
