import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/api/provider";
import type { LiveFlowResponse, PlannedSensor } from "@/api/types";
import { useTransitStops } from "@/features/events/queries";

/** Ogni quanto la vista LIVE rilegge i tratti (08 4): la cache del server (5 minuti) limita le
 * chiamate vere a TomTom, questo solo quelle al nostro server. */
export const LIVE_POLL_MS = 60_000;

export const liveFlowKey = ["live", "flow"] as const;

/** I tratti LIVE (`GET /api/live/flow` con `X-View: live`). Con `poll` si rileggono ogni minuto, e
 * solo se la scheda è in primo piano (nessuna interrogazione se nessuno guarda, 08 1): lo chiede
 * **un solo** componente, il guscio; gli altri leggono la stessa cache. Fuori da LIVE (`enabled`
 * falso) non si chiede nulla: SCENARIO non dipende da TomTom. */
export function useLiveFlow(enabled: boolean, options: { poll?: boolean } = {}) {
  const api = useApi();
  return useQuery<LiveFlowResponse>({
    queryKey: liveFlowKey,
    queryFn: () => api.liveFlow(),
    enabled,
    refetchInterval: enabled && options.poll ? LIVE_POLL_MS : false,
    refetchIntervalInBackground: false,
    staleTime: LIVE_POLL_MS / 2,
    retry: false,
  });
}

/** I sensori previsti (`GET /api/sensors`, spech 11.5): un elenco statico del file di configurazione,
 * si legge una volta. Solo in LIVE (`enabled`): in SCENARIO non si chiede nulla. Un errore (503: il
 * file non si legge) lascia LIVE com'è, senza il livello e senza le righe «previsto»: i sensori
 * previsti sono un accenno, non devono toglierle nulla. */
export function useSensors(enabled: boolean) {
  const api = useApi();
  return useQuery<PlannedSensor[]>({
    queryKey: ["live", "sensors"],
    queryFn: () => api.listSensors(),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
}

/** La rete del trasporto pubblico da mostrare in LIVE (07 5: fermate e linee, orari programmati):
 * le linee e le fermate dentro `bbox` ("ovest,sud,est,nord"). Sono dati statici (il feed GTFS): si
 * leggono una volta. Un errore (rete, troppe fermate) lascia la mappa con i soli tratti. */
export function useLiveNetwork(enabled: boolean, bbox: string | undefined) {
  const api = useApi();
  const lines = useQuery({
    queryKey: ["live", "lines"],
    queryFn: () => api.transitLines(),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
  const stops = useTransitStops(enabled ? bbox : undefined);
  return { lines: lines.data, stops: stops.data };
}
