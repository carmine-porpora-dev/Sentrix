import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadText } from "@/lib/download";
import { formatClock } from "@/lib/format";

describe("downloadText", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("scarica un testo come file: un collegamento con il nome, cliccato e tolto, e l'URL rilasciato", () => {
    const create = vi.fn(() => "blob:finto");
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const clicked: { href: string; download: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({ href: this.href, download: this.download });
      expect(document.body.contains(this)).toBe(true); // nel documento mentre si clicca
    });
    downloadText("run.csv", "text/csv", "a,b");
    expect(create).toHaveBeenCalledTimes(1);
    const blob = (create.mock.calls[0] as unknown as [Blob])[0];
    expect(blob.type).toBe("text/csv");
    expect(blob.size).toBe(3);
    expect(clicked).toEqual([{ href: "blob:finto", download: "run.csv" }]);
    expect(revoke).toHaveBeenCalledWith("blob:finto");
    expect(document.querySelector("a[download]")).toBeNull(); // non resta nella pagina
  });
});

describe("formatClock", () => {
  it("l'ora di Roma, a 24 ore, con gli zeri", () => {
    expect(formatClock("2026-11-09T10:05:00+01:00")).toBe("10:05");
    expect(formatClock("2026-11-09T09:05:00+00:00")).toBe("10:05"); // novembre: UTC+1
    expect(formatClock("2026-07-09T08:05:00+00:00")).toBe("10:05"); // luglio: UTC+2
    expect(formatClock("2026-11-09T00:00:00+01:00")).toBe("00:00");
    expect(formatClock("2026-11-09T23:59:00+01:00")).toBe("23:59");
  });

  it("un testo che non è una data resta com'è", () => {
    expect(formatClock("boh")).toBe("boh");
  });
});
