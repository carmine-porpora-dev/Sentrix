import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/api/provider";
import type { CreateRunRequest, Event, EventInput, EventSummary } from "@/api/types";

export const eventsKey = ["events"] as const;
export const eventKey = (eventId: string) => ["event", eventId] as const;

/** L'elenco degli eventi (06 3): i seed e quelli creati. */
export function useEvents() {
  const api = useApi();
  return useQuery<EventSummary[]>({
    queryKey: eventsKey,
    queryFn: () => api.listEvents(),
    staleTime: Infinity,
  });
}

/** Salva l'Evento: lo crea (POST) o lo aggiorna (PUT, una nuova revisione). L'Evento restituito dal
 * server sostituisce quello in cache e l'elenco si rilegge (nome, data, revisione). */
export function useSaveEvent() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ input, isNew }: { input: EventInput; isNew: boolean }): Promise<Event> =>
      isNew ? api.createEvent(input) : api.updateEvent(input.id, input),
    onSuccess: (saved) => {
      queryClient.setQueryData(eventKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: eventsKey });
    },
  });
}

/** «Ripristina preset»: rimette il contenuto del file seed come nuova revisione. */
export function useResetEvent() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (eventId: string): Promise<Event> => api.resetEvent(eventId),
    onSuccess: (event) => {
      queryClient.setQueryData(eventKey(event.id), event);
      void queryClient.invalidateQueries({ queryKey: eventsKey });
    },
  });
}

export function useCreateRun() {
  const api = useApi();
  return useMutation({ mutationFn: (body: CreateRunRequest) => api.createRun(body) });
}

/** L'anteprima del risolutore (chiusure risolte in archi, punti agganciati): per l'Evento salvato, e
 * si rilegge a ogni revisione. */
export function useEventPreview(eventId: string | undefined, revision: number | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ["event-preview", eventId, revision],
    queryFn: () => api.resolveEvent(eventId as string),
    enabled: eventId !== undefined && revision !== undefined,
    staleTime: Infinity,
    retry: false,
  });
}

/** Le strade da cliccare nel rettangolo `bbox` (`ovest,sud,est,nord`). */
export function useNetworkEdges(bbox: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ["network-edges", bbox],
    queryFn: () => api.networkEdges(bbox as string),
    enabled: bbox !== undefined,
    staleTime: Infinity,
    retry: false,
  });
}

/** Le fermate da cliccare nel rettangolo `bbox`. */
export function useTransitStops(bbox: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ["transit-stops", bbox],
    queryFn: () => api.transitStops(bbox as string),
    enabled: bbox !== undefined,
    staleTime: Infinity,
    retry: false,
  });
}
