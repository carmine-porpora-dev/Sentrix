CREATE TABLE IF NOT EXISTS events (
    id          TEXT    NOT NULL PRIMARY KEY,
    name        TEXT    NOT NULL,
    json        TEXT    NOT NULL,                              -- Evento intero, validato
    revision    INTEGER NOT NULL CHECK (revision >= 1),
    is_seed     INTEGER NOT NULL CHECK (is_seed IN (0, 1)),
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
) STRICT;

-- Revisioni SUPERATE di un evento (non in 01 4: aggiunta su decisione del proprietario). Quando un
-- evento si modifica, il JSON della revisione che viene sostituita passa qui; la revisione in corso
-- sta solo in `events.json` (un dato vive in un solo posto). Un run registra `event_revision`: così
-- l'export (06 5) ritrova l'evento com'era quando il run è partito. Append-only, come le decisioni.
CREATE TABLE IF NOT EXISTS event_revisions (
    event_id       TEXT    NOT NULL REFERENCES events (id),
    revision       INTEGER NOT NULL CHECK (revision >= 1),
    json           TEXT    NOT NULL,                           -- Evento intero, com'era in quella revisione
    superseded_at  TEXT    NOT NULL,                           -- quando è stata sostituita
    PRIMARY KEY (event_id, revision)
) STRICT;

CREATE TRIGGER IF NOT EXISTS event_revisions_no_update BEFORE UPDATE ON event_revisions
BEGIN
    SELECT RAISE(ABORT, 'event_revisions è append-only: UPDATE vietato');
END;

CREATE TRIGGER IF NOT EXISTS event_revisions_no_delete BEFORE DELETE ON event_revisions
BEGIN
    SELECT RAISE(ABORT, 'event_revisions è append-only: DELETE vietato');
END;

-- Come per `decisions`: senza questo, INSERT OR REPLACE riscriverebbe una revisione in silenzio.
CREATE TRIGGER IF NOT EXISTS event_revisions_no_replace BEFORE INSERT ON event_revisions
WHEN EXISTS (SELECT 1 FROM event_revisions WHERE event_id = NEW.event_id AND revision = NEW.revision)
BEGIN
    SELECT RAISE(ABORT, 'event_revisions è append-only: la revisione esiste già, non si sostituisce');
END;

