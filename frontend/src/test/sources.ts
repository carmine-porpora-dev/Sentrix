import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

const SRC = path.resolve(import.meta.dirname, "..");

export interface Source {
  file: string;
  /** Il testo senza i commenti (le righe restano al loro posto). */
  code: string;
}

// Toglie i commenti di riga e di blocco lasciando le righe al loro posto («https://…» non è un commento).
export function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, " "))
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
}

export function sources(): Source[] {
  const files = readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .map((entry) => entry.split(path.sep).join("/"))
    .filter((entry) => /\.(tsx?|css)$/.test(entry))
    .filter((entry) => !/\.test\.tsx?$/.test(entry))
    .filter((entry) => !/\.generated\./.test(entry))
    .filter((entry) => !entry.startsWith("test/") && !entry.startsWith("api/fixtures/"))
    .filter((entry) => entry !== "api/schema.d.ts");
  return files.map((file) => ({
    file,
    code: stripComments(readFileSync(path.join(SRC, file), "utf8")),
  }));
}

/** Le righe (con il numero) di ogni sorgente in cui `pattern` trova qualcosa. */
export function offences(pattern: RegExp): string[] {
  const found: string[] = [];
  for (const { file, code } of sources()) {
    code.split("\n").forEach((line, index) => {
      const match = line.match(pattern);
      if (match) found.push(`${file}:${index + 1}  «${match[0]}»`);
    });
  }
  return found;
}
