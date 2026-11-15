import { layers, namedFlavor, type Flavor } from "@protomaps/basemaps";
import type { StyleSpecification } from "maplibre-gl";
import type { MapTokens } from "@/features/map/tokens";

/** Il nome della sorgente vettoriale della base map nello stile. */
export const BASEMAP_SOURCE = "protomaps";

// Le strade grandi e le linee più marcate; il resto (minori, servizio, altro) è più tenue.
const MAJOR_ROADS =
  /^(major|highway|link|railway|runway|pier|tunnel_(major|highway|link)|bridges_(major|highway|link))/;

/** La base map con i colori del design: stessa struttura del tema scuro di Protomaps, ma ogni colore è
 * un token (07 1). Terra e sfondo sono `bg`; usi del suolo, edifici e acqua salgono di poco verso
 * `surface-1`/`surface-2` perché si leggano senza competere con i livelli dell'analisi; le strade
 * sono `border` e `border-strong`, le etichette (che non si disegnano) `text-secondary`. */
export function tokenFlavor(tokens: MapTokens): Flavor {
  const { colors: c } = tokens;
  const base = namedFlavor("dark");
  const out: Record<string, unknown> = {};
  const roads = (key: string) =>
    key.includes("casing") ? c.bg : MAJOR_ROADS.test(key) ? c.borderStrong : c.border;
  for (const [key, value] of Object.entries(base)) {
    if (key === "pois") {
      out[key] = Object.fromEntries(
        Object.keys(value as object).map((name) => [name, c.textSecondary]),
      );
    } else if (key === "landcover") {
      out[key] = Object.fromEntries(Object.keys(value as object).map((name) => [name, c.surface1]));
    } else if (key === "background" || key === "earth" || key === "glacier") {
      out[key] = c.bg;
    } else if (key === "water") {
      out[key] = c.surface2;
    } else if (key === "buildings") {
      out[key] = c.surface1;
    } else if (key.endsWith("_label") || key.endsWith("_halo")) {
      out[key] = key.endsWith("_halo") ? c.bg : c.textSecondary;
    } else if (key === "boundaries") {
      out[key] = c.borderStrong;
    } else if (
      /(casing|^other|^minor|^link|^major|^highway|^railway|^tunnel|^bridges|^pier|^runway)/.test(
        key,
      )
    ) {
      out[key] = roads(key);
    } else {
      // usi del suolo (parchi, boschi, ospedali, scuole…)
      out[key] = c.surface1;
    }
  }
  return out as unknown as Flavor;
}

/** Lo stile della base map: tile vettoriali dal file PMTiles locale e i livelli del tema. Senza
 * l'opzione `lang` la libreria non produce le etichette (i livelli `symbol`): nessun font da
 * caricare, la mappa funziona del tutto offline (07 5). Se un aggiornamento le introducesse, il
 * test «non ha etichette né glyphs» lo segnala. */
export function buildBaseStyle(tilesUrl: string, tokens: MapTokens): StyleSpecification {
  return {
    version: 8,
    sources: {
      [BASEMAP_SOURCE]: { type: "vector", url: `pmtiles://${tilesUrl}` },
    },
    layers: layers(BASEMAP_SOURCE, tokenFlavor(tokens)) as StyleSpecification["layers"],
  };
}
