#!/usr/bin/env bash
set -euo pipefail

echo '+ docker rm -f juice_shop >/dev/null 2>&1 || true'
docker rm -f juice_shop >/dev/null 2>&1 || true

echo '+ docker run -d --name juice_shop --restart unless-stopped -p 127.0.0.1:2000:3000 bkimminich/juice-shop'
docker run -d --name juice_shop --restart unless-stopped -p 127.0.0.1:2000:3000 bkimminich/juice-shop
