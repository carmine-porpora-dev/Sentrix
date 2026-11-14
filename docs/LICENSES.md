# Licenze

Che cosa usa Sentrix e a quali condizioni. Scritto a F4-08 per font, software e dati noti; **F9-05 lo completa** (verifiche aperte in fondo). Un test per parte (`frontend/src/styles/licenses.test.ts` e `backend/tests/unit/test_licenses_doc.py`) fa fallire la suite se una dipendenza diretta cambia versione o licenza senza che questa pagina cambi.

## Font (serviti da noi, nessuna richiesta esterna)
| Font | Pesi | Licenza | Copyright |
| --- | --- | --- | --- |
| Plus Jakarta Sans | 400, 500, 600, 700 | SIL Open Font License 1.1 | Copyright 2020 The Plus Jakarta Sans Project Authors (https://github.com/tokotype/PlusJakartaSans) |
| Geist Mono | 500, 600, 700 | SIL Open Font License 1.1 | Copyright 2024 The Geist Project Authors (https://github.com/vercel/geist-font.git) |

I file sono quelli di `design/design-system/fonts/` (sottoinsieme latino, woff2), copiati in `frontend/src/assets/fonts/`; un test li confronta byte per byte con quelli del designer. L'OFL chiede che ogni copia riporti i copyright e il testo della licenza: il testo è in `frontend/public/licenses/OFL.txt` (servito come `/licenses/OFL.txt`) e i copyright sono anche nei metadati dei file. Non vengono venduti da soli e non sono modificati.

## Frontend: dipendenze dirette di produzione
| Pacchetto | Versione | Licenza |
| --- | --- | --- |
| @protomaps/basemaps | 5.7.2 | BSD-3-Clause |
| @tanstack/react-query | 5.107.1 | MIT |
| class-variance-authority | 0.7.1 | Apache-2.0 |
| clsx | 2.1.1 | MIT |
| lucide-react | 1.70.0 | ISC |
| maplibre-gl | 5.24.0 | BSD-3-Clause |
| pmtiles | 4.5.0 | BSD-3-Clause |
| react | 18.3.1 | MIT |
| react-dom | 18.3.1 | MIT |
| react-map-gl | 8.1.3 | MIT |
| tailwind-merge | 3.7.0 | MIT |
| tailwindcss-animate | 1.0.7 | MIT |

Le icone sono di Lucide (ISC); alcune derivano da Feather (MIT, Cole Bemis), come dice la licenza del pacchetto. Le dipendenze di sviluppo (Vite, Vitest, ESLint, Playwright, Tailwind…) non finiscono nel pacchetto distribuito. Le dipendenze indirette sono quelle di `frontend/package-lock.json`.

## Backend: dipendenze dirette
| Pacchetto | Versione | Licenza |
| --- | --- | --- |
| fastapi | 0.162.1 | MIT |
| google-genai | 3.1.0 | Apache-2.0 |
| httpx2 | 2.16.0 | BSD-3-Clause |
| networkx | 3.7 | BSD-3-Clause |
| osmnx | 2.1.1 | MIT |
| pandas | 3.1.1 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| pyyaml | 6.0.3 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |

`google-genai` (Gemini Flash dentro il prodotto) non è ancora tra le dipendenze: si aggiunge con gli agenti (F6) e va aggiunta qui. Le indirette sono quelle di `backend/uv.lock`.

## Dati
| Fonte | Licenza o termini (come registrati accanto ai file in `data/`) | Obblighi |
| --- | --- | --- |
| OpenStreetMap (rete stradale, base map) | ODbL 1.0 | «© OpenStreetMap contributors» sempre visibile (`MapAttribution`) |
| Base map PMTiles (build Protomaps) | Dati OSM sotto ODbL 1.0; **licenza della build da verificare** | «Protomaps» nell'attribuzione |
| GTFS ANM (orari del trasporto pubblico) | **Da verificare sul feed** (Transitland indica IODL 2.0, `spech.md` 6.5) | — |
| TomTom Traffic Flow (solo LIVE) | Termini d'uso TomTom; **conservazione dei dati su disco: da definire** (Q2, `spech.md` 9) | La chiave sta solo in `.env` |

## Grafica
Token, componenti di riferimento, schermate e icone della cartella `design/` sono la consegna del designer per questo progetto.

## Aperto (per F9-05)
- Licenza del feed GTFS ANM e della build Protomaps: da verificare (proprietario).
- Termini TomTom sulla conservazione dello snapshot (Q2): verifica del proprietario.
- Aggiungere `google-genai` e i suoi termini d'uso quando entra.
