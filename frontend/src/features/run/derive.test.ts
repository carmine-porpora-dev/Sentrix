import { describe, expect, it } from "vitest";
import type { PlanItem, RequestView, Run, RunView, VdeptRegistry } from "@/api/types";
import {
  REJECT_CODES,
  actorLabel,
  awaitsPerson,
  departmentCards,
  evidenceIteration,
  groupRequests,
  operationsOrder,
  producedIterations,
  runDisplay,
  runSignature,
} from "@/features/run/derive";
import { fixture } from "@/test/fixtures";

const view = (name: string) => fixture<RunView>(`run_view/${name}.json`);
const done = view("step_13_done");
const registry = fixture<VdeptRegistry>("vdept_registry.json");

const run = (state: Run["state"]): Run => ({ ...done.run, state });
const plan = (...statuses: PlanItem["status"][]): PlanItem[] =>
  statuses.map((status, index) => ({ ...(done.plan[0] as PlanItem), seq: index + 1, status }));

function request(id: string, changes: Partial<RequestView["request"]> = {}): RequestView {
  return {
    request: { ...(done.requests[0] as RequestView).request, action_id: id, ...changes },
    events: [],
  };
}

describe("runDisplay", () => {
  it("lo stato del run, di solito", () => {
    expect(runDisplay(run("AWAIT"), plan("accepted"))).toEqual({
      display: "AWAIT",
      step: undefined,
    });
    expect(runDisplay(run("DONE"), plan("accepted", "replaced"))).toEqual({
      display: "DONE",
      step: undefined,
    });
  });

  it("una misura che aspetta una persona è «decisione richiesta», alla tappa dove il run si è fermato", () => {
    expect(runDisplay(run("DONE"), plan("accepted", "human_decision_required"))).toEqual({
      display: "DECISION_REQUIRED",
      step: 8,
    });
    expect(runDisplay(run("VERIFY"), plan("human_decision_required")).step).toBe(7);
  });

  it("l'errore vince su tutto", () => {
    expect(runDisplay(run("ERROR"), plan("human_decision_required"))).toEqual({
      display: "ERROR",
      step: undefined,
    });
  });
});

describe("groupRequests", () => {
  it("l'alternativa sta sotto la richiesta rifiutata, nell'ordine dell'API", () => {
    const groups = groupRequests(done.requests);
    expect(
      groups.map((g) => [
        g.primary.request.action_id,
        g.alternatives.map((a) => a.request.action_id),
      ]),
    ).toEqual([
      ["act_001", []],
      ["act_002", ["act_004"]],
      ["act_003", []],
      ["act_005", []],
    ]);
  });

  it("un'alternativa di un'alternativa finisce nello stesso gruppo, in ordine", () => {
    const groups = groupRequests([
      request("a"),
      request("b", { alternative_of: "a" }),
      request("c", { alternative_of: "b" }),
      request("d"),
    ]);
    expect(
      groups.map((g) => [
        g.primary.request.action_id,
        g.alternatives.map((x) => x.request.action_id),
      ]),
    ).toEqual([
      ["a", ["b", "c"]],
      ["d", []],
    ]);
  });

  it("un'alternativa senza la sua originale sta da sola; un riferimento circolare non cicla", () => {
    expect(
      groupRequests([request("b", { alternative_of: "assente" })]).map(
        (g) => g.primary.request.action_id,
      ),
    ).toEqual(["b"]);
    const loop = groupRequests([
      request("a", { alternative_of: "b" }),
      request("b", { alternative_of: "a" }),
    ]);
    expect(loop.length).toBeGreaterThan(0);
  });

  it("l'alternativa che arriva prima dell'originale non si perde", () => {
    const groups = groupRequests([request("b", { alternative_of: "a" }), request("a")]);
    expect(
      groups.map((g) => [
        g.primary.request.action_id,
        g.alternatives.map((x) => x.request.action_id),
      ]),
    ).toEqual([["a", ["b"]]]);
  });

  it("senza richieste non ci sono gruppi", () => {
    expect(groupRequests([])).toEqual([]);
  });
});

