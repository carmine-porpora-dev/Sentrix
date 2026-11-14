import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "../..");
const PORT = process.env.E2E_BACKEND_PORT ?? "8010";

/** I dati che `make data` produce e il backend legge; senza, la prova non ha senso. */
const NEEDED = ["data/osm/graph_drive.graphml", "data/gtfs/anm", "data/tiles/napoli.pmtiles"];
const missing = NEEDED.filter((item) => !existsSync(path.join(ROOT, item)));
if (missing.length > 0) {
  console.error(`Mancano i dati: ${missing.join(", ")}. Si creano con \`make data\`.`);
  process.exit(1);
}

// Una cartella dati propria: i dati grandi (di sola lettura) sono collegamenti, il database nasce qui.
const dataDir = mkdtempSync(path.join(tmpdir(), "nuo-e2e-"));
for (const name of ["osm", "gtfs", "tiles"]) {
  symlinkSync(path.join(ROOT, "data", name), path.join(dataDir, name));
}

// LIVE senza TomTom (nessuna chiave, nessuna rete): l'ultimo dato noto sta nello snapshot su disco
// (08 5). Si prepara con i tratti delle fixture (scritte dal backend con i suoi stessi modelli),
// più vecchi di 5 minuti: LIVE li mostra come «ultimo dato disponibile», con il perché.
const snapshotSource = path.join(ROOT, "frontend/src/api/fixtures/live_flow_snapshot.json");
if (existsSync(snapshotSource)) {
  const { segments } = JSON.parse(readFileSync(snapshotSource, "utf8")) as { segments: unknown[] };
  mkdirSync(path.join(dataDir, "tomtom"));
  writeFileSync(path.join(dataDir, "tomtom", "snapshot.json"), JSON.stringify({ segments }));
}

const child = spawn(
  "uv",
  ["run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT],
  {
    cwd: path.join(ROOT, "backend"),
    stdio: "inherit",
    env: {
      ...process.env,
      ENV: "local",
      DATA_DIR: dataDir,
      LLM_MODE: "cache_only",
      // Vuote, non assenti: un valore vuoto vince sul `.env` del proprietario (che non si sovrascrive).
      GEMINI_API_KEY: "",
      TOMTOM_API_KEY: "",
      // Nessun messaggio vero: ogni run finito ne manderebbe uno al numero del `.env` (spech 12.4).
      WHATSAPP_MODE: "off",
      LIVE_SNAPSHOT_PERSIST: "true",
      APP_PASSWORD: process.env.E2E_PASSWORD ?? "",
      SESSION_SECRET: process.env.E2E_SESSION_SECRET ?? "",
    },
  },
);

let closing = false;
function close(code: number): void {
  if (closing) return;
  closing = true;
  // si toglie la cartella temporanea: contiene solo collegamenti e il database di questa prova
  rmSync(dataDir, { recursive: true, force: true });
  process.exit(code);
}
child.on("exit", (code) => close(code ?? 1));
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    child.kill("SIGTERM");
    setTimeout(() => close(0), 3000).unref();
  });
}
