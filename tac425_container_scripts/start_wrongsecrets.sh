#!/usr/bin/env bash
set -euo pipefail

echo '+ docker rm -f wrongsecrets >/dev/null 2>&1 || true'
docker rm -f wrongsecrets >/dev/null 2>&1 || true

echo '+ docker run -d --name wrongsecrets --restart unless-stopped -p 127.0.0.1:3000:8080 jeroenwillemsen/wrongsecrets:latest-no-vault'
docker run -d --name wrongsecrets --restart unless-stopped -p 127.0.0.1:3000:8080 jeroenwillemsen/wrongsecrets:latest-no-vault
