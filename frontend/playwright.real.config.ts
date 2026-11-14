import { randomBytes } from "node:crypto";
import { defineConfig, devices } from "@playwright/test";

// F7-TEST: gli e2e contro il backend vero (`LLM_MODE=cache_only`, dati veri, motori veri), per i
// due eventi precaricati. L'interfaccia è il server di sviluppo in modalità `http`, che parla con
// il backend dei test (porta propria) tramite il proxy di Vite. Nessun servizio esterno è chiamato.
// Si lancia solo ai cancelli `-TEST`: `npm run e2e:real`.
const FRONT = 5197;
const BACK = 8010;

// Password e chiave della sessione: casuali a ogni lancio, mai scritte da nessuna parte. Si impostano
// qui, nel processo principale, prima che nascano i lavoratori: così le leggono anche i test.
process.env.E2E_PASSWORD ??= randomBytes(12).toString("hex");
process.env.E2E_SESSION_SECRET ??= randomBytes(24).toString("hex");
process.env.E2E_BACKEND_PORT = String(BACK);

// Le due risoluzioni di verifica (07 9).
const SCREENS = [
  { name: "1920x1080", viewport: { width: 1920, height: 1080 } },
  { name: "1366x768", viewport: { width: 1366, height: 768 } },
];

export default defineConfig({
  testDir: "e2e-real",
  testMatch: "*.spec.ts",
  // Un run vero dura una o due decine di secondi (i motori); i test che lo seguono hanno margine.
  timeout: 240_000,
  expect: { timeout: 15_000 },
  // Uno alla volta: i motori usano più processi e due run insieme falserebbero i tempi. Niente
  // ripetizioni: un test che passa al secondo giro nasconde un'instabilità (e POST /api/runs ha un
  // tetto di 20 all'ora per tutto il backend, 06 5).
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report-real" }]],
  outputDir: "test-results-real",
  use: {
    baseURL: `http://127.0.0.1:${FRONT}`,
    trace: "retain-on-failure",
    launchOptions: {
      // La mappa è WebGL: in headless senza GPU lo fornisce SwiftShader (software).
      args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
  projects: SCREENS.map(({ name, viewport }) => ({
    name,
    use: { ...devices["Desktop Chrome"], viewport },
  })),
  webServer: [
    {
      command: "npx tsx e2e-real/backend.ts",
      url: `http://127.0.0.1:${BACK}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 8_000 },
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `npm run dev -- --port ${FRONT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${FRONT}`,
      reuseExistingServer: false,
      env: { VITE_API_MODE: "http", API_ORIGIN: `http://127.0.0.1:${BACK}` },
    },
  ],
});
