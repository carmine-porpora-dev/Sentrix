import { readFileSync } from "node:fs";
import { readMapTokens, type MapTokens, type TokenReader } from "@/features/map/tokens";
import { repoPath } from "@/test/fixtures";

const CSS = readFileSync(repoPath("frontend", "src", "styles", "tokens.generated.css"), "utf8");

/** Le variabili CSS generate dai token (`--nome: valore;`), come le leggerebbe il browser. */
export const GENERATED: ReadonlyMap<string, string> = new Map(
  Array.from(CSS.matchAll(/^\s*(--[\w-]+):\s*([^;]+);/gm), (m) => [
    m[1] as string,
    (m[2] as string).trim(),
  ]),
);

export const generatedReader: TokenReader = (name) => GENERATED.get(name) ?? "";

/** I token della mappa con i valori veri del design. */
export const mapTokens = (): MapTokens => readMapTokens(generatedReader);
