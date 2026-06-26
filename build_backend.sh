#!/bin/bash
set -e
cd /Users/jun16/repo/chungu/app
docker build -f Dockerfile.backend -t chungu-backend:multimedia . --build-arg VITE_SUPABASE_URL=http://192.168.1.50:28000 --build-arg VITE_SUPABASE_ANON_KEY=anonkey
