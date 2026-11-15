import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type {
  Decision,
  Event,
  MetricsResponse,
  RequestView,
  RunView,
  VdeptRegistry,
} from "@/api/types";
import { ShellProvider, useShell } from "@/features/shell/ShellProvider";
import { fixture } from "@/test/fixtures";

export const RUN = "run_mock_match_2027";
export const doneView = fixture<RunView>("run_view/step_13_done.json");
export const registry = fixture<VdeptRegistry>("vdept_registry.json");
export const decisions = fixture<Decision[]>("run_decisions/step_13.json");
export const event = fixture<Event>("event_match_2027.json");
export const metrics = (n: number) => fixture<MetricsResponse>(`run_metrics/iteration_${n}.json`);

interface Options {
  view?: RunView;
  decisions?: Decision[];
  registry?: VdeptRegistry;
  event?: Event;
  overrides?: Partial<ApiClient>;
}

/** Un client le cui letture danno ciò che si sceglie (di base il run finito del mock): ogni
 * operazione che i pannelli usano è una `vi.fn()`, per vedere con che cosa è stata chiamata. */
export function runClient(options: Options = {}) {
  const view = options.view ?? doneView;
  const calls = {
    getRun: vi.fn<ApiClient["getRun"]>(() => Promise.resolve(view)),
    getEvent: vi.fn<ApiClient["getEvent"]>(() => Promise.resolve(options.event ?? event)),
    vdeptRegistry: vi.fn<ApiClient["vdeptRegistry"]>(() =>
      Promise.resolve(options.registry ?? registry),
    ),
    runDecisions: vi.fn<ApiClient["runDecisions"]>(() =>
      Promise.resolve(options.decisions ?? decisions),
    ),
    runMetrics: vi.fn<ApiClient["runMetrics"]>((_runId, n) => Promise.resolve(metrics(n))),
    exportRun: vi.fn<ApiClient["exportRun"]>(() =>
      Promise.resolve({ run: view.run } as unknown as Awaited<ReturnType<ApiClient["exportRun"]>>),
    ),
    exportRunCsv: vi.fn<ApiClient["exportRunCsv"]>(() => Promise.resolve("a,b\n1,2\n")),
    manualResponse: vi.fn<ApiClient["manualResponse"]>(() =>
      Promise.resolve(view.requests[0] as RequestView),
    ),
  };
  const client: ApiClient = {
    ...createMockClient({ authenticated: true }),
    ...calls,
    ...options.overrides,
  };
  return { client, ...calls };
}

/** Lo stato dell'interfaccia che interessa ai test dei pannelli, scritto in una riga. */
export function ShellProbe() {
  const shell = useShell();
  const focus = shell.focus
    ? `${shell.focus.lat},${shell.focus.lon}#${shell.focus.key}`
    : "nessuno";
  return (
    <output data-testid="shell">
      {`manual=${shell.manualResponse};runManual=${shell.runManual};focus=${focus};window=${shell.window}`}
    </output>
  );
}

export function renderPanel(
  client: ApiClient,
  panel: ReactNode,
  initial: Parameters<typeof ShellProvider>[0]["initial"] = { runId: RUN },
) {
  return render(
    <ApiProvider client={client}>
      <ShellProvider initial={initial}>
        {panel}
        <ShellProbe />
      </ShellProvider>
    </ApiProvider>,
  );
}

/** Un `RunView` con qualche campo cambiato. */
export const withRun = (
  changes: Partial<RunView["run"]>,
  rest: Partial<RunView> = {},
): RunView => ({
  ...doneView,
  ...rest,
  run: { ...doneView.run, ...changes },
});
