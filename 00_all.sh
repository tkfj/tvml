#!/bin/bash

SCRIPT_PATH=$(realpath "$0")
SCRIPT_DIR=$(dirname "${SCRIPT_PATH}")

docker compose -f ${SCRIPT_DIR}/docker-compose.yml run --rm app uv run src/prepare.py
docker compose -f ${SCRIPT_DIR}/docker-compose.yml run --rm app uv run src/main.py
