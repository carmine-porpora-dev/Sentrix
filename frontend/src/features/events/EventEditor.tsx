import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "@/api/errors";
import type { AttendanceLevel, Event, EventSummary, Feature, FeatureCollection } from "@/api/types";
import { isRunFinished, useRun } from "@/api/queries";
import {
  draftFromEvent,
  draftToInput,
  emptyDraft,
  renderedPaths,
  sameDraft,
  slugFromName,
  toggleEdge,
  toggleStop,
  withCenter,
  type EdgeRef,
  type EventDraft,
  type StopRef,
} from "@/features/events/draft";
import { errorMap, paths, type FieldErrors, type FieldProblem } from "@/features/events/paths";
import { useEvents, useResetEvent, useSaveEvent, useCreateRun } from "@/features/events/queries";
import { useEvent } from "@/features/metrics/queries";
import { useShell } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";

/** Che cosa fa il prossimo clic sulla mappa: nulla (si guarda), sceglie il centro dell'area, un arco
 * da chiudere, una fermata da interrompere. */
export type MapMode = "idle" | "area" | "closures" | "stops";

/** «Evento nuovo» al posto dell'identificativo di un Evento. */
export const NEW_EVENT = "__new__";

export interface EventEditorState {
  events: EventSummary[];
  eventsStatus: "loading" | "ready" | "error";
  selectedId: string | undefined;
  isNew: boolean;
  /** Cambia quando il form si riempie con un Evento (o con uno nuovo): dice quale «versione» si sta modificando. */
  loadKey: string | undefined;
  /** L'Evento come sta sul server (non c'è per uno nuovo). */
  saved: Event | undefined;
  /** Si sta leggendo l'Evento scelto, o la lettura è fallita. */
  eventStatus: "idle" | "loading" | "ready" | "error";
  select: (eventId: string) => void;
  startNew: () => void;
  resetPreset: () => void;
  resetting: boolean;

  draft: EventDraft;
  /** Il nome (e, per un Evento nuovo, l'identificativo che ne deriva) e l'identificativo scritto a mano. */
  setName: (name: string) => void;
  setId: (id: string) => void;
  /** Cambia la bozza; i campi `clear` perdono l'errore dell'API (si sta correggendo). */
  edit: (change: (draft: EventDraft) => EventDraft, clear?: readonly string[]) => void;
  dirty: boolean;

  /** Gli errori da mostrare accanto ai campi: quelli dell'API e quelli del form (un campo vuoto si
   * segnala solo dopo averlo toccato o provato a salvare). */
  errors: FieldErrors;
  /** Errori dell'API su campi che il form non mostra: si leggono in cima. */
  unplaced: FieldProblem[];
  /** Perché il form non si può inviare (campi mancanti), per «Analizza» disabilitato. */
  missing: number;
  touch: (path: string) => void;

  level: AttendanceLevel;
  setLevel: (level: AttendanceLevel) => void;

  mapMode: MapMode;
  toggleMapMode: (mode: Exclude<MapMode, "idle">) => void;
  /** Il rettangolo visibile della mappa (per chiedere strade e fermate). */
  viewBounds: [[number, number], [number, number]] | undefined;
  setViewBounds: (bounds: [[number, number], [number, number]]) => void;
  placeCenter: (lat: number, lon: number) => void;
  toggleEdgeAt: (edge: EdgeRef, geometry: Feature["geometry"]) => void;
  toggleStopAt: (stop: StopRef) => void;
  /** La geometria degli archi scelti in questa sessione, per disegnarli prima di salvare. */
  pickedEdges: FeatureCollection;

  analyze: () => Promise<void>;
  analyzing: boolean;
  /** Il form si può inviare: nessun campo mancante e l'evento è letto. Che un run sia in corso o che si
   * stia già inviando lo dice `analyzing`/`runInProgress`: in quel caso «Analizza» non risponde. */
  canAnalyze: boolean;
  /** Perché «Analizza» non è partito (rete, limite di richieste…), se non è un errore di campo. */
  submitError: string | undefined;
  /** Un run è in corso. */
  runInProgress: boolean;
}

const EditorContext = createContext<EventEditorState | null>(null);

export function useEventEditor(): EventEditorState {
  const editor = useContext(EditorContext);
  if (!editor) throw new Error("useEventEditor fuori da <EventEditorProvider>");
  return editor;
}

/** Come `useEventEditor`, ma senza l'editor (la mappa si può usare anche da sola). */
export function useOptionalEventEditor(): EventEditorState | null {
  return useContext(EditorContext);
}

/** Le righe `{path, message}` di un 400 `VALIDATION_ERROR` (06 1), o nessuna. */
export function validationProblems(error: unknown): FieldProblem[] {
  if (!(error instanceof ApiError) || error.status !== 400) return [];
  const fields = error.details?.fields;
  if (!Array.isArray(fields)) return [];
  return fields.flatMap((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return [];
    const { path, message } = item as { path?: unknown; message?: unknown };
    return typeof path === "string" && typeof message === "string" ? [{ path, message }] : [];
  });
}

