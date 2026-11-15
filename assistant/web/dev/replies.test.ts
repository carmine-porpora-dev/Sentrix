import { describe, expect, it } from "vitest";
import { parseChatResponse } from "../src/api/chat.ts";
import { parseAnswer } from "../src/lib/answer.ts";
import { pickReply } from "./replies.ts";

describe("pickReply", () => {
  it.each([
    ["Devo andare in via Tasso alle 13:30", "10,2 min"],
    ["Da Centrale a Mergellina alle 16:45", "8,0 min"],
  ])("«%s» ha il percorso calcolato", (message, minutes) => {
    const reply = pickReply(message);
    expect(reply.text).toContain(minutes);
    expect(reply.sources.length).toBeGreaterThan(0);
    expect(reply.sources.every((source) => source.kind === "simulated")).toBe(true);
  });

  it("per il resto dice che non ha l'informazione, senza numeri né fonti", () => {
    const reply = pickReply("Che tempo fa?");
    expect(reply.text).toBe("Non ho questa informazione.");
    expect(reply.sources).toEqual([]);
  });

  it("le risposte rispettano il contratto dell'API e il formato dei testi", () => {
    for (const message of ["via Tasso", "Mergellina", "altro"]) {
      const reply = pickReply(message);
      expect(parseChatResponse(reply)).toEqual(reply);
      expect(parseAnswer(reply.text).length).toBeGreaterThan(0);
    }
  });
});
