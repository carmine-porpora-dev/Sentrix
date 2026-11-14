import { readFile } from "node:fs/promises";
import {
  bar,
  expect,
  expectOnlyTokenColors,
  expectWithin,
  latestRunId,
  localEffects,
  login,
  mapRegion,
  metricValue,
  metrics,
  notifications,
  runView,
  settleMap,
  shot,
  test,
  waitForRunEnd,
  whole,
} from "./support.ts";

// F7-TEST: il ciclo del prodotto sul backend vero (dati veri, motori veri, `cache_only`) per i due
// eventi precaricati: evento → Analizza → piano → richieste → esiti → verifica → confronto → esportazione.
// Ogni numero che l'interfaccia mostra si confronta con quello che dà l'API.

const EVENTS = [
  { id: "match_2027", attendance: "150.000", realMeasures: false },
  { id: "regate_sep_2026", attendance: "40.000", realMeasures: true },
] as const;

for (const event of EVENTS) {
  test(`${event.id}: dal login all'esportazione sul backend vero`, async ({ page }, testInfo) => {
    // i tile arrivano dal backend, dietro la sessione, con le richieste a intervallo (206)
    const tileStatuses: number[] = [];
    page.on("response", (response) => {
      if (new URL(response.url()).pathname === "/tiles/napoli.pmtiles") {
        tileStatuses.push(response.status());
      }
    });

    await login(page);
    const picker = page.getByLabel("Evento", { exact: true });
    await picker.selectOption(event.id);
    await expect(picker).toHaveValue(event.id);
    await expect(page.getByText("preset", { exact: true })).toBeVisible();
    // senza analisi nessun numero: niente è inventato
    await expect(metrics(page).getByText("Nessuna analisi")).toHaveCount(5);
    await settleMap(page);
    expect(tileStatuses, "tile della base map").toContain(206);
    await shot(page, testInfo, `${event.id}-01-evento`);

    // --- Analizza: il run parte, l'Event Manager si comprime, lo stato avanza
    await page.getByRole("button", { name: "Analizza" }).click();
    await expect(page.locator("[data-layout='rail']")).toBeVisible();
    await expect(bar(page).getByText(/Iterazione \d di 3/)).toBeVisible();
    await waitForRunEnd(page);
    await settleMap(page);
    await shot(page, testInfo, `${event.id}-02-completato`);

    const runId = await latestRunId(page, event.id);
    const view = await runView(page, runId);
    expect(view.run.state).toBe("DONE");
    // la barra dice la passata corrente (indice dell'API + 1) su 3
    await expect(bar(page).getByText(`Iterazione ${view.run.iteration + 1} di 3`)).toBeVisible();

    // --- Agenti: i quattro hanno finito
    const panel = page.getByRole("tabpanel");
    for (const agent of [
      "Event & Demand Agent",
      "Traffic Agent",
      "Transit Agent",
      "Operations Agent",
    ]) {
      await expect(panel.getByText(agent, { exact: true })).toBeVisible();
    }
    await expect(panel.getByText("Timeout o errore")).toHaveCount(0);
    await expectOnlyTokenColors(page, `${event.id}: agenti`);

    // --- Metriche: le cinque card dicono ciò che dice l'API, con la provenienza di ognuna
    const last = view.run.iteration;
    const hoursBefore = whole(await metricValue(page, runId, 0, "road.departure.veh_hours"));
    const hoursAfter = whole(await metricValue(page, runId, last, "road.departure.veh_hours"));
    const edgesAfter = whole(
      await metricValue(page, runId, last, "road.departure.critical_edges.count"),
    );
    await expect(metrics(page)).toContainText(hoursBefore);
    await expect(metrics(page)).toContainText(hoursAfter);
    await expect(metrics(page)).toContainText(edgesAfter);
    await expect(metrics(page)).toContainText(event.attendance);
    await expect(metrics(page).getByText("SIMULATO")).toHaveCount(4);
    await expect(metrics(page).getByText("STIMA")).toHaveCount(1);
    await expect(metrics(page).getByText("Nessuna analisi")).toHaveCount(0);

    // il tooltip di provenienza: fonte, metodo, unità, ora del dato; quello del TPL dice l'ipotesi
    const cards = metrics(page).locator("[data-measured]:visible");
    await cards.first().hover();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toBeVisible();
    for (const label of ["Fonte", "Metodo", "Unità", "Ora del dato"]) {
      await expect(tooltip.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(tooltip).toHaveCSS("box-shadow", "none");
    await page.mouse.move(0, 0);
    await expect(tooltip).toHaveCount(0);
    await metrics(page)
      .locator(":scope > *")
      .filter({ hasText: /Carico TPL massimo/ })
      .locator("[data-measured]:visible")
      .first()
      .hover();
    await expect(page.getByRole("tooltip")).toContainText("primo itinerario disponibile");
    await page.mouse.move(0, 0);

    // --- Mappa: i marker hanno un nome (il bersaglio e lo stato), le chiusure il divieto
    const map = mapRegion(page);
    const names = await map
      .locator("button[aria-label]")
      .evaluateAll((els) => els.map((el) => el.getAttribute("aria-label") ?? ""));
    expect(names.filter((name) => name.startsWith("Chiusura:")).length).toBeGreaterThan(0);
    const requests = names.filter((name) =>
      /: (In corso|Completata|Accettata|Rifiutata)$/.test(name),
    );
    expect(requests.length, "marker delle richieste").toBeGreaterThan(0);
    expect(
      requests.filter((name) => name.startsWith(":")),
      "marker senza nome",
    ).toEqual([]);
    await expectWithin(
      map.getByRole("group", { name: "Legenda della congestione" }),
      map,
      "legenda",
    );
    await expectWithin(map.getByRole("link", { name: /OpenStreetMap/ }), map, "attribuzione");
    await expectWithin(map.getByRole("switch", { name: "Prima / Dopo" }), map, "Prima/Dopo");
    await expectWithin(map.getByRole("button", { name: "Livelli mappa" }), map, "livelli mappa");

    // --- Operations: il piano e le richieste, con i nomi dei dipartimenti dal registro
    await page.getByRole("tab", { name: "Operations" }).click();
    // le misure scartate (fuori dal tetto, o da RECONCILE) non sono nel piano: non si contano nel titolo
    const inPlan = view.plan.filter((item) => item.status !== "discarded").length;
    await expect(page.getByRole("heading", { name: `Piano — ${inPlan} misure` })).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(view.requests.length);
    await expect(page.getByRole("article").first()).toContainText("(virtuale)");
    const realMeasures = page.getByRole("region", { name: "Misure adottate nella realtà" });
    await expect(realMeasures).toHaveCount(event.realMeasures ? 1 : 0);
    if (event.realMeasures) {
      await expect(realMeasures.getByText("REALE").first()).toBeVisible();
    }
    // l'effetto locale delle misure stradali (02 7), uguale a quello dell'API: massimo v/c prima → dopo
    const local = await localEffects(page, runId, view.run.iteration);
    expect(local.length, "misure stradali con un effetto").toBeGreaterThan(0);
    for (const effect of local) {
      const card = page.getByRole("article", { name: effect.actionId, exact: true });
      await expect(card.getByText("Effetto locale")).toBeVisible();
      await expect(card).toContainText(
        `${whole(effect.before * 100)}→${whole(effect.after * 100)}%`,
      );
    }
    // le richieste senza un effetto da dire (l'avviso ai cittadini) non hanno la riga
    await expect(page.getByText("Effetto locale")).toHaveCount(local.length);

    // --- Servizi di emergenza (spech 12.3): un bollettino simulato per destinatario, dal run vero.
    // Partono dopo DONE, in secondo piano: la sezione compare quando ci sono.
    const emergency = page.getByRole("region", { name: "Servizi di emergenza" });
    await expect(emergency.getByRole("group")).toHaveCount(8);
    await expect(emergency.getByText("SIMULATO")).toBeVisible();
    await expect(emergency.getByText(/a nessun ente reale/)).toBeVisible();
    const bulletins = await notifications(page, runId, "emergency_bulletin");
    expect(bulletins, "un bollettino per destinatario").toHaveLength(8);
    expect(bulletins.every((n) => n.simulation && n.state === "DELIVERED")).toBe(true);
    const questura = emergency.getByRole("group", { name: "Questura di Napoli (sala operativa)" });
    await questura.getByRole("button", { name: "Mostra il bollettino" }).click();
    await expect(questura.getByText(/BOLLETTINO VIABILITÀ — SIMULATO/)).toBeVisible();
    await expect(questura).toContainText("Via Francesco Caracciolo"); // le chiusure dell'evento
    // «Conferma ricezione»: lo stato lo dice anche l'API, e la conferma entra nel registro
    await questura.getByRole("button", { name: "Conferma ricezione" }).click();
    await expect(questura.getByText("Ricezione confermata")).toBeVisible();
    await expect(questura.getByRole("button", { name: "Conferma ricezione" })).toHaveCount(0);
    const confirmed = await notifications(page, runId, "emergency_bulletin");
    expect(confirmed.filter((n) => n.state === "ACKNOWLEDGED")).toHaveLength(1);
    // nessun WhatsApp vero nei test: l'invio è spento e la riga lo dice
    const comms = page.getByRole("region", { name: "Comunicazioni" });
    await expect(comms).toContainText("WhatsApp · non inviato: invio disattivato");
    await shot(page, testInfo, `${event.id}-03-operations`);
    await expectOnlyTokenColors(page, `${event.id}: operations`);

    // --- Prima / Dopo: «Prima» è la situazione di partenza, senza variazioni
    const beforeAfter = map.getByRole("switch", { name: "Prima / Dopo" });
    await expect(beforeAfter).toHaveAttribute("aria-checked", "true");
    await beforeAfter.click();
    await expect(beforeAfter).toHaveAttribute("aria-checked", "false");
    await expect(metrics(page)).toContainText(hoursBefore);
    await expect(metrics(page).getByText("−")).toHaveCount(0);
    await settleMap(page);
    await shot(page, testInfo, `${event.id}-04-prima`);
    await beforeAfter.click();
    await expect(metrics(page)).toContainText(hoursAfter);

    // il confronto tra iterazioni: la colonna «Prima» è piena (era vuota prima di F7-02)
    const comparison = page.getByRole("table");
    await expect(comparison.getByRole("columnheader", { name: "Prima" })).toBeVisible();
    await expect(comparison.getByRole("row", { name: /Ore-veicolo/ })).toContainText(hoursBefore);

    // --- Decisioni: il registro e le tre esportazioni, uguali a ciò che dà l'API
    await page.getByRole("tab", { name: "Decisioni" }).click();
    await expect(page.getByText("Registro decisioni")).toBeVisible();
    await expect(page.locator("table tbody tr").first()).toBeVisible();
    await shot(page, testInfo, `${event.id}-05-decisioni`);

    const exported = async (label: string) => {
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.getByRole("button", { name: label }).click(),
      ]);
      return {
        name: download.suggestedFilename(),
        text: await readFile(await download.path(), "utf8"),
      };
    };
    const json = await exported("Esporta JSON");
    const document = JSON.parse(json.text) as {
      run: { id: string; state: string };
      metrics: unknown[];
      requests: unknown[];
      decisions: unknown[];
    };
    expect(document.run).toMatchObject({ id: runId, state: "DONE" });
    expect(document.requests).toHaveLength(view.requests.length);
    expect(document.metrics.length).toBeGreaterThan(0);
    expect(document.decisions.length).toBeGreaterThan(0);

    const metricsCsv = await exported("CSV metriche");
    const apiMetricsCsv = await (
      await page.request.get(`/api/runs/${runId}/export?format=csv&what=metrics`)
    ).text();
    expect(metricsCsv.name).toBe(`${runId}_metrics.csv`);
    expect(metricsCsv.text).toBe(apiMetricsCsv);
    expect(metricsCsv.text).toContain("road.departure.veh_hours");

    const edgesCsv = await exported("CSV archi critici");
    expect(edgesCsv.name).toBe(`${runId}_critical_edges.csv`);
    expect(edgesCsv.text.split("\n").length).toBeGreaterThan(2);
  });
}
