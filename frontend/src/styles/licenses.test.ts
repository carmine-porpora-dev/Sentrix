import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(import.meta.dirname, "../..");
const doc = readFileSync(path.resolve(ROOT, "../docs/LICENSES.md"), "utf8");
const pkg = JSON.parse(readFileSync(path.join(ROOT, "package.json"), "utf8")) as {
  dependencies: Record<string, string>;
};

/** La riga di tabella `| nome | versione | licenza |` di un pacchetto nella pagina delle licenze. */
function row(name: string): string[] | undefined {
  const line = doc.split("\n").find((l) => l.startsWith(`| ${name} |`));
  return line
    ?.split("|")
    .slice(1, -1)
    .map((cell) => cell.trim());
}

describe("docs/LICENSES.md: dipendenze del frontend (F4-08)", () => {
  for (const name of Object.keys(pkg.dependencies)) {
    it(`${name}: versione e licenza sono quelle installate`, () => {
      const installed = JSON.parse(
        readFileSync(path.join(ROOT, "node_modules", name, "package.json"), "utf8"),
      ) as { version: string; license: string };
      expect(row(name), `manca la riga di ${name}`).toEqual([
        name,
        installed.version,
        installed.license,
      ]);
    });
  }

  it("la pagina non elenca pacchetti che non sono dipendenze dirette", () => {
    const section =
      doc.split("## Frontend: dipendenze dirette di produzione")[1]?.split("## Backend")[0] ?? "";
    const listed = section
      .split("\n")
      .filter((l) => l.startsWith("| ") && !l.startsWith("| Pacchetto") && !l.startsWith("| ---"))
      .map((l) => l.split("|")[1]?.trim());
    expect(listed.sort()).toEqual(Object.keys(pkg.dependencies).sort());
  });

  it("i font hanno la loro licenza e il testo è servito dall'app", () => {
    expect(doc).toContain("Plus Jakarta Sans");
    expect(doc).toContain("Geist Mono");
    expect(doc).toContain("SIL Open Font License 1.1");
    expect(doc).toContain("/licenses/OFL.txt");
  });
});
