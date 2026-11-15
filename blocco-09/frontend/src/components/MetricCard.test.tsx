import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricCard } from "@/components/MetricCard";
import { measured } from "@/test/measured";

const value = measured({
  id: "m.r.it2.road.departure.veh_hours",
  value: 4690,
  unit: "veic·h",
  source: "engine-after",
});
const before = measured({
  id: "m.r.it0.road.departure.veh_hours",
  value: 4820,
  unit: "veic·h",
  source: "engine-before",
});
const delta = measured({
  id: "m.r.it2.delta_baseline.road.departure.veh_hours",
  value: -130,
  unit: "veic·h",
  source: "engine-delta",
});

/** Apre il tooltip del numero e dice da quale fonte viene. */
function sourceOf(text: string | RegExp): string {
  const anchor = screen.getByText(text).closest("[tabindex]") as HTMLElement;
  fireEvent.focus(anchor);
  const source = within(screen.getByRole("tooltip")).getByText(/^engine-/).textContent ?? "";
  fireEvent.blur(anchor);
  return source;
}

describe("MetricCard pronta", () => {
  it("etichetta, valore con unità e badge della sua natura", () => {
    render(<MetricCard label="Ore-veicolo" value={value} />);
    expect(screen.getByText("Ore-veicolo")).toBeInTheDocument();
    expect(screen.getByText("4.690")).toBeInTheDocument();
    expect(screen.getByText("ore-veicolo")).toBeInTheDocument();
    expect(screen.getByText("SIMULATO")).toHaveAttribute("data-kind", "simulated");
  });

  it("il badge segue il kind del valore", () => {
    const { rerender } = render(<MetricCard label="x" value={measured({ kind: "real" })} />);
    expect(screen.getByText("REALE")).toBeInTheDocument();
    rerender(<MetricCard label="x" value={measured({ kind: "estimate" })} />);
    expect(screen.getByText("STIMA")).toBeInTheDocument();
  });

  it("«prima → dopo», con la variazione", () => {
    render(<MetricCard label="Ore-veicolo" value={value} before={before} delta={delta} />);
    expect(screen.getByText("4.820")).toBeInTheDocument();
    expect(screen.getByText("4.690")).toBeInTheDocument();
    expect(screen.getByText("−130")).toBeInTheDocument();
    // la variazione è sulla riga sotto, con il suo colore
    expect(screen.getByText("−130").closest("[data-tone]")).toHaveAttribute("data-tone", "better");
  });

  it("«prima → dopo» sta solo da 1440 px in su: sotto non c'è posto e resta la variazione", () => {
    const { container } = render(
      <MetricCard label="Ore-veicolo" value={value} before={before} delta={delta} />,
    );
    const beforeValue = screen.getByText("4.820").closest("[tabindex]") as HTMLElement;
    expect(beforeValue).toHaveClass("hidden", "compact:inline");
    expect(container.querySelector("svg.lucide-arrow-right")).toHaveClass(
      "hidden",
      "compact:block",
    );
    expect(screen.getByText("4.690").closest("[tabindex]")).not.toHaveClass("hidden");
    expect(screen.getByText("−130").closest("[tabindex]")).not.toHaveClass("hidden");
  });

  it("il «prima» ha un solo valore, senza unità (c'è già quella del dopo)", () => {
    render(<MetricCard label="Ore-veicolo" value={value} before={before} />);
    expect(screen.getAllByText("ore-veicolo")).toHaveLength(1);
  });

  it("senza «prima» né variazione ci sono solo valore e badge", () => {
    render(<MetricCard label="Ore-veicolo" value={value} />);
    expect(screen.queryByText("4.820")).not.toBeInTheDocument();
    expect(screen.queryByText(/−130/)).not.toBeInTheDocument();
  });

  it("l'unità lunga non sta accanto alla variazione, quella corta sì", () => {
    const { rerender } = render(<MetricCard label="Ore" value={value} delta={delta} />);
    expect(screen.getAllByText("ore-veicolo")).toHaveLength(1); // solo accanto al valore
    rerender(
      <MetricCard
        label="Tempo"
        value={measured({ value: 36.2, unit: "min" })}
        delta={measured({ value: -2.2, unit: "min" })}
      />,
    );
    expect(screen.getAllByText("min")).toHaveLength(2);
  });

  it("in un rapporto, la variazione è in punti percentuali", () => {
    render(
      <MetricCard
        label="Carico TPL massimo"
        value={measured({ value: 0.96, unit: "rapporto", kind: "estimate" })}
        delta={measured({ value: -0.32, unit: "rapporto" })}
      />,
    );
    expect(screen.getByText("96")).toBeInTheDocument();
    expect(screen.getByText("−32")).toBeInTheDocument();
    expect(screen.getByText("pp")).toBeInTheDocument();
  });

  it("il verso decide il colore: dove più è meglio, salire è verde", () => {
    render(
      <MetricCard
        label="x"
        value={measured({ value: 10, unit: "n" })}
        delta={measured({ value: 4, unit: "n" })}
        better="higher"
      />,
    );
    expect(screen.getByText("+4").closest("[data-tone]")).toHaveAttribute("data-tone", "better");
  });

  it("per default meno è meglio: salire è rosso", () => {
    render(
      <MetricCard
        label="x"
        value={measured({ value: 10, unit: "n" })}
        delta={measured({ value: 4, unit: "n" })}
      />,
    );
    expect(screen.getByText("+4").closest("[data-tone]")).toHaveAttribute("data-tone", "worse");
  });

  it("un secondo numero (i km degli archi critici) accanto al valore, separato", () => {
    render(
      <MetricCard
        label="Archi critici"
        value={measured({ value: 3, unit: "n" })}
        secondary={measured({ value: 2.2, unit: "km" })}
        secondaryLabel="Archi critici (km)"
      />,
    );
    expect(screen.getByText("2,2")).toBeInTheDocument();
    expect(screen.getByText("km")).toBeInTheDocument();
    expect(screen.getByText("·")).toBeInTheDocument();
  });

  it("una precisazione accanto all'etichetta", () => {
    render(
      <MetricCard
        label="Carico TPL massimo"
        hint="Linea 6"
        value={measured({ value: 1.1, unit: "rapporto" })}
      />,
    );
    expect(screen.getByText(/Carico TPL massimo/)).toHaveTextContent(
      "Carico TPL massimo · Linea 6",
    );
  });

  it("senza «prima» il valore principale è l'unico numero grande", () => {
    render(<MetricCard label="x" value={value} />);
    expect(screen.getByText("4.690").closest("[tabindex]")).toBeInTheDocument();
  });
});

