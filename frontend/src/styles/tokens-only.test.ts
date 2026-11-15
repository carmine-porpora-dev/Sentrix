import { describe, expect, it } from "vitest";
import { offences, sources, stripComments } from "../test/sources.ts";

// F4-REF: i colori (e le ombre) vengono solo dai token del designer. Il test legge i sorgenti dell'interfaccia,
// non i test né i file generati, e fallisce se trova un colore scritto a mano o una classe che non è un token.
// Il CSS compilato lo controlla `build.test.ts`: questo trova il difetto dove lo si scrive.

const PALETTE =
  "white|black|slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const COLOR_UTILITIES =
  "bg|text|border|ring|ring-offset|fill|stroke|from|to|via|outline|divide|accent|caret|decoration|placeholder|shadow";

describe("i colori vengono solo dai token (F4-REF)", () => {
  it("il test legge i sorgenti (non passa per una cartella sbagliata)", () => {
    const files = sources().map((source) => source.file);
    expect(files.length).toBeGreaterThan(60);
    expect(files).toContain("index.css");
    expect(files).toContain("components/MeasuredValue.tsx");
    expect(files.some((file) => file.endsWith(".test.tsx"))).toBe(false);
    expect(files.some((file) => file.includes(".generated."))).toBe(false);
  });

  it("nessun colore scritto a mano: né esadecimale né rgb(), hsl(), oklch()", () => {
    expect(offences(/#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(/)).toEqual([]);
  });

  it("nessun colore con il nome (white, red…) come valore di colore, sfondo, riempimento o tratto", () => {
    const named = "white|black|red|green|blue|yellow|orange|purple|pink|gray|grey|cyan|magenta";
    expect(
      offences(
        new RegExp(
          `\\b(?:color|background(?:-color)?|fill|stroke|border(?:-color)?|line-color|fill-color|text-color)["']?\\s*:\\s*["'\`](?:${named})["'\`]`,
          "i",
        ),
      ),
    ).toEqual([]);
  });

  it("nessuna classe della palette di Tailwind (bg-white, text-red-500…)", () => {
    const palette = new RegExp(
      `(?<![\\w-])(?:${COLOR_UTILITIES})-(?:${PALETTE})(?:-\\d{2,3})?(?![\\w-])`,
    );
    expect(offences(palette)).toEqual([]);
  });

  it("nessun colore arbitrario in una classe (bg-[#fff], text-[rgb(…)])", () => {
    expect(
      offences(new RegExp(`(?<![\\w-])(?:${COLOR_UTILITIES})-\\[(?:#|rgb|hsl|oklch|color:)`, "i")),
    ).toEqual([]);
  });

  it("nessuna ombra né anello di Tailwind: il design non li ha (le ombre di Tailwind sono nere)", () => {
    expect(offences(/(?<![\w-])(?:drop-)?shadow-(?:sm|md|lg|xl|2xl|inner|none)(?![\w-])/)).toEqual(
      [],
    );
    expect(offences(/(?<![\w-])(?:ring(?:-offset)?-\d+|ring-inset|inset-ring)(?![\w-])/)).toEqual(
      [],
    );
  });

  it("gli stili in linea non portano colori: solo misure e variabili (--swatch)", () => {
    const inline = [
      ...sources().flatMap(({ file, code }) =>
        [...code.matchAll(/style=\{\{([^}]*)\}\}/g)].map((match) => ({
          where: file,
          style: match[1] ?? "",
        })),
      ),
    ];
    expect(inline.length).toBeGreaterThan(0); // la ricerca trova gli stili in linea
    const colored = inline.filter(({ style }) =>
      /(?:^|[\s,])["']?(?:color|background|backgroundColor|borderColor|fill|stroke|outlineColor|boxShadow)["']?\s*:/.test(
        style,
      ),
    );
    expect(colored.map(({ where, style }) => `${where}: ${style.trim()}`)).toEqual([]);
  });

  it("il rilevatore vede i casi che deve vedere (prova delle regole)", () => {
    const hit = (pattern: RegExp, text: string) => pattern.test(text);
    expect(hit(/#[0-9a-fA-F]{3,8}\b/, 'className="bg-[#fff]"')).toBe(true);
    expect(
      hit(
        new RegExp(`(?<![\\w-])(?:${COLOR_UTILITIES})-(?:${PALETTE})(?:-\\d{2,3})?(?![\\w-])`),
        '"flex bg-white text-red-500"',
      ),
    ).toBe(true);
    expect(
      hit(
        new RegExp(`(?<![\\w-])(?:${COLOR_UTILITIES})-(?:${PALETTE})(?:-\\d{2,3})?(?![\\w-])`),
        '"bg-surface-1 text-data-real border-status-rejected text-text-primary"',
      ),
    ).toBe(false);
    expect(stripComments("a // #fff\nb https://x.it/#abc")).toBe("a \nb https://x.it/#abc");
  });
});
