#!/bin/sh
# Projektets egna systempaket (skelett, D8:8, D8:18). Körs som root sist i `ci`, som `dev` bygger på,
# så allt här påverkar också imagens golv och grindens verktyg. Håll skriptet litet och granska varje
# ändring (strict). Exempel:
#   apt-get update && apt-get install -y --no-install-recommends libpq-dev && rm -rf /var/lib/apt/lists/*
set -e
