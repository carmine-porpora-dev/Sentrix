import { readFile } from "node:fs/promises";
import type { Locator, Page } from "@playwright/test";
import {
  bar,
  expect,
  expectOnlyTokenColors,
  latestRunId,
  localEffects,
  login,
  runView,
  shot,
  test,
  whole,
} from "./support.ts";

// F7-TEST: la risposta manuale sul backend vero (04 5). Con l'interruttore acceso il run aspetta
// che chi usa l'interfaccia risponda a ogni richiesta ricevuta; un rifiuto fa ripianificare
// (alternativa dal catalogo, nuova simulazione) e, se anche le alternative sono rifiutate, il
// sistema si ferma e chiede una decisione umana (schermata 09).

/** Le alternative stanno dentro la scheda della richiesta che sostituiscono: la scheda che aspetta
 * una risposta è quella che ha direttamente i pulsanti. */
const waitingButton = (page: Page): Locator =>
  page.getByRole("button", { name: "Rifiuta", exact: true });

/** Il run è finito (`DONE`) secondo l'API: «Decisione richiesta» compare nella barra anche prima, a
 * run ancora in corso, perché dice che una misura aspetta una persona. */
async function runIsDone(page: Page): Promise<boolean> {
  const runs = (await (await page.request.get("/api/runs?event_id=match_2027")).json()) as {
    state: string;
  }[];
  return runs[0]?.state === "DONE";
}

type Answer = "accept" | "reject";

/** Risponde a ogni richiesta «Ricevuta» finché il run non finisce (`done`) o passano 2 minuti. */
async function answer(
  page: Page,
  decide: (request: { id: string; text: string }) => Answer,
  done: () => Promise<boolean>,
): Promise<void> {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (await done()) return;
    if ((await waitingButton(page).count()) === 0) {
      await page.waitForTimeout(500);
      continue;
    }
    const own = waitingButton(page).first().locator("xpath=ancestor::article[1]");
    const id = (await own.getAttribute("aria-label")) ?? "";
    const card = page.getByRole("article", { name: id, exact: true });
    const text = await own.innerText();
    if (decide({ id, text }) === "accept") {
      await card.getByRole("button", { name: "Accetta", exact: true }).click();
    } else {
      await card.getByRole("button", { name: "Rifiuta", exact: true }).click();
      await card.getByLabel("Motivo").fill("Nessuna pattuglia libera nella finestra");
      await card.getByRole("button", { name: "Conferma il rifiuto" }).click();
    }
    // la richiesta ha avuto risposta: non è più in attesa (e il polling lo rilegge)
    await expect(card.getByRole("button", { name: "Rifiuta", exact: true })).toHaveCount(0);
  }
  throw new Error("il run non è finito entro 2 minuti");
}

const isFirstRequest = ({ id }: { id: string }) => id.endsWith("_001");
const isAlternative = ({ text }: { text: string }) => text.includes("Alternativa a ");

async function startManualRun(page: Page): Promise<void> {
  await login(page);
  await page.getByRole("tab", { name: "Operations" }).click();
  const manual = page.getByRole("switch", { name: "Risposta manuale" });
  await expect(manual).toHaveAttribute("aria-checked", "false");
  await manual.click();
  await expect(manual).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Analizza" }).click();
}

