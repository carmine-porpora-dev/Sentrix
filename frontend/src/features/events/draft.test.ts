import { describe, expect, it } from "vitest";
import type { Event, EventInput } from "@/api/types";
import {
  DEFAULT_RADIUS_M,
  parseTime,
  ZONE_TYPES,
  closedEdgeKeys,
  decimalText,
  disruptedStopIds,
  draftFromEvent,
  draftToInput,
  emptyDraft,
  integerText,
  parseCoordinate,
  parseDecimal,
  parseInteger,
  sameDraft,
  slugFromName,
  toggleEdge,
  toggleStop,
  withCenter,
} from "@/features/events/draft";
import { fixture, openApi } from "@/test/fixtures";

const match = fixture<Event>("event_match_2027.json");
const regate = fixture<Event>("event_regate_sep_2026.json");

/** L'Evento senza i campi che decide il server: quello che deve tornare dal form non toccato. */
function asInput(event: Event): EventInput {
  const input: Partial<Event> = { ...event };
  delete input.revision;
  delete input.created_at;
  delete input.updated_at;
  return input as EventInput;
}

describe("numeri come testo", () => {
  it.each([
    ["150000", 150000],
    ["150.000", 150000],
    ["1.234.567", 1234567],
    ["6", 6],
    [" 42 ", 42],
    ["0", 0],
  ])("parseInteger(%j) = %d", (text, value) => {
    expect(parseInteger(text)).toBe(value);
  });

  it.each(["", "1.5", "1,5", "12.34.5", "1.2345", "abc", "-3", "1e3", "15 000", "1.000.00"])(
    "parseInteger(%j) non è un intero",
    (text) => {
      expect(parseInteger(text)).toBeUndefined();
    },
  );

  it.each([
    ["2,2", 2.2],
    ["2.2", 2.2],
    ["40", 40],
    ["0,25", 0.25],
  ])("parseDecimal(%j) = %d", (text, value) => {
    expect(parseDecimal(text)).toBe(value);
  });

  it.each(["", ",5", "5,", "1,2,3", "abc", "-1", "1 2"])(
    "parseDecimal(%j) non è un numero",
    (text) => {
      expect(parseDecimal(text)).toBeUndefined();
    },
  );

  it("le coordinate possono essere negative", () => {
    expect(parseCoordinate("-4,5")).toBe(-4.5);
    expect(parseCoordinate("40.83200")).toBe(40.832);
    expect(parseCoordinate("40.8.3")).toBeUndefined();
  });

  it("integerText e decimalText sono all'italiana e senza rumore di calcolo", () => {
    expect(integerText(150000)).toBe("150.000");
    expect(integerText(6)).toBe("6");
    expect(integerText(1000)).toBe("1.000");
    expect(decimalText(0.4 * 100)).toBe("40"); // 40.00000000000001
    expect(decimalText(2.2)).toBe("2,2");
    expect(decimalText(0.07 * 100)).toBe("7");
    expect(decimalText(33.5)).toBe("33,5");
  });
});

describe("parseTime", () => {
  it.each([
    ["18:30", "18:30"],
    ["9:05", "09:05"],
    ["00:00", "00:00"],
    ["23:59", "23:59"],
    [" 7:00 ", "07:00"],
  ])("%j → %j", (text, normalized) => {
    expect(parseTime(text)).toBe(normalized);
  });

  it.each(["", "24:00", "7pm", "18:3", "18:60", "1830", "18.30", "-1:00", "18:30:00"])(
    "%j non è un orario",
    (text) => {
      expect(parseTime(text)).toBeUndefined();
    },
  );
});