describe("runSignature", () => {
  it("cambia con lo stato, l'iterazione e lo stato di ogni richiesta", () => {
    const base = runSignature(done);
    expect(runSignature(done)).toBe(base);
    expect(runSignature({ ...done, run: { ...done.run, state: "VERIFY" } })).not.toBe(base);
    expect(runSignature({ ...done, run: { ...done.run, iteration: 0 } })).not.toBe(base);
    const moved = {
      ...done,
      requests: [
        {
          ...done.requests[0],
          request: { ...(done.requests[0] as RequestView).request, state: "REJECTED" as const },
        },
        ...done.requests.slice(1),
      ],
    } as RunView;
    expect(runSignature(moved)).not.toBe(base);
  });

  it("senza run è vuota", () => {
    expect(runSignature(undefined)).toBe("");
  });
});

describe("departmentCards", () => {
  it("i quattro dipartimenti nell'ordine del design, con le risorse della finestra", () => {
    const cards = departmentCards(registry, "departure");
    expect(cards.map((c) => c.id)).toEqual([
      "traffic_control",
      "municipal_police",
      "transport_control",
      "public_comms",
    ]);
    expect(cards.map((c) => c.name)).toEqual([
      "Controllo Traffico (virtuale)",
      "Polizia Municipale (virtuale)",
      "Controllo Trasporti (virtuale)",
      "Comunicazione Pubblica (virtuale)",
    ]);
    const police = cards.find((c) => c.id === "municipal_police");
    expect(police?.resources).toEqual([{ resource: "patrols", remaining: 0, total: 6 }]);
    expect(cards.find((c) => c.id === "public_comms")?.resources).toEqual([]);
    expect(
      cards.find((c) => c.id === "transport_control")?.resources.map((r) => r.resource),
    ).toEqual(["reserve_buses", "hour_extensions"]);
  });

  it("l'altra finestra ha altri numeri", () => {
    const arrival = departmentCards(registry, "arrival").find((c) => c.id === "municipal_police");
    expect(arrival?.resources).toEqual([{ resource: "patrols", remaining: 3, total: 6 }]);
  });

  it("senza registro non c'è nulla; un dipartimento nuovo si mostra dopo gli altri, col nome dell'API", () => {
    expect(departmentCards(undefined, "departure")).toEqual([]);
    const extra: VdeptRegistry = {
      ...registry,
      departments: [
        ...registry.departments,
        {
          id: "nuovo",
          label: "Nuovo dipartimento",
          endpoint: "internal://nuovo",
          request_types: [],
        },
      ],
    };
    const cards = departmentCards(extra, "departure");
    expect(cards.at(-1)).toEqual({ id: "nuovo", name: "Nuovo dipartimento", resources: [] });
  });

  it("senza risorse nel registro (nessun run) i dipartimenti ci sono, vuoti", () => {
    const bare: VdeptRegistry = { departments: registry.departments };
    expect(departmentCards(bare, "arrival").every((c) => c.resources.length === 0)).toBe(true);
  });
});

describe("evidenceIteration", () => {
  it.each([
    ["m.run_mock_match_2027.it2.road.departure.veh_hours", 2],
    ["m.r.it0.transit.arrival.walk_people", 0],
    ["m.r.it11.x", 11],
  ])("%s → %d", (id, n) => {
    expect(evidenceIteration(id)).toBe(n);
  });

  it.each(["act_001", "18122092-8475097329-0", "m.r.road.x", "", "m.r.it.x"])(
    "%j non è una metrica",
    (id) => {
      expect(evidenceIteration(id)).toBeUndefined();
    },
  );
});

describe("actorLabel", () => {
  const named = (id: string) => `nome di ${id}`;
  it("agenti, sistema, utente e dipartimenti in parole; il resto com'è", () => {
    expect(actorLabel("system", named)).toBe("Sistema");
    expect(actorLabel("orchestrator", named)).toBe("Orchestratore");
    expect(actorLabel("user", named)).toBe("Utente");
    expect(actorLabel("event_demand", named)).toBe("Agente Event & Demand");
    expect(actorLabel("municipal_police", named)).toBe("nome di municipal_police");
    expect(actorLabel("sconosciuto", named)).toBe("sconosciuto"); // non è un dipartimento: l'id
  });
});

