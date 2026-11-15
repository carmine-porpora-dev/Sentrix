import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Bounds } from "@/features/map/layers";
import { useFitOnKey, type Fittable } from "@/features/map/useFitOnKey";

const OPTIONS = { padding: 80, maxZoom: 15, duration: 600 };
const A: Bounds = [
  [14.2, 40.8],
  [14.25, 40.85],
];
const B: Bounds = [
  [14.1, 40.78],
  [14.3, 40.9],
];

interface Props {
  bounds?: Bounds;
  key?: string;
  ready?: boolean;
}

function setup(initial: Props) {
  const fitBounds = vi.fn();
  const map = { current: { fitBounds } satisfies Fittable };
  const hook = renderHook(
    (props: Props) => useFitOnKey(map, props.bounds, props.key, OPTIONS, props.ready ?? true),
    {
      initialProps: initial,
    },
  );
  return { fitBounds, ...hook };
}

describe("useFitOnKey", () => {
  it("porta la mappa sul rettangolo quando c'è la chiave, con le opzioni date", () => {
    const { fitBounds } = setup({ bounds: A, key: "run1" });
    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds).toHaveBeenCalledWith(A, OPTIONS);
  });

  it("senza chiave o senza rettangolo non fa nulla", () => {
    expect(setup({ bounds: A }).fitBounds).not.toHaveBeenCalled();
    expect(setup({ key: "run1" }).fitBounds).not.toHaveBeenCalled();
    expect(setup({}).fitBounds).not.toHaveBeenCalled();
  });

  it("aspetta il rettangolo: la chiave arriva quando i dati ci sono", () => {
    const { fitBounds, rerender } = setup({});
    rerender({ bounds: A });
    expect(fitBounds).not.toHaveBeenCalled();
    rerender({ bounds: A, key: "run1" });
    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds).toHaveBeenLastCalledWith(A, OPTIONS);
  });

  it("nuovi dati dello stesso run non la spostano; un run nuovo sì, sul suo rettangolo", () => {
    const { fitBounds, rerender } = setup({ bounds: A, key: "run1" });
    rerender({ bounds: B, key: "run1" }); // un'altra iterazione, stesso run
    rerender({ bounds: A, key: "run1" });
    expect(fitBounds).toHaveBeenCalledTimes(1);
    rerender({ bounds: B, key: "run2" });
    expect(fitBounds).toHaveBeenCalledTimes(2);
    expect(fitBounds).toHaveBeenLastCalledWith(B, OPTIONS);
  });

  it("aspetta che la mappa sia pronta: prima il riferimento è vuoto, e poi la chiave non cambia più", () => {
    const { fitBounds, rerender } = setup({ bounds: A, key: "run1", ready: false });
    expect(fitBounds).not.toHaveBeenCalled();
    rerender({ bounds: A, key: "run1", ready: true });
    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds).toHaveBeenLastCalledWith(A, OPTIONS);
    rerender({ bounds: B, key: "run1", ready: true });
    expect(fitBounds).toHaveBeenCalledTimes(1);
  });

  it("senza mappa montata non si rompe", () => {
    const map = { current: null };
    expect(() => renderHook(() => useFitOnKey(map, A, "run1", OPTIONS, true))).not.toThrow();
  });
});
