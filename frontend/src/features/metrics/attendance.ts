import type { AttendanceLevel, Event, Measured } from "@/api/types";

/** L'affluenza ipotizzata come `Measured`, costruita dall'interfaccia dai dati dell'Evento: la card
 * «Affluenza ipotizzata» (design) deve poterla mostrare appena c'è l'Evento (anche a run in errore,
 * quando l'iterazione 0 non è mai stata salvata) e passare da `MeasuredValue` come ogni numero.
 * Il backend ne scrive una uguale tra le metriche dell'iterazione 0 (`attendance_measured`, in
 * `backend/app/agents/tools.py`): testo e id sono gli stessi, e `metrics.test.ts` verifica che
 * coincidano con quella delle fixture, scritta dal backend. È sempre **SIMULATO**: è un'ipotesi di scenario (07 4: ogni numero inserito
 * dall'utente è SIMULATO o ha la sua fonte, che qui è `source_ref`). Nessun numero nuovo: è quello
 * dell'Evento per il livello del run. */
export function attendanceMeasured(event: Event, level: AttendanceLevel, runId: string): Measured {
  const note = event.attendance.source_ref?.trim();
  return {
    id: `m.${runId}.it0.event.attendance`,
    value: event.attendance[level],
    unit: "pax",
    kind: "simulated",
    source: `Evento ${event.id} (revisione ${event.revision})`,
    method: `affluenza del livello ${level} indicata nell'Evento, ipotesi di scenario`,
    inputs: [`event ${event.id} rev ${event.revision}`, `livello di affluenza ${level}`],
    assumptions: note ? [`fonte indicata nell'Evento: ${note}`] : [],
    as_of: event.updated_at,
  };
}
