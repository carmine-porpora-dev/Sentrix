#!/bin/sh

set -eu

cd "$(dirname "$0")/.."

# Con /data vuota (primo avvio) scarica grafo, orari e mappa; con i dati presenti non fa nulla. Va in
# BACKGROUND: con la rete che non risponde lo script OSM può restare fermo per decine di minuti
# (provato: oltre 28 con un proxy morto) e il server non partirebbe mai. L'applicazione carica
# grafo e orari alla prima richiesta che li usa e non ricorda un caricamento fallito: appena i file
# arrivano, /api/health torna `ok` e i run funzionano, senza riavviare. Intanto /api/health dice
# `degraded` con i dati mancanti (09 3.6). Va tenuto un `init` nel container (compose: `init: true`)
# perché il processo 1, uvicorn, non raccoglie lo script quando finisce.
python -m scripts.bootstrap_data &

# exec: uvicorn diventa il processo principale del container e riceve SIGTERM
# (`docker compose stop`): chiude i run in corso invece di essere ucciso.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
