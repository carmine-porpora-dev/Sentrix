import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  LayerPanel,
  LayerToggleButton,
  MapAttribution,
  MapLegend,
  ClosureSymbol,
  SensorSymbol,
  MapMarker,
  MapToggle,
  type LayerItem,
} from "@/components/MapControls";
import { strings } from "@/i18n/it";

const copy = strings.map;

describe("LayerToggleButton", () => {
  it("apre e chiude: aria-expanded dice com'è", () => {
    const onToggle = vi.fn();
    const { rerender } = render(<LayerToggleButton open={false} onToggle={onToggle} />);
    const button = screen.getByRole("button", { name: copy.layersButton });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(<LayerToggleButton open onToggle={onToggle} />);
    expect(screen.getByRole("button", { name: copy.layersButton })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});

describe("LayerPanel", () => {
  const items: LayerItem[] = [
    { id: "a", name: "Congestione", on: true, color: "var(--color-map-congestion-3)" },
    { id: "b", name: "Chiusure", on: false, color: "var(--color-map-closure)", dashed: true },
  ];

  it("una casella per livello, con lo stato; il clic dice quale", () => {
    const onToggle = vi.fn();
    render(<LayerPanel layers={items} onToggle={onToggle} />);
    const group = screen.getByRole("group", { name: copy.layersTitle });
    const boxes = within(group).getAllByRole("checkbox");
    expect(boxes.map((b) => [b.textContent, b.getAttribute("aria-checked")])).toEqual([
      ["Congestione", "true"],
      ["Chiusure", "false"],
    ]);
    fireEvent.click(boxes[1] as HTMLElement);
    expect(onToggle).toHaveBeenCalledWith("b");
  });

  it("il campione ha il colore del livello; quello tratteggiato lo è; spento è attenuato", () => {
    render(<LayerPanel layers={items} onToggle={() => undefined} />);
    const swatches = document.querySelectorAll<HTMLElement>("[style*='--swatch']");
    expect(swatches).toHaveLength(2);
    expect(swatches[0]?.style.getPropertyValue("--swatch")).toBe("var(--color-map-congestion-3)");
    expect(swatches[0]).not.toHaveAttribute("data-dashed");
    expect(swatches[0]?.className).not.toContain("repeating-linear-gradient");
    expect(swatches[1]).toHaveAttribute("data-dashed", "true");
    expect(swatches[1]?.className).toContain("repeating-linear-gradient");
    expect(swatches[0]).not.toHaveClass("opacity-40");
    expect(swatches[1]).toHaveClass("opacity-40");
  });

  it("le opzioni della vista stanno sotto i livelli, con la casella ma senza campione", () => {
    const onOption = vi.fn();
    render(
      <LayerPanel
        layers={items}
        onToggle={() => undefined}
        options={[{ id: "presentation", name: "Vista presentazione", on: true }]}
        onOption={onOption}
      />,
    );
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes.map((b) => b.textContent)).toEqual([
      "Congestione",
      "Chiusure",
      "Vista presentazione",
    ]);
    const option = boxes[2] as HTMLElement;
    expect(option).toHaveAttribute("aria-checked", "true");
    expect(option.querySelector("[style*='--swatch']")).toBeNull();
    expect(option.querySelector("svg")).not.toBeNull(); // la spunta
    expect(boxes[1]?.querySelector("svg")).toBeNull(); // spento: nessuna spunta
    fireEvent.click(option);
    expect(onOption).toHaveBeenCalledWith("presentation");
  });

  it("senza opzioni non c'è il separatore", () => {
    render(<LayerPanel layers={items} onToggle={() => undefined} />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });
});

describe("MapToggle (Prima / Dopo)", () => {
  function setup(after: boolean, iteration = 2, iterations = 3) {
    const onAfterChange = vi.fn();
    const onIterationChange = vi.fn();
    render(
      <MapToggle
        after={after}
        onAfterChange={onAfterChange}
        iteration={iteration}
        onIterationChange={onIterationChange}
        iterations={iterations}
        label={copy.iteration(iteration + 1)}
      />,
    );
    return { onAfterChange, onIterationChange };
  }

  it("l'interruttore dice dove si è e passa all'altro stato", () => {
    const { onAfterChange } = setup(true);
    const toggle = screen.getByRole("switch", { name: copy.beforeAfter });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    expect(onAfterChange).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByRole("button", { name: copy.before }));
    expect(onAfterChange).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByRole("button", { name: copy.after }));
    expect(onAfterChange).toHaveBeenLastCalledWith(true);
  });

  it("«Prima»: l'interruttore è spento e il selettore dell'iterazione disattivato", () => {
    setup(false);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("button", { name: copy.previousIteration })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.nextIteration })).toBeDisabled();
  });

  it("mostra l'iterazione e la cambia con le frecce, a giro da 1 a n", () => {
    const { onIterationChange } = setup(true, 2, 3);
    expect(screen.getByText(copy.iteration(3))).toBeInTheDocument(); // il testo lo dà chi chiama
    fireEvent.click(screen.getByRole("button", { name: copy.nextIteration }));
    expect(onIterationChange).toHaveBeenLastCalledWith(3);
    fireEvent.click(screen.getByRole("button", { name: copy.previousIteration }));
    expect(onIterationChange).toHaveBeenLastCalledWith(1);
  });

  it("dall'ultima si torna alla prima e viceversa", () => {
    const last = setup(true, 3, 3);
    fireEvent.click(screen.getByRole("button", { name: copy.nextIteration }));
    expect(last.onIterationChange).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: copy.previousIteration }));
    expect(last.onIterationChange).toHaveBeenLastCalledWith(2);
  });

  it("con una sola iterazione le frecce restano sulla stessa", () => {
    const { onIterationChange } = setup(true, 1, 1);
    fireEvent.click(screen.getByRole("button", { name: copy.nextIteration }));
    expect(onIterationChange).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: copy.previousIteration }));
    expect(onIterationChange).toHaveBeenLastCalledWith(1);
  });
});

