import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, vi } from "vitest";

// Senza globals di Vitest, Testing Library non registra da sola la pulizia del DOM.
afterEach(() => {
  cleanup();
});

// jsdom non ha WebGL: la mappa vera (MapLibre) si prova nel browser (cancello F4-TEST). Nei test
// del resto dell'interfaccia al suo posto c'è un segnaposto che espone cosa riceverebbe.
vi.mock("@/features/map/MapCanvas", () => ({
  MapCanvas: (props: {
    data: Record<string, unknown>;
    visible: ReadonlySet<string>;
    presentation: boolean;
    window: string;
    fitKey: string | undefined;
    fitTo: unknown;
    focus?: { lat: number; lon: number; label?: string | null; key: number };
    editor?: {
      mode: string;
      closedKeys: string[];
      disruptedIds: string[];
      onPickCenter: (lat: number, lon: number) => void;
      onPickEdge: (
        edge: { edgeKey: string; reverseKey: string | null; name: string },
        geometry: unknown,
      ) => void;
      onPickStop: (stop: { stopId: string; name: string }) => void;
    };
  }) =>
    createElement(
      "div",
      {
        "data-testid": "map-canvas",
        "data-layers": Object.keys(props.data).sort().join(","),
        "data-visible": [...props.visible].sort().join(","),
        "data-presentation": String(props.presentation),
        "data-window": props.window,
        "data-fit-key": props.fitKey ?? "",
        "data-fit-to": props.fitTo ? JSON.stringify(props.fitTo) : "",
        "data-focus": props.focus ? `${props.focus.lat},${props.focus.lon}#${props.focus.key}` : "",
        "data-editor-mode": props.editor?.mode ?? "",
        "data-closure-lines": String(
          (props.data.closures as { features: unknown[] } | undefined)?.features.length ?? 0,
        ),
        "data-closed-stops": String(
          (
            (props.data.stops as { features: { properties?: { closed?: boolean } }[] } | undefined)
              ?.features ?? []
          ).filter((f) => f.properties?.closed === true).length,
        ),
        "data-closed": props.editor?.closedKeys.join(",") ?? "",
        "data-disrupted": props.editor?.disruptedIds.join(",") ?? "",
      },
      // i clic che la mappa vera darebbe all'Event Manager (centro, strada, fermata)
      props.editor && [
        createElement(
          "button",
          { key: "c", onClick: () => props.editor?.onPickCenter(40.8, 14.2) },
          "mock: clic sul centro",
        ),
        createElement(
          "button",
          {
            key: "e",
            onClick: () =>
              props.editor?.onPickEdge(
                { edgeKey: "1-2-0", reverseKey: "2-1-0", name: "Via Nuova" },
                {
                  type: "LineString",
                  coordinates: [
                    [14.2, 40.8],
                    [14.21, 40.8],
                  ],
                },
              ),
          },
          "mock: clic su una strada",
        ),
        createElement(
          "button",
          {
            key: "s",
            onClick: () => props.editor?.onPickStop({ stopId: "77", name: "Piazza Cavour" }),
          },
          "mock: clic su una fermata",
        ),
      ],
    ),
}));
