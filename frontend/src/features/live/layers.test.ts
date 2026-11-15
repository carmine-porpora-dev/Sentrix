import { describe, expect, it } from "vitest";
import type { LiveFlowResponse } from "@/api/types";
import { liveEdges, liveMeasures, segmentOfSpeed, summaryValue } from "@/features/live/layers";
import { fixture } from "@/test/fixtures";

const fresh = () => fixture<LiveFlowResponse>("live_flow_fresh.json");

describe("liveEdges: i tratti come livello di congestione", () => {
  it("un tratto per feature, con la classe dell'API (non ricalcolata) e il nome", () => {
    const flow = fresh();
    const edges = liveEdges(flow);
    expect(edges?.features).toHaveLength(14);
    flow.segments.forEach((segment, index) => {
      const feature = edges?.features[index];
      expect(feature?.id).toBe(segment.id);
      expect(feature?.geometry).toEqual(segment.geometry);
      expect(feature?.properties).toMatchObject({
        edge_key: segment.id,
        name: segment.label,
        vc_class: segment.congestion_class,
        closed: false,
        detour: false,
        live: true,
        speed_id: segment.current_speed.id,
        free_flow_id: segment.free_flow_speed.id,
        ratio_id: segment.ratio.id,
      });
    });
  });

  it("senza `window`: i tratti si vedono con qualunque finestra", () => {
    for (const feature of liveEdges(fresh())?.features ?? []) {
      expect(feature.properties).not.toHaveProperty("window");
    }
  });

  it("senza tratti (nessun dato) non c'è un livello", () => {
    expect(liveEdges(undefined)).toBeUndefined();
    expect(liveEdges({ ...fresh(), segments: [] })).toBeUndefined();
    expect(liveEdges(fixture<LiveFlowResponse>("live_flow_unavailable.json"))).toBeUndefined();
  });
});

describe("liveMeasures e il riepilogo", () => {
  it("ogni misura dei tratti e del riepilogo per id", () => {
    const flow = fresh();
    const found = liveMeasures(flow);
    expect(found.size).toBe(14 * 3 + 5);
    expect(found.get(flow.segments[0]?.ratio.id ?? "")).toBe(flow.segments[0]?.ratio);
    expect(found.get(flow.summary?.[0]?.id ?? "")).toBe(flow.summary?.[0]);
    expect(liveMeasures(undefined).size).toBe(0);
  });

  it("un numero del riepilogo per nome; assente se non c'è", () => {
    const flow = fresh();
    expect(summaryValue(flow, "mean_speed")?.unit).toBe("km/h");
    expect(summaryValue(flow, "covered_count")?.value).toBe(14);
    expect(summaryValue(flow, "boh")).toBeUndefined();
    expect(summaryValue(undefined, "mean_speed")).toBeUndefined();
    expect(summaryValue({ ...flow, summary: undefined }, "mean_speed")).toBeUndefined();
  });

  it("il tratto più lento si trova dall'id della sua velocità, non dal testo del metodo", () => {
    const flow = fresh();
    const slowest = summaryValue(flow, "slowest_speed");
    const segment = segmentOfSpeed(flow, slowest?.inputs[0]);
    expect(segment?.current_speed.value).toBe(slowest?.value);
    expect(segment?.label).toBe("Via Caracciolo");
    expect(segmentOfSpeed(flow, "m.live.nessuno.current_speed")).toBeUndefined();
    expect(segmentOfSpeed(flow, undefined)).toBeUndefined();
  });
});
