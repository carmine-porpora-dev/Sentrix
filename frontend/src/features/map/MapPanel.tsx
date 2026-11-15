import { Suspense, lazy, useMemo, useState } from "react";
import { useRun } from "@/api/queries";
import { useApi } from "@/api/provider";
import {
  LayerPanel,
  LayerToggleButton,
  MapAttribution,
  MapLegend,
  MapToggle,
} from "@/components/MapControls";
import { WindowToggle } from "@/components/WindowToggle";
import { afterIterations, chooseIteration } from "@/features/metrics/iterations";
import { useRunMetrics } from "@/features/metrics/queries";
import { indexMetrics, tail } from "@/features/metrics/cards";
import { useSensors } from "@/features/live/queries";
import { sensorMarkers } from "@/features/live/sensors";
import { useLiveMap } from "@/features/live/useLiveMap";
import { useRunLayers } from "@/features/map/data";
import { MAP_LAYER_IDS, boundsOf, type MapLayerId } from "@/features/map/layers";
import { useEditorMap } from "@/features/events/useEditorMap";
import { useShell } from "@/features/shell/ShellProvider";
import { iterationNumber } from "@/features/shell/run";
import { strings } from "@/i18n/it";

const MapCanvas = lazy(() =>
  import("@/features/map/MapCanvas").then((m) => ({ default: m.MapCanvas })),
);

/** Il colore del campione di ogni livello nel pannello (variabili del design) e se è tratteggiato. */
const SWATCH: Record<MapLayerId, { color: string; dashed?: boolean }> = {
  congestion: { color: "var(--color-map-congestion-3)" },
  detours: { color: "var(--color-map-detour)" },
  closures: { color: "var(--color-map-closure)", dashed: true },
  event_area: { color: "var(--color-map-event-area)" },
  sections: { color: "var(--color-map-stop-mid)" },
  stops: { color: "var(--color-map-stop-low)" },
  intersections: { color: "var(--color-map-congestion-3)" },
  requests: { color: "var(--color-accent)" },
};

/** La mappa con i suoi controlli (07 5): la finestra (Arrivo | Deflusso), Prima/Dopo e l'iterazione,
 * il pannello dei livelli, la vista presentazione, la legenda e l'attribuzione. Mostra i livelli
 * dell'iterazione scelta del run seguito; in LIVE i tratti TomTom (per classe di congestione), le
 * linee e le fermate del TPL (F8-03), senza i controlli dell'analisi. */
