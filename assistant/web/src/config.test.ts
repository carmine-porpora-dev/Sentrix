import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import viteConfig from "../vite.config.ts";

const root = (file: string) => join(import.meta.dirname, "..", file);

describe("pagina e percorso di pubblicazione", () => {
  it("l'interfaccia vive sotto /assistente/, come la serve Caddy", () => {
    expect(viteConfig.base).toBe("/assistente/");
  });

  it("la pagina è in italiano, a tutta altezza e scura", () => {
    const html = readFileSync(root("index.html"), "utf-8");
    expect(html).toContain('<html lang="it">');
    expect(html).toContain("viewport-fit=cover");
    expect(html).toContain('name="color-scheme" content="dark"');
  });
});
