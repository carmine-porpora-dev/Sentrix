import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Mode } from "@/components/ModeSelector";
import { DEFAULT_VIEW, type IterationView } from "@/features/metrics/iterations";

export type Section = "dashboard" | "requests" | "log";
/** La finestra a cui si riferiscono metriche e mappa: l'arrivo o il deflusso dell'Evento. */
export type EventWindow = "arrival" | "departure";
export type PanelTab = "agents" | "operations" | "decisions";

/** Il punto che l'interfaccia chiede alla mappa di mostrare; `key` cambia a ogni richiesta, anche per
 * lo stesso punto (la mappa ci torna). */
export interface MapFocus {
  lat: number;
  lon: number;
  label?: string | null;
  key: number;
}

/** La scheda che ogni sezione della barra laterale apre (la plancia lascia quella corrente). */
const SECTION_TAB: Partial<Record<Section, PanelTab>> = {
  requests: "operations",
  log: "decisions",
};

interface ShellState {
  mode: Mode;
  /** Cambia modalità. Entrando in LIVE si apre la scheda Operations, che lì dice lo stato dei tratti. */
  setMode: (mode: Mode) => void;
  section: Section;
  /** Sceglie la sezione della barra laterale e apre la scheda che le corrisponde. */
  selectSection: (section: Section) => void;
  tab: PanelTab;
  setTab: (tab: PanelTab) => void;
  window: EventWindow;
  setWindow: (window: EventWindow) => void;
  /** Prima/Dopo e l'iterazione scelta: valgono per la mappa e per le metriche. */
  view: IterationView;
  setAfter: (after: boolean) => void;
  /** Sceglie una delle iterazioni «dopo» (da 1) e passa a «Dopo». */
  pickIteration: (iteration: number) => void;
  /** L'Event Manager aperto (360 px) o compresso a binario (108 px: il pannello destro si allarga). */
  eventManagerOpen: boolean;
  setEventManagerOpen: (open: boolean) => void;
  /** Il run che l'interfaccia sta seguendo (lo imposta «Analizza», F4-06). */
  runId: string | undefined;
  /** Segue un run: da quel momento l'Event Manager si comprime, come nel design, e la vista è SCENARIO
   * (anche se «Analizza» è stato premuto in LIVE). `manual` dice se il run è partito con la risposta
   * manuale (è una scelta alla partenza: non cambia a run avviato). */
  followRun: (runId: string | undefined, options?: { manual?: boolean }) => void;
  /** Il run seguito è partito con la risposta manuale: solo allora le richieste ricevute si possono
   * accettare o rifiutare dall'interfaccia (04 5). */
  runManual: boolean;
  /** Un punto da mostrare sulla mappa (un'evidenza, una richiesta): la mappa ci va e lo segna. */
  focus: MapFocus | undefined;
  focusOn: (point: { lat: number; lon: number; label?: string | null }) => void;
  /** «Risposta manuale»: il prossimo run lascia a chi usa l'interfaccia accettare o rifiutare le
   * richieste dei dipartimenti (l'interruttore è nella scheda Operations, F4-07). */
  manualResponse: boolean;
  setManualResponse: (manual: boolean) => void;
}

const ShellContext = createContext<ShellState | null>(null);

export function useShell(): ShellState {
  const shell = useContext(ShellContext);
  if (!shell) throw new Error("useShell fuori da <ShellProvider>");
  return shell;
}

interface ShellProviderProps {
  children: ReactNode;
  /** Solo per i test e le schermate: lo stato iniziale. */
  initial?: Partial<
    Pick<
      ShellState,
      | "mode"
      | "section"
      | "tab"
      | "window"
      | "view"
      | "eventManagerOpen"
      | "runId"
      | "manualResponse"
      | "runManual"
    >
  >;
}

/** Lo stato dell'interfaccia (non dei dati del server, che sono in TanStack Query). La modalità
 * parte da SCENARIO: funziona offline e non chiama nessuna fonte esterna; la finestra dal
 * deflusso, dove l'Evento è più critico. */
export function ShellProvider({ children, initial }: ShellProviderProps) {
  const [mode, setModeState] = useState<Mode>(initial?.mode ?? "scenario");
  const [section, setSection] = useState<Section>(initial?.section ?? "dashboard");
  const [tab, setTab] = useState<PanelTab>(initial?.tab ?? "agents");
  const [window, setWindow] = useState<EventWindow>(initial?.window ?? "departure");
  const [view, setView] = useState<IterationView>(initial?.view ?? DEFAULT_VIEW);
  const [eventManagerOpen, setEventManagerOpen] = useState(initial?.eventManagerOpen ?? true);
  const [runId, setRunId] = useState<string | undefined>(initial?.runId);
  const [manualResponse, setManualResponse] = useState(initial?.manualResponse ?? false);
  const [runManual, setRunManual] = useState(
    initial?.runManual ?? initial?.manualResponse ?? false,
  );
  const [focus, setFocus] = useState<MapFocus | undefined>(undefined);

  const setMode = useCallback((next: Mode) => {
    setModeState(next);
    if (next === "live") setTab("operations"); // design 01: in LIVE la scheda attiva è Operations
  }, []);
  const selectSection = useCallback((next: Section) => {
    setSection(next);
    const opens = SECTION_TAB[next];
    if (opens) setTab(opens);
  }, []);
  const setAfter = useCallback((after: boolean) => setView((v) => ({ ...v, after })), []);
  const pickIteration = useCallback(
    (iteration: number) => setView({ after: true, pinned: iteration }),
    [],
  );
  const focusOn = useCallback((point: { lat: number; lon: number; label?: string | null }) => {
    setFocus((current) => ({ ...point, key: (current?.key ?? 0) + 1 }));
  }, []);
  const followRun = useCallback((next: string | undefined, options?: { manual?: boolean }) => {
    setRunId(next);
    setRunManual(options?.manual ?? false);
    setFocus(undefined);
    setView(DEFAULT_VIEW); // un run nuovo parte dalla sua iterazione più recente
    if (next !== undefined) {
      setEventManagerOpen(false);
      setModeState("scenario"); // un run è una simulazione: i suoi risultati non stanno in LIVE
    }
  }, []);

  const value = useMemo<ShellState>(
    () => ({
      mode,
      setMode,
      section,
      selectSection,
      tab,
      setTab,
      window,
      setWindow,
      view,
      setAfter,
      pickIteration,
      eventManagerOpen,
      setEventManagerOpen,
      runId,
      followRun,
      runManual,
      focus,
      focusOn,
      manualResponse,
      setManualResponse,
    }),
    [
      mode,
      setMode,
      section,
      selectSection,
      tab,
      window,
      view,
      setAfter,
      pickIteration,
      eventManagerOpen,
      runId,
      followRun,
      runManual,
      focus,
      focusOn,
      manualResponse,
    ],
  );
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}
