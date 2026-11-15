import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Badge, type BadgeKind } from "@/components/Badge";
import { MeasuredValue } from "@/components/MeasuredValue";
import { Provenance, ProvenanceTooltip } from "@/components/Provenance";
import { measured } from "@/test/measured";

describe("Badge", () => {
  it.each([
    ["real", "REALE", "border-data-real", "bg-badge-fill-real"],
    ["estimate", "STIMA", "border-data-estimate", "bg-badge-fill-estimate"],
    ["simulated", "SIMULATO", "border-data-simulated", "bg-badge-fill-simulated"],
    ["unavailable", "Non disponibile", "border-dashed", "bg-badge-fill-unavailable"],
    ["pending", "In attesa", "border-warning", "bg-badge-fill-pending"],
  ] as [BadgeKind, string, string, string][])(
    "%s dice «%s» con i colori del suo tipo",
    (kind, label, border, fill) => {
      render(<Badge kind={kind} />);
      const badge = screen.getByText(label);
      expect(badge).toHaveAttribute("data-kind", kind);
      expect(badge).toHaveClass(border, fill);
    },
  );

  it("le tre nature dei dati hanno tre colori diversi", () => {
    render(
      <>
        <Badge kind="real" />
        <Badge kind="estimate" />
        <Badge kind="simulated" />
      </>,
    );
    const texts = ["text-data-real", "text-data-estimate", "text-data-simulated"];
    ["REALE", "STIMA", "SIMULATO"].forEach((label, index) => {
      expect(screen.getByText(label)).toHaveClass(texts[index] as string);
    });
  });
});

describe("ProvenanceTooltip", () => {
  const show = (m = measured(), title = "Ore-veicolo") =>
    render(<ProvenanceTooltip measured={m} title={title} id="t1" />);
  const row = (name: string) => screen.getByText(name).parentElement as HTMLElement;

  it("fonte, metodo, input, unità, ora del dato e assunzioni", () => {
    show();
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveAttribute("id", "t1");
    expect(within(tip).getByText("Ore-veicolo")).toBeInTheDocument();
    // il testo si legge per intero anche se i numeri sono in elementi a parte (monospazio)
    expect(row("Fonte")).toHaveTextContent("engine.metrics v1");
    expect(row("Metodo")).toHaveTextContent("Σ archi v × t / 60");
    expect(row("Input")).toHaveTextContent("event e1 rev 3");
    expect(row("Input")).toHaveTextContent("osm 2026-11-07");
    expect(row("Ora del dato")).toHaveTextContent("09/11/2026 10:00");
    expect(row("Assunzioni")).toHaveTextContent("modello statico non calibrato");
  });

  it("il testo è nel carattere dell'interfaccia e solo i numeri sono in monospazio (design, schermata 12)", () => {
    show(measured({ source: "Evento match_2027 (revisione 1)", method: "Σ archi v × t / 60" }));
    const mono = (name: string) =>
      Array.from(row(name).querySelectorAll(".font-mono"), (el) => el.textContent);
    expect(mono("Fonte")).toEqual(["2027", "1"]); // nel nome dell'evento solo le cifre
    expect(mono("Metodo")).toEqual(["60"]);
    expect(row("Metodo").querySelector(".font-mono")?.className).toContain("whitespace-nowrap");
    // l'ora del dato è tutta cifre: tutta in monospazio
    expect(mono("Ora del dato")).toEqual(["09/11/2026 10:00"]);
  });

  it("più alto dello schermo si scorre (le metriche del TPL hanno una ventina di assunzioni)", () => {
    render(<ProvenanceTooltip measured={measured()} title="Ore-veicolo" id="t" />);
    expect(screen.getByRole("tooltip")).toHaveClass(
      "max-h-[calc(100vh-1rem)]",
      "overflow-y-auto",
      "overscroll-contain",
    );
  });

  it("è largo 340 px come nel design (`.nuo-prov`)", () => {
    show();
    expect(screen.getByRole("tooltip")).toHaveClass("w-[340px]");
  });

  it("c'è il badge della natura del dato", () => {
    show(measured({ kind: "estimate" }));
    expect(screen.getByText("STIMA")).toBeInTheDocument();
  });

  it("l'unità è quella del backend e, se si mostra diversa, come si mostra", () => {
    const { unmount } = show(measured({ unit: "veic·h" }));
    expect(row("Unità")).toHaveTextContent("veic·h (mostrato in ore-veicolo)");
    unmount();
    show(measured({ unit: "rapporto", value: 1.28 }));
    expect(row("Unità")).toHaveTextContent("rapporto (mostrato in %)");
  });

  it("un'unità che si mostra com'è non ha spiegazioni", () => {
    show(measured({ unit: "min", value: 36.2 }));
    expect(within(row("Unità")).getByText("min")).toBeInTheDocument();
  });

  it("senza assunzioni la riga non c'è", () => {
    show(measured({ assumptions: [] }));
    expect(screen.queryByText("Assunzioni")).not.toBeInTheDocument();
  });

  it("non mostra il valore: i numeri passano da MeasuredValue", () => {
    show(measured({ value: 1240 }));
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("1.240");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("1240");
  });
});