describe("draftFromEvent", () => {
  const draft = draftFromEvent(match);

  it("porta in testo i campi che si digitano", () => {
    expect(draft.id).toBe("match_2027");
    expect(draft.date).toBe("2027-07-10");
    expect(draft.arrival).toEqual({ start: "16:00", end: "19:00", peak: "18:00" });
    expect(draft.departure).toEqual({ start: "21:00", end: "23:00", peak: "21:30" });
    expect(draft.attendance).toEqual({
      low: "50.000",
      mid: "150.000",
      high: "300.000",
      source: "Ipotesi di scenario (documento di progetto 5.2)",
    });
    expect(draft.background).toEqual({ arrival: "40", departure: "25" }); // 0,4 e 0,25 in %
    expect(draft.centerLat).toBe("40.832");
    expect(draft.centerLabel).toBe("Rotonda Diaz");
    expect(draft.radius).toBe("400");
    expect(draft.carOccupancy).toBe(""); // predefinito del modello
  });

  it("le risorse restano nell'ordine dell'Evento (l'API ne cita l'indice negli errori)", () => {
    expect(draft.resources.map((item) => item.window)).toEqual(
      match.resources.map((item) => item.window),
    );
    expect(draft.resources[0]?.values.municipal_police_patrols_total).toBe(
      String(match.resources[0]?.municipal_police_patrols_total),
    );
  });

  it("tiene chiusure e interruzioni com'erano, senza condividerle con l'Evento", () => {
    expect(draft.closures).toEqual(match.closures);
    expect(draft.disruptions).toEqual(match.transit_disruptions);
    expect(draft.closures[0]).not.toBe(match.closures?.[0]);
    expect(closedEdgeKeys(draft)).toEqual(
      new Set([
        "18122092-8475097329-0",
        "8475097329-18122092-0",
        "8399521491-8475097329-0",
        "8475097329-8399521499-0",
      ]),
    ); // le due chiusure dell'Evento ne condividono due
    expect(disruptedStopIds(draft)).toEqual(new Set(["6236", "6237"]));
  });

  it("senza ripartizione propria tutti i tipi di zona sono vuoti", () => {
    expect(Object.keys(draft.modalSplit)).toEqual([...ZONE_TYPES]);
    for (const row of Object.values(draft.modalSplit))
      expect(row).toEqual({ car: "", transit: "", walk: "" });
  });

  it("con una ripartizione propria compila solo quel tipo", () => {
    const own = draftFromEvent({
      ...match,
      car_occupancy: 2.5,
      modal_split_override: { near: { car_pct: 30, transit_pct: 20.5, walk_pct: 49.5 } },
    });
    expect(own.carOccupancy).toBe("2,5");
    expect(own.modalSplit.near).toEqual({ car: "30", transit: "20,5", walk: "49,5" });
    expect(own.modalSplit.far).toEqual({ car: "", transit: "", walk: "" });
  });
});

describe("draftToInput: il form non toccato rimanda l'Evento com'era", () => {
  it.each([
    ["match_2027", match],
    ["regate_sep_2026", regate],
  ])("%s", (_name, event) => {
    const result = draftToInput(draftFromEvent(event));
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.input).toEqual(asInput(event));
  });

  it("anche con una ripartizione, l'occupazione e le misure reali proprie", () => {
    const rich: Event = {
      ...match,
      car_occupancy: 2.5,
      modal_split_override: { near: { car_pct: 30, transit_pct: 20.5, walk_pct: 49.5 } },
      real_measures: [{ label: "L", measure_type: "traffic_post", target: "t", source_ref: "s" }],
      sources: ["Fonte A"],
      description: "Una nota",
    };
    const result = draftToInput(draftFromEvent(rich));
    expect(result.ok && result.input).toEqual(asInput(rich));
  });

  it("zone e destinazioni auto proprie si conservano, anche se il form non le modifica", () => {
    const own: Event = {
      ...match,
      zones_override: [
        {
          id: "z",
          name: "Z",
          type: "near",
          weight_pct: 100,
          centroid: { lat: 40.8, lon: 14.2, label: null },
        },
      ],
      car_destinations: [{ point: { lat: 40.8, lon: 14.2, label: null }, share_pct: 100 }],
    };
    const result = draftToInput(draftFromEvent(own));
    expect(result.ok && result.input.zones_override).toEqual(own.zones_override);
    expect(result.ok && result.input.car_destinations).toEqual(own.car_destinations);
  });

  it("gli orari vanno all'API con i secondi, come li scrive l'API", () => {
    const result = draftToInput(draftFromEvent(match));
    expect(result.ok && result.input.arrival).toEqual({
      start: "16:00:00",
      end: "19:00:00",
      peak: "18:00:00",
    });
  });
});

