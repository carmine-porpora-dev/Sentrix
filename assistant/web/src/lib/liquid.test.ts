import { describe, expect, it } from "vitest";
import { hexToRgb, readPalette } from "@/lib/liquid";

function style(values: Record<string, string>): CSSStyleDeclaration {
  return { getPropertyValue: (name: string) => values[name] ?? "" } as CSSStyleDeclaration;
}

const TOKENS = {
  "--color-accent": "#5B7CFA",
  "--color-accent-hover": " #7994FB",
  "--color-text": "#F2EDE6",
  "--color-liquid-highlight": "#a9bbff",
  "--color-bg": "#121110",
};

describe("hexToRgb", () => {
  it("converte un esadecimale in componenti", () => {
    expect(hexToRgb("#5B7CFA")).toBe("91,124,250");
    expect(hexToRgb(" #121110 ")).toBe("18,17,16");
  });

  it.each(["", "5B7CFA", "#5B7", "rgba(1,2,3,.4)", "#GGGGGG"])("rifiuta «%s»", (value) => {
    expect(hexToRgb(value)).toBeNull();
  });
});

describe("readPalette", () => {
  it("legge i colori dai token", () => {
    expect(readPalette(style(TOKENS))).toEqual({
      accent: "91,124,250",
      accentHover: "121,148,251",
      text: "242,237,230",
      highlight: "169,187,255",
      bg: "18,17,16",
    });
  });

  it("senza un token non disegna", () => {
    const { "--color-bg": _removed, ...rest } = TOKENS;
    void _removed;
    expect(readPalette(style(rest))).toBeNull();
  });
});
