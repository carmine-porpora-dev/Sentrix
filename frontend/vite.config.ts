import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// L'indirizzo del backend; solo i test e2e sul backend vero (F7-TEST) ne usano uno diverso.
const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  // Un solo .env alla radice del repository (vedi .env.example). Vite espone al client
  // solo le variabili con prefisso VITE_: gli altri segreti dello stesso file restano fuori dal bundle.
  envDir: "..",
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  // In sviluppo l'interfaccia (5173) parla con il backend (8000) come se fosse lo stesso sito:
  // il cookie di sessione e gli URL relativi del client `http` funzionano come in produzione.
  server: {
    proxy: {
      "/api": apiOrigin,
      "/tiles": apiOrigin,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
