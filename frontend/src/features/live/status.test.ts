import { describe, expect, it } from "vitest";
import type { LiveFlowResponse } from "@/api/types";
import { liveStatus } from "@/features/live/status";
import { fixture } from "@/test/fixtures";

const fresh = fixture<LiveFlowResponse>("live_flow_fresh.json");
const snapshot = fixture<LiveFlowResponse>("live_flow_snapshot.json");
const unavailable = fixture<LiveFlowResponse>("live_flow_unavailable.json");

const query = (
  data: LiveFlowResponse | undefined,
  flags: { pending?: boolean; error?: boolean },
) => ({
  data,
  isPending: flags.pending ?? false,
  isError: flags.error ?? false,
});

describe("liveStatus: lo stesso stato per fascia, pannello e chip", () => {
  it("mentre legge: in lettura", () => {
    expect(liveStatus(query(undefined, { pending: true }))).toBe("loading");
  });

  it("dati recenti: ok", () => {
    expect(liveStatus(query(fresh, {}))).toBe("ok");
  });

  it("l'ultimo dato noto (snapshot): parziali", () => {
    expect(liveStatus(query(snapshot, {}))).toBe("partial");
  });

  it("nessun tratto, o nessuna risposta: nessun dato", () => {
    expect(liveStatus(query(unavailable, {}))).toBe("none");
    expect(liveStatus(query(undefined, { error: true }))).toBe("none");
  });

  it("una lettura che fallisce dopo che i tratti c'erano: gli ultimi dati sono parziali, non ordinari", () => {
    expect(liveStatus(query(fresh, { error: true }))).toBe("partial");
  });
});
