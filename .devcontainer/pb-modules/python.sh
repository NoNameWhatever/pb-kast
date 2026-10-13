#!/bin/sh
# python-modulens verktyg i ci-stadiet (D8:8, D8:26). Körs som root av pb-Dockerfile i alfabetisk ordning.
# uv, Ruff och basedpyright installeras med hashar ur låsfilen (D6:27); Python själv hämtas vid körning av uv
# enligt .python-version, mot hashar som uv bär (D8:30). Grindverktygen omfattas inte av cooldownen (D8:11).
set -e
apt-get update
apt-get install -y --no-install-recommends python3-venv python3-pip
rm -rf /var/lib/apt/lists/*
python3 -m venv /opt/pb-python-tools
/opt/pb-python-tools/bin/pip install --no-cache-dir --no-deps --require-hashes \
  -r /opt/pb-modules/python-tools.lock
for tool in uv uvx ruff basedpyright basedpyright-langserver; do
  ln -sf "/opt/pb-python-tools/bin/$tool" "/usr/local/bin/$tool"
done
install -d -m 0755 /etc/uv
install -m 0644 /opt/pb-modules/python-uv.toml /etc/uv/uv.toml
