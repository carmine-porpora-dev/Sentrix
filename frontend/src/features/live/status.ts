import type { LiveFlowResponse } from "@/api/types";

/** Come sta LIVE, per chi lo mostra: ancora in lettura, senza nessun dato (nemmeno uno snapshot),
 * con dati vecchi o non aggiornabili («parziali»), con dati recenti. Lo chiedono insieme la fascia,
 * il pannello e il chip della barra: lo stesso stato, la stessa parola. */
export type LiveStatus = "loading" | "none" | "partial" | "ok";

/** Un errore verso il nostro server dopo che i tratti c'erano (una lettura ogni minuto che fallisce)
 * lascia gli ultimi dati sullo schermo: sono «parziali», non «ordinari» (08 1: non si inventa nulla). */
export function liveStatus(query: {
  data?: LiveFlowResponse | undefined;
  isPending: boolean;
  isError: boolean;
}): LiveStatus {
  if (query.isPending) return "loading";
  const flow = query.data;
  if (!flow || flow.segments.length === 0) return "none";
  return query.isError || flow.mode === "snapshot" ? "partial" : "ok";
}