export function MapPanel() {
  const api = useApi();
  const shell = useShell();
  const run = useRun(shell.runId).data?.run;
  const metrics = useRunMetrics(run, shell.view);
  const live = shell.mode === "live";
  const liveMap = useLiveMap(live);
  const runData = useRunLayers(run?.id, live ? undefined : metrics.iteration);
  // Senza un run si vede l'Evento che si sta modificando: la sua area, le chiusure e le fermate
  // interrotte. Con un run, i suoi livelli (e le strade da scegliere, se si sta scegliendo).
  const editorMap = useEditorMap();
  const editing = editorMap !== undefined && !live && shell.runId === undefined;
  const data = live ? liveMap.data : editing ? editorMap.data : runData;

  const [visible, setVisible] = useState<ReadonlySet<MapLayerId>>(() => new Set(MAP_LAYER_IDS));
  const [panelOpen, setPanelOpen] = useState(false);
  const [presentation, setPresentation] = useState(false);
  const [error, setError] = useState<string | undefined>();

  // «Sensori previsti» (spech 11.5): solo in LIVE, **spento di default**, e ogni visita a LIVE riparte
  // spenta. L'elenco si legge solo in LIVE; senza (errore, o ancora in lettura) non c'è l'interruttore.
  const sensors = useSensors(live);
  const [sensorsOn, setSensorsOn] = useState(false);
  if (!live && sensorsOn) setSensorsOn(false); // uscendo da LIVE si spegne (aggiornamento nel render)
  const sensorList = live ? sensors.data : undefined;
  const sensorSymbols = useMemo(
    () => (sensorsOn ? sensorMarkers(sensorList, liveMap.data.sections) : []),
    [sensorsOn, sensorList, liveMap.data.sections],
  );

  // la mappa va sull'area dell'evento una volta per run, appena c'è (poi la muove l'utente)
  const runBounds = useMemo(() => boundsOf(data.event_area), [data.event_area]);
  const bounds = live ? liveMap.bounds : editing ? editorMap.fitTo : runBounds;
  const fitKey = live
    ? liveMap.bounds && "live"
    : editing
      ? editorMap.fitKey
      : run && runBounds
        ? run.id
        : undefined;

  const { current: currentMetrics } = metrics;
  const measures = useMemo(() => indexMetrics(currentMetrics), [currentMetrics]);
  const measuredFor = live
    ? liveMap.measuredFor
    : (evidenceId: string) => measures.get(tail(evidenceId));

  const later = afterIterations(metrics.available);
  const latest = later.length > 0 ? Math.max(...later) : undefined;
  const afterShown = chooseIteration(metrics.available, { after: true, pinned: shell.view.pinned });

  const toggle = (id: string) =>
    setVisible((current) => {
      const next = new Set(current);
      if (next.has(id as MapLayerId)) next.delete(id as MapLayerId);
      else next.add(id as MapLayerId);
      return next;
    });

  const showCongestion = !error && Boolean(data.edges_vc) && visible.has("congestion");
  const sensorsToggle =
    !error && sensorList && sensorList.length > 0
      ? { on: sensorsOn, onToggle: () => setSensorsOn(!sensorsOn) }
      : undefined;

  const layers = MAP_LAYER_IDS.map((id) => ({
    id,
    name: strings.map.layers[id],
    on: visible.has(id),
    ...SWATCH[id],
  }));

  return (
    <div className="relative h-full">
      <Suspense
        fallback={
          <div className="grid h-full place-items-center text-text-secondary">
            {strings.map.loading}
          </div>
        }
      >
        <MapCanvas
          tilesUrl={api.tilesUrl}
          data={data}
          visible={visible}
          presentation={presentation}
          window={shell.window}
          fitTo={bounds}
          fitKey={fitKey}
          measuredFor={measuredFor}
          focus={shell.focus}
          editor={live ? undefined : editorMap?.props}
          sensors={sensorSymbols}
          onError={setError}
        />
      </Suspense>

      {/* Le fasce non catturano i clic sulla mappa, solo i loro controlli; a mappa stretta
          (1366 px) i controlli vanno a capo invece di sovrapporsi. */}
      {!error && !live && (
        <div className="pointer-events-none absolute inset-x-space-16 top-space-16 z-10 flex items-start justify-between gap-space-8">
          <div className="pointer-events-auto flex flex-wrap items-center gap-space-8">
            <WindowToggle value={shell.window} onChange={shell.setWindow} />
            {latest !== undefined && (
              <MapToggle
                after={shell.view.after}
                onAfterChange={shell.setAfter}
                iteration={afterShown ?? latest}
                onIterationChange={shell.pickIteration}
                iterations={latest}
                label={strings.map.iteration(iterationNumber(afterShown ?? latest))}
              />
            )}
          </div>
          <div className="pointer-events-auto flex flex-none flex-col items-end gap-space-8">
            <LayerToggleButton open={panelOpen} onToggle={() => setPanelOpen(!panelOpen)} />
            {panelOpen && (
              <LayerPanel
                layers={layers}
                onToggle={toggle}
                options={[{ id: "presentation", name: strings.map.presentation, on: presentation }]}
                onOption={() => setPresentation(!presentation)}
              />
            )}
          </div>
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-space-16 bottom-space-16 z-10 flex flex-wrap items-end justify-between gap-space-8">
        {showCongestion || sensorsToggle ? (
          <div className="pointer-events-auto min-w-0 max-w-full">
            <MapLegend congestion={showCongestion} sensors={sensorsToggle} />
          </div>
        ) : (
          <span />
        )}
        <div className="pointer-events-auto">
          <MapAttribution />
        </div>
      </div>
    </div>
  );
}
