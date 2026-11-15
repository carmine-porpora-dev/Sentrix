import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "@/components/Composer";
import { MAX_MESSAGE_LENGTH } from "@/config";

function Harness({
  compact = false,
  onSend,
}: {
  compact?: boolean;
  onSend: (text: string) => void;
}) {
  const [value, setValue] = useState("");
  const canSend = value.trim().length > 0 && value.length <= MAX_MESSAGE_LENGTH;
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSend={() => {
        onSend(value);
        setValue("");
      }}
      canSend={canSend}
      compact={compact}
    />
  );
}

const field = () => screen.getByLabelText("Scrivi all'Assistente") as HTMLTextAreaElement;
const send = () => screen.getByRole("button", { name: "Invia" });
const type = (text: string) => fireEvent.change(field(), { target: { value: text } });

describe("Composer", () => {
  it("a riposo ha il segnaposto e l'invio disabilitato", () => {
    render(<Harness onSend={vi.fn()} />);
    expect(field()).toHaveAttribute("placeholder", "Dove devi andare?");
    expect(send()).toBeDisabled();
  });

  it("con del testo l'invio si abilita; solo spazi non basta", () => {
    render(<Harness onSend={vi.fn()} />);
    type("   ");
    expect(send()).toBeDisabled();
    type("Dove vado?");
    expect(send()).toBeEnabled();
  });

  it("il pulsante invia, svuota il campo e rimette il fuoco nel campo", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    type("Dove vado?");
    fireEvent.click(send());
    expect(onSend).toHaveBeenCalledWith("Dove vado?");
    expect(field()).toHaveValue("");
    expect(field()).toHaveFocus();
    expect(send()).toBeDisabled();
  });

  it("su schermo largo Invio invia e Maiusc+Invio non invia", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    type("Ciao");
    fireEvent.keyDown(field(), { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Ciao");
  });

  it("su telefono Invio va a capo e non invia", () => {
    const onSend = vi.fn();
    render(<Harness compact onSend={onSend} />);
    type("Ciao");
    const notPrevented = fireEvent.keyDown(field(), { key: "Enter" });
    expect(notPrevented).toBe(true);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("durante la composizione (tastiere IME) Invio non invia", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    type("こんにちは");
    fireEvent.keyDown(field(), { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("Invio con il campo vuoto non invia", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("oltre il limite mostra l'errore, segna il campo e disabilita l'invio", () => {
    render(<Harness onSend={vi.fn()} />);
    type("a".repeat(MAX_MESSAGE_LENGTH));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(send()).toBeEnabled();
    type("a".repeat(MAX_MESSAGE_LENGTH + 1));
    expect(screen.getByRole("alert")).toHaveTextContent("Massimo 500 caratteri.");
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(send()).toBeDisabled();
  });

  it("il tasto di invio è l'aeroplanino, non una freccia in su", () => {
    render(<Harness onSend={vi.fn()} />);
    const paths = [...send().querySelectorAll("path")].map((path) => path.getAttribute("d"));
    expect(paths).toEqual([
      "M10 14l11 -11",
      "M21 3l-6.5 18a.55.55 0 0 1 -1 0l-3.5 -7l-7 -3.5a.55.55 0 0 1 0 -1l18 -6.5",
    ]);
  });
});
