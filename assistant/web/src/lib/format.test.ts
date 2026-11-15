import { describe, expect, it } from "vitest";
import { formatAsOf } from "@/lib/format";

describe("formatAsOf", () => {
  it("scrive data e ora all'italiana, nel fuso di Roma", () => {
    expect(formatAsOf("2026-09-26T13:30:00+02:00")).toBe("26/09/2026 13:30");
    expect(formatAsOf("2026-09-26T11:30:00Z")).toBe("26/09/2026 13:30");
  });

  it("un testo che non è una data resta com'è", () => {
    expect(formatAsOf("ieri sera")).toBe("ieri sera");
  });
});
