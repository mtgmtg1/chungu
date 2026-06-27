#!/bin/bash
set -e
cd /Users/jun16/repo/chungu/app
docker build -f Dockerfile.backend -t chungu-backend:multimedia . --build-arg VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlLWNodW5ndSIsImlhdCI6MTc4MjM3NzA0MiwiZXhwIjoyMDk3NzM3MDQyfQ._WSiSZmzrmnmgfKHfEN9FrSnZ_a5PiMiJvyS4hmHmEc
