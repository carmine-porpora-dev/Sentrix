import maplibregl, { type GeoJSONSourceSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import { Ban } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentProps } from "react";
import MapGL, {
  Layer,
  Marker,
  Popup,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre";
import type { Measured } from "@/api/types";
import { Icon } from "@/components/Icon";
import { ClosureSymbol, FocusMarker, MapMarker, SensorSymbol } from "@/components/MapControls";
import { buildBaseStyle } from "@/features/map/basemap";
import {
  FIT_PADDING,
  FOCUS_ZOOM,
  MAX_ZOOM,
  NAPOLI_BOUNDS,
  POPUP_OFFSET,
  PRESENTATION_PITCH,
} from "@/features/map/config";
import { routeEditorClick, type ClickedFeature } from "@/features/events/mapClick";
import type { EditorMapProps } from "@/features/events/useEditorMap";
import type { SensorMarker } from "@/features/live/sensors";
import type { LayerData } from "@/features/map/data";
import {
  API_LAYER,
  EDIT_EDGES_LAYER,
  EDIT_EDGES_SOURCE,
  EDIT_STOPS_LAYER,
  EDIT_STOPS_SOURCE,
  MAP_LAYER_IDS,
  PROMOTE_ID,
  closureSymbols,
  editLayerSpecs,
  interactiveIds,
  layerSpecs,
  sourceId,
  type Bounds,
  type MapLayerId,
} from "@/features/map/layers";
import type { EventWindow, MapFocus } from "@/features/shell/ShellProvider";
import { useFitOnKey } from "@/features/map/useFitOnKey";
import { FeaturePopup, type PopupTarget } from "@/features/map/popup";
import { readMapTokens, type MapTokens } from "@/features/map/tokens";
import { markerState, requestMarkerLabel } from "@/lib/departments";
import { strings } from "@/i18n/it";
import type { LayerName } from "@/api/types";

// Il protocollo `pmtiles://` legge i tile dal file PMTiles con richieste Range (una sola volta).
let protocolReady = false;
function registerProtocol(): void {
  if (protocolReady) return;
  maplibregl.addProtocol("pmtiles", new Protocol().tile);
  protocolReady = true;
}

/** L'ordine in cui si disegnano le sorgenti, dal fondo: l'area, gli archi, le chiusure, le tratte,
 * le fermate e gli incroci sopra. */
const DRAW_ORDER: readonly LayerName[] = [
  "event_area",
  "edges_vc",
  "closures",
  "sections",
  "stops",
  "critical_intersections",
];

interface MapCanvasProps {
  tilesUrl: string;
  data: LayerData;
  visible: ReadonlySet<MapLayerId>;
  /** La vista inclinata («vista presentazione»). */
  presentation: boolean;
  /** La finestra di cui si mostrano gli archi (`window` delle feature). */
  window: EventWindow;
  /** Dove portare la mappa (l'area dell'evento)... */
  fitTo: Bounds | undefined;
  /** ...ogni volta che questa chiave cambia (il run), non a ogni nuovo dato dello stesso run. */
  fitKey: string | undefined;
  /** La metrica collegata a un `evidence_id`, per i popup. */
  measuredFor: (evidenceId: string) => Measured | undefined;
  /** Un punto da mostrare (un'evidenza, una richiesta): la mappa ci va e lo segna. */
  focus?: MapFocus;
  /** Per scegliere sulla mappa (Event Manager): la modalità, le strade e le fermate candidate. */
  editor?: EditorMapProps;
  /** I sensori previsti da disegnare (solo LIVE, livello acceso: spech 11.5). Nessun dato, solo posti. */
  sensors?: readonly SensorMarker[];
  /** Se manca un token del design (`MapTokenError`) o la base map non si carica. */
  onError?: (message: string) => void;
  /** Solo per i test. */
  tokens?: MapTokens;
}

/** La mappa MapLibre: base map PMTiles locale con i colori del design, i livelli dell'analisi come
 * sorgenti GeoJSON, i marker delle richieste e delle fermate chiuse, il popup al clic. */
export function MapCanvas({
  tilesUrl,
  data,
  visible,
  presentation,
  window,
  fitTo,
  fitKey,
  measuredFor,
  focus,
  editor,
  sensors,
  onError,
  tokens: given,
}: MapCanvasProps) {
  const ref = useRef<MapRef>(null);
  const hovered = useRef<{ source: string; id: string } | undefined>(undefined);
  const [popup, setPopup] = useState<
    { lng: number; lat: number; target: PopupTarget; offset: number } | undefined
  >();

  const built = useMemo(() => {
    try {
      registerProtocol();
      const tokens = given ?? readMapTokens();
      return { tokens, style: buildBaseStyle(tilesUrl, tokens) };
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) };
    }
  }, [tilesUrl, given]);

  useEffect(() => {
    if (built.error) onError?.(built.error);
  }, [built.error, onError]);

  const [ready, setReady] = useState(false);
  useFitOnKey(
    ref,
    fitTo,
    fitKey,
    { padding: FIT_PADDING, maxZoom: MAX_ZOOM, duration: 600 },
    ready,
  );

  useEffect(() => {
    ref.current?.easeTo({ pitch: presentation ? PRESENTATION_PITCH : 0, duration: 600 });
  }, [presentation]);

  // un punto chiesto dall'interfaccia: ci si va (almeno allo zoom di una strada) a ogni richiesta
  useEffect(() => {
    if (!focus) return;
    const map = ref.current;
    map?.flyTo({
      center: [focus.lon, focus.lat],
      zoom: Math.max(map.getZoom(), FOCUS_ZOOM),
      duration: 800,
    });
  }, [focus]);

  const picking = editor !== undefined && editor.mode !== "idle";
  const interactive = useMemo(() => {
    if (!built.tokens) return [];
    // scegliendo, si clicca solo ciò che si può scegliere (le strade, o le fermate)
    if (editor?.mode === "closures") return [EDIT_EDGES_LAYER];
    if (editor?.mode === "stops") return [EDIT_STOPS_LAYER];
    if (picking) return [];
    return MAP_LAYER_IDS.flatMap((id) => interactiveIds(id, built.tokens));
  }, [built.tokens, editor?.mode, picking]);
  const editSpecs = useMemo(
    () =>
      built.tokens && editor
        ? editLayerSpecs(built.tokens, editor.closedKeys, editor.disruptedIds)
        : [],
    [built.tokens, editor],
  );

  const setHover = useCallback((next: { source: string; id: string } | undefined) => {
    const map = ref.current?.getMap();
    const previous = hovered.current;
    if (previous && map) map.setFeatureState(previous, { hover: false });
    if (next && map) map.setFeatureState(next, { hover: true });
    hovered.current = next;
  }, []);

  const onMouseMove = useCallback(
    (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      const id = feature?.properties?.edge_key;
      const source = feature?.source;
      setHover(typeof id === "string" && typeof source === "string" ? { source, id } : undefined);
    },
    [setHover],
  );

  const onClick = useCallback(
    (event: MapLayerMouseEvent) => {
      // un clic su un marker lo gestisce il marker (apre il suo popup): la mappa non lo chiude
      const target = event.originalEvent.target;
      if (target instanceof Element && target.closest(".maplibregl-marker")) return;
      if (editor) {
        const clicked: ClickedFeature[] = (event.features ?? []).map((f) => ({
          layerId: f.layer.id,
          properties: f.properties,
          geometry: f.geometry as ClickedFeature["geometry"],
        }));
        if (routeEditorClick(editor.mode, event.lngLat, clicked, editor)) return;
      }
      const feature = event.features?.[0];
      if (!feature) return setPopup(undefined);
      const layer = typeof feature.source === "string" ? feature.source.replace(/^nuo-/, "") : "";
      setPopup({
        lng: event.lngLat.lng,
        lat: event.lngLat.lat,
        offset: POPUP_OFFSET.feature,
        target: { layer, properties: feature.properties ?? {} },
      });
    },
    [editor],
  );

  if (built.error || !built.tokens || !built.style) {
    return (
      <div
        role="alert"
        className="grid h-full place-items-center p-space-24 text-center text-text-secondary"
      >
        <div>
          <p className="text-lg text-text-primary">{strings.map.unavailable}</p>
          <p className="mt-1 text-sm">{built.error ?? strings.map.unavailableHint}</p>
        </div>
      </div>
    );
  }
  const { tokens, style } = built;

  const requests = data.requests?.features ?? [];
  const closures = closureSymbols(data.closures, window);
  const closedStops = (data.stops?.features ?? []).filter((f) => f.properties?.closed === true);
  const point = (geometry: unknown) =>
    (geometry as { coordinates?: [number, number] } | null)?.coordinates;

  return (
    <MapGL
      ref={ref}
      mapLib={maplibregl}
      mapStyle={style}
      initialViewState={{
        bounds: [...NAPOLI_BOUNDS[0], ...NAPOLI_BOUNDS[1]] as [number, number, number, number],
      }}
      maxBounds={[...NAPOLI_BOUNDS[0], ...NAPOLI_BOUNDS[1]] as [number, number, number, number]}
      maxPitch={60}
      attributionControl={false}
      locale={{ "Popup.Close": strings.map.popup.close }}
      interactiveLayerIds={interactive}
      onMouseMove={onMouseMove}
      onClick={onClick}
      onLoad={() => setReady(true)}
      cursor={picking ? "crosshair" : undefined}
      onMoveEnd={(event) => {
        // il rettangolo visibile: con questo l'Event Manager chiede le strade e le fermate da scegliere
        const box = event.target.getBounds();
        editor?.onViewBounds([
          [box.getWest(), box.getSouth()],
          [box.getEast(), box.getNorth()],
        ]);
      }}
      onError={(event) => onError?.(event.error?.message ?? strings.map.error)}
      style={{ width: "100%", height: "100%" }}
    >
      {DRAW_ORDER.map((apiLayer) => {
        const collection = data[apiLayer];
        if (!collection) return null;
        const groups = MAP_LAYER_IDS.filter((id) => API_LAYER[id] === apiLayer);
        return (
          <Source
            key={apiLayer}
            id={sourceId(apiLayer)}
            type="geojson"
            data={collection as unknown as GeoJSONSourceSpecification["data"]}
            promoteId={PROMOTE_ID[apiLayer]}
          >
            {groups.flatMap((id) =>
              layerSpecs(id, tokens, window).map((spec) => {
                const props = {
                  ...spec,
                  layout: { ...spec.layout, visibility: visible.has(id) ? "visible" : "none" },
                } as unknown as ComponentProps<typeof Layer>;
                return <Layer key={spec.id} {...props} />;
              }),
            )}
          </Source>
        );
      })}

      {editor?.mode === "closures" && editor.edges && (
        <Source
          id={EDIT_EDGES_SOURCE}
          type="geojson"
          data={editor.edges as unknown as GeoJSONSourceSpecification["data"]}
          promoteId="edge_key"
        >
          <Layer
            {...(editSpecs.find(
              (spec) => spec.id === EDIT_EDGES_LAYER,
            ) as unknown as ComponentProps<typeof Layer>)}
          />
        </Source>
      )}
      {editor?.mode === "stops" && editor.stops && (
        <Source
          id={EDIT_STOPS_SOURCE}
          type="geojson"
          data={editor.stops as unknown as GeoJSONSourceSpecification["data"]}
          promoteId="stop_id"
        >
          <Layer
            {...(editSpecs.find(
              (spec) => spec.id === EDIT_STOPS_LAYER,
            ) as unknown as ComponentProps<typeof Layer>)}
          />
        </Source>
      )}

      {visible.has("requests") &&
        requests.map((feature, index) => {
          const coordinates = point(feature.geometry);
          const props = (feature.properties ?? {}) as Record<string, unknown>;
          if (!coordinates) return null;
          return (
            <Marker
              key={String(props.action_id ?? index)}
              longitude={coordinates[0]}
              latitude={coordinates[1]}
              anchor="bottom"
            >
              <button
                type="button"
                aria-label={requestMarkerLabel(props)}
                onClick={() =>
                  setPopup({
                    lng: coordinates[0],
                    lat: coordinates[1],
                    offset: POPUP_OFFSET.marker,
                    target: { layer: "requests", properties: props },
                  })
                }
              >
                <MapMarker
                  department={String(props.department)}
                  state={markerState(String(props.state))}
                />
              </button>
            </Marker>
          );
        })}

      {visible.has("closures") &&
        closures.map((symbol) => (
          <Marker key={symbol.id} longitude={symbol.center[0]} latitude={symbol.center[1]}>
            <button
              type="button"
              aria-label={`${strings.map.popup.closure}: ${String(symbol.properties.label ?? "")}`}
              onClick={() =>
                setPopup({
                  lng: symbol.center[0],
                  lat: symbol.center[1],
                  offset: POPUP_OFFSET.feature + 12,
                  target: { layer: "closures", properties: symbol.properties },
                })
              }
            >
              <ClosureSymbol />
            </button>
          </Marker>
        ))}

      {visible.has("stops") &&
        closedStops.map((feature, index) => {
          const coordinates = point(feature.geometry);
          if (!coordinates) return null;
          const props = (feature.properties ?? {}) as Record<string, unknown>;
          return (
            <Marker
              key={String(props.stop_id ?? index)}
              longitude={coordinates[0]}
              latitude={coordinates[1]}
            >
              <button
                type="button"
                aria-label={`${strings.map.popup.closedStop}: ${String(props.name ?? "")}`}
                onClick={() =>
                  setPopup({
                    lng: coordinates[0],
                    lat: coordinates[1],
                    offset: POPUP_OFFSET.feature + tokens.sizes.iconMarker / 2,
                    target: { layer: "stops", properties: props },
                  })
                }
                className="text-text-primary"
              >
                <Icon icon={Ban} size="marker" />
              </button>
            </Marker>
          );
        })}

      {sensors?.map((marker) => (
        <Marker key={marker.key} longitude={marker.lng} latitude={marker.lat}>
          <button
            type="button"
            aria-label={strings.live.sensors.markerLabel(marker.sensor.name)}
            onClick={() =>
              setPopup({
                lng: marker.lng,
                lat: marker.lat,
                offset: POPUP_OFFSET.feature + 12,
                target: { layer: "sensors", properties: { ...marker.sensor } },
              })
            }
          >
            <SensorSymbol type={marker.sensor.type} />
          </button>
        </Marker>
      ))}

      {focus && (
        <Marker key={focus.key} longitude={focus.lon} latitude={focus.lat}>
          <FocusMarker label={focus.label} />
        </Marker>
      )}

      {popup && (
        <Popup
          longitude={popup.lng}
          latitude={popup.lat}
          maxWidth="var(--size-popover-width)"
          offset={popup.offset}
          focusAfterOpen={false}
          closeButton
          closeOnClick={false}
          onClose={() => setPopup(undefined)}
          className="nuo-popup"
        >
          <FeaturePopup
            target={popup.target}
            measured={
              typeof popup.target.properties.evidence_id === "string"
                ? measuredFor(popup.target.properties.evidence_id)
                : undefined
            }
            lookup={measuredFor}
          />
        </Popup>
      )}
    </MapGL>
  );
}
