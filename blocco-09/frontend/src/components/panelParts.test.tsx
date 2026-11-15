import { fireEvent, render, screen } from "@testing-library/react";
import { Check } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { Callout } from "@/components/Callout";
import { ManualSwitch } from "@/components/forms/ManualSwitch";
import { FocusMarker } from "@/components/MapControls";
import { StateChip } from "@/components/StateChip";
import { strings } from "@/i18n/it";

describe("Callout", () => {
  it("l'errore si annuncia subito (role alert); la decisione e l'informazione no", () => {
    const { rerender } = render(
      <Callout tone="error" title="Guasto">
        dettaglio
      </Callout>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Guasto");
    expect(screen.getByRole("alert")).toHaveTextContent("dettaglio");
    rerender(
      <Callout tone="warning" title="Decisione">
        x
      </Callout>,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    rerender(<Callout tone="info" title="Nota" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Nota")).toBeInTheDocument();
  });

  it("i colori sono dei token (bordo e fondo del tipo)", () => {
    const { container, rerender } = render(<Callout tone="error" title="a" />);
    expect(container.firstElementChild).toHaveClass("border-danger", "bg-state-fill-error");
    rerender(<Callout tone="warning" title="a" />);
    expect(container.firstElementChild).toHaveClass("border-warning", "bg-state-fill-waiting");
  });
});

describe("StateChip", () => {
  it("dice lo stato con il testo e il tipo (colore) a parte", () => {
    render(<StateChip tone="accepted" icon={Check} label="Accettata" />);
    const chip = screen.getByText("Accettata");
    expect(chip).toHaveAttribute("data-tone", "accepted");
    expect(chip).toHaveClass("border-status-accepted", "text-status-accepted");
    expect(chip.querySelector("svg")).not.toBeNull();
  });

  it.each([
    ["pending", "text-status-pending"],
    ["rejected", "text-status-rejected"],
    ["neutral", "text-text-secondary"],
  ] as const)("%s", (tone, cls) => {
    render(<StateChip tone={tone} label="x" />);
    expect(screen.getByText("x")).toHaveClass(cls);
  });
});

describe("ManualSwitch", () => {
  const props = {
    label: "Risposta manuale",
    stateLabels: { on: "On", off: "Off" },
    hint: "un suggerimento",
  };

  it("è un interruttore che dice il suo stato e che cosa cambia", () => {
    render(<ManualSwitch {...props} checked={false} onChange={() => undefined} />);
    const toggle = screen.getByRole("switch", { name: /Risposta manuale/ });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toHaveTextContent("Off");
    expect(screen.getByText("un suggerimento")).toBeInTheDocument();
  });

  it("il clic chiede lo stato opposto", () => {
    const onChange = vi.fn();
    const { rerender } = render(<ManualSwitch {...props} checked={false} onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenLastCalledWith(true);
    rerender(<ManualSwitch {...props} checked onChange={onChange} />);
    expect(screen.getByRole("switch")).toHaveTextContent("On");
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenLastCalledWith(false);
  });
});

describe("FocusMarker", () => {
  it("si annuncia come punto evidenziato, con il luogo se c'è", () => {
    const { rerender } = render(<FocusMarker />);
    expect(screen.getByRole("img", { name: strings.map.focusLabel })).toBeInTheDocument();
    rerender(<FocusMarker label="Piazza Vittoria" />);
    expect(
      screen.getByRole("img", { name: `${strings.map.focusLabel}: Piazza Vittoria` }),
    ).toBeInTheDocument();
  });

  it("l'anello pulsa solo se il sistema non chiede di ridurre i movimenti", () => {
    render(<FocusMarker />);
    expect(screen.getByRole("img").querySelector(".motion-safe\\:animate-ping")).not.toBeNull();
  });
});
