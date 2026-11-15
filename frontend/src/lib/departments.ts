import { Bus, Megaphone, Shield, TrafficCone, type LucideIcon } from "lucide-react";
import { strings } from "@/i18n/it";

/** I dipartimenti virtuali (04 2) con l'icona del design (`design/icons/README.md`), nell'ordine in cui
 * si mostrano. Il **nome** non sta qui: lo dà il registro dell'API (`useDepartmentName`). */
export const DEPARTMENTS: Record<string, { icon: LucideIcon }> = {
  traffic_control: { icon: TrafficCone },
  municipal_police: { icon: Shield },
  transport_control: { icon: Bus },
  public_comms: { icon: Megaphone },
};

/** Lo stato di una richiesta come lo mostra un marker sulla mappa: accettata (e poi in corso o
 * completata) con il segno di spunta, rifiutata con la croce, le altre senza badge. */
export type MarkerState = "normal" | "accepted" | "rejected";

export function markerState(state: string): MarkerState {
  switch (state) {
    case "ACCEPTED":
    case "IN_PROGRESS":
    case "COMPLETED":
      return "accepted";
    case "REJECTED":
      return "rejected";
    default:
      return "normal";
  }
}

/** Il nome assistivo del marker di una richiesta sulla mappa: il bersaglio e lo stato («Via Depretis:
 * In corso»), dalle proprietà del layer `requests` (`target_label`, `state`: i nomi che scrive il
 * backend, `requests_layer`). */
export function requestMarkerLabel(properties: Readonly<Record<string, unknown>>): string {
  return strings.map.markerLabel(
    String(properties.target_label ?? ""),
    requestStateLabel(String(properties.state ?? "")),
  );
}

/** Lo stato di una richiesta a parole (le etichette sono di `strings.panels.ops.state`: un posto solo,
 * per la scheda, il popup e il marker). Uno stato che l'interfaccia non conosce si mostra com'è. */
export function requestStateLabel(state: string): string {
  const labels: Readonly<Record<string, string>> = strings.panels.ops.state;
  return labels[state] ?? state;
}
