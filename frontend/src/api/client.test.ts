import { readFileSync } from "node:fs";
import openapiTS, { astToString } from "openapi-typescript";
import { describe, expect, it } from "vitest";
import { createApiClient, resolveApiMode } from "@/api/client";
import { SCHEMA_FILE, repoUrl } from "@/test/fixtures";

describe("resolveApiMode", () => {
  it.each([
    ["http", "http"],
    ["mock", "mock"],
    [" mock ", "mock"],
  ])("«%s» → %s", (value, mode) => {
    expect(resolveApiMode(value)).toBe(mode);
  });

  it("vuoto o assente = http: il mock non si attiva per sbaglio", () => {
    expect(resolveApiMode(undefined)).toBe("http");
    expect(resolveApiMode("")).toBe("http");
    expect(resolveApiMode("  ")).toBe("http");
  });

  it("un valore sconosciuto è un errore di configurazione, non un ripiego", () => {
    expect(() => resolveApiMode("Mock")).toThrow("VITE_API_MODE non valido: «Mock»");
    expect(() => resolveApiMode("prod")).toThrow(/http, mock/);
  });
});

describe("createApiClient", () => {
  it("sceglie l'implementazione dalla modalità", () => {
    expect(createApiClient({ mode: "mock" }).mode).toBe("mock");
    expect(createApiClient({ mode: "http" }).mode).toBe("http");
  });

  it("le due implementazioni hanno gli stessi metodi", () => {
    const keys = (mode: "http" | "mock") => Object.keys(createApiClient({ mode })).sort();
    expect(keys("mock")).toEqual(keys("http"));
  });

  it("la base map è la stessa in tutte e due", () => {
    expect(createApiClient({ mode: "mock" }).tilesUrl).toBe("/tiles/napoli.pmtiles");
    expect(createApiClient({ mode: "http" }).tilesUrl).toBe("/tiles/napoli.pmtiles");
  });
});

describe("tipi dell'API", () => {
  it("schema.d.ts è quello generato da docs/spec/openapi.json (npm run api:types)", async () => {
    const generated = astToString(await openapiTS(repoUrl("docs", "spec", "openapi.json")));
    const committed = readFileSync(SCHEMA_FILE, "utf8");
    const body = committed.slice(committed.indexOf("export interface paths"));
    expect(body === generated, "schema.d.ts è indietro: esegui `npm run api:types`").toBe(true);
  });
});
