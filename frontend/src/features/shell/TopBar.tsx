import { LogOut } from "lucide-react";
import { useLogout, useMe, useRun } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { IterationIndicator } from "@/components/IterationIndicator";
import { ModeSelector } from "@/components/ModeSelector";
import { RunStatus } from "@/components/RunStatus";
import { SimulationBanner } from "@/components/SimulationBanner";
import { LiveSourceChip } from "@/features/live/LiveSourceChip";
import { runDisplay } from "@/features/run/derive";
import { iterationNumber, iterationTotal } from "@/features/shell/run";
import { useShell } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";

/** La barra superiore (64 px): a sinistra il nome, lo stato e l'iterazione del run, al centro (in
 * SCENARIO) il banner SIMULAZIONE, a destra (in LIVE, se TomTom non risponde, il chip della fonte, a
 * sinistra del selettore: design 02) il selettore LIVE / SCENARIO e l'uscita. */
export function TopBar() {
  const { mode, setMode, runId } = useShell();
  const view = useRun(runId).data;
  const run = view?.run;
  const status = run ? runDisplay(run, view?.plan ?? []) : undefined;
  const logout = useLogout();
  // con l'accesso libero (`PUBLIC_ACCESS`) non c'è una sessione da chiudere: senza «Esci» nessuno resta
  // fuori da un login che non ha password
  const publicAccess = useMe().data?.public_access === true;
  return (
    <header className="grid h-size-topbar-height flex-none grid-cols-[1fr_auto_1fr] items-center gap-space-24 border-b-hairline border-border bg-surface-1 px-space-16">
      <div className="flex items-center gap-space-24">
        <h1 className="whitespace-nowrap text-xl">{strings.appName}</h1>
        {run && (
          <>
            <RunStatus state={status?.display ?? run.state} step={status?.step} />
            <IterationIndicator
              current={iterationNumber(run.iteration)}
              total={iterationTotal(run.iteration)}
            />
          </>
        )}
      </div>
      {/* il banner sta al centro della barra; se a sinistra manca lo spazio scivola a destra, non si sovrappone */}
      <div>{mode === "scenario" && <SimulationBanner />}</div>
      <div className="flex items-center justify-end gap-space-24">
        {mode === "live" && <LiveSourceChip />}
        <ModeSelector value={mode} onChange={setMode} />
        {!publicAccess && (
          <button
            type="button"
            aria-label={strings.shell.logout}
            title={strings.shell.logout}
            onClick={() => logout.mutate()}
            className="grid size-size-control-height place-items-center rounded-control border-control border-transparent text-text-secondary transition-base hover:bg-surface-2 hover:text-text-primary"
          >
            <Icon icon={LogOut} />
          </button>
        )}
      </div>
    </header>
  );
}
