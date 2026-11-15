export class MapTokenError extends Error {
  constructor(name: string) {
    super(`Token del design mancante per la mappa: ${name} (npm run tokens?)`);
    this.name = "MapTokenError";
  }
}

export type TokenReader = (name: string) => string;

/** Il valore di una variabile CSS della pagina (vuoto se non c'è). */
export const cssVariable: TokenReader = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export interface MapTokens {
  colors: {
    bg: string;
    surface1: string;
    surface2: string;
    border: string;
    borderStrong: string;
    text: string;
    textSecondary: string;
    accent: string;
    /** Le quattro classi di congestione: scorrevole, rallentata, intensa, satura. */
    congestion: readonly [string, string, string, string];
    detour: string;
    closure: string;
    eventArea: string;
    stopLow: string;
    stopMid: string;
    stopOver: string;
    accepted: string;
    rejected: string;
    pending: string;
  };
  /** In pixel. */
  sizes: {
    roadLine: number;
    node: number;
    marker: number;
    markerBadge: number;
    iconMarker: number;
    /** Lo spessore dei contorni (bordo dell'area, anello dei cerchi): `border-control`. */
    outline: number;
  };
  opacity: { congestionRest: number; congestionHover: number; eventAreaFill: number };
}

function required(read: TokenReader, name: string): string {
  const value = read(name);
  if (value === "") throw new MapTokenError(name);
  return value;
}

const color = (read: TokenReader, name: string) => required(read, `--color-${name}`);

function pixels(read: TokenReader, name: string): number {
  const value = Number.parseFloat(required(read, name));
  if (Number.isNaN(value)) throw new MapTokenError(name);
  return value;
}

/** Tutti i token della mappa, o `MapTokenError` con il nome di quello che manca. */
export function readMapTokens(read: TokenReader = cssVariable): MapTokens {
  return {
    colors: {
      bg: color(read, "bg"),
      surface1: color(read, "surface-1"),
      surface2: color(read, "surface-2"),
      border: color(read, "border"),
      borderStrong: color(read, "border-strong"),
      text: color(read, "text"),
      textSecondary: color(read, "text-secondary"),
      accent: color(read, "accent"),
      congestion: [
        color(read, "map-congestion-1"),
        color(read, "map-congestion-2"),
        color(read, "map-congestion-3"),
        color(read, "map-congestion-4"),
      ],
      detour: color(read, "map-detour"),
      closure: color(read, "map-closure"),
      eventArea: color(read, "map-event-area"),
      stopLow: color(read, "map-stop-low"),
      stopMid: color(read, "map-stop-mid"),
      stopOver: color(read, "map-stop-over"),
      accepted: color(read, "status-accepted"),
      rejected: color(read, "status-rejected"),
      pending: color(read, "status-pending"),
    },
    sizes: {
      roadLine: pixels(read, "--size-road-line"),
      node: pixels(read, "--size-node"),
      marker: pixels(read, "--size-marker"),
      markerBadge: pixels(read, "--size-marker-badge"),
      iconMarker: pixels(read, "--size-icon-marker"),
      outline: pixels(read, "--border-control"),
    },
    opacity: {
      congestionRest: pixels(read, "--opacity-congestion-rest"),
      congestionHover: pixels(read, "--opacity-congestion-hover"),
      eventAreaFill: pixels(read, "--opacity-event-area-fill"),
    },
  };
}