describe("MapLegend e MapAttribution", () => {
  it("la legenda ha le quattro classi di congestione nell'ordine del design", () => {
    render(<MapLegend />);
    const group = screen.getByRole("group", { name: copy.legendLabel });
    expect(Array.from(group.children, (c) => c.textContent)).toEqual([
      "Scorrevole",
      "Rallentata",
      "Intensa",
      "Satura",
    ]);
    const swatches = Array.from(group.querySelectorAll("span > span"));
    expect(swatches.map((s) => s.className.match(/bg-map-congestion-\d/)?.[0])).toEqual([
      "bg-map-congestion-1",
      "bg-map-congestion-2",
      "bg-map-congestion-3",
      "bg-map-congestion-4",
    ]);
  });

  it("l'attribuzione ODbL: OpenStreetMap e Protomaps, con i collegamenti", () => {
    render(<MapAttribution />);
    expect(screen.getByRole("link", { name: copy.attribution.osm })).toHaveAttribute(
      "href",
      "https://www.openstreetmap.org/copyright",
    );
    expect(screen.getByRole("link", { name: copy.attribution.protomaps })).toHaveAttribute(
      "href",
      "https://protomaps.com",
    );
  });
});

describe("ClosureSymbol", () => {
  it("disco del divieto da 24 px, fondo bg, bordo e icona nel colore delle chiusure (map-style 2.2)", () => {
    const { container } = render(<ClosureSymbol />);
    const disc = container.firstElementChild as HTMLElement;
    expect(disc).toHaveClass(
      "size-6",
      "rounded-full",
      "border-control",
      "border-map-closure",
      "bg-bg",
      "text-map-closure",
    );
    expect(disc).toHaveAttribute("aria-hidden", "true");
    const icon = disc.querySelector("svg") as SVGElement;
    expect(icon).toHaveClass("size-space-16", "stroke-2"); // 16 px, tratto 2
  });
});