describe("risposta manuale", () => {
  it("una persona risponde solo se il run è manuale e la richiesta è «ricevuta»", () => {
    expect(awaitsPerson(request("a", { state: "RECEIVED" }), true)).toBe(true);
    expect(awaitsPerson(request("a", { state: "RECEIVED" }), false)).toBe(false);
    for (const state of [
      "CREATED",
      "SENT",
      "ACCEPTED",
      "REJECTED",
      "IN_PROGRESS",
      "COMPLETED",
    ] as const) {
      expect(awaitsPerson(request("a", { state }), true), state).toBe(false);
    }
  });

  it("ogni dipartimento ha almeno un codice di rifiuto (04 2)", () => {
    expect(Object.keys(REJECT_CODES).sort()).toEqual([
      "municipal_police",
      "public_comms",
      "traffic_control",
      "transport_control",
    ]);
    for (const codes of Object.values(REJECT_CODES)) expect(codes.length).toBeGreaterThan(0);
    expect(REJECT_CODES.municipal_police).toEqual(["UNAVAILABLE"]);
  });
});

describe("operationsOrder", () => {
  const STATES: Run["state"][] = [
    "INTAKE",
    "ANALYZE",
    "RECONCILE",
    "PLAN",
    "DISPATCH",
    "AWAIT",
    "REPLAN",
    "VERIFY",
    "DONE",
    "ERROR",
  ];

  it("ogni stato mostra tutti e quattro i blocchi, ognuno una volta: cambia solo l'ordine", () => {
    for (const state of STATES) {
      expect([...operationsOrder(state)].sort(), state).toEqual([
        "comparison",
        "departments",
        "plan",
        "requests",
      ]);
    }
    expect([...operationsOrder(undefined)].sort()).toEqual([
      "comparison",
      "departments",
      "plan",
      "requests",
    ]);
  });

  it("in cima c'è ciò che serve nella fase (design: 05 piano, 07 dipartimenti e richieste, 08 confronto)", () => {
    for (const state of ["INTAKE", "ANALYZE", "RECONCILE", "PLAN"] as const) {
      expect(operationsOrder(state)[0], state).toBe("plan");
    }
    for (const state of ["DISPATCH", "AWAIT", "REPLAN"] as const) {
      expect(operationsOrder(state).slice(0, 2), state).toEqual(["departments", "requests"]);
    }
    expect(operationsOrder("VERIFY")[0]).toBe("comparison");
    expect(operationsOrder("DONE").slice(0, 2)).toEqual(["comparison", "plan"]);
  });

  it("con una decisione umana richiesta le richieste vengono per prime, gli altri blocchi restano nell'ordine della fase (schermata 09)", () => {
    for (const state of STATES) {
      const order = operationsOrder(state, true);
      expect(order[0], state).toBe("requests");
      expect([...order].sort(), state).toEqual(["comparison", "departments", "plan", "requests"]);
      expect(order.slice(1), state).toEqual(
        operationsOrder(state).filter((block) => block !== "requests"),
      );
    }
    expect(operationsOrder("DONE", true)).toEqual([
      "requests",
      "comparison",
      "plan",
      "departments",
    ]);
    expect(operationsOrder("DONE", false)).toEqual(operationsOrder("DONE"));
  });

  it("senza run, o in errore, l'ordine di partenza (piano per primo)", () => {
    expect(operationsOrder(undefined)[0]).toBe("plan");
    expect(operationsOrder("ERROR")[0]).toBe("plan");
  });
});

describe("producedIterations", () => {
  it("toglie in coda quelle che non ci sono ancora, non quelle in mezzo", () => {
    expect(producedIterations([1, 2, undefined])).toEqual([1, 2]);
    expect(producedIterations([1, undefined, undefined])).toEqual([1]);
    expect(producedIterations([1, undefined, 3])).toEqual([1, undefined, 3]);
    expect(producedIterations([undefined, undefined])).toEqual([]);
    expect(producedIterations([])).toEqual([]);
    expect(producedIterations([1, 2, 3])).toEqual([1, 2, 3]);
  });
});
