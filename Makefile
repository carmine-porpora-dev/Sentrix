.DEFAULT_GOAL := help
.PHONY: help setup dev data demo test test-real lint

help:
	@echo "Comandi disponibili:"
	@echo "  make setup  installa le dipendenze (uv sync, npm ci) e crea .env da .env.example se manca"
	@echo "  make dev    backend (uvicorn --reload, :8000) e frontend (vite, :5173) insieme; Ctrl-C ferma entrambi"
	@echo "  make data   scarica i dati (OSM, GTFS, PMTiles, sonda TomTom) e genera il report; richiede rete"
	@echo "  make demo   build del frontend e avvio offline su :8000           [non ancora disponibile]"
	@echo "  make test   suite veloce: pytest (senza 'live', 'realdata', 'perf') + vitest"
	@echo "  make test-real  integrazione e prestazioni sui dati veri (serve make data); ai cancelli di fase"
	@echo "  make lint   ruff, mypy, eslint, prettier"

setup:
	cd backend && uv sync
	cd frontend && npm ci
	@if [ ! -f .env ]; then cp .env.example .env; echo "Creato .env da .env.example: compilare i valori."; fi

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload) & \
	(cd frontend && npm run dev) & \
	wait

# Script dati di 00-data-sources.md, in ordine. Sono idempotenti: ciò che esiste già viene saltato
# (--force sui singoli script per rifare). La sonda TomTom usa la chiave di .env e consuma quota: se
# manca o fallisce non blocca (il prefisso '-'), ed è il report a segnalarlo. Il target esce con
# l'esito del report (1 se manca un artefatto).
data:
	cd backend && uv run python -m scripts.prepare_osm
	cd backend && uv run python -m scripts.prepare_gtfs
	cd backend && uv run python -m scripts.prepare_pmtiles
	-cd backend && uv run python -m scripts.tomtom_probe
	cd backend && uv run python -m scripts.data_report

# Stub: il backend non serve ancora il frontend compilato (F9-01) e LLM_MODE non esiste ancora (F6-01).
demo:
	@echo "make demo: non ancora disponibile (serve il backend che serve il frontend: F9-01, F9-04)." >&2
	@exit 1

test:
	cd backend && uv run pytest
	cd frontend && npm test

# Ai cancelli di fase: integrazione sui dati veri (serve `make data`) e prestazioni.
test-real:
	cd backend && uv run pytest -m "realdata or perf" -s

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && npm run lint && npm run format:check
