import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { mockApi } from "./dev/mock-api.ts";

// L'indirizzo del servizio assistente; in produzione Caddy toglie il prefisso /assistente (10 §3).
const apiOrigin = process.env.ASSISTANT_ORIGIN ?? "http://127.0.0.1:8100";
// Solo `npm run dev:mock`: risposte di prova per vedere l'interfaccia senza il servizio (mai nel build).
const useMock = process.env.ASSISTANT_DEV_MOCK === "1";

export default defineConfig({
  base: "/assistente/",
  plugins: [react(), ...(useMock ? [mockApi()] : [])],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  server: {
    // token e font stanno in design/, alla radice del repository
    fs: { allow: [path.resolve(import.meta.dirname, "../..")] },
    proxy: useMock
      ? undefined
      : {
          "/assistente/api": {
            target: apiOrigin,
            rewrite: (requestPath) => requestPath.replace(/^\/assistente/, ""),
          },
        },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "dev/**/*.test.ts"],
  },
});
