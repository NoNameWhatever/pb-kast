#!/bin/sh
# postgres-modulens verktyg i ci-stadiet (D8:8, D8:28): psql för checken och Squawk för klassningen av destruktiv DDL.
# Squawk installeras med hashar ur låsfilen (D6:27). Körs som root av pb-Dockerfile i alfabetisk ordning.
set -e
apt-get update
apt-get install -y --no-install-recommends postgresql-client python3-venv python3-pip
rm -rf /var/lib/apt/lists/*
python3 -m venv /opt/pb-postgres-tools
/opt/pb-postgres-tools/bin/pip install --no-cache-dir --no-deps --require-hashes \
  -r /opt/pb-modules/postgres-tools.lock
ln -sf /opt/pb-postgres-tools/bin/squawk /usr/local/bin/squawk
