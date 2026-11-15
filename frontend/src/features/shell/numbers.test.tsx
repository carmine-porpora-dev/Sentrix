import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "@/api/provider";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";
import { RUN, runClient } from "@/test/runPanels";

// F4-REF — «nessun numero senza MeasuredValue» (principio 2). Si guarda l'interfaccia com'è, con il run
// finito: ogni numero che compare da solo (un testo fatto di sole cifre) sta dentro un `MeasuredValue`
// (`data-measured`, con il suo tooltip di provenienza) oppure dichiara perché non lo è (`data-number`):
//   input     un valore che chi compila l'Evento ha scritto lui (livelli di affluenza)
//   ordinal   un numero d'ordine di una lista (le misure del piano)
//   clock     l'ora di una riga del registro
//   resource  le risorse dei dipartimenti (rimaste su totali): ECCEZIONE ACCETTATA, vedi sotto
// I numeri dentro una frase (testo degli agenti, delle misure, del registro) sono prosa del backend:
// quelli che contano hanno la loro evidenza con `MeasuredValue` accanto (07 6, decisione 9).
//
// ECCEZIONE ACCETTATA (proprietario, 11/11/2026, CHECKLIST F4-REFa): `ResourceBalance` dà conteggi, non
// `Measured`, e restano così sotto il badge SIMULATO della sezione. Se un giorno diventano `Measured`, la
// categoria `resource` sparisce da qui e il test deve dirlo.

const STANDALONE_NUMBER = /^[+−\-–]?\d[\d.,:]*\s*(%|pp)?$/;
const CATEGORIES = ["clock", "input", "ordinal", "resource"] as const;

interface Found {
  text: string;
  category: string | undefined;
  where: string;
}

/** Ogni testo fatto di sole cifre (con segno, separatori, % o pp) sotto `root`, e a che categoria
 * appartiene: `measured`, una `data-number`, o `undefined` se nessuna. I tooltip sono la provenienza. */
function standaloneNumbers(root: HTMLElement): Found[] {
  const found: Found[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = (node.textContent ?? "").trim();
    const element = node.parentElement;
    if (!element || !STANDALONE_NUMBER.test(text)) continue;
    const category = element.closest("[data-measured]")
      ? "measured"
      : element.closest("[role='tooltip']")
        ? "tooltip"
        : element.closest("[data-number]")?.getAttribute("data-number");
    found.push({
      text,
      category: category ?? undefined,
      where: `${element.tagName.toLowerCase()} in «${(element.parentElement?.textContent ?? "").slice(0, 60)}»`,
    });
  }
  return found;
}

async function openShell() {
  const made = runClient();
  render(
    <ApiProvider client={made.client}>
      <ShellProvider initial={{ runId: RUN }}>
        <AppShell />
      </ShellProvider>
    </ApiProvider>,
  );
  await screen.findByRole("heading", { name: strings.panels.agents.title });
  await waitFor(() => expect(screen.getAllByText("4.690").length).toBeGreaterThan(0));
}

/** Apre una scheda e aspetta i suoi dati (le richieste partono dopo che la scheda si è aperta). */
async function openTab(name: string, heading: string, loaded?: () => void) {
  fireEvent.click(screen.getByRole("tab", { name }));
  await screen.findByRole("heading", { name: heading });
  if (loaded) await waitFor(loaded);
}

describe("i numeri dell'interfaccia (F4-REF)", () => {
  it("ogni numero da solo è un MeasuredValue o dichiara la sua categoria, in tutte e tre le schede", async () => {
    await openShell();
    const seen = new Set<string>();
    const tabs: [string, string, () => void][] = [
      [strings.shell.tabs.agents, strings.panels.agents.title, () => undefined],
      [
        strings.shell.tabs.operations,
        strings.panels.ops.requests,
        () => expect(screen.getAllByText(strings.panels.ops.resources.patrols).length).toBe(1),
      ],
      [
        strings.shell.tabs.decisions,
        strings.panels.log.title,
        () => expect(screen.getAllByRole("row").length).toBeGreaterThan(5),
      ],
    ];
    for (const [name, heading, loaded] of tabs) {
      await openTab(name, heading, loaded);
      const found = standaloneNumbers(document.body);
      expect(found.length, name).toBeGreaterThan(0);
      const without = found.filter((item) => item.category === undefined);
      expect(
        without.map((item) => `${item.text} ← ${item.where}`),
        `${name}: numeri senza MeasuredValue e senza categoria`,
      ).toEqual([]);
      for (const item of found) if (item.category) seen.add(item.category);
    }
    // le categorie dichiarate sono tutte e sole quelle dell'inventario: una che sparisce o che compare
    // senza essere qui elencata è una decisione da prendere (e da scrivere nell'intestazione)
    expect([...seen].filter((c) => c !== "measured" && c !== "tooltip").sort()).toEqual([
      ...CATEGORIES,
    ]);
    expect(seen.has("measured")).toBe(true);
  });

  it("le fasce di numeri dei dati (metriche, evidenze, confronto) sono MeasuredValue", async () => {
    await openShell();
    await openTab(strings.shell.tabs.operations, strings.panels.ops.requests, () =>
      expect(screen.getAllByText(strings.panels.ops.resources.patrols).length).toBe(1),
    );
    const measured = document.body.querySelectorAll("[data-measured]");
    expect(measured.length).toBeGreaterThan(15);
    for (const element of measured) {
      expect(["real", "estimate", "simulated", "unavailable"]).toContain(
        element.getAttribute("data-measured"),
      );
    }
    // la fascia delle metriche e il confronto: i valori sono dentro un MeasuredValue
    const strip = screen.getByRole("region", { name: strings.metrics.regionLabel });
    expect(standaloneNumbers(strip).every((item) => item.category === "measured")).toBe(true);
    const table = screen.getByRole("table");
    expect(standaloneNumbers(table).every((item) => item.category === "measured")).toBe(true);
  });

  it("il rilevatore vede un numero nudo (prova della regola)", () => {
    const { container } = render(
      <div>
        <span>42</span>
        <span data-number="ordinal">1</span>
        <span data-measured="simulated">7,5</span>
        <p>Una frase con 12 numeri dentro</p>
      </div>,
    );
    const found = standaloneNumbers(container);
    expect(found.map((item) => [item.text, item.category])).toEqual([
      ["42", undefined],
      ["1", "ordinal"],
      ["7,5", "measured"],
    ]);
  });
});
