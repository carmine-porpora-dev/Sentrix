import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import { bboxOf, useLiveMap } from "@/features/live/useLiveMap";

const wrapper = ({ children }: { children: ReactNode }) => (
  <ApiProvider client={createMockClient({ authenticated: true })}>{children}</ApiProvider>
);

describe("useLiveMap", () => {
  it("in LIVE: i tratti per classe, le linee e le fermate senza carico (il neutro)", async () => {
    const { result } = renderHook(() => useLiveMap(true), { wrapper });
    await waitFor(() =>
      expect(Object.keys(result.current.data).sort()).toEqual(["edges_vc", "sections", "stops"]),
    );
    const { data } = result.current;
    expect(data.edges_vc?.features).toHaveLength(14);
    // gli orari programmati non sono un carico: nessun rapporto, quindi il colore neutro e non «basso»
    for (const feature of [...(data.stops?.features ?? []), ...(data.sections?.features ?? [])]) {
      expect(feature.properties?.load_ratio).toBeNull();
    }
    for (const feature of data.stops?.features ?? [])
      expect(feature.properties?.closed).toBe(false);
    // i numeri del popup si trovano per id
    const first = data.edges_vc?.features[0]?.properties as Record<string, string>;
    expect(result.current.measuredFor(first.speed_id ?? "")?.unit).toBe("km/h");
    expect(result.current.bounds).toBeDefined();
  });

  it("fuori da LIVE non c'è niente e non si chiede niente", async () => {
    const { result } = renderHook(() => useLiveMap(false), { wrapper });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(result.current.data).toEqual({});
    expect(result.current.bounds).toBeUndefined();
  });

  it("il riquadro per le fermate: i tratti con un margine, a cinque decimali", () => {
    expect(
      bboxOf(
        [
          [14.2, 40.8],
          [14.3, 40.9],
        ],
        0.01,
      ),
    ).toBe("14.19,40.79,14.31,40.91");
    expect(bboxOf(undefined)).toBeUndefined();
  });

  it("il riquadro non porta il rumore della virgola mobile (40.821000000000005) nell'indirizzo", () => {
    // 40.831 − 0.01 = 40.821000000000005 e 14.2 + 0.01 = 14.209999999999999 in virgola mobile
    expect(
      bboxOf(
        [
          [14.1, 40.831],
          [14.2, 40.83],
        ],
        0.01,
      ),
    ).toBe("14.09,40.821,14.21,40.84");
  });
});
