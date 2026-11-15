import { describe, expect, it, vi } from "vitest";
import { routeEditorClick, type ClickedFeature } from "@/features/events/mapClick";
import { EDIT_EDGES_LAYER, EDIT_STOPS_LAYER } from "@/features/map/layers";

const geometry = {
  type: "LineString",
  coordinates: [
    [14.2, 40.8],
    [14.21, 40.8],
  ],
};
const edge = (key: unknown, name: unknown = "Via X", reverse?: unknown): ClickedFeature => ({
  layerId: EDIT_EDGES_LAYER,
  properties: { edge_key: key, name, reverse_key: reverse },
  geometry,
});
const stop = (id: unknown): ClickedFeature => ({
  layerId: EDIT_STOPS_LAYER,
  properties: { stop_id: id, name: "Centrale" },
  geometry: { type: "Point", coordinates: [14.2, 40.8] },
});

function handlers() {
  return { onPickCenter: vi.fn(), onPickEdge: vi.fn(), onPickStop: vi.fn() };
}
const AT = { lng: 14.2345, lat: 40.8312 };

describe("routeEditorClick", () => {
  it("in modo idle non usa il clic (si aprono i popup)", () => {
    const h = handlers();
    expect(routeEditorClick("idle", AT, [edge("1-2-0")], h)).toBe(false);
    expect(h.onPickCenter).not.toHaveBeenCalled();
    expect(h.onPickEdge).not.toHaveBeenCalled();
  });

  it("area: qualunque clic dà il centro (lat, lon nell'ordine giusto), anche sopra una strada", () => {
    const h = handlers();
    expect(routeEditorClick("area", AT, [edge("1-2-0")], h)).toBe(true);
    expect(h.onPickCenter).toHaveBeenCalledWith(40.8312, 14.2345);
    expect(h.onPickEdge).not.toHaveBeenCalled();
  });

  it("strade: sceglie l'arco sotto il clic, con nome e geometria", () => {
    const h = handlers();
    expect(routeEditorClick("closures", AT, [edge("1-2-0", "Via Nuova")], h)).toBe(true);
    expect(h.onPickEdge).toHaveBeenCalledWith(
      { edgeKey: "1-2-0", reverseKey: null, name: "Via Nuova" },
      geometry,
    );
    expect(h.onPickCenter).not.toHaveBeenCalled();
    expect(h.onPickStop).not.toHaveBeenCalled();
  });

  it("strade: porta con sé l'altro senso di marcia; a senso unico (null, vuoto, non testo) è null", () => {
    const h = handlers();
    routeEditorClick("closures", AT, [edge("1-2-0", "Via Nuova", "2-1-0")], h);
    expect(h.onPickEdge).toHaveBeenLastCalledWith(
      { edgeKey: "1-2-0", reverseKey: "2-1-0", name: "Via Nuova" },
      geometry,
    );
    for (const none of [null, "", 7, undefined]) {
      routeEditorClick("closures", AT, [edge("1-2-0", "Via Nuova", none)], h);
      expect(h.onPickEdge.mock.lastCall?.[0].reverseKey).toBeNull();
    }
  });

  it("strade: un clic nel vuoto, o su una fermata, non sceglie nulla ma è «usato»", () => {
    const h = handlers();
    expect(routeEditorClick("closures", AT, [], h)).toBe(true);
    expect(routeEditorClick("closures", AT, [stop("1")], h)).toBe(true);
    expect(h.onPickEdge).not.toHaveBeenCalled();
  });

  it("strade: un arco senza chiave non si sceglie; senza nome il nome è vuoto", () => {
    const h = handlers();
    routeEditorClick("closures", AT, [edge(undefined)], h);
    routeEditorClick("closures", AT, [edge(42)], h);
    expect(h.onPickEdge).not.toHaveBeenCalled();
    routeEditorClick("closures", AT, [edge("9-9-0", null)], h);
    expect(h.onPickEdge).toHaveBeenCalledWith(
      { edgeKey: "9-9-0", reverseKey: null, name: "" },
      geometry,
    );
  });

  it("fermate: sceglie la fermata sotto il clic", () => {
    const h = handlers();
    expect(routeEditorClick("stops", AT, [stop("6236")], h)).toBe(true);
    expect(h.onPickStop).toHaveBeenCalledWith({ stopId: "6236", name: "Centrale" });
    expect(h.onPickEdge).not.toHaveBeenCalled();
  });

  it("fermate: un clic su una strada o nel vuoto non sceglie nulla", () => {
    const h = handlers();
    expect(routeEditorClick("stops", AT, [edge("1-2-0")], h)).toBe(true);
    expect(routeEditorClick("stops", AT, [], h)).toBe(true);
    expect(routeEditorClick("stops", AT, [stop(undefined)], h)).toBe(true);
    expect(h.onPickStop).not.toHaveBeenCalled();
  });

  it("conta il livello cliccato, non solo le proprietà: una fermata con una chiave d'arco non è una strada", () => {
    const h = handlers();
    const imposter: ClickedFeature = {
      ...stop("1"),
      properties: { edge_key: "1-2-0", stop_id: "1" },
    };
    routeEditorClick("closures", AT, [imposter], h);
    expect(h.onPickEdge).not.toHaveBeenCalled();
    const road: ClickedFeature = {
      ...edge("1-2-0"),
      properties: { edge_key: "1-2-0", stop_id: "1" },
    };
    routeEditorClick("stops", AT, [road], h);
    expect(h.onPickStop).not.toHaveBeenCalled();
  });

  it("con più feature sotto il clic prende la prima del livello giusto", () => {
    const h = handlers();
    routeEditorClick("closures", AT, [stop("1"), edge("a"), edge("b")], h);
    expect(h.onPickEdge).toHaveBeenCalledTimes(1);
    expect(h.onPickEdge.mock.calls[0]?.[0].edgeKey).toBe("a");
  });
});