describe("Provenance", () => {
  const anchor = () => screen.getByTestId("anchor");
  const open = () => screen.queryByRole("tooltip");

  function setup() {
    return render(
      <Provenance measured={measured()} label="Ore-veicolo" data-testid="anchor">
        <span>1.240</span>
      </Provenance>,
    );
  }

  it("è raggiungibile con Tab e il tooltip non c'è finché non serve", () => {
    setup();
    expect(anchor()).toHaveAttribute("tabindex", "0");
    expect(open()).not.toBeInTheDocument();
    expect(anchor()).not.toHaveAttribute("aria-describedby");
  });

  describe("con il mouse", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });
    const wait = (ms: number) => act(() => vi.advanceTimersByTime(ms));

    it("lo apre; il tooltip descrive l'elemento; uscito il mouse si chiude dopo un attimo", () => {
      setup();
      fireEvent.mouseEnter(anchor());
      expect(open()).toBeInTheDocument();
      expect(anchor()).toHaveAttribute("aria-describedby", open()?.id);
      fireEvent.mouseLeave(anchor());
      expect(open()).toBeInTheDocument(); // non subito: il mouse può andare sul tooltip
      wait(149);
      expect(open()).toBeInTheDocument();
      wait(1);
      expect(open()).not.toBeInTheDocument();
      expect(anchor()).not.toHaveAttribute("aria-describedby");
    });

    it("dal numero al tooltip senza chiudersi (e si può scorrere); uscito dal tooltip, si chiude", () => {
      setup();
      fireEvent.mouseEnter(anchor());
      fireEvent.mouseLeave(anchor());
      wait(100);
      fireEvent.mouseEnter(open() as HTMLElement);
      wait(1000);
      expect(open()).toBeInTheDocument();
      fireEvent.mouseLeave(open() as HTMLElement);
      wait(149);
      expect(open()).toBeInTheDocument();
      wait(1);
      expect(open()).not.toBeInTheDocument();
    });

    it("se il mouse torna sul numero prima dello scadere, resta aperto", () => {
      setup();
      fireEvent.mouseEnter(anchor());
      fireEvent.mouseLeave(anchor());
      wait(100);
      fireEvent.mouseEnter(anchor());
      wait(1000);
      expect(open()).toBeInTheDocument();
    });

    it("il fuoco non aspetta: l'uscita dal fuoco chiude subito, e annulla l'attesa del mouse", () => {
      setup();
      fireEvent.mouseEnter(anchor());
      fireEvent.mouseLeave(anchor());
      fireEvent.blur(anchor());
      expect(open()).not.toBeInTheDocument();
      fireEvent.focus(anchor());
      wait(1000); // il vecchio timer non chiude il tooltip riaperto dal fuoco
      expect(open()).toBeInTheDocument();
    });

    it("smontato con la chiusura in attesa, non resta nessun timer", () => {
      const { unmount } = setup();
      fireEvent.mouseEnter(anchor());
      fireEvent.mouseLeave(anchor());
      unmount();
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  it("il fuoco lo apre e l'uscita dal fuoco lo chiude", () => {
    setup();
    fireEvent.focus(anchor());
    expect(open()).toBeInTheDocument();
    fireEvent.blur(anchor());
    expect(open()).not.toBeInTheDocument();
  });

  it("Esc lo chiude, un altro tasto no", () => {
    setup();
    fireEvent.focus(anchor());
    fireEvent.keyDown(anchor(), { key: "a" });
    expect(open()).toBeInTheDocument();
    fireEvent.keyDown(anchor(), { key: "Escape" });
    expect(open()).not.toBeInTheDocument();
  });

  it("sta nel documento, fuori dalla scheda: nessun contenitore lo taglia", () => {
    const { container } = setup();
    fireEvent.focus(anchor());
    expect(container).not.toContainElement(open());
    expect(document.body).toContainElement(open());
    expect(open()).toHaveClass("fixed", "z-50");
  });

  it("porta il titolo e i dati del Measured", () => {
    setup();
    fireEvent.focus(anchor());
    expect(within(open() as HTMLElement).getByText("Ore-veicolo")).toBeInTheDocument();
    expect(open()).toHaveTextContent("engine.metrics v1");
  });

  describe("posizione", () => {
    const rect = (left: number, top: number, width = 100, height = 40) =>
      ({
        left,
        top,
        right: left + width,
        bottom: top + height,
        width,
        height,
        x: left,
        y: top,
        toJSON: () => ({}),
      }) as DOMRect;
    let anchorRect: DOMRect;

    beforeEach(() => {
      vi.stubGlobal("innerWidth", 1000);
      vi.stubGlobal("innerHeight", 800);
      anchorRect = rect(100, 100);
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => anchorRect);
      Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
        configurable: true,
        get: () => 300,
      });
      Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
        configurable: true,
        get: () => 200,
      });
    });
    afterEach(() => {
      vi.unstubAllGlobals();
      vi.restoreAllMocks();
      Reflect.deleteProperty(HTMLElement.prototype, "offsetWidth");
      Reflect.deleteProperty(HTMLElement.prototype, "offsetHeight");
    });

    const place = () => {
      setup();
      act(() => {
        fireEvent.focus(anchor());
      });
      const tip = open() as HTMLElement;
      return { top: Number.parseFloat(tip.style.top), left: Number.parseFloat(tip.style.left) };
    };

    it("sotto l'elemento, allineato a sinistra", () => {
      expect(place()).toEqual({ top: 146, left: 100 }); // bottom 140 + 6
    });

    it("non esce a destra: si ferma a 8 px dal bordo", () => {
      anchorRect = rect(900, 100);
      expect(place().left).toBe(1000 - 300 - 8);
    });

    it("non esce a sinistra", () => {
      anchorRect = rect(-50, 100);
      expect(place().left).toBe(8);
    });

    it("se sotto non ci sta, va sopra", () => {
      anchorRect = rect(100, 650); // bottom 690 + 6 + 200 > 800 - 8
      expect(place().top).toBe(650 - 6 - 200);
    });

    it("dentro una card sta sotto la card, allineato al suo bordo sinistro (design, schermata 12)", () => {
      const card = document.createElement("div");
      card.dataset.tooltipAnchor = "";
      const number = rect(160, 120, 60, 20); // il numero sta dentro la card, più a destra e più in alto
      const host = rect(40, 80, 350, 146);
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
        this: HTMLElement,
      ) {
        return this === card ? host : number;
      });
      const { container } = render(
        <Provenance measured={measured()} label="Ore-veicolo">
          <span>4.690</span>
        </Provenance>,
        { container: document.body.appendChild(card) },
      );
      act(() => {
        fireEvent.focus(container.querySelector("[tabindex]") as HTMLElement);
      });
      const tip = open() as HTMLElement;
      expect(Number.parseFloat(tip.style.left)).toBe(40); // il bordo sinistro della card, non del numero
      expect(Number.parseFloat(tip.style.top)).toBe(80 + 146 + 6); // sotto la card, non sotto il numero
    });

    it("sopra non esce dall'alto", () => {
      vi.stubGlobal("innerHeight", 250);
      anchorRect = rect(100, 150); // sotto non ci sta; sopra: 150 - 6 - 200 < 8
      expect(place().top).toBe(8);
    });
  });
});

