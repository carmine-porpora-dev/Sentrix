import { DataSources } from "@/features/live/DataSources";
import { LivePanel } from "@/features/live/LivePanel";

/** La scheda Operations in LIVE: lo stato dei tratti (`LivePanel`, design 01–02) e, sotto, il riquadro
 * «Fonti dati» (spech 11.5). Il messaggio dello stato riempie lo spazio che resta, quindi il riquadro
 * sta in fondo; se l'elenco dei tratti è lungo, la scheda scorre. */
export function LiveOperations() {
  return (
    <div className="flex min-h-full flex-col">
      <LivePanel />
      <DataSources />
    </div>
  );
}
