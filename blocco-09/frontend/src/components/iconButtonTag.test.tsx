import { fireEvent, render, screen } from "@testing-library/react";
import { MapPin } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { IconButton } from "@/components/IconButton";
import { Tag } from "@/components/Tag";

describe("IconButton", () => {
  it("è un pulsante col suo nome, di sola icona e senza testo", () => {
    const onClick = vi.fn();
    render(<IconButton icon={MapPin} label="Mostra sulla mappa" onClick={onClick} />);
    const button = screen.getByRole("button", { name: "Mostra sulla mappa" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveTextContent("");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("il suggerimento del mouse c'è solo se lo si chiede", () => {
    const { rerender } = render(<IconButton icon={MapPin} label="Rimuovi" />);
    expect(screen.getByRole("button")).not.toHaveAttribute("title");
    rerender(<IconButton icon={MapPin} label="Rimuovi" tooltip />);
    expect(screen.getByRole("button")).toHaveAttribute("title", "Rimuovi");
  });

  it("il passaggio del mouse è un gradino più in là dello sfondo su cui sta", () => {
    const { rerender } = render(<IconButton icon={MapPin} label="a" on="surface-1" />);
    expect(screen.getByRole("button")).toHaveClass("hover:bg-surface-2");
    expect(screen.getByRole("button")).not.toHaveClass("hover:bg-surface-3");
    rerender(<IconButton icon={MapPin} label="a" on="surface-2" />);
    expect(screen.getByRole("button")).toHaveClass("hover:bg-surface-3");
    rerender(<IconButton icon={MapPin} label="a" />); // lo sfondo più comune: surface-2
    expect(screen.getByRole("button")).toHaveClass("hover:bg-surface-3");
  });

  it("lascia passare gli attributi di un pulsante (aria-expanded, disabled)", () => {
    render(<IconButton icon={MapPin} label="Comprimi" aria-expanded disabled />);
    const button = screen.getByRole("button", { name: "Comprimi" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toBeDisabled();
  });

  it("ha le misure del chip del design, senza bordo", () => {
    render(<IconButton icon={MapPin} label="a" />);
    expect(screen.getByRole("button")).toHaveClass(
      "size-size-chip-height",
      "rounded-control",
      "text-text-secondary",
    );
  });
});

describe("Tag", () => {
  it("è un'etichetta su fondo surface-3, in monospazio, inline", () => {
    render(<Tag>build_demand</Tag>);
    const tag = screen.getByText("build_demand");
    expect(tag.tagName).toBe("SPAN");
    expect(tag).toHaveClass("rounded-tag", "bg-surface-3", "text-xs", "font-mono");
    expect(tag).not.toHaveClass("truncate");
    expect(tag).not.toHaveAttribute("title");
  });

  it("può essere un elemento di elenco, con il testo intero nel suggerimento", () => {
    render(
      <ul>
        <Tag as="li" title="m.run1.it0.road.departure.veh_hours" truncate>
          road.departure.veh_hours
        </Tag>
      </ul>,
    );
    const item = screen.getByRole("listitem");
    expect(item).toHaveAttribute("title", "m.run1.it0.road.departure.veh_hours");
    expect(item).toHaveClass("truncate", "max-w-full");
  });

  it("senza monospazio è nel carattere dell'interfaccia", () => {
    render(<Tag mono={false}>testo</Tag>);
    expect(screen.getByText("testo")).not.toHaveClass("font-mono");
  });

  it("le classi in più si aggiungono, non sostituiscono quelle dell'etichetta", () => {
    render(<Tag className="flex gap-1.5">x</Tag>);
    expect(screen.getByText("x")).toHaveClass("flex", "gap-1.5", "bg-surface-3");
  });
});