describe("draftToInput: che cosa manca", () => {
  it("un Evento nuovo vuoto elenca ogni campo da compilare, per percorso", () => {
    const result = draftToInput(emptyDraft());
    expect(result.ok).toBe(false);
    const paths = result.ok ? [] : result.problems.map((p) => p.path);
    expect(paths).toEqual([
      "id",
      "name",
      "date",
      "area_center.lat",
      "area_center.lon",
      // il raggio ha il valore del modello: non manca
      "arrival.start",
      "arrival.end",
      "arrival.peak",
      "departure.start",
      "departure.end",
      "departure.peak",
      "attendance.low",
      "attendance.mid",
      "attendance.high",
      "background.arrival_peak_share",
      "background.departure_peak_share",
      ...[0, 1].flatMap((i) =>
        [
          "municipal_police_patrols_total",
          "municipal_police_patrols_committed",
          "traffic_control_signal_changes_max",
          "transport_control_reserve_buses",
          "transport_control_hour_extensions",
        ].map((f) => `resources.${i}.${f}`),
      ),
    ]);
    if (!result.ok)
      expect(new Set(result.problems.map((p) => p.message))).toEqual(
        new Set(["Campo obbligatorio"]),
      );
  });

  it("un valore non leggibile come numero è un errore sul campo, con il suo testo", () => {
    const draft = draftFromEvent(match);
    draft.attendance.mid = "tanta";
    draft.carOccupancy = "due";
    draft.background.arrival = "4x";
    draft.centerLat = "nord";
    draft.resources[1]!.values.municipal_police_patrols_total = "1,5";
    const result = draftToInput(draft);
    expect(result.ok).toBe(false);
    const problems = new Map(result.ok ? [] : result.problems.map((p) => [p.path, p.message]));
    expect(problems.get("attendance.mid")).toBe("Inserisci un numero intero");
    expect(problems.get("car_occupancy")).toBe("Inserisci un numero");
    expect(problems.get("background.arrival_peak_share")).toBe("Inserisci un numero");
    expect(problems.get("area_center.lat")).toBe("Inserisci un numero");
    expect(problems.get("resources.1.municipal_police_patrols_total")).toBe(
      "Inserisci un numero intero",
    );
    expect(problems.size).toBe(5);
  });

  it("un orario scritto male è un errore sul suo campo; uno corto si completa", () => {
    const draft = draftFromEvent(match);
    draft.arrival.start = "7pm";
    draft.departure.peak = "9:05";
    const bad = draftToInput(draft);
    expect(bad.ok).toBe(false);
    const problems = bad.ok ? [] : bad.problems;
    expect(problems).toEqual([
      { path: "arrival.start", message: "Usa ore e minuti, per esempio 18:30" },
    ]);
    draft.arrival.start = "16:00";
    const good = draftToInput(draft);
    expect(good.ok && good.input.departure.peak).toBe("09:05:00");
  });

  it("non applica le regole dell'Evento: il picco fuori dalla finestra lo dice l'API", () => {
    const draft = draftFromEvent(match);
    draft.arrival.peak = "23:30"; // dopo la fine
    draft.attendance.mid = "10"; // sotto il livello basso
    const result = draftToInput(draft);
    expect(result.ok).toBe(true);
  });

  it("chiusure, interruzioni e misure reali senza etichetta non partono", () => {
    const draft = draftFromEvent(match);
    draft.closures[0] = { ...draft.closures[0]!, label: " " };
    draft.disruptions[0] = { ...draft.disruptions[0]!, label: "" };
    draft.realMeasures = [{ label: "x", measure_type: "", target: "", source_ref: "s" }];
    const result = draftToInput(draft);
    const paths = result.ok ? [] : result.problems.map((p) => p.path);
    expect(paths).toEqual([
      "closures.0.label",
      "transit_disruptions.0.label",
      "real_measures.0.measure_type",
      "real_measures.0.target",
    ]);
  });

  it("la ripartizione modale: tutti vuoti = predefinita; uno compilato chiede gli altri", () => {
    const draft = draftFromEvent(match);
    draft.modalSplit.near = { car: "30", transit: "", walk: "" };
    const result = draftToInput(draft);
    const paths = result.ok ? [] : result.problems.map((p) => p.path);
    expect(paths).toEqual([
      "modal_split_override.near.transit_pct",
      "modal_split_override.near.walk_pct",
    ]);
    draft.modalSplit.near = { car: "30", transit: "20", walk: "50" };
    const ok = draftToInput(draft);
    expect(ok.ok && ok.input.modal_split_override).toEqual({
      near: { car_pct: 30, transit_pct: 20, walk_pct: 50 },
    });
  });

  it("ripartizione modale: basta un campo qualunque per chiedere gli altri due", () => {
    for (const [filled, missing] of [
      ["transit", ["car_pct", "walk_pct"]],
      ["walk", ["car_pct", "transit_pct"]],
    ] as const) {
      const draft = draftFromEvent(match);
      draft.modalSplit.far = { car: "", transit: "", walk: "", [filled]: "30" };
      const result = draftToInput(draft);
      const paths = result.ok ? [] : result.problems.map((p) => p.path);
      expect(paths).toEqual(missing.map((m) => `modal_split_override.far.${m}`));
    }
  });

  it("campi facoltativi: vuoti diventano null o spariscono", () => {
    const draft = draftFromEvent({ ...match, description: "x", sources: ["a"] });
    draft.description = "  ";
    draft.attendance.source = "";
    draft.centerLabel = "";
    draft.carOccupancy = "";
    draft.sources = ["a", "", "  ", "b"];
    const result = draftToInput(draft);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.input.description).toBeNull();
      expect(result.input.attendance.source_ref).toBeNull();
      expect(result.input.area_center.label).toBeNull();
      expect(result.input.car_occupancy).toBeNull();
      expect(result.input.sources).toEqual(["a", "b"]);
    }
  });

  it("il raggio proposto è quello del modello (OpenAPI)", () => {
    const radius = openApi() as unknown as {
      components: {
        schemas: { EventInput: { properties: { area_radius_m: { default: number } } } };
      };
    };
    expect(radius.components.schemas.EventInput.properties.area_radius_m.default).toBe(
      DEFAULT_RADIUS_M,
    );
    expect(emptyDraft().radius).toBe(String(DEFAULT_RADIUS_M));
  });
});

