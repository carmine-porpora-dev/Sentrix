# Risposte TomTom Flow Segment Data (reali)

Corpi grezzi delle 3 richieste della sonda di F0-08 (2026-11-07T16:27:53+01:00), uno per file: `flow_<id>.json`.
Endpoint: `https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json`. La chiave non è nei file (la sonda non la salva).

Conservarle qui è stato consentito dal proprietario il 9/11/2026 (Q2 di `spech.md`, opzione A). Non
modificarle a mano: servono a provare che il parser regge risposte vere. I casi anomali (strada
chiusa, confidenza bassa, campi mancanti) si costruiscono nei test a partire da questi corpi.
