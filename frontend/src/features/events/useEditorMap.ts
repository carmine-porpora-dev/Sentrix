import { useMemo } from "react";
import type { Feature, FeatureCollection } from "@/api/types";
import { closedEdgeKeys, disruptedStopIds } from "@/features/events/draft";
import { useOptionalEventEditor, type MapMode } from "@/features/events/EventEditor";
import {
  areaBounds,
  bboxParam,
  closureLines,
  disruptedPoints,
  draftArea,
  snapBounds,
} from "@/features/events/geo";
import type { PickHandlers } from "@/features/events/mapClick";
import { useEventPreview, useNetworkEdges, useTransitStops } from "@/features/events/queries";
import type { LayerData } from "@/features/map/data";
import { boundsOf, type Bounds } from "@/features/map/layers";

/** Ciò che la mappa usa per scegliere sulla mappa: la modalità, le strade e le fermate candidate, quelle
 * già scelte e che cosa fare a ogni clic. */
export interface EditorMapProps extends PickHandlers {
  mode: MapMode;
  edges: FeatureCollection | undefined;
  stops: FeatureCollection | undefined;
  closedKeys: readonly string[];
  disruptedIds: readonly string[];
  onViewBounds: (bounds: Bounds) => void;
}

export interface EditorMap {
  /** Cosa disegnare dell'Evento in modifica, nei livelli che la mappa già conosce. */
  data: LayerData;
  props: EditorMapProps;
  /** Dove portare la mappa quando si sceglie un altro Evento. */
  fitTo: Bounds | undefined;
  fitKey: string | undefined;
}

const asClosed = (feature: Feature): Feature => ({
  ...feature,
  properties: { ...feature.properties, closed: true },
});

/** L'Evento che si sta modificando come lo vede la mappa; `undefined` se non c'è un editor. Le
 * chiusure e le fermate interrotte si disegnano con gli stessi livelli dell'analisi (linee
 * tratteggiate, marker di fermata chiusa), l'area con il livello `event_area`. */
export function useEditorMap(): EditorMap | undefined {
  const editor = useOptionalEventEditor();
  const draft = editor?.draft;
  const mode = editor?.mapMode ?? "idle";
  const saved = editor?.saved;

  const closedKeys = useMemo(() => (draft ? closedEdgeKeys(draft) : new Set<string>()), [draft]);
  const disruptedIds = useMemo(
    () => (draft ? disruptedStopIds(draft) : new Set<string>()),
    [draft],
  );

  // le strade e le fermate si chiedono per la zona che si guarda (o attorno all'area evento)
  const view = editor?.viewBounds
    ? snapBounds(editor.viewBounds)
    : draft
      ? areaBounds(draft)
      : undefined;
  const bbox = view ? bboxParam(snapBounds(view)) : undefined;
  const edges = useNetworkEdges(mode === "closures" ? bbox : undefined);
  const stops = useTransitStops(mode === "stops" || disruptedIds.size > 0 ? bbox : undefined);
  const preview = useEventPreview(saved?.id, saved?.revision);

  const area = useMemo(() => (draft ? draftArea(draft) : undefined), [draft]);
  const lines = useMemo(
    () => closureLines(closedKeys, preview.data, editor?.pickedEdges, edges.data),
    [closedKeys, preview.data, editor?.pickedEdges, edges.data],
  );
  const stopMarkers = useMemo<FeatureCollection>(() => {
    const found = disruptedPoints(disruptedIds, stops.data);
    return { ...found, features: found.features.map(asClosed) };
  }, [disruptedIds, stops.data]);

  const closedList = useMemo(() => [...closedKeys], [closedKeys]);
  const disruptedList = useMemo(() => [...disruptedIds], [disruptedIds]);
  const data = useMemo<LayerData>(
    () => ({
      ...(area ? { event_area: area } : {}),
      closures: lines,
      stops: stopMarkers,
    }),
    [area, lines, stopMarkers],
  );
  const fitTo = useMemo(() => boundsOf(area), [area]);

  if (!editor) return undefined;
  return {
    data,
    fitTo,
    // la mappa va sull'area quando il form si riempie con un Evento che ne ha una
    fitKey: fitTo && editor.loadKey ? `edit:${editor.loadKey}` : undefined,
    props: {
      mode,
      edges: edges.data,
      stops: stops.data,
      closedKeys: closedList,
      disruptedIds: disruptedList,
      onPickCenter: editor.placeCenter,
      onPickEdge: editor.toggleEdgeAt,
      onPickStop: editor.toggleStopAt,
      onViewBounds: editor.setViewBounds,
    },
  };
}
