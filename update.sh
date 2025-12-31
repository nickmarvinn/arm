#!/bin/bash
git pull
docker compose down
docker compose up --build
docker image prune -f
echo "Update complete."