import { expect, expectOnlyTokenColors, login, shot, test, waitForRunDone } from "./support.ts";

// La risposta manuale (04 5): con l'interruttore acceso il run si ferma finché chi usa l'interfaccia
// non ha accettato o rifiutato ogni richiesta ricevuta dai dipartimenti. Il mock fa lo stesso del
// backend: tiene il fotogramma delle richieste «Ricevuta» e riprende quando tutte hanno risposta.

test("risposta manuale: il run aspetta, Accetta e Rifiuta (con motivo), poi riprende", async ({
  page,
}, testInfo) => {
  await login(page);
  await page.getByRole("tab", { name: "Operations" }).click();

  // L'interruttore vale dal prossimo run: si accende prima di Analizza.
  const manual = page.getByRole("switch", { name: "Risposta manuale" });
  await expect(manual).toHaveAttribute("aria-checked", "false");
  await manual.click();
  await expect(manual).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Analizza" }).click();

  const first = page.getByRole("article", { name: "act_001" });
  const second = page.getByRole("article", { name: "act_002" });
  const third = page.getByRole("article", { name: "act_003" });

  // Le richieste arrivano ai dipartimenti e restano «Ricevuta», ognuna con i suoi due pulsanti.
  for (const request of [first, second, third]) {
    await expect(request.getByText("Ricevuta", { exact: true })).toBeVisible({ timeout: 40_000 });
    await expect(request.getByRole("button", { name: "Accetta" })).toBeVisible();
    await expect(request.getByRole("button", { name: "Rifiuta" })).toBeVisible();
  }
  await expect(page.getByRole("banner").getByText("In attesa risposte")).toBeVisible();
  await shot(page, testInfo, "15-risposta-manuale-attesa");

  // Il run aspetta davvero: dopo qualche polling (1 s l'uno) è ancora lì, non è andato avanti da solo.
  await page.waitForTimeout(3000);
  await expect(first.getByText("Ricevuta", { exact: true })).toBeVisible();
  await expect(page.getByRole("banner").getByText("In attesa risposte")).toBeVisible();
  await expect(page.getByRole("banner").getByText("Completato", { exact: true })).toHaveCount(0);

  // Accetta: la richiesta diventa accettata e perde i pulsanti; le altre aspettano ancora.
  await first.getByRole("button", { name: "Accetta" }).click();
  await expect(first.getByText("Accettata", { exact: true })).toBeVisible();
  await expect(first.getByRole("button", { name: "Accetta" })).toHaveCount(0);
  await expect(second.getByText("Ricevuta", { exact: true })).toBeVisible();

  // Rifiuta: servono il codice (del dipartimento) e il motivo. Senza motivo non parte nulla.
  await second.getByRole("button", { name: "Rifiuta" }).click();
  const code = await second.getByLabel("Codice del rifiuto").inputValue();
  expect(code).not.toBe("");
  await second.getByRole("button", { name: "Conferma il rifiuto" }).click();
  await expect(second.getByText("Scrivi il motivo del rifiuto")).toBeVisible();
  await expect(second.getByText("Ricevuta", { exact: true })).toBeVisible();
  await shot(page, testInfo, "16-risposta-manuale-rifiuto");
  await expectOnlyTokenColors(page, "modulo del rifiuto con l'errore");

  const reason = "Nessuna pattuglia libera nella finestra";
  await second.getByLabel("Motivo").fill(reason);
  await second.getByRole("button", { name: "Conferma il rifiuto" }).click();
  await expect(second.getByText("Rifiutata", { exact: true })).toBeVisible();
  await expect(second.getByText(code, { exact: true })).toBeVisible();
  await expect(second.getByText(reason)).toBeVisible();
  // Una richiesta aspetta ancora: il run non riprende.
  await expect(third.getByText("Ricevuta", { exact: true })).toBeVisible();
  await expect(page.getByRole("banner").getByText("In attesa risposte")).toBeVisible();
  await shot(page, testInfo, "17-risposta-manuale-risposte");

  // L'ultima risposta libera il run, che arriva in fondo (con la sequenza registrata del mock).
  await third.getByRole("button", { name: "Accetta" }).click();
  await waitForRunDone(page);
  await expect(page.getByRole("button", { name: "1 alternativa" })).toBeVisible();
});
