import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "@/App";
import { createMockClient } from "@/api/mock";
import { strings } from "@/i18n/it";

describe("App", () => {
  it("con la sessione aperta mostra il guscio: titolo, contenuto principale e uscita", async () => {
    render(<App client={createMockClient({ authenticated: true })} />);
    expect(
      await screen.findByRole("heading", { level: 1, name: strings.appName }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: strings.shell.logout })).toBeInTheDocument();
    expect(screen.queryByLabelText(strings.login.passwordLabel)).not.toBeInTheDocument();
  });

  it("con l'accesso libero (PUBLIC_ACCESS) entra senza password e senza «Esci»", async () => {
    render(<App client={createMockClient({ publicAccess: true })} />);
    expect(
      await screen.findByRole("heading", { level: 1, name: strings.appName }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(strings.login.passwordLabel)).not.toBeInTheDocument();
    // «Esci» chiuderebbe una sessione che non c'è, e il login non avrebbe una password da chiedere
    expect(screen.queryByRole("button", { name: strings.shell.logout })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /SCENARIO/ })).toBeChecked();
  });

  it("con l'accesso protetto «Esci» c'è e il login si chiede come sempre", async () => {
    render(<App client={createMockClient({ authenticated: true, publicAccess: false })} />);
    expect(await screen.findByRole("button", { name: strings.shell.logout })).toBeInTheDocument();
  });

  it("senza sessione mostra il login e non il guscio", async () => {
    render(<App client={createMockClient()} />);
    expect(await screen.findByLabelText(strings.login.passwordLabel)).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("dopo il login entra nel guscio, in SCENARIO", async () => {
    render(<App client={createMockClient()} />);
    const field = await screen.findByLabelText(strings.login.passwordLabel);
    fireEvent.change(field, { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: strings.login.submit }));
    expect(await screen.findByText(strings.shell.simulationBanner)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /SCENARIO/ })).toBeChecked();
  });
});