CREATE TABLE IF NOT EXISTS runs (
    id               TEXT    NOT NULL PRIMARY KEY,
    event_id         TEXT    NOT NULL REFERENCES events (id),
    event_revision   INTEGER NOT NULL,
    attendance_level TEXT    NOT NULL,
    state            TEXT    NOT NULL,
    iteration        INTEGER NOT NULL,
    replans          INTEGER NOT NULL,
    params_hash      TEXT    NOT NULL,
    seed             INTEGER NOT NULL,
    llm_mode         TEXT    NOT NULL,
    error            TEXT,
    started_at       TEXT    NOT NULL,
    ended_at         TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS agent_results (
    id           INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL REFERENCES runs (id),
    agent        TEXT    NOT NULL,
    iteration    INTEGER NOT NULL,
    input_hash   TEXT    NOT NULL,
    json         TEXT    NOT NULL,                             -- AgentResult intero
    duration_ms  INTEGER NOT NULL,
    validation   TEXT    NOT NULL
) STRICT;

-- Elementi del piano (non in 01 4: aggiunta su decisione del proprietario). `GET /api/runs/{id}`
-- restituisce il piano (06 5) e `PlanItem` ha stati (scartato, decisione umana richiesta) che non
-- derivano da altre tabelle. `seq` è unico nel run. Lo stato vive solo nel JSON.
CREATE TABLE IF NOT EXISTS plan_items (
    run_id  TEXT    NOT NULL REFERENCES runs (id),
    seq     INTEGER NOT NULL,
    json    TEXT    NOT NULL,                                  -- PlanItem intero
    PRIMARY KEY (run_id, seq)
) STRICT;

CREATE TABLE IF NOT EXISTS metrics (
    run_id     TEXT    NOT NULL REFERENCES runs (id),
    iteration  INTEGER NOT NULL,
    metric_id  TEXT    NOT NULL,
    json       TEXT    NOT NULL,                               -- Measured
    PRIMARY KEY (run_id, iteration, metric_id)
) STRICT;

CREATE TABLE IF NOT EXISTS layers (
    run_id     TEXT    NOT NULL REFERENCES runs (id),
    iteration  INTEGER NOT NULL,
    layer      TEXT    NOT NULL,
    geojson    TEXT    NOT NULL,                               -- generato in VERIFY
    PRIMARY KEY (run_id, iteration, layer)
) STRICT;

CREATE TABLE IF NOT EXISTS operation_requests (
    action_id   TEXT    NOT NULL PRIMARY KEY,
    run_id      TEXT    NOT NULL REFERENCES runs (id),
    iteration   INTEGER NOT NULL,
    department  TEXT    NOT NULL,
    type        TEXT    NOT NULL,
    state       TEXT    NOT NULL,
    json        TEXT    NOT NULL,                              -- OperationRequest intera
    -- Principio 3 (azioni solo simulate): senza default, e solo il valore 1 è ammesso.
    simulation  INTEGER NOT NULL CHECK (simulation = 1)
) STRICT;

CREATE TABLE IF NOT EXISTS operation_events (
    id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    action_id   TEXT    NOT NULL REFERENCES operation_requests (action_id),
    from_state  TEXT,                                          -- NULL alla creazione
    to_state    TEXT    NOT NULL,
    reason      TEXT,
    at          TEXT    NOT NULL                               -- una riga per transizione
) STRICT;

CREATE TABLE IF NOT EXISTS decisions (
    run_id      TEXT    NOT NULL REFERENCES runs (id),
    seq         INTEGER NOT NULL,
    at          TEXT    NOT NULL,
    actor       TEXT    NOT NULL,
    decision    TEXT    NOT NULL,
    rationale   TEXT    NOT NULL,
    refs_json   TEXT    NOT NULL,                              -- elenco JSON di id Measured, action_id, stati
    PRIMARY KEY (run_id, seq)
) STRICT;

-- Log decisioni append-only: nessuna voce si modifica o si toglie.
CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decisions è append-only: UPDATE vietato');
END;

CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decisions è append-only: DELETE vietato');
END;

-- Terzo trigger, oltre ai due della spec: `INSERT OR REPLACE` / `REPLACE INTO` su una voce già
-- presente la sostituirebbe SENZA far scattare il trigger di DELETE (verificato su SQLite 3.53).
CREATE TRIGGER IF NOT EXISTS decisions_no_replace BEFORE INSERT ON decisions
WHEN EXISTS (SELECT 1 FROM decisions WHERE run_id = NEW.run_id AND seq = NEW.seq)
BEGIN
    SELECT RAISE(ABORT, 'decisions è append-only: la voce esiste già, non si sostituisce');
END;

CREATE TABLE IF NOT EXISTS llm_cache (
    key            TEXT NOT NULL PRIMARY KEY,                  -- sha256(modello + prompt + schema + input)
    response_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS live_cache (
    segment_id  TEXT NOT NULL PRIMARY KEY,
    json        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
) STRICT;

-- Chiamate LLM fatte in un giorno (Europe/Rome): il tetto applicativo `LLM_DAILY_CALL_LIMIT` (05 1).
-- Tabella aggiunta in F6-01 (non in 01 4): senza, un riavvio azzererebbe il conteggio.
CREATE TABLE IF NOT EXISTS llm_usage (
    day    TEXT    NOT NULL PRIMARY KEY,                       -- AAAA-MM-GG
    calls  INTEGER NOT NULL CHECK (calls >= 0)
) STRICT;

-- Notifiche in uscita (spech.md 12.2), append-only come `decisions`: ogni esito è una riga nuova.
-- `simulation = 1` solo per il bollettino ai servizi di emergenza (12.3); WhatsApp (12.4) è reale.
-- Il testo del messaggio è conservato; il numero di telefono mai in chiaro (`recipient_label` è
-- mascherato). Un solo messaggio WhatsApp per run: lo garantisce l'indice unico parziale.
CREATE TABLE IF NOT EXISTS notifications (
    id                   INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT    REFERENCES runs (id),
    iteration            INTEGER NOT NULL,
    channel              TEXT    NOT NULL,
    recipient_id         TEXT    NOT NULL,
    recipient_label      TEXT,
    kind                 TEXT    NOT NULL,
    text                 TEXT    NOT NULL,
    evidence_ids_json    TEXT    NOT NULL,                     -- elenco JSON di action_id
    state                TEXT    NOT NULL,
    provider_message_id  TEXT,
    error_code           TEXT,
    simulation           INTEGER NOT NULL CHECK (simulation IN (0, 1)),
    created_at           TEXT    NOT NULL,
    CHECK (channel <> 'emergency_bulletin' OR simulation = 1)
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS notifications_one_whatsapp_per_run
    ON notifications (run_id) WHERE channel = 'whatsapp';

CREATE TRIGGER IF NOT EXISTS notifications_no_update BEFORE UPDATE ON notifications
BEGIN
    SELECT RAISE(ABORT, 'notifications è append-only: UPDATE vietato');
END;

CREATE TRIGGER IF NOT EXISTS notifications_no_delete BEFORE DELETE ON notifications
BEGIN
    SELECT RAISE(ABORT, 'notifications è append-only: DELETE vietato');
END;

-- Come per `decisions`: INSERT OR REPLACE sull'indice unico sostituirebbe la riga senza far
-- scattare il trigger di DELETE.
CREATE TRIGGER IF NOT EXISTS notifications_no_replace BEFORE INSERT ON notifications
WHEN NEW.run_id IS NOT NULL AND NEW.channel = 'whatsapp'
     AND EXISTS (SELECT 1 FROM notifications WHERE run_id = NEW.run_id AND channel = 'whatsapp')
BEGIN
    SELECT RAISE(ABORT, 'notifications è append-only: il messaggio WhatsApp di questo run esiste già');
END;

-- Il ciclo di vita del bollettino ai servizi di emergenza (spech 12.3): SENT → DELIVERED →
-- ACKNOWLEDGED. `notifications` è append-only e non si aggiorna: la riga porta lo stato alla
-- creazione e ogni passaggio successivo è una riga qui (come `operation_events` per le richieste).
-- Lo stato corrente è quello dell'ultimo evento, o quello della riga se non ce ne sono.
CREATE TABLE IF NOT EXISTS notification_events (
    id               INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    notification_id  INTEGER NOT NULL REFERENCES notifications (id),
    from_state       TEXT    NOT NULL,
    to_state         TEXT    NOT NULL,
    at               TEXT    NOT NULL
) STRICT;

CREATE TRIGGER IF NOT EXISTS notification_events_no_update BEFORE UPDATE ON notification_events
BEGIN
    SELECT RAISE(ABORT, 'notification_events è append-only: UPDATE vietato');
END;

CREATE TRIGGER IF NOT EXISTS notification_events_no_delete BEFORE DELETE ON notification_events
BEGIN
    SELECT RAISE(ABORT, 'notification_events è append-only: DELETE vietato');
END;

-- Un solo bollettino per destinatario e per run.
CREATE UNIQUE INDEX IF NOT EXISTS notifications_one_bulletin_per_recipient
    ON notifications (run_id, recipient_id) WHERE channel = 'emergency_bulletin';

CREATE TRIGGER IF NOT EXISTS notifications_no_replace_bulletin BEFORE INSERT ON notifications
WHEN NEW.run_id IS NOT NULL AND NEW.channel = 'emergency_bulletin'
     AND EXISTS (SELECT 1 FROM notifications
                 WHERE run_id = NEW.run_id AND channel = 'emergency_bulletin'
                   AND recipient_id = NEW.recipient_id)
BEGIN
    SELECT RAISE(ABORT, 'notifications è append-only: il bollettino di questo destinatario esiste già');
END;
