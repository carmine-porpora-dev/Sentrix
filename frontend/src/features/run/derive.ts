import type { Decision, PlanItem, RequestView, Run, RunView, VdeptRegistry } from "@/api/types";
import { DEPARTMENTS } from "@/lib/departments";
import { RUN_STEPS, type RunDisplay } from "@/features/shell/run";
import { strings } from "@/i18n/it";

/** Che cosa dice il chip dello stato del run: lo stato, o «decisione richiesta» se una misura del
 * piano aspetta una persona (nello spec è lo stato di una misura, non del run: D6 del design). Per
 * «decisione richiesta» la tappa evidenziata è quella dove il run si è fermato. */
export function runDisplay(
  run: Run,
  plan: readonly PlanItem[],
): { display: RunDisplay; step: number | undefined } {
  if (run.state === "ERROR") return { display: "ERROR", step: undefined };
  if (plan.some((item) => item.status === "human_decision_required")) {
    // ogni stato che non è ERROR è una tappa della barra
    return {
      display: "DECISION_REQUIRED",
      step: (RUN_STEPS as readonly string[]).indexOf(run.state),
    };
  }
  return { display: run.state, step: undefined };
}

export interface RequestGroup {
  /** La richiesta originale. */
  primary: RequestView;
  /** Le sue alternative (dopo un rifiuto), anche quelle di un'alternativa, nell'ordine in cui sono nate. */
  alternatives: RequestView[];
}

/** Le richieste raggruppate: ognuna con le alternative che ne sono nate. Un'alternativa senza la sua
 * originale (non ancora arrivata) sta da sola. L'ordine è quello dell'API. */
export function groupRequests(requests: readonly RequestView[]): RequestGroup[] {
  const byId = new Map(requests.map((item) => [item.request.action_id, item]));
  const rootOf = (item: RequestView): string => {
    const seen = new Set<string>();
    let current = item;
    for (;;) {
      const parent = current.request.alternative_of;
      if (!parent || seen.has(current.request.action_id)) return current.request.action_id;
      const next = byId.get(parent);
      if (!next) return current.request.action_id;
      seen.add(current.request.action_id);
      current = next;
    }
  };
  const groups = new Map<string, RequestGroup>();
  for (const item of requests) {
    const root = rootOf(item);
    if (root === item.request.action_id) {
      groups.set(root, { primary: item, alternatives: groups.get(root)?.alternatives ?? [] });
    } else {
      const group = groups.get(root) ?? {
        primary: byId.get(root) as RequestView,
        alternatives: [],
      };
      group.alternatives.push(item);
      groups.set(root, group);
    }
  }
  return [...groups.values()];
}

/** Cambia quando cambia qualcosa che i pannelli devono rileggere dal server (le risorse residue, il
 * registro): lo stato del run, l'iterazione e lo stato di ogni richiesta. */
export function runSignature(view: RunView | undefined): string {
  if (!view) return "";
  const states = view.requests.map((item) => `${item.request.action_id}=${item.request.state}`);
  return [view.run.state, view.run.iteration, ...states].join("|");
}

export interface ResourceLine {
  resource: string;
  remaining: number;
  total: number;
}

export interface DepartmentCard {
  id: string;
  name: string;
  resources: ResourceLine[];
}

/** I dipartimenti con le risorse della finestra scelta, nell'ordine del design. Senza registro non c'è
 * nulla da mostrare; un dipartimento senza risorse (la comunicazione) ha un elenco vuoto. */
export function departmentCards(
  registry: VdeptRegistry | undefined,
  window: "arrival" | "departure",
): DepartmentCard[] {
  if (!registry) return [];
  const known = Object.keys(DEPARTMENTS);
  const ids = [
    ...known.filter((id) => registry.departments.some((d) => d.id === id)),
    ...registry.departments.map((d) => d.id).filter((id) => !known.includes(id)),
  ];
  return ids.map((id) => ({
    id,
    name: registry.departments.find((d) => d.id === id)?.label ?? id,
    resources: (registry.resources ?? [])
      .filter((r) => r.department === id && r.window === window)
      .map((r) => ({ resource: r.resource, remaining: r.remaining, total: r.total })),
  }));
}

/** L'iterazione a cui appartiene una metrica citata (`m.<run>.it<n>.…`), se l'id è di una metrica. */
export function evidenceIteration(id: string): number | undefined {
  const match = /^m\.[^.]+\.it(\d+)\./.exec(id);
  return match ? Number(match[1]) : undefined;
}

/** Chi ha scritto una riga del registro, in parole: un agente, un dipartimento, il sistema, l'utente. */
export function actorLabel(
  actor: Decision["actor"],
  departmentName: (id: string) => string,
): string {
  const labels = strings.panels.log.actors as Record<string, string>;
  return labels[actor] ?? (actor in DEPARTMENTS ? departmentName(actor) : actor);
}

/** I codici con cui un dipartimento può rifiutare (04 2). Per la risposta manuale l'utente sceglie tra
 * questi, con il motivo scritto a mano. */
export const REJECT_CODES: Readonly<Record<string, readonly string[]>> = {
  municipal_police: ["UNAVAILABLE"],
  traffic_control: ["LIMIT_REACHED", "CONFLICT_ACTIVE_DETOUR"],
  transport_control: ["NO_RESERVE", "NO_EXTENSION_LEFT", "CONFLICT_CLOSED_EDGE"],
  public_comms: ["UNAPPROVED_MEASURE"],
};

/** Una richiesta aspetta la risposta di una persona: solo se il run è partito con la risposta manuale e
 * la richiesta è in `RECEIVED` (04 5). */
export function awaitsPerson(item: RequestView, runManual: boolean): boolean {
  return runManual && item.request.state === "RECEIVED";
}

export type OperationsBlock = "plan" | "departments" | "requests" | "comparison";

/** In che ordine la scheda Operations mette i suoi blocchi: in cima quello che interessa nella fase in
 * cui si trova il run (design, schermate 05, 07 e 08: il piano mentre si pianifica, i dipartimenti e le
 * richieste mentre si inviano e si aspettano le risposte, il confronto quando si verifica). Se una
 * decisione aspetta una persona le richieste vengono subito sotto il riquadro (schermata 09: la
 * richiesta rifiutata e le sue alternative). Nessun blocco sparisce: cambia solo cosa si vede senza
 * scorrere. */
export function operationsOrder(
  state: Run["state"] | undefined,
  decisionRequired = false,
): OperationsBlock[] {
  const order = orderFor(state);
  return decisionRequired ? ["requests", ...order.filter((block) => block !== "requests")] : order;
}

function orderFor(state: Run["state"] | undefined): OperationsBlock[] {
  switch (state) {
    case "DISPATCH":
    case "AWAIT":
    case "REPLAN":
      return ["departments", "requests", "plan", "comparison"];
    case "VERIFY":
      return ["comparison", "requests", "departments", "plan"];
    case "DONE":
      return ["comparison", "plan", "requests", "departments"];
    default:
      return ["plan", "departments", "requests", "comparison"];
  }
}

/** Le metriche delle iterazioni già prodotte: dall'ultima si tolgono quelle che non ci sono ancora (il run
 * è già all'iterazione 2 ma le sue metriche arrivano dopo), così il confronto non ha colonne vuote e
 * la variazione è quella dell'ultima iterazione che c'è. */
export function producedIterations<T>(responses: readonly (T | undefined)[]): (T | undefined)[] {
  let end = responses.length;
  while (end > 0 && responses[end - 1] === undefined) end--;
  return responses.slice(0, end);
}
