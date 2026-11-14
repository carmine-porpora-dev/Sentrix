import {
  expect,
  expectOnlyTokenColors,
  latestRunId,
  login,
  runView,
  shot,
  test,
  waitForRunEnd,
} from "./support.ts";

// F7-TEST: un run che va in errore sul backend vero (schermata 11). Un Evento con una chiusura che
// non si risolve su nessuna strada porta il run in `ERROR` all'analisi: l'interfaccia lo dice con
// parole leggibili (niente nome di classe Python, niente percorsi del server), riapre l'Event Manager
// e, corretto l'evento, un nuovo run arriva in fondo.

test("un evento con una chiusura che non si risolve: errore leggibile, poi si riparte", async ({
  page,
  allowedProblems,
}, testInfo) => {
  // senza analisi riuscita l'iterazione 0 non ha metriche: l'interfaccia le chiede e riceve 404
  // (è la risposta voluta, 06 5) e il browser la scrive in console
  allowedProblems.push(/^HTTP 404 GET \/api\/runs\/[^/]+\/(metrics|layers\/\w+)\?iteration=0$/);

  await login(page);

  // l'evento di prova: il Match 2027 con una chiusura su una strada che non esiste (un id per
  // risoluzione: il backend è lo stesso per tutta la prova e un id esiste una volta sola)
  const eventId = `prova_errore_${testInfo.project.name}`;
  const fields = (await (await page.request.get("/api/events/match_2027")).json()) as Record<
    string,
    unknown
  >;
  // i campi che il server scrive da sé non si rimandano
  for (const key of ["created_at", "updated_at", "revision"]) delete fields[key];
  const created = await page.request.post("/api/events", {
    data: {
      ...fields,
      id: eventId,
      name: "Prova errore",
      closures: [
        {
          label: "Via Che Non Esiste",
          street_names: ["Via Che Non Esiste"],
          source_ref: "prova e2e: una strada che non c'è",
        },
      ],
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  await page.reload();
  await page.getByLabel("Evento", { exact: true }).selectOption(eventId);

  await page.getByRole("button", { name: "Analizza" }).click();
  await waitForRunEnd(page, "Errore");
  const runId = await latestRunId(page, eventId);
  const view = await runView(page, runId);
  expect(view.run.state).toBe("ERROR");

  // il messaggio dice cosa non va, senza nome di classe né percorsi del server
  expect(view.run.error ?? "").toContain("Via Che Non Esiste");
  expect(view.run.error ?? "").not.toMatch(/ResolveError|Traceback|\/Users\/|\.graphml/);
  const agents = page.getByRole("tabpanel");
  await expect(agents.getByText("Analisi interrotta")).toBeVisible();
  await expect(agents.getByText("Correggi l'evento e premi Analizza per riprovare.")).toBeVisible();
  await expect(agents.getByText(/Via Che Non Esiste/).first()).toBeVisible();
  await expect(agents.getByText(/ResolveError|Traceback|\/Users\/|\.graphml/)).toHaveCount(0);

  // le quattro card del motore non hanno numeri: «Non disponibile», non un valore inventato;
  // la quinta, l'affluenza, viene dall'Evento e c'è comunque
  const strip = page.getByRole("region", { name: "Metriche" });
  await expect(strip.getByText("Non disponibile")).toHaveCount(4);
  await expect(strip).toContainText("150.000");

  // l'Event Manager si riapre da sé (schermata 11) con «Analizza» di nuovo attivo
  await expect(page.locator("[data-layout='open']")).toBeVisible();
  await expect(page.getByRole("button", { name: "Analizza" })).toBeEnabled();
  await shot(page, testInfo, "errore-01-run-in-errore");
  await expectOnlyTokenColors(page, "run in errore");

  // il registro lo racconta
  await page.getByRole("tab", { name: "Decisioni" }).click();
  await expect(page.locator("table tbody tr").filter({ hasText: "Run interrotto" })).toHaveCount(1);
  await shot(page, testInfo, "errore-02-registro");

  // si corregge l'evento (si sceglie quello buono) e si riparte: il run arriva in fondo
  await page.getByLabel("Evento", { exact: true }).selectOption("match_2027");
  await page.getByRole("button", { name: "Analizza" }).click();
  await waitForRunEnd(page);
  await page.getByRole("tab", { name: "Agenti" }).click();
  await expect(page.getByText("Analisi interrotta")).toHaveCount(0);
  await expect(strip.getByText("Non disponibile")).toHaveCount(0);
  await expect(strip.getByText("SIMULATO")).toHaveCount(4);
});