export function EventEditorProvider({ children }: { children: ReactNode }) {
  const shell = useShell();
  const events = useEvents();
  const [chosenId, setChosenId] = useState<string | undefined>(undefined);
  // finché non se ne sceglie uno, quello di partenza è il primo dell'elenco
  const selectedId = chosenId ?? events.data?.[0]?.id;
  const isNew = selectedId === NEW_EVENT;
  const loaded = useEvent(isNew ? undefined : selectedId);
  const saved = isNew ? undefined : loaded.data;

  const [draft, setDraft] = useState<EventDraft>(emptyDraft);
  const [baseline, setBaseline] = useState<EventDraft>(emptyDraft);
  const [serverProblems, setServerProblems] = useState<FieldProblem[]>([]);
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());
  const [attempted, setAttempted] = useState(false);
  const [idEdited, setIdEdited] = useState(false);
  const [level, setLevel] = useState<AttendanceLevel>("mid");
  const [mapMode, setMapMode] = useState<MapMode>("idle");
  const [viewBounds, setViewBounds] = useState<EventEditorState["viewBounds"]>(undefined);
  const [picked, setPicked] = useState<ReadonlyMap<string, Feature>>(new Map());
  const [analyzing, setAnalyzing] = useState(false);
  const [submitError, setSubmitError] = useState<string | undefined>(undefined);
  // cambia quando c'è un Evento nuovo da riempire, o dopo aver salvato o ripristinato
  const [version, setVersion] = useState(0);
  const [appliedKey, setAppliedKey] = useState<string | undefined>(undefined);

  const save = useSaveEvent();
  const resetEvent = useResetEvent();
  const createRun = useCreateRun();
  const run = useRun(shell.runId).data?.run;
  const runInProgress = run !== undefined && !isRunFinished(run.state);

  // Il form si riempie quando arriva l'Evento scelto (o uno nuovo, vuoto), e di nuovo dopo un
  // salvataggio o un ripristino. Si sistema durante il rendering e non in un effetto: così il form
  // non mostra mai per un istante i dati dell'Evento di prima.
  const sourceKey = isNew
    ? `new#${version}`
    : loaded.data
      ? `${loaded.data.id}#${version}`
      : undefined;
  if (sourceKey !== undefined && sourceKey !== appliedKey) {
    const next = loaded.data && !isNew ? draftFromEvent(loaded.data) : emptyDraft();
    setAppliedKey(sourceKey);
    setDraft(next);
    setBaseline(next);
    setServerProblems([]);
    setTouched(new Set());
    setAttempted(false);
    setSubmitError(undefined);
    setIdEdited(false);
    setPicked(new Map());
  }

  const dirty = !sameDraft(draft, baseline);

  const confirmDiscard = useCallback(
    () => !dirty || window.confirm(strings.events.discardConfirm),
    [dirty],
  );

  const select = useCallback(
    (eventId: string) => {
      if (eventId === selectedId || !confirmDiscard()) return;
      setMapMode("idle");
      setChosenId(eventId);
    },
    [selectedId, confirmDiscard],
  );

  const startNew = useCallback(() => {
    if (!confirmDiscard()) return;
    setMapMode("idle");
    setChosenId(NEW_EVENT);
    setVersion((current) => current + 1);
  }, [confirmDiscard]);

  const resetPreset = useCallback(() => {
    if (!selectedId || isNew) return;
    if (dirty && !window.confirm(strings.events.discardConfirm)) return;
    resetEvent.mutate(selectedId, { onSuccess: () => setVersion((current) => current + 1) });
  }, [selectedId, isNew, dirty, resetEvent]);

  const taken = useMemo(() => new Set((events.data ?? []).map((item) => item.id)), [events.data]);

  const edit = useCallback(
    (change: (draft: EventDraft) => EventDraft, clear: readonly string[] = []) => {
      setDraft(change);
      if (clear.length > 0) {
        setServerProblems((current) => current.filter((item) => !clear.includes(item.path)));
      }
    },
    [],
  );

  // Un Evento nuovo: l'identificativo segue il nome finché non lo si scrive a mano.
  const setName = useCallback(
    (name: string) => {
      setDraft((current) => ({
        ...current,
        name,
        id: isNew && !idEdited ? slugFromName(name, taken) : current.id,
      }));
      setServerProblems((current) =>
        current.filter((item) => item.path !== paths.name && item.path !== paths.id),
      );
    },
    [isNew, idEdited, taken],
  );

  const setId = useCallback((id: string) => {
    setIdEdited(true);
    setDraft((current) => ({ ...current, id }));
    setServerProblems((current) => current.filter((item) => item.path !== paths.id));
  }, []);

  const touch = useCallback(
    (path: string) =>
      setTouched((current) => (current.has(path) ? current : new Set(current).add(path))),
    [],
  );

  const result = useMemo(() => draftToInput(draft), [draft]);
  const localProblems = useMemo(() => (result.ok ? [] : result.problems), [result]);

  const errors = useMemo(() => {
    const shown = localProblems.filter(
      (item) =>
        item.message !== strings.events.problems.required || attempted || touched.has(item.path),
    );
    // l'errore dell'API vale finché non si corregge quel campo
    return errorMap([...shown, ...serverProblems]);
  }, [localProblems, serverProblems, touched, attempted]);

  const unplaced = useMemo(() => {
    const known = renderedPaths(draft);
    return serverProblems.filter((item) => !known.has(item.path));
  }, [serverProblems, draft]);

  const placeCenter = useCallback(
    (lat: number, lon: number) => {
      edit((current) => withCenter(current, lat, lon), [paths.centerLat, paths.centerLon]);
      setMapMode("idle");
    },
    [edit],
  );

  const toggleEdgeAt = useCallback(
    (edge: EdgeRef, geometry: Feature["geometry"]) => {
      setPicked((current) =>
        new Map(current).set(edge.edgeKey, {
          type: "Feature",
          geometry,
          properties: { edge_key: edge.edgeKey, reverse_key: edge.reverseKey, name: edge.name },
        }),
      );
      edit((current) => toggleEdge(current, edge));
    },
    [edit],
  );

  const toggleStopAt = useCallback(
    (stop: StopRef) => edit((current) => toggleStop(current, stop)),
    [edit],
  );

  const toggleMapMode = useCallback(
    (mode: Exclude<MapMode, "idle">) => setMapMode((current) => (current === mode ? "idle" : mode)),
    [],
  );

  const pickedEdges = useMemo<FeatureCollection>(
    () => ({ type: "FeatureCollection", features: [...picked.values()] }),
    [picked],
  );

  const eventStatus: EventEditorState["eventStatus"] = isNew
    ? "ready"
    : selectedId === undefined
      ? "idle"
      : loaded.isError
        ? "error"
        : loaded.data
          ? "ready"
          : "loading";

  // gli errori dell'API non bloccano: si correggono e si riprova (alcuni non hanno un campo)
  const canAnalyze = result.ok && eventStatus === "ready";

  const analyze = useCallback(async () => {
    setAttempted(true);
    setSubmitError(undefined);
    if (!result.ok || runInProgress) return;
    setAnalyzing(true);
    try {
      let eventId = result.input.id;
      if (isNew || dirty) {
        const savedEvent = await save.mutateAsync({ input: result.input, isNew });
        eventId = savedEvent.id;
        setChosenId(savedEvent.id);
        setVersion((current) => current + 1);
      }
      const created = await createRun.mutateAsync({
        event_id: eventId,
        attendance_level: level,
        manual_response: shell.manualResponse,
      });
      setMapMode("idle");
      shell.followRun(created.run_id, { manual: shell.manualResponse });
    } catch (error) {
      const problems = validationProblems(error);
      if (problems.length > 0) setServerProblems(problems);
      else setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setAnalyzing(false);
    }
  }, [result, runInProgress, isNew, dirty, save, createRun, level, shell]);

  const value = useMemo<EventEditorState>(
    () => ({
      events: events.data ?? [],
      eventsStatus: events.isError ? "error" : events.data ? "ready" : "loading",
      selectedId,
      isNew,
      loadKey: appliedKey,
      saved,
      eventStatus,
      select,
      startNew,
      resetPreset,
      resetting: resetEvent.isPending,
      draft,
      setName,
      setId,
      edit,
      dirty,
      errors,
      unplaced,
      missing: localProblems.length,
      touch,
      level,
      setLevel,
      mapMode,
      toggleMapMode,
      viewBounds,
      setViewBounds,
      placeCenter,
      toggleEdgeAt,
      toggleStopAt,
      pickedEdges,
      analyze,
      analyzing,
      canAnalyze,
      submitError,
      runInProgress,
    }),
    [
      events.data,
      events.isError,
      selectedId,
      isNew,
      appliedKey,
      saved,
      eventStatus,
      select,
      startNew,
      resetPreset,
      resetEvent.isPending,
      draft,
      setName,
      setId,
      edit,
      dirty,
      errors,
      unplaced,
      localProblems.length,
      touch,
      level,
      mapMode,
      toggleMapMode,
      viewBounds,
      placeCenter,
      toggleEdgeAt,
      toggleStopAt,
      pickedEdges,
      analyze,
      analyzing,
      canAnalyze,
      submitError,
      runInProgress,
    ],
  );

  return <EditorContext.Provider value={value}>{children}</EditorContext.Provider>;
}
