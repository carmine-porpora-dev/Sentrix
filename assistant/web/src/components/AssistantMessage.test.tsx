import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Source } from "@/api/chat";
import { AssistantMessage } from "@/components/AssistantMessage";

const SOURCES: Source[] = [
  {
    label: "Tempo del percorso",
    kind: "simulated",
    as_of: "2026-09-26T13:30:00+02:00",
    value: "8,0 min",
  },
  { label: "Orari della linea", kind: "real", as_of: "2026-09-25T09:00:00+02:00" },
  { label: "Tempo a piedi", kind: "estimate", as_of: "" },
];

function renderMessage(overrides: Partial<Parameters<typeof AssistantMessage>[0]> = {}) {
  const onChoose = vi.fn();
  render(
    <AssistantMessage
      text="Domani [[strada:Via Caracciolo]] è chiusa dalle 6:00. Servono circa 8 min."
      sources={[]}
      choices={[]}
      showChoices
      disabled={false}
      onChoose={onChoose}
      {...overrides}
    />,
  );
  return { onChoose };
}

describe("AssistantMessage", () => {
  it("mostra le chip di entità e i numeri in monospazio, senza bolla", () => {
    renderMessage();
    const chip = document.querySelector("[data-chip='strada']");
    expect(chip).toHaveTextContent("Via Caracciolo");
    for (const value of ["6:00", "8 min"]) {
      const number = screen.getByText(value);
      expect(number).toHaveClass("font-mono", "font-semibold", "tabular-nums");
    }
  });

  it("le chip non sono pulsanti né raggiungibili con Tab", () => {
    renderMessage();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    const chip = document.querySelector("[data-chip]") as HTMLElement;
    expect(chip.tabIndex).toBe(-1);
  });

  it("i passi sono numerati da 1 anche se il testo ricomincia da un altro numero", () => {
    renderMessage({ text: "Ecco:\n\n4. Primo passo\n9. Secondo passo" });
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("1Primo passo");
    expect(items[1]).toHaveTextContent("2Secondo passo");
  });

  it("senza fonti non mostra il riquadro «Fonti»", () => {
    renderMessage();
    expect(screen.queryByRole("region", { name: "Fonti" })).not.toBeInTheDocument();
  });

  it("le fonti dicono natura, etichetta, valore e data di ogni dato", () => {
    renderMessage({ sources: SOURCES });
    const box = screen.getByRole("region", { name: "Fonti" });
    const rows = within(box).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("SIMULATOTempo del percorso8,0 mindati del 26/09/2026 13:30");
    expect(rows[0].querySelector("[data-kind]")).toHaveAttribute("data-kind", "simulated");
    expect(rows[1]).toHaveTextContent("REALEOrari della lineadati del 25/09/2026 09:00");
    expect(rows[2]).toHaveTextContent("STIMATempo a piedi");
    expect(rows[2]).not.toHaveTextContent("dati del");
  });

  it("le scelte rapide appaiono solo sull'ultima risposta e inviano la scelta", () => {
    const { onChoose } = renderMessage({ choices: ["Via Tasso", "Via Foria"] });
    const group = screen.getByRole("group", { name: "Scelte rapide" });
    fireEvent.click(within(group).getByRole("button", { name: "Via Foria" }));
    expect(onChoose).toHaveBeenCalledWith("Via Foria");
  });

  it("le scelte non si vedono se la risposta non è l'ultima", () => {
    renderMessage({ choices: ["Via Tasso"], showChoices: false });
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("le scelte si bloccano mentre si aspetta una risposta", () => {
    renderMessage({ choices: ["Via Tasso"], disabled: true });
    expect(screen.getByRole("button", { name: "Via Tasso" })).toBeDisabled();
  });
});