describe("ogni numero ha la sua provenienza", () => {
  it("valore, prima, variazione e badge aprono ciascuno il tooltip del loro Measured", () => {
    render(<MetricCard label="Ore-veicolo" value={value} before={before} delta={delta} />);
    expect(sourceOf("4.690")).toBe("engine-after");
    expect(sourceOf("4.820")).toBe("engine-before");
    expect(sourceOf("−130")).toBe("engine-delta");
    expect(sourceOf("SIMULATO")).toBe("engine-after");
  });

  it("i titoli dicono che cosa è: il «prima» e la variazione lo dichiarano", () => {
    render(<MetricCard label="Ore-veicolo" value={value} before={before} delta={delta} />);
    fireEvent.focus(screen.getByText("4.820").closest("[tabindex]") as HTMLElement);
    expect(
      within(screen.getByRole("tooltip")).getByText(
        /Ore-veicolo \(rispetto alla situazione senza misure\)/,
      ),
    ).toBeInTheDocument();
    fireEvent.blur(screen.getByText("4.820").closest("[tabindex]") as HTMLElement);
    fireEvent.focus(screen.getByText("−130").closest("[tabindex]") as HTMLElement);
    expect(
      within(screen.getByRole("tooltip")).getByText(
        /variazione rispetto alla situazione senza misure/,
      ),
    ).toBeInTheDocument();
  });

  it("il secondo numero usa il suo titolo", () => {
    render(
      <MetricCard
        label="Archi critici"
        value={measured({ value: 3, unit: "n" })}
        secondary={measured({ value: 2.2, unit: "km", source: "engine-km" })}
        secondaryLabel="Archi critici (km)"
      />,
    );
    fireEvent.focus(screen.getByText("2,2").closest("[tabindex]") as HTMLElement);
    expect(within(screen.getByRole("tooltip")).getByText("Archi critici (km)")).toBeInTheDocument();
  });
});

describe("MetricCard senza numeri", () => {
  it("in caricamento: occupata, senza numeri né badge", () => {
    const { container } = render(<MetricCard label="Ore-veicolo" state="loading" />);
    expect(container.firstElementChild).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Ore-veicolo")).toBeInTheDocument();
    expect(screen.getByText("In caricamento…")).toBeInTheDocument();
    expect(screen.queryByText(/SIMULATO|STIMA|REALE|Non disponibile/)).not.toBeInTheDocument();
  });

  it("senza analisi: un trattino e «Nessuna analisi», nessun badge", () => {
    render(<MetricCard label="Ore-veicolo" state="empty" />);
    expect(screen.getByLabelText("Non disponibile")).toHaveTextContent("—");
    expect(screen.getByText("Nessuna analisi")).toBeInTheDocument();
    expect(screen.queryByText(/SIMULATO|STIMA|REALE|Non disponibile$/)).not.toBeInTheDocument();
  });

  it("non disponibile: un trattino e il badge «Non disponibile»", () => {
    render(<MetricCard label="Ore-veicolo" state="unavailable" />);
    expect(screen.getByText("Non disponibile", { selector: "[data-kind]" })).toHaveAttribute(
      "data-kind",
      "unavailable",
    );
    expect(screen.queryByText("Nessuna analisi")).not.toBeInTheDocument();
  });

  it("pronta ma senza valore: non disponibile, non una scheda vuota", () => {
    render(<MetricCard label="Ore-veicolo" state="ready" />);
    expect(screen.getByText("Non disponibile", { selector: "[data-kind]" })).toBeInTheDocument();
  });

  it("una nota al posto di «Nessuna analisi»", () => {
    render(<MetricCard label="x" state="empty" note="Scegli un evento" />);
    expect(screen.getByText("Scegli un evento")).toBeInTheDocument();
    expect(screen.queryByText("Nessuna analisi")).not.toBeInTheDocument();
  });
});

describe("MetricCard: il tooltip sta sotto la card (design, schermata 12)", () => {
  it("ogni stato della card è l'àncora del tooltip dei suoi numeri", () => {
    const states = [
      <MetricCard key="r" label="Ore-veicolo" state="ready" value={value} />,
      <MetricCard key="l" label="Ore-veicolo" state="loading" />,
      <MetricCard key="e" label="Ore-veicolo" state="empty" />,
      <MetricCard key="u" label="Ore-veicolo" state="unavailable" />,
    ];
    for (const card of states) {
      const { container, unmount } = render(card);
      expect(container.firstElementChild).toHaveAttribute("data-tooltip-anchor");
      unmount();
    }
  });
});
