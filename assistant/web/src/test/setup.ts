import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// Telefono (`compact`) o schermo largo: lo decide il test con `setCompact`.
let compact = false;
export function setCompact(value: boolean) {
  compact = value;
}

beforeEach(() => {
  compact = false;
  window.matchMedia = ((query: string) => ({
    matches: query.includes("max-width") ? compact : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
  // jsdom non ha un canvas: lo sfondo liquido non disegna, il resto dell'interfaccia sì
  HTMLCanvasElement.prototype.getContext = (() =>
    null) as typeof HTMLCanvasElement.prototype.getContext;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
