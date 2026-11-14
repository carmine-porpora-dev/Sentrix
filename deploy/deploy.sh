#!/bin/sh

set -eu

IMAGE="napoli-urban-ops"        # il nome dell'immagine in docker-compose.yml
ALPINE_IMAGE="alpine:3.24.4"    # solo per dare i permessi a /data
APP_UID=10001                   # l'utente del container (Dockerfile)
DATA_HOST_DIR="/data"           # la cartella dei dati sulla VM (montata in /data nel container)
BRANCH="${DEPLOY_BRANCH:-main}"
HEALTH_WAIT_S="${HEALTH_WAIT_S:-180}"
HEALTH_POLL_S="${HEALTH_POLL_S:-3}"
# Variabili senza le quali l'applicazione non serve (GEMINI_API_KEY solo con LLM_MODE=live).
REQUIRED_VARS="DOMAIN APP_PASSWORD SESSION_SECRET GEMINI_MODEL TOMTOM_API_KEY LLM_MODE ENV"
DRY_RUN=0

say() { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy] ERRORE: %s\n' "$*" >&2; exit 1; }

# Esegue il comando; con --dry-run lo mostra soltanto.
run() {
  if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi
}

# Il valore di una variabile del .env, senza virgolette. Solo per i controlli: non va mai stampato.
env_value() {
  sed -n "s/^$1=//p" .env | tail -n 1 | sed "s/^[\"']//; s/[\"']\$//"
}

check_env() {
  [ -f .env ] || fail ".env non trovato in $(pwd): copia .env.example in .env e compilalo"
  chmod 600 .env
  missing=""
  for name in $REQUIRED_VARS; do
    [ -n "$(env_value "$name")" ] || missing="$missing $name"
  done
  [ -z "$missing" ] || fail "nel .env mancano o sono vuote:$missing"
  [ "$(env_value ENV)" = production ] || fail "nel .env ENV deve essere 'production'"
  case "$(env_value LLM_MODE)" in
    live | cache_only | template) ;;
    *) fail "nel .env LLM_MODE deve essere live, cache_only o template" ;;
  esac
  if [ "$(env_value LLM_MODE)" = live ] && [ -z "$(env_value GEMINI_API_KEY)" ]; then
    fail "nel .env LLM_MODE=live richiede GEMINI_API_KEY"
  fi
  say ".env completo"
}

# Tiene una copia dell'immagine in esecuzione, per tornare indietro se la nuova non parte.
keep_previous() {
  if [ "$DRY_RUN" = 1 ]; then
    say "(dry-run) se $IMAGE:latest esiste, la tengo come $IMAGE:previous"
  elif docker image inspect "$IMAGE:latest" >/dev/null 2>&1; then
    docker tag "$IMAGE:latest" "$IMAGE:previous"
  fi
}

# Aspetta che l'app sia «healthy» (il controllo è in docker-compose.yml). 0 = sì, 1 = no.
wait_healthy() {
  if [ "$DRY_RUN" = 1 ]; then
    say "(dry-run) aspetto fino a ${HEALTH_WAIT_S} s che l'app sia in salute"
    return 0
  fi
  elapsed=0
  while [ "$elapsed" -lt "$HEALTH_WAIT_S" ]; do
    cid=$(docker compose ps -q app 2>/dev/null || true)
    status=""
    [ -z "$cid" ] || status=$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)
    case "$status" in
      healthy) return 0 ;;
      unhealthy) return 1 ;;
    esac
    sleep "$HEALTH_POLL_S"
    elapsed=$((elapsed + 1 + HEALTH_POLL_S))
  done
  return 1
}

rollback() {
  say "l'app non è in salute dopo ${HEALTH_WAIT_S} s: ultime righe del suo log"
  docker compose logs --tail 60 app || true
  if docker image inspect "$IMAGE:previous" >/dev/null 2>&1; then
    say "torno alla versione precedente"
    docker tag "$IMAGE:previous" "$IMAGE:latest"
    docker compose up -d --no-build app
    if wait_healthy; then
      say "versione precedente ripristinata"
    else
      say "ATTENZIONE: nemmeno la versione precedente è in salute"
    fi
  else
    say "nessuna versione precedente da ripristinare (è il primo deploy)"
  fi
  fail "deploy non riuscito"
}

main() {
  case "${1:-}" in
    "") ;;
    --dry-run) DRY_RUN=1 ;;
    *) fail "uso: deploy.sh [--dry-run]" ;;
  esac
  cd "$(dirname "$0")/.."
  if [ "$DRY_RUN" = 1 ]; then say "DRY RUN: nessun comando viene eseguito"; fi
  say "inizio, $(date '+%Y-%m-%d %H:%M:%S')"

  # 1. il codice
  run git fetch --quiet origin "$BRANCH"
  run git reset --hard "origin/$BRANCH"

  # 2. il .env
  if [ "$DRY_RUN" = 1 ]; then
    say "(dry-run) controllerei che il .env abbia: $REQUIRED_VARS (ENV=production)"
  else
    check_env
  fi

  # 3. i permessi di /data, senza sudo
  run docker run --rm -v "$DATA_HOST_DIR:/data" "$ALPINE_IMAGE" chown -R "$APP_UID:$APP_UID" /data

  # 4. la build: se fallisce si esce qui, la versione in esecuzione non è toccata
  keep_previous
  run docker compose build app ||
    fail "build non riuscita: la versione in esecuzione non è stata toccata"

  # 5. l'avvio, e il ritorno alla versione precedente se l'app non sta in salute
  run docker compose up -d || fail "docker compose up non riuscito"
  wait_healthy || rollback

  # 6. le immagini orfane
  run docker image prune -f

  if [ "$DRY_RUN" = 1 ]; then
    say "(dry-run) finito senza eseguire nulla"
  else
    say "fatto: commit $(git rev-parse --short HEAD), $(date '+%Y-%m-%d %H:%M:%S')"
    say "stato dei dati: https://$(env_value DOMAIN)/api/health (ok = pronto; degraded = dati in preparazione)"
  fi
}

# Tutto lo script è già letto prima di eseguire `main`, e `exit` chiude: `git reset` può riscrivere
# questo stesso file mentre gira senza che la shell ne legga un pezzo a metà.
main "$@"; exit $?
