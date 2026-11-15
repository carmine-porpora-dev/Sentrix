import type { ChatResponse, Source } from "../src/api/chat.ts";

// Numeri e strade vengono dalla pagina di verifica dei percorsi di Sentrix (A1, ultima analisi
// dell'evento di prova): sono quelli calcolati dal motore, non scritti a mano per il mockup.
const AS_OF = "2026-09-26T13:30:00+02:00";

const TASSO: Omit<ChatResponse, "conversation_id"> = {
  text: [
    "Da [[luogo:Piazza Garibaldi]] a [[strada:Via Torquato Tasso]] alle 13:30 il percorso più veloce, secondo la simulazione, richiede circa 10,2 min (6,79 km):",
    "",
    "1. Percorri [[strada:Via Nuova Marina]] per 1158 m.",
    "2. Prosegui su [[strada:Corso Vittorio Emanuele]] per 1326 m.",
    "3. Arrivi su [[strada:Via Torquato Tasso]], 1231 m.",
    "",
    "Sul percorso, secondo la simulazione, [[strada:Via Agostino Depretis]] è molto trafficata. In alternativa, passando da [[strada:Via Foria]], servono circa 11,8 min (9,24 km).",
  ].join("\n"),
  sources: [
    { label: "Tempo e lunghezza del percorso", kind: "simulated", as_of: AS_OF, value: "10,2 min" },
    {
      label: "Traffico su Via Agostino Depretis",
      kind: "simulated",
      as_of: AS_OF,
      value: "v/c 1,0",
    },
  ] satisfies Source[],
  needs: null,
  choices: [],
};

const MERGELLINA: Omit<ChatResponse, "conversation_id"> = {
  text: [
    "Alle 16:45 da [[luogo:Stazione Centrale]] a [[luogo:Mergellina]] il percorso più veloce richiede circa 8,0 min (5,98 km):",
    "",
    "1. Da [[luogo:Piazza Garibaldi]] segui [[strada:Corso Umberto Primo]] fino a [[luogo:Piazza Municipio]].",
    "2. Prosegui su [[strada:Via Ferdinando Acton]] e poi su [[strada:Riviera di Chiaia]] (1396 m).",
    "3. Arrivi a Mergellina da [[strada:Via Piedigrotta]].",
    "",
    "Cosa eviti: [[strada:Via Francesco Caracciolo]] e [[strada:Viale Anton Dohrn]] sono chiuse; il percorso le evita già. Secondo la simulazione, [[strada:Piazza Giuseppe Garibaldi]] è molto trafficata.",
  ].join("\n"),
  sources: [
    { label: "Tempo e lunghezza del percorso", kind: "simulated", as_of: AS_OF, value: "8,0 min" },
    {
      label: "Traffico su Piazza Giuseppe Garibaldi",
      kind: "simulated",
      as_of: AS_OF,
      value: "v/c 1,62",
    },
  ] satisfies Source[],
  needs: null,
  choices: [],
};

const UNKNOWN: Omit<ChatResponse, "conversation_id"> = {
  text: "Non ho questa informazione.",
  sources: [],
  needs: null,
  choices: [],
};

/** La risposta di prova a una domanda: le due domande con percorso calcolato, altrimenti «non so». */
export function pickReply(message: string): ChatResponse {
  const text = message.toLowerCase();
  const reply = text.includes("tasso") ? TASSO : text.includes("mergellina") ? MERGELLINA : UNKNOWN;
  return { conversation_id: "dev-mock", ...reply };
}