describe("sameDraft", () => {
  it("riconosce un form non modificato e uno modificato", () => {
    const a = draftFromEvent(match);
    expect(sameDraft(a, draftFromEvent(match))).toBe(true);
    expect(sameDraft(a, { ...a, name: `${a.name}!` })).toBe(false);
  });
});

describe("scelte sulla mappa", () => {
  it("withCenter: coordinate a 5 decimali e l'etichetta del vecchio luogo si svuota", () => {
    const moved = withCenter(draftFromEvent(match), 40.8321234, 14.2349876);
    expect(moved.centerLat).toBe("40.83212");
    expect(moved.centerLon).toBe("14.23499");
    expect(moved.centerLabel).toBe("");
  });

  describe("toggleEdge", () => {
    const draft = draftFromEvent(match);

    it("un arco nuovo apre una chiusura con il nome della strada, in modo «chiusa»", () => {
      const next = toggleEdge(draft, { edgeKey: "1-2-0", reverseKey: null, name: "Via Nuova" });
      expect(next.closures).toHaveLength(3);
      expect(next.closures[2]).toEqual({
        label: "Via Nuova",
        street_names: [],
        bbox: null,
        edge_keys: ["1-2-0"],
        mode: "closed",
        capacity_factor: 0,
        source_ref: null,
      });
      expect(draft.closures).toHaveLength(2); // l'originale non cambia
    });

    it("un secondo arco della stessa strada va nella stessa chiusura", () => {
      const once = toggleEdge(draft, { edgeKey: "1-2-0", reverseKey: null, name: "Via Nuova" });
      const twice = toggleEdge(once, { edgeKey: "2-1-0", reverseKey: null, name: "Via Nuova" });
      expect(twice.closures).toHaveLength(3);
      expect(twice.closures[2]?.edge_keys).toEqual(["1-2-0", "2-1-0"]);
    });

    it("un arco già chiuso si riapre, anche se lo chiudono due chiusure", () => {
      const once = toggleEdge(draft, {
        edgeKey: "18122092-8475097329-0",
        reverseKey: null,
        name: "x",
      });
      expect(closedEdgeKeys(once).has("18122092-8475097329-0")).toBe(false);
      expect(once.closures[0]?.edge_keys).toEqual(["8475097329-18122092-0"]);
      expect(once.closures[1]?.edge_keys).toEqual([
        "8399521491-8475097329-0",
        "8475097329-18122092-0",
        "8475097329-8399521499-0",
      ]);
    });

    it("una strada a due sensi si chiude e si riapre in entrambi i sensi, con una sola chiusura", () => {
      const road = { edgeKey: "1-2-0", reverseKey: "2-1-0", name: "Via Nuova" };
      const closed = toggleEdge(draft, road);
      expect(closed.closures).toHaveLength(3);
      expect(closed.closures[2]?.edge_keys).toEqual(["1-2-0", "2-1-0"]);
      const reopened = toggleEdge(closed, road);
      expect(reopened.closures).toHaveLength(2);
      expect(closedEdgeKeys(reopened).has("1-2-0")).toBe(false);
      expect(closedEdgeKeys(reopened).has("2-1-0")).toBe(false);
    });

    it("se è chiuso un solo senso, il clic riapre la strada (e non la chiude dall'altro lato)", () => {
      const one = toggleEdge(draft, { edgeKey: "2-1-0", reverseKey: null, name: "Via Nuova" });
      const road = { edgeKey: "1-2-0", reverseKey: "2-1-0", name: "Via Nuova" };
      const next = toggleEdge(one, road);
      expect(closedEdgeKeys(next).has("2-1-0")).toBe(false);
      expect(closedEdgeKeys(next).has("1-2-0")).toBe(false);
      expect(next.closures).toHaveLength(2);
      // lo stesso clic dato sul senso opposto (la feature ha l'altra chiave come principale)
      const back = toggleEdge(one, { edgeKey: "2-1-0", reverseKey: "1-2-0", name: "Via Nuova" });
      expect(closedEdgeKeys(back).has("2-1-0")).toBe(false);
    });

    it("una seconda strada con lo stesso nome entra nella stessa chiusura, con i suoi due sensi", () => {
      const first = toggleEdge(draft, { edgeKey: "1-2-0", reverseKey: "2-1-0", name: "Via Nuova" });
      const second = toggleEdge(first, {
        edgeKey: "5-6-0",
        reverseKey: "6-5-0",
        name: "Via Nuova",
      });
      expect(second.closures).toHaveLength(3);
      expect(second.closures[2]?.edge_keys).toEqual(["1-2-0", "2-1-0", "5-6-0", "6-5-0"]);
    });

    it("riaprire una strada toglie entrambi i sensi anche da chiusure diverse", () => {
      const named = toggleEdge(draft, { edgeKey: "9-8-0", reverseKey: null, name: "Altra" });
      const both = {
        ...named,
        closures: named.closures.map((c, i) =>
          i === 2 ? { ...c, edge_keys: ["9-8-0", "8-9-0"] } : c,
        ),
      };
      const next = toggleEdge(both, { edgeKey: "9-8-0", reverseKey: "8-9-0", name: "Altra" });
      expect(next.closures).toHaveLength(2);
    });

    it("riaprire un arco non tocca le chiusure che non lo contengono, nemmeno quelle dei soli nomi", () => {
      const named = {
        ...draft,
        closures: [
          ...draft.closures,
          {
            label: "Solo nomi",
            street_names: ["Via Roma"],
            bbox: null,
            edge_keys: [],
            mode: "closed" as const,
            capacity_factor: 0,
            source_ref: null,
          },
        ],
      };
      const next = toggleEdge(named, {
        edgeKey: "18122092-8475097329-0",
        reverseKey: null,
        name: "x",
      });
      expect(next.closures.map((c) => c.label)).toContain("Solo nomi");
      expect(next.closures).toHaveLength(3);
    });

    it("stessa cosa per le interruzioni: una senza fermate risolte resta", () => {
      const named = {
        ...draft,
        disruptions: [
          ...draft.disruptions,
          {
            label: "Per nome",
            stop_name: "Duomo",
            stop_ids: [],
            window: "both" as const,
            source_ref: null,
          },
        ],
      };
      const next = toggleStop(named, { stopId: "6236", name: "Arco Mirelli" });
      expect(next.disruptions.map((d) => d.label)).toContain("Per nome");
    });

    it("l'ultimo arco di una chiusura la fa sparire (non restano i soli nomi di strada)", () => {
      const one = toggleEdge(emptyDraft(), {
        edgeKey: "1-2-0",
        reverseKey: null,
        name: "Via Nuova",
      });
      expect(
        toggleEdge(one, { edgeKey: "1-2-0", reverseKey: null, name: "Via Nuova" }).closures,
      ).toEqual([]);
      const named = { ...one, closures: [{ ...one.closures[0]!, street_names: ["Via Nuova"] }] };
      expect(
        toggleEdge(named, { edgeKey: "1-2-0", reverseKey: null, name: "Via Nuova" }).closures,
      ).toEqual([]);
    });

    it("senza nome la chiusura si chiama con la chiave dell'arco", () => {
      const next = toggleEdge(emptyDraft(), { edgeKey: "9-9-0", reverseKey: null, name: "  " });
      expect(next.closures[0]?.label).toBe("9-9-0");
    });

    it("chiudere e riaprire lo stesso arco riporta al punto di partenza", () => {
      const there = toggleEdge(emptyDraft(), {
        edgeKey: "1-2-0",
        reverseKey: null,
        name: "Via Nuova",
      });
      expect(
        toggleEdge(there, { edgeKey: "1-2-0", reverseKey: null, name: "Via Nuova" }).closures,
      ).toEqual([]);
    });
  });

  describe("toggleStop", () => {
    const draft = draftFromEvent(match);

    it("una fermata nuova apre un'interruzione «<nome> chiusa» per entrambe le finestre", () => {
      const next = toggleStop(draft, { stopId: "77", name: "Piazza Cavour" });
      expect(next.disruptions).toHaveLength(2);
      expect(next.disruptions[1]).toEqual({
        label: "Piazza Cavour chiusa",
        stop_name: "Piazza Cavour",
        stop_ids: ["77"],
        window: "both",
        source_ref: null,
      });
    });

    it("le banchine con lo stesso nome stanno in una sola interruzione", () => {
      const once = toggleStop(emptyDraft(), { stopId: "1", name: "Centrale" });
      const twice = toggleStop(once, { stopId: "2", name: "Centrale" });
      expect(twice.disruptions).toHaveLength(1);
      expect(twice.disruptions[0]?.stop_ids).toEqual(["1", "2"]);
    });

    it("una fermata già interrotta si riapre; l'ultima fa sparire l'interruzione", () => {
      const once = toggleStop(draft, { stopId: "6236", name: "Arco Mirelli" });
      expect(once.disruptions[0]?.stop_ids).toEqual(["6237"]);
      expect(toggleStop(once, { stopId: "6237", name: "Arco Mirelli" }).disruptions).toEqual([]);
    });
  });
});

describe("slugFromName", () => {
  const none = new Set<string>();

  it.each([
    ["Serata Match 2027", "serata_match_2027"],
    ["Città — Festa & Co.", "citta_festa_co"],
    ["  già  ", "gia"],
    ["2027 Regate", "evento_2027_regate"],
    ["Ünïcode àèìòù", "unicode_aeiou"],
  ])("%j → %j", (name, slug) => {
    expect(slugFromName(name, none)).toBe(slug);
  });

  it("senza lettere o cifre non c'è un identificativo", () => {
    expect(slugFromName("", none)).toBe("");
    expect(slugFromName("— · —", none)).toBe("");
  });

  it("se esiste già ne cerca uno libero", () => {
    expect(slugFromName("Match", new Set(["match"]))).toBe("match_2");
    expect(slugFromName("Match", new Set(["match", "match_2", "match_3"]))).toBe("match_4");
  });

  it("l'identificativo risponde al modello dell'API (Slug)", () => {
    for (const name of ["Serata 1", "9 volte", "Ça va", "x"]) {
      expect(slugFromName(name, none)).toMatch(/^[a-z][a-z0-9_]*$/);
    }
  });
});
