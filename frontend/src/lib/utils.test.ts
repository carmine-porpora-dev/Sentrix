import { describe, expect, it } from "vitest";
import { cn } from "@/lib/utils";

describe("cn", () => {
  it("unisce le classi ignorando i valori falsy", () => {
    expect(cn("p-2", false, undefined, null, "text-sm")).toBe("p-2 text-sm");
  });

  it("risolve i conflitti Tailwind: vince l'ultima classe", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });
});

describe("cn con i token del designer", () => {
  it("un corpo del testo non cancella il colore del testo", () => {
    expect(cn("text-text-primary", "text-kpi")).toBe("text-text-primary text-kpi");
    expect(cn("text-kpi-sm", "text-badge", "text-danger")).toBe("text-badge text-danger");
  });

  it("due corpi del testo sono in conflitto: vince l'ultimo", () => {
    expect(cn("text-xs", "text-xl")).toBe("text-xl");
    expect(cn("text-kpi", "text-md")).toBe("text-md");
  });

  it("due colori del testo sono in conflitto: vince l'ultimo", () => {
    expect(cn("text-text-primary", "text-text-secondary")).toBe("text-text-secondary");
  });

  it("lo spessore del bordo non cancella il colore del bordo (e viceversa)", () => {
    expect(cn("border-hairline", "border-border-strong")).toBe(
      "border-hairline border-border-strong",
    );
    expect(cn("border-control", "border-hairline")).toBe("border-hairline");
    expect(cn("border-border", "border-data-real")).toBe("border-data-real");
  });

  it("gli angoli dei token sono in conflitto tra loro", () => {
    expect(cn("rounded-card", "rounded-control")).toBe("rounded-control");
    expect(cn("rounded-card", "p-space-16")).toBe("rounded-card p-space-16");
  });
});
