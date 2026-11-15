import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { ApiClient } from "@/api/client";
import { ApiError, networkError } from "@/api/errors";
import { createHttpClient } from "@/api/http";
import { createMockClient } from "@/api/mock";
import { ApiProvider, useApi } from "@/api/provider";
import { useLogout } from "@/api/queries";
import { AuthGate } from "@/features/auth/AuthGate";
import { strings } from "@/i18n/it";

const text = strings.login;

function typePassword(value: string) {
  fireEvent.change(screen.getByLabelText(text.passwordLabel), { target: { value } });
}
const submit = () => fireEvent.click(screen.getByRole("button", { name: text.submit }));

/** Un client mock in cui alcuni metodi sono sostituiti. */
function withOverrides(overrides: Partial<ApiClient>, authenticated = false): ApiClient {
  return { ...createMockClient({ authenticated }), ...overrides };
}

const rejects = (status: number, code: string, details?: Record<string, unknown>) =>
  vi.fn(() => Promise.reject(new ApiError(status, { code, message: code, details })));

describe("login", () => {
  it("senza sessione mostra il campo password e nessun contenuto dell'applicazione", async () => {
    render(<App client={createMockClient()} />);
    const field = await screen.findByLabelText(text.passwordLabel);
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: text.submit })).toBeEnabled();
    expect(screen.queryByRole("button", { name: strings.session.logout })).not.toBeInTheDocument();
  });

  it("in modalità mock avvisa che i dati sono di esempio", async () => {
    render(<App client={createMockClient()} />);
    expect(await screen.findByRole("note")).toHaveTextContent(strings.mockNotice);
  });

  it("in modalità http non c'è l'avviso", async () => {
    const fetchImpl = vi.fn(() =>
      Promise.resolve(new Response('{"authenticated":false}')),
    ) as unknown as typeof fetch;
    render(<App client={createHttpClient(fetchImpl)} />);
    await screen.findByLabelText(text.passwordLabel);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("una password vuota si segnala senza chiamare il server", async () => {
    const login = vi.fn();
    render(<App client={withOverrides({ login })} />);
    await screen.findByLabelText(text.passwordLabel);
    submit();
    expect(screen.getByRole("alert")).toHaveTextContent(text.emptyPassword);
    expect(screen.getByLabelText(text.passwordLabel)).toHaveAttribute("aria-invalid", "true");
    await act(async () => undefined); // il mutation parte in modo asincrono: lasciamogli il tempo
    expect(login).not.toHaveBeenCalled();
  });

  it("con la password giusta entra nell'applicazione", async () => {
    const login = vi.fn((password: string) => createMockClient().login(password));
    render(<App client={withOverrides({ login })} />);
    await screen.findByLabelText(text.passwordLabel);
    typePassword("la-password");
    submit();
    expect(await screen.findByRole("button", { name: strings.session.logout })).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith("la-password");
    expect(screen.queryByLabelText(text.passwordLabel)).not.toBeInTheDocument();
  });

  it("durante l'accesso il pulsante è disabilitato e lo dice", async () => {
    let finish: () => void = () => undefined;
    const login = vi.fn(
      () =>
        new Promise<{ authenticated: boolean }>((resolve) => {
          finish = () => resolve({ authenticated: true });
        }),
    );
    render(<App client={withOverrides({ login })} />);
    await screen.findByLabelText(text.passwordLabel);
    typePassword("x");
    submit();
    const busy = await screen.findByRole("button", { name: text.submitting });
    expect(busy).toBeDisabled();
    finish();
    expect(await screen.findByRole("button", { name: strings.session.logout })).toBeInTheDocument();
  });

  it("password errata (401): messaggio nella pagina di login, non un ritorno al login", async () => {
    render(<App client={withOverrides({ login: rejects(401, "UNAUTHENTICATED") })} />);
    await screen.findByLabelText(text.passwordLabel);
    typePassword("sbagliata");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(text.wrongPassword);
    expect(screen.getByLabelText(text.passwordLabel)).toHaveValue("sbagliata");
  });

  it.each([
    [
      "troppi tentativi con i secondi d'attesa",
      429,
      "RATE_LIMITED",
      { retry_after_s: 42 },
      "Troppi tentativi: riprova tra 42 secondi.",
    ],
    [
      "troppi tentativi senza secondi",
      429,
      "RATE_LIMITED",
      undefined,
      "Troppi tentativi: riprova tra poco.",
    ],
    ["accesso non configurato", 503, "AUTH_NOT_CONFIGURED", undefined, text.notConfigured],
    ["altro errore del server", 500, "INTERNAL", undefined, text.generic],
  ])("%s", async (_name, status, code, details, message) => {
    render(<App client={withOverrides({ login: rejects(status, code, details) })} />);
    await screen.findByLabelText(text.passwordLabel);
    typePassword("x");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("server che non risponde: messaggio di rete", async () => {
    const login = vi.fn(() => Promise.reject(networkError("Il server non risponde")));
    render(<App client={withOverrides({ login })} />);
    await screen.findByLabelText(text.passwordLabel);
    typePassword("x");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(text.network);
  });

  it("un errore che non è dell'API ha il messaggio generico", async () => {
    const login = vi.fn(() => Promise.reject(new Error("boom")));
    render(<App client={withOverrides({ login })} />);
    await screen.findByLabelText(text.passwordLabel);
    typePassword("x");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(text.generic);
  });

  it("al secondo tentativo l'errore di prima sparisce", async () => {
    const login = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(401, { code: "UNAUTHENTICATED", message: "x" }));
    login.mockImplementation((password: string) => createMockClient().login(password));
    render(<App client={withOverrides({ login })} />);
    await screen.findByLabelText(text.passwordLabel);
    typePassword("no");
    submit();
    await screen.findByRole("alert");
    typePassword("si");
    submit();
    await screen.findByRole("button", { name: strings.session.logout });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("sessione", () => {
  it("mentre verifica la sessione lo dice", async () => {
    const me = vi.fn(() => new Promise<never>(() => undefined));
    render(<App client={withOverrides({ me })} />);
    expect(screen.getByRole("status")).toHaveTextContent(strings.session.checking);
  });

  it("se non riesce a verificarla propone di riprovare", async () => {
    const real = createMockClient({ authenticated: true });
    const me = vi
      .fn()
      .mockRejectedValueOnce(networkError("giù"))
      .mockImplementation(() => real.me());
    render(<App client={withOverrides({ me })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(strings.session.unavailable);
    fireEvent.click(screen.getByRole("button", { name: strings.session.retry }));
    expect(await screen.findByRole("button", { name: strings.session.logout })).toBeInTheDocument();
  });

  it("Esci chiude la sessione e torna al login", async () => {
    const client = createMockClient({ authenticated: true });
    render(<App client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: strings.session.logout }));
    expect(await screen.findByLabelText(text.passwordLabel)).toBeInTheDocument();
    await expect(client.me()).resolves.toEqual({ authenticated: false });
  });
});

/** Una parte dell'applicazione che legge un dato protetto. */
function Events() {
  const api = useApi();
  const events = useQuery({ queryKey: ["events"], queryFn: () => api.listEvents() });
  return <p>{events.data ? `${events.data.length} eventi` : "in attesa"}</p>;
}

function Logout() {
  const logout = useLogout();
  return <button onClick={() => logout.mutate()}>{strings.session.logout}</button>;
}

function renderGate(client: ApiClient) {
  return render(
    <ApiProvider client={client}>
      <AuthGate>
        <Events />
      </AuthGate>
    </ApiProvider>,
  );
}

describe("401 da qualunque chiamata", () => {
  it("a sessione scaduta riporta al login e butta i dati dell'utente dalla cache", async () => {
    let expired = false;
    const real = createMockClient({ authenticated: true });
    const client = withOverrides(
      {
        listEvents: () => real.listEvents(),
        getRun: () =>
          expired
            ? Promise.reject(new ApiError(401, { code: "UNAUTHENTICATED", message: "scaduta" }))
            : real.getRun("run_mock_match_2027"),
      },
      true,
    );
    const held: { queryClient?: QueryClient } = {};
    function Poll() {
      const api = useApi();
      const queryClient = useQueryClient();
      useEffect(() => {
        held.queryClient = queryClient;
      }, [queryClient]);
      return (
        <button
          onClick={() =>
            void queryClient
              .fetchQuery({ queryKey: ["run", "x"], queryFn: () => api.getRun("x") })
              .catch(() => undefined)
          }
        >
          rileggi
        </button>
      );
    }
    render(
      <ApiProvider client={client}>
        <AuthGate>
          <Events />
          <Poll />
        </AuthGate>
      </ApiProvider>,
    );
    expect(await screen.findByText("2 eventi")).toBeInTheDocument();
    expect(held.queryClient?.getQueryData(["events"])).toHaveLength(2);

    expired = true;
    fireEvent.click(screen.getByRole("button", { name: "rileggi" }));
    expect(await screen.findByLabelText(text.passwordLabel)).toBeInTheDocument();
    expect(held.queryClient?.getQueryData(["events"])).toBeUndefined();
    expect(held.queryClient?.getQueryData(["me"])).toEqual({ authenticated: false });
  });

  it("un 401 su una query rimette lo stato anonimo e mostra il login", async () => {
    const client = withOverrides({ listEvents: rejects(401, "UNAUTHENTICATED") }, true);
    renderGate(client);
    expect(await screen.findByLabelText(text.passwordLabel)).toBeInTheDocument();
    expect(screen.queryByText(/eventi/)).not.toBeInTheDocument();
  });

  it("anche il 401 di un'azione dell'utente (Esci con la sessione già scaduta) riporta al login", async () => {
    const logout = rejects(401, "UNAUTHENTICATED");
    render(<App client={withOverrides({ logout }, true)} />);
    fireEvent.click(await screen.findByRole("button", { name: strings.session.logout }));
    expect(await screen.findByLabelText(text.passwordLabel)).toBeInTheDocument();
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("Esci butta dalla cache i dati dell'utente (non restano per il prossimo accesso)", async () => {
    const held: { queryClient?: QueryClient } = {};
    function Capture() {
      const queryClient = useQueryClient();
      useEffect(() => {
        held.queryClient = queryClient;
      }, [queryClient]);
      return null;
    }
    render(
      <ApiProvider client={createMockClient({ authenticated: true })}>
        <AuthGate>
          <Events />
          <Capture />
          <Logout />
        </AuthGate>
      </ApiProvider>,
    );
    expect(await screen.findByText("2 eventi")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: strings.session.logout }));
    expect(await screen.findByLabelText(text.passwordLabel)).toBeInTheDocument();
    expect(held.queryClient?.getQueryData(["events"])).toBeUndefined();
    expect(held.queryClient?.getQueryData(["me"])).toEqual({ authenticated: false });
  });

  it("un errore che non è 401 non butta fuori l'utente", async () => {
    const client = withOverrides({ listEvents: rejects(500, "INTERNAL") }, true);
    renderGate(client);
    await waitFor(() => expect(screen.getByText("in attesa")).toBeInTheDocument());
    expect(screen.queryByLabelText(text.passwordLabel)).not.toBeInTheDocument();
  });
});
