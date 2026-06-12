#!/usr/bin/env bash
set -euo pipefail

echo '+ docker rm -f juice_shop >/dev/null 2>&1 || true'
docker rm -f juice_shop >/dev/null 2>&1 || true
