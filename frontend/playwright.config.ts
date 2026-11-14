import { defineConfig, devices } from "@playwright/test";

// I test e2e girano contro il client `mock` (VITE_API_MODE=mock): nessun backend, nessuna rete, la
// stessa sequenza del run di F1-09 (un fotogramma a ogni lettura, un rifiuto, una ripianificazione).
// Il server di sviluppo è dedicato (porta propria, mai riusato): uno già acceso in modalità `http`
// farebbe girare i test contro un altro backend. Si lanciano solo ai cancelli `-TEST`.
const PORT = 5199;

// Le due risoluzioni di verifica (07 9): lo schermo della demo e quello di un portatile.
const SCREENS = [
  { name: "1920x1080", viewport: { width: 1920, height: 1080 } },
  { name: "1366x768", viewport: { width: 1366, height: 768 } },
];

export default defineConfig({
  testDir: "e2e",
  // Il run del mock dura ~15 s (un fotogramma al secondo): i test che lo seguono hanno il loro margine.
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
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
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    env: { VITE_API_MODE: "mock" },
  },
});