describe("MeasuredValue", () => {
  it("il valore in formato italiano con l'unità", () => {
    render(<MeasuredValue measured={measured({ value: 1240 })} label="Ore-veicolo" />);
    expect(screen.getByText("1.240")).toBeInTheDocument();
    expect(screen.getByText("ore-veicolo")).toBeInTheDocument();
  });

  it("senza unità se non c'è o se si chiede di nasconderla", () => {
    const { rerender } = render(
      <MeasuredValue measured={measured({ value: 12, unit: "n" })} label="Archi" />,
    );
    expect(screen.getByText("12").parentElement?.children).toHaveLength(1);
    rerender(<MeasuredValue measured={measured({ value: 1240 })} label="Ore" showUnit={false} />);
    expect(screen.queryByText("ore-veicolo")).not.toBeInTheDocument();
  });

  it("un rapporto è una percentuale", () => {
    render(<MeasuredValue measured={measured({ value: 1.28, unit: "rapporto" })} label="Carico" />);
    expect(screen.getByText("128")).toBeInTheDocument();
    expect(screen.getByText("%")).toBeInTheDocument();
  });

  it("ha il tooltip di provenienza con il titolo dato", () => {
    render(<MeasuredValue measured={measured()} label="Ore-veicolo" />);
    fireEvent.focus(screen.getByText("1.240").closest("[tabindex]") as HTMLElement);
    expect(within(screen.getByRole("tooltip")).getByText("Ore-veicolo")).toBeInTheDocument();
  });

  it("un testo (metrica qualitativa) si mostra com'è", () => {
    render(
      <MeasuredValue
        measured={measured({ value: "itinerario 1: A → B", unit: "testo" })}
        label="Itinerario"
      />,
    );
    expect(screen.getByText("itinerario 1: A → B")).toBeInTheDocument();
  });

  describe("variazione", () => {
    const delta = (value: number, unit = "veic·h") => measured({ value, unit });
    const view = (
      value: number,
      better: "lower" | "higher" | "none" = "lower",
      unit?: string,
      showUnit?: boolean,
    ) =>
      render(
        <MeasuredValue
          measured={delta(value, unit)}
          label="Ore"
          variant="delta"
          better={better}
          showUnit={showUnit}
        />,
      );
    const chip = () => screen.getByText(/[+−]?\d/).closest("[data-tone]") as HTMLElement;

    it("la freccia va nel verso della variazione: giù, su, nessuna (trattino)", () => {
      const { container, rerender } = view(-330);
      expect(container.querySelector("svg")).toHaveClass("lucide-arrow-down");
      rerender(<MeasuredValue measured={delta(12)} label="Ore" variant="delta" />);
      expect(container.querySelector("svg")).toHaveClass("lucide-arrow-up");
      rerender(<MeasuredValue measured={delta(0)} label="Ore" variant="delta" />);
      expect(container.querySelector("svg")).toHaveClass("lucide-minus");
    });

    it("una discesa dove meno è meglio è verde, con il segno meno vero", () => {
      view(-330);
      expect(screen.getByText("−330")).toBeInTheDocument();
      expect(chip()).toHaveAttribute("data-tone", "better");
      expect(chip()).toHaveClass("text-delta-better");
    });

    it("una salita dove meno è meglio è rossa, con il più", () => {
      view(12);
      expect(screen.getByText("+12")).toBeInTheDocument();
      expect(chip()).toHaveAttribute("data-tone", "worse");
      expect(chip()).toHaveClass("text-delta-worse");
    });

    it("dove più è meglio è il contrario", () => {
      view(12, "higher");
      expect(chip()).toHaveClass("text-delta-better");
    });

    it("senza verso, o senza variazione, è neutra", () => {
      view(12, "none");
      expect(chip()).toHaveClass("text-text-secondary");
    });

    it("una differenza che si arrotonda a zero è neutra e senza segno", () => {
      view(-0.004, "lower", "min");
      expect(screen.getByText("0,0")).toBeInTheDocument();
      expect(chip()).toHaveAttribute("data-tone", "neutral");
    });

    it("i rapporti sono punti percentuali", () => {
      view(-0.32, "lower", "rapporto");
      expect(screen.getByText("−32")).toBeInTheDocument();
      expect(screen.getByText("pp")).toBeInTheDocument();
    });

    it("l'unità si può nascondere", () => {
      view(-330, "lower", undefined, false);
      expect(screen.queryByText("ore-veicolo")).not.toBeInTheDocument();
    });

    it("ha anche lei il tooltip di provenienza", () => {
      view(-330);
      fireEvent.focus(chip());
      expect(screen.getByRole("tooltip")).toBeInTheDocument();
    });
  });
});
