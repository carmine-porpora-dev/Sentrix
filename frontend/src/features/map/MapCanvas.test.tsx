import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MapLayerId } from "@/features/map/layers";
import { strings } from "@/i18n/it";

// La mappa vera (MapLibre) ha bisogno di WebGL, che jsdom non ha: la si prova nel browser
// (F4-TEST). Qui solo ciò che non lo richiede, cioè il modo in cui si rifiuta di partire.
type Canvas = typeof import("@/features/map/MapCanvas");
const actual = () => vi.importActual<Canvas>("@/features/map/MapCanvas");

const props = {
  tilesUrl: "/tiles/napoli.pmtiles",
  data: {},
  visible: new Set<MapLayerId>(),
  presentation: false,
  window: "departure" as const,
  fitTo: undefined,
  fitKey: undefined,
  measuredFor: () => undefined,
};

describe("MapCanvas senza i token del design", () => {
  it("non parte: dice quale token manca e non disegna una mappa a colori inventati", async () => {
    const { MapCanvas } = await actual();
    const onError = vi.fn();
    render(<MapCanvas {...props} onError={onError} />);
    // nei test il CSS dei token non è caricato, quindi il primo token letto manca
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(strings.map.unavailable);
    expect(alert).toHaveTextContent(/Token del design mancante per la mappa: --color-/);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0]?.[0]).toMatch(/--color-bg/);
  });

  it("senza onError non si rompe", async () => {
    const { MapCanvas } = await actual();
    expect(() => render(<MapCanvas {...props} />)).not.toThrow();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
