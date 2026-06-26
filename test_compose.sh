#!/bin/bash
set -e
cd /Users/jun16/repo/chungu/app
docker compose down
docker compose up -d
sleep 5
docker compose ps
echo "--- API logs ---"
docker compose logs api --tail 20