test("rifiuto con alternativa: il run aspetta, rifiuta, ripianifica e verifica", async ({
  page,
}, testInfo) => {
  await startManualRun(page);

  // le richieste arrivano ai dipartimenti e restano «Ricevuta»: il run aspetta
  await expect(bar(page).getByText("In attesa risposte")).toBeVisible({ timeout: 60_000 });
  await expect(waitingButton(page).first()).toBeVisible();
  await shot(page, testInfo, "rifiuto-01-attesa");
  await page.waitForTimeout(3000);
  await expect(bar(page).getByText("In attesa risposte")).toBeVisible();
  await expect(bar(page).getByText("Completato", { exact: true })).toHaveCount(0);

  // senza motivo il rifiuto non parte
  const first = page.getByRole("article", { name: /act_[0-9a-f]+_001/ });
  await expect(first).toBeVisible();
  await first.getByRole("button", { name: "Rifiuta", exact: true }).click();
  await expect(first.getByLabel("Codice del rifiuto")).not.toHaveValue("");
  await first.getByRole("button", { name: "Conferma il rifiuto" }).click();
  await expect(first.getByText("Scrivi il motivo del rifiuto")).toBeVisible();
  await expect(first.getByText("Ricevuta", { exact: true })).toBeVisible();
  await first.getByRole("button", { name: "Annulla" }).click();

  // il primo presidio è rifiutato, tutto il resto accettato (anche l'alternativa che ne nasce)
  await answer(
    page,
    (request) => (isFirstRequest(request) ? "reject" : "accept"),
    () => runIsDone(page),
  );
  await expect(bar(page).getByText("Iterazione 3 di 3")).toBeVisible();

  const runId = await latestRunId(page, "match_2027");
  const view = await runView(page, runId);
  expect(view.run.state).toBe("DONE");
  expect(view.run.replans).toBeGreaterThanOrEqual(1);
  const rejected = view.requests.map((r) => r.request).filter((r) => r.state === "REJECTED");
  expect(rejected).toHaveLength(1);
  expect(rejected[0]?.reject_code).toBe("UNAVAILABLE");

  // Operations: la rifiutata col codice, il motivo e l'alternativa che ne è nata
  const rejectedCard = page.getByRole("article", { name: rejected[0]?.action_id });
  await expect(rejectedCard.getByText("Rifiutata", { exact: true })).toBeVisible();
  await expect(rejectedCard.getByText("UNAVAILABLE")).toBeVisible();
  await expect(rejectedCard.getByText("Nessuna pattuglia libera nella finestra")).toBeVisible();
  await expect(page.getByRole("button", { name: "1 alternativa" })).toBeVisible();
  await expect(page.getByText(/Sostituita dalla misura \d+/)).toBeVisible();
  await rejectedCard.scrollIntoViewIfNeeded();
  await shot(page, testInfo, "rifiuto-02-operations");
  await expectOnlyTokenColors(page, "operations con il rifiuto");

  // la misura sostitutiva (cambio di piano semaforico) dice il suo effetto locale: il motore lo calcola
  // all'iterazione in cui entra in vigore (la 2), prima → dopo, e il v/c dell'arco favorito scende
  const replacementId = view.requests.find((r) => r.request.alternative_of)?.request.action_id;
  expect(replacementId).toBeDefined();
  const effects = await localEffects(page, runId, view.run.iteration);
  const mine = effects.find((e) => e.actionId === replacementId);
  expect(mine, "effetto della misura sostitutiva").toBeDefined();
  expect(mine?.after).toBeLessThan(mine?.before ?? 0);
  const replacement = page.getByRole("article", { name: replacementId, exact: true });
  await expect(replacement.getByText("Effetto locale")).toBeVisible();
  await expect(replacement).toContainText(
    `${whole((mine?.before ?? 0) * 100)}→${whole((mine?.after ?? 0) * 100)}%`,
  );

  // il confronto ha una colonna per iterazione: Prima, 2 e 3
  const comparison = page.getByRole("table");
  for (const name of ["Prima", "Iterazione 2", "Iterazione 3"]) {
    await expect(comparison.getByRole("columnheader", { name })).toBeVisible();
  }
  await comparison.scrollIntoViewIfNeeded();
  await shot(page, testInfo, "rifiuto-03-confronto");

  // Decisioni: il rifiuto è nel registro, con chi l'ha preso
  await page.getByRole("tab", { name: "Decisioni" }).click();
  const row = page.locator("table tbody tr").filter({ hasText: "rifiutata (UNAVAILABLE)" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Utente");
  await shot(page, testInfo, "rifiuto-04-decisioni");

  // l'esportazione porta lo stesso rifiuto
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Esporta JSON" }).click(),
  ]);
  const document = JSON.parse(await readFile(await download.path(), "utf8")) as {
    decisions: { actor: string; decision: string }[];
  };
  expect(
    document.decisions.some((d) => d.actor === "user" && d.decision.includes("UNAVAILABLE")),
  ).toBeTruthy();
});

test("rifiuti a catena: il sistema si ferma e chiede una decisione umana", async ({
  page,
}, testInfo) => {
  await startManualRun(page);
  await expect(bar(page).getByText("In attesa risposte")).toBeVisible({ timeout: 60_000 });

  // il primo presidio e ogni alternativa che ne nasce sono rifiutati; il resto accettato
  await answer(
    page,
    (request) => (isFirstRequest(request) || isAlternative(request) ? "reject" : "accept"),
    () => runIsDone(page),
  );
  await expect(bar(page).getByText("Decisione richiesta")).toBeVisible();

  const runId = await latestRunId(page, "match_2027");
  const view = await runView(page, runId);
  expect(view.run.state).toBe("DONE");
  expect(view.plan.some((item) => item.status === "human_decision_required")).toBeTruthy();
  const rejected = view.requests.map((r) => r.request).filter((r) => r.state === "REJECTED");
  expect(rejected.length).toBeGreaterThanOrEqual(2);

  // Operations: il riquadro in evidenza per primo, poi le richieste (schermata 09)
  await page.getByRole("tab", { name: "Operations" }).click();
  const box = page.getByText("Decisione umana richiesta", { exact: true });
  await expect(box).toBeVisible();
  const headings = await page.getByRole("heading").allInnerTexts();
  expect(headings.indexOf("Decisione umana richiesta")).toBeLessThan(
    headings.indexOf("Richieste operative"),
  );
  await expect(page.getByText("Decisione umana", { exact: true }).first()).toBeVisible();
  await box.scrollIntoViewIfNeeded();
  await shot(page, testInfo, "decisione-umana-01-operations");
  await expectOnlyTokenColors(page, "decisione umana richiesta");

  // l'esportazione serve ancora: il run è DONE
  await page.getByRole("tab", { name: "Decisioni" }).click();
  await expect(page.getByRole("button", { name: "Esporta JSON" })).toBeEnabled();
  await shot(page, testInfo, "decisione-umana-02-decisioni");
});