describe("MapMarker", () => {
  it("normale: senza badge; accettata: spunta; rifiutata: croce", () => {
    const { container, rerender } = render(
      <MapMarker department="traffic_control" state="normal" />,
    );
    const root = () => container.firstElementChild as HTMLElement;
    expect(root()).toHaveAttribute("data-state", "normal");
    expect(container.querySelectorAll("svg")).toHaveLength(1); // solo l'icona del dipartimento
    rerender(<MapMarker department="traffic_control" state="accepted" />);
    expect(root()).toHaveAttribute("data-state", "accepted");
    expect(container.querySelectorAll("svg")).toHaveLength(2);
    expect(container.innerHTML).toContain("border-status-accepted");
    expect(container.querySelector("svg.lucide-check")).not.toBeNull(); // accettata: spunta
    expect(container.querySelector("svg.lucide-x")).toBeNull();
    rerender(<MapMarker department="traffic_control" state="rejected" />);
    expect(container.querySelector("svg.lucide-x")).not.toBeNull(); // rifiutata: croce
    expect(container.querySelector("svg.lucide-check")).toBeNull();
    expect(container.innerHTML).toContain("border-status-rejected");
    expect(container.innerHTML).toContain("bg-status-rejected");
  });

  it("un dipartimento sconosciuto non rompe il marker (nessuna icona)", () => {
    const { container } = render(<MapMarker department="boh" state="normal" />);
    expect(container.querySelectorAll("svg")).toHaveLength(0);
  });
});

describe("SensorSymbol: un sensore previsto non è un dato attivo (spech 11.5)", () => {
  it.each(["gps_probe", "turnstile", "people_counter", "ramp_counter"] as const)(
    "%s: grigio, contorno tratteggiato, con la sua icona",
    (type) => {
      const { container } = render(<SensorSymbol type={type} />);
      const symbol = container.firstElementChild as HTMLElement;
      expect(symbol).toHaveAttribute("data-sensor", type);
      expect(symbol).toHaveAttribute("aria-hidden", "true");
      // tratteggiato e grigio (token `text-secondary`), non il colore di un dato
      expect(symbol).toHaveClass("border-dashed", "border-text-secondary", "text-text-secondary");
      expect(symbol.className).not.toMatch(/map-|data-|status-|action/);
      expect(symbol.querySelector("svg")).not.toBeNull();
    },
  );

  it("senza tipo è il solo campione della legenda: contorno tratteggiato, nessuna icona", () => {
    const { container } = render(<SensorSymbol />);
    const symbol = container.firstElementChild as HTMLElement;
    expect(symbol).toHaveAttribute("data-sensor", "legend");
    expect(symbol).toHaveClass("border-dashed");
    expect(symbol.querySelector("svg")).toBeNull();
  });
});

describe("MapLegend con l'interruttore «Sensori previsti»", () => {
  const label = strings.live.sensors.layer;

  it("senza interruttore è la legenda di sempre (SCENARIO non cambia)", () => {
    render(<MapLegend />);
    const legend = screen.getByRole("group", { name: copy.legendLabel });
    expect(
      within(legend)
        .getAllByText(/./)
        .map((n) => n.textContent),
    ).toEqual(expect.arrayContaining([...copy.congestion]));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(label)).not.toBeInTheDocument();
  });

  it("con l'interruttore: casella, campione tratteggiato e nome; il clic lo cambia", () => {
    const onToggle = vi.fn();
    const { rerender } = render(<MapLegend sensors={{ on: false, onToggle }} />);
    const box = screen.getByRole("checkbox", { name: label });
    expect(box).toHaveAttribute("aria-checked", "false");
    expect(box.querySelector("[data-sensor='legend']")).not.toBeNull();
    expect(box.querySelector("svg")).toBeNull(); // spento: nessuna spunta
    fireEvent.click(box);
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(<MapLegend sensors={{ on: true, onToggle }} />);
    expect(screen.getByRole("checkbox", { name: label })).toHaveAttribute("aria-checked", "true");
    expect(box.querySelector("svg")).not.toBeNull(); // acceso: la spunta
    // le classi della congestione ci sono ancora
    for (const name of copy.congestion) expect(screen.getByText(name)).toBeInTheDocument();
  });

  it("senza la congestione resta solo l'interruttore, con un nome che non parla di congestione", () => {
    render(<MapLegend congestion={false} sensors={{ on: false, onToggle: () => undefined }} />);
    const legend = screen.getByRole("group", { name: strings.live.sensors.legendLabel });
    expect(within(legend).getByRole("checkbox", { name: label })).toBeInTheDocument();
    for (const name of copy.congestion) expect(screen.queryByText(name)).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: copy.legendLabel })).not.toBeInTheDocument();
  });
});
