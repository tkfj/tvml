#!/bin/bash

SCRIPT_PATH=$(realpath "$0")
SCRIPT_DIR=$(dirname "${SCRIPT_PATH}")

docker compose -f ${SCRIPT_DIR}/docker-compose.yml run --rm app python src/test2.py
docker compose -f ${SCRIPT_DIR}/docker-compose.yml run --rm app python src/main.py
