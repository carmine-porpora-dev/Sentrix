import { Building2, Info, LayoutDashboard, ScrollText } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { isRunFinished, useRun } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { EventManagerPanel } from "@/components/EventManagerShell";
import { Sidebar, type SidebarItem } from "@/components/Sidebar";
import { Tabs, type TabItem } from "@/components/Tabs";
import { EventEditorProvider } from "@/features/events/EventEditor";
import { EventManager } from "@/features/events/EventManager";
import { LiveOperations } from "@/features/live/LiveOperations";
import { LiveStrip } from "@/features/live/LiveStrip";
import { useLiveFlow } from "@/features/live/queries";
import { MapPanel } from "@/features/map/MapPanel";
import { MetricStrip } from "@/features/metrics/MetricStrip";
import { AgentsPanel } from "@/features/run/AgentsPanel";
import { DecisionsPanel } from "@/features/run/DecisionsPanel";
import { OperationsPanel } from "@/features/run/OperationsPanel";
import { TopBar } from "@/features/shell/TopBar";
import { useShell, type PanelTab, type Section } from "@/features/shell/ShellProvider";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const SECTIONS: readonly SidebarItem<Section>[] = [
  { id: "dashboard", icon: LayoutDashboard, label: strings.shell.nav.dashboard },
  { id: "requests", icon: Building2, label: strings.shell.nav.requests },
  { id: "log", icon: ScrollText, label: strings.shell.nav.log },
];

const TABS: readonly TabItem<PanelTab>[] = [
  { id: "agents", label: strings.shell.tabs.agents },
  { id: "operations", label: strings.shell.tabs.operations },
  { id: "decisions", label: strings.shell.tabs.decisions },
];

/** I pannelli di destra (07 6) se chi monta il guscio non ne dà altri. In LIVE la scheda Operations
 * dice lo stato dei tratti (design 01–02) e da dove vengono i dati («Fonti dati»): non c'è un run di
 * cui parlare. */
const DEFAULT_PANELS: Record<PanelTab, ReactNode> = {
  agents: <AgentsPanel />,
  operations: <OperationsPanel />,
  decisions: <DecisionsPanel />,
};
const LIVE_PANELS: Record<PanelTab, ReactNode> = {
  ...DEFAULT_PANELS,
  operations: <LiveOperations />,
};

interface AppShellProps {
  /** La fascia delle cinque metriche (F4-04). */
  metrics?: ReactNode;
  /** Il form dell'Event Manager (F4-06). */
  eventManager?: ReactNode;
  /** La mappa (F4-05). */
  map?: ReactNode;
  /** Il contenuto di ogni scheda del pannello destro (F4-07). */
  panels?: Partial<Record<PanelTab, ReactNode>>;
}

/** Il guscio dell'interfaccia (07 2): barra laterale, barra superiore, fascia delle metriche e le
 * tre colonne (Event Manager · mappa · Agenti/Operations/Decisioni). In SCENARIO: cornice
 * `scenario-frame` attorno alla finestra e avviso sotto le colonne. */
export function AppShell(props: AppShellProps) {
  return (
    <EventEditorProvider>
      <Shell {...props} />
    </EventEditorProvider>
  );
}

function Shell({ metrics, eventManager, map, panels }: AppShellProps) {
  const shell = useShell();
  // «In corso» finché il run non è finito (o non se ne conosce ancora lo stato): a `DONE` o `ERROR` si spegne
  const runState = useRun(shell.runId).data?.run.state;
  const running = shell.runId !== undefined && !isRunFinished(runState);
  const scenario = shell.mode === "scenario";
  const live = shell.mode === "live";
  // un solo componente rilegge i tratti ogni minuto (e solo se la scheda è in primo piano): gli altri
  // leggono la stessa cache
  useLiveFlow(live, { poll: true });
  const open = shell.eventManagerOpen;
  const { setEventManagerOpen } = shell;
  // Un run in ERRORE riapre l'Event Manager, con «Analizza» di nuovo attivo (design, schermata 11:
  // si riparte da lì). Solo al passaggio a ERRORE: chi lo richiude a mano lo trova richiuso.
  useEffect(() => {
    if (runState === "ERROR") setEventManagerOpen(true);
  }, [runState, setEventManagerOpen]);
  return (
    <div className="flex h-screen overflow-hidden bg-bg text-text-primary">
      <Sidebar items={SECTIONS} active={shell.section} onSelect={shell.selectSection} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex min-h-0 flex-1 flex-col gap-layout-gap p-layout-screen-padding">
          <section
            aria-label={strings.metrics.regionLabel}
            className="grid h-size-metrics-height flex-none grid-cols-5 gap-layout-gap"
          >
            {metrics ?? (live ? <LiveStrip /> : <MetricStrip />)}
          </section>
          <div
            data-layout={open ? "open" : "rail"}
            className={cn(
              "grid min-h-0 flex-1 gap-layout-gap",
              open
                ? "grid-cols-[var(--layout-event-manager-compact)_minmax(0,1fr)_var(--layout-right-panel-compact)] compact:grid-cols-[var(--layout-event-manager)_minmax(0,1fr)_var(--layout-right-panel)]"
                : "grid-cols-[var(--layout-event-manager-rail)_minmax(0,1fr)_var(--layout-right-panel-wide)]",
            )}
          >
            <EventManagerPanel
              open={open}
              onToggle={() => shell.setEventManagerOpen(!open)}
              running={running}
              collapsible={shell.runId !== undefined}
            >
              {eventManager ?? <EventManager />}
            </EventManagerPanel>
            <section
              aria-label={strings.shell.regions.map}
              className="relative min-h-0 overflow-hidden rounded-card-inner border-hairline border-border bg-bg"
            >
              {map ?? <MapPanel />}
            </section>
            <Tabs
              items={TABS}
              active={shell.tab}
              onChange={shell.setTab}
              label={strings.shell.panelTabs}
              className="overflow-hidden rounded-card border-hairline border-border-card bg-surface-1"
            >
              {panels?.[shell.tab] ?? (live ? LIVE_PANELS : DEFAULT_PANELS)[shell.tab]}
            </Tabs>
          </div>
        </main>
        {scenario && (
          <p className="flex flex-none items-center gap-space-8 px-space-16 pb-2.5 text-xs text-text-secondary">
            <Icon icon={Info} size="inline" />
            {strings.shell.disclaimer}
          </p>
        )}
      </div>
      {scenario && (
        <div
          aria-hidden
          data-testid="scenario-frame"
          className="pointer-events-none fixed inset-0 z-50 border-scenario-frame-width border-scenario-frame"
        />
      )}
    </div>
  );
}
