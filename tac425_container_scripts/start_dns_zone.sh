#!/usr/bin/env bash
set -euo pipefail

echo '+ docker rm -f dns_zone >/dev/null 2>&1 || true'
docker rm -f dns_zone >/dev/null 2>&1 || true

echo '+ docker run -d --name dns_zone --restart unless-stopped -p 127.0.0.1:5353:53/tcp -p 127.0.0.1:5353:53/udp tac425/dns_zone:latest'
docker run -d --name dns_zone --restart unless-stopped -p 127.0.0.1:5353:53/tcp -p 127.0.0.1:5353:53/udp tac425/dns_zone:latest
