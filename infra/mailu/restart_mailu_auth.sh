#!/bin/bash
# [Flow: Step 1 (Mailu 재시작) -> Step 2 (Supabase auth에 Mailu CA 포함 이미지 적용) -> Step 3 (SMTP 설정 적용)]
set -e

cd /home/jun/mailu
/usr/bin/docker compose up -d

cd /opt/supabase-chungu
/usr/bin/docker compose -f docker-compose.yml -f /home/jun/supabase-auth-override.yml --env-file /home/jun/supabase-chungu.env up -d --no-deps --force-recreate auth
