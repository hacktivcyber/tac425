#!/usr/bin/env bash
set -euo pipefail

echo '+ docker rm -f webgoat >/dev/null 2>&1 || true'
docker rm -f webgoat >/dev/null 2>&1 || true

echo '+ docker run -d --name webgoat --restart unless-stopped -p 127.0.0.1:4000:8080 webgoat/webgoat'
docker run -d --name webgoat --restart unless-stopped -p 127.0.0.1:4000:8080 webgoat/webgoat
