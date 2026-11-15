import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/components/Button";
import { FormSection } from "@/components/forms/FormSection";
import { SelectField } from "@/components/forms/SelectField";
import { TextField } from "@/components/forms/TextField";

describe("TextField", () => {
  const props = { id: "f", label: "Nome", value: "ciao", onChange: () => undefined };

  it("l'etichetta è collegata al campo", () => {
    render(<TextField {...props} />);
    expect(screen.getByLabelText("Nome")).toHaveValue("ciao");
  });

  it("scrivere chiama onChange con il testo; uscire chiama onBlur", () => {
    const onChange = vi.fn();
    const onBlur = vi.fn();
    render(<TextField {...props} onChange={onChange} onBlur={onBlur} />);
    fireEvent.change(screen.getByLabelText("Nome"), { target: { value: "altro" } });
    expect(onChange).toHaveBeenCalledWith("altro");
    fireEvent.blur(screen.getByLabelText("Nome"));
    expect(onBlur).toHaveBeenCalledTimes(1);
  });

  it("l'errore è testo sotto il campo, con aria-invalid e la descrizione collegata", () => {
    render(<TextField {...props} error="Campo obbligatorio" hint="un suggerimento" />);
    const input = screen.getByLabelText("Nome");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Campo obbligatorio");
    expect(screen.queryByText("un suggerimento")).not.toBeInTheDocument(); // l'errore sostituisce il suggerimento
  });

  it("il suggerimento si vede se non c'è un errore", () => {
    render(<TextField {...props} hint="un suggerimento" />);
    expect(screen.getByLabelText("Nome")).toHaveAccessibleDescription("un suggerimento");
    expect(screen.getByLabelText("Nome")).not.toHaveAttribute("aria-invalid");
  });

  it("l'unità sta a destra; l'etichetta nascosta resta per le tecnologie assistive", () => {
    render(<TextField {...props} suffix="persone" labelHidden />);
    expect(screen.getByText("persone")).toBeInTheDocument();
    expect(screen.getByText("Nome")).toHaveClass("sr-only");
    expect(screen.getByLabelText("Nome")).toBeInTheDocument();
  });

  it("disattivato non si modifica", () => {
    render(<TextField {...props} disabled />);
    expect(screen.getByLabelText("Nome")).toBeDisabled();
  });
});

describe("SelectField", () => {
  const options = [
    { value: "a", label: "Alfa" },
    { value: "b", label: "Beta" },
  ];

  it("mostra il valore, elenca le opzioni e dice la scelta", () => {
    const onChange = vi.fn();
    render(<SelectField id="s" label="Lettera" value="a" options={options} onChange={onChange} />);
    const select = screen.getByRole("combobox", { name: "Lettera" });
    expect(select).toHaveValue("a");
    fireEvent.change(select, { target: { value: "b" } });
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("l'errore e l'etichetta a destra si vedono", () => {
    render(
      <SelectField
        id="s"
        label="Lettera"
        value="a"
        options={options}
        onChange={() => undefined}
        error="Non valida"
        labelAside={<span>preset</span>}
      />,
    );
    expect(screen.getByText("Non valida")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("preset")).toBeInTheDocument();
  });
});

describe("FormSection", () => {
  it("aperta mostra il contenuto; il titolo lo comprime e lo riapre", () => {
    render(
      <FormSection title="Area">
        <p>contenuto</p>
      </FormSection>,
    );
    const toggle = screen.getByRole("button", { name: "Area" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("contenuto")).toBeVisible();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("contenuto")).not.toBeVisible();
    fireEvent.click(toggle);
    expect(screen.getByText("contenuto")).toBeVisible();
  });

  it("chiusa all'inizio se lo si chiede; il contenuto resta nella pagina; il badge a destra", () => {
    render(
      <FormSection title="Avanzate" defaultOpen={false} aside={<span>badge</span>}>
        <input aria-label="dentro" />
      </FormSection>,
    );
    expect(screen.getByRole("button", { name: "Avanzate" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByLabelText("dentro")).not.toBeVisible();
    expect(screen.getByText("badge")).toBeVisible();
  });

  it("il pulsante controlla il suo contenuto (aria-controls)", () => {
    render(
      <FormSection title="Area">
        <p>contenuto</p>
      </FormSection>,
    );
    const id = screen.getByRole("button", { name: "Area" }).getAttribute("aria-controls") as string;
    expect(document.getElementById(id)).toContainElement(screen.getByText("contenuto"));
  });
});

describe("Button", () => {
  it("chiama onClick; di default non invia un form (type=button)", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Vai</Button>);
    const button = screen.getByRole("button", { name: "Vai" });
    expect(button).toHaveAttribute("type", "button");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("disattivato non risponde", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Vai
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Vai" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("in corso è disattivato e lo dice (aria-busy)", () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Vai
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Vai" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("le tre varianti hanno i colori del design", () => {
    render(
      <>
        <Button variant="solid">s</Button>
        <Button variant="stroke">t</Button>
        <Button variant="ghost">g</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "s" })).toHaveClass("bg-action", "text-bg");
    expect(screen.getByRole("button", { name: "t" })).toHaveClass("border-action", "text-action");
    expect(screen.getByRole("button", { name: "g" })).toHaveClass("text-text-primary");
  });

  it("block occupa tutta la larghezza", () => {
    render(<Button block>Vai</Button>);
    expect(screen.getByRole("button", { name: "Vai" })).toHaveClass("w-full");
  });
});
