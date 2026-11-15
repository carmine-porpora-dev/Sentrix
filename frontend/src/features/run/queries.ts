import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useMemo } from "react";
import { useApi } from "@/api/provider";
import type {
  Decision,
  ManualResponse,
  Measured,
  MetricsResponse,
  Notification,
  NotificationChannel,
  RequestView,
  Run,
  VdeptRegistry,
} from "@/api/types";
import { iterationMayBeReady, metricsQuery } from "@/features/metrics/queries";
import { evidenceIteration } from "@/features/run/derive";

/** Il registro dei dipartimenti con, per un run, le risorse residue. Si rilegge quando cambia qualcosa
 * (`signature`: stato del run e delle richieste) e intanto tiene i numeri di prima. */
export function useVdeptRegistry(runId: string | undefined, signature: string) {
  const api = useApi();
  return useQuery<VdeptRegistry>({
    queryKey: ["vdept", runId ?? "", signature],
    queryFn: () => api.vdeptRegistry(runId),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

/** Il registro delle decisioni di un run, riletto quando cambia qualcosa. */
export function useDecisions(runId: string | undefined, signature: string) {
  const api = useApi();
  return useQuery<Decision[]>({
    queryKey: ["decisions", runId ?? "", signature],
    queryFn: () => api.runDecisions(runId as string),
    enabled: runId !== undefined,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

/** Ogni quanto si chiede se il messaggio WhatsApp è partito, e fino a quando: il servizio può metterci
 * fino a due tentativi da 15 s (spech 12.4), poi non ha senso insistere (un evento senza chiusure non
 * ne manda nessuno, e non c'è modo di saperlo se non aspettando). */
export const NOTIFICATION_POLL_MS = 2000;
export const NOTIFICATION_WAIT_MS = 45_000;

/** Ogni quanto rileggere l'esito: mai se c'è già, né se il run è finito da troppo (o senza `ended_at`). */
export function notificationPollInterval(
  found: boolean,
  endedAt: number,
  now: number,
): number | false {
  return found || !(now - endedAt < NOTIFICATION_WAIT_MS) ? false : NOTIFICATION_POLL_MS;
}

/** Le notifiche in uscita di un canale per un run finito (spech 12): il messaggio WhatsApp e i
 * bollettini ai servizi di emergenza partono DOPO `DONE`, in secondo piano. Finché non ce n'è
 * nessuna si rilegge ogni `NOTIFICATION_POLL_MS`, per al più `NOTIFICATION_WAIT_MS` dalla fine del
 * run. Vuoto finché non ci sono (o se il run non ne ha). */
export function useNotifications(
  run: Run | undefined,
  channel: NotificationChannel,
): Notification[] {
  const api = useApi();
  const runId = run?.id;
  const endedAt = run?.ended_at ? Date.parse(run.ended_at) : Number.NaN;
  const { data } = useQuery<Notification[]>({
    queryKey: ["notifications", runId ?? "", channel],
    queryFn: () => api.runNotifications(runId as string, channel),
    enabled: runId !== undefined && run?.state === "DONE",
    refetchInterval: (query) =>
      notificationPollInterval((query.state.data?.length ?? 0) > 0, endedAt, Date.now()),
    staleTime: Infinity,
  });
  return data ?? [];
}

/** L'esito della notifica WhatsApp del run (la sola riga di stato: nessuna anteprima, nessun
 * pulsante). `undefined` finché non c'è (o se il run non ne ha). */
export function useWhatsAppNotification(run: Run | undefined): Notification | undefined {
  return useNotifications(run, "whatsapp")[0];
}

/** I bollettini ai servizi di emergenza del run (simulati), uno per destinatario. */
export function useEmergencyBulletins(run: Run | undefined): Notification[] {
  return useNotifications(run, "emergency_bulletin");
}

/** «Conferma ricezione» di un bollettino: poi si rileggono le notifiche e il registro decisioni. */
export function useAcknowledge(runId: string | undefined) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (notificationId: number): Promise<Notification> =>
      api.ackNotification(notificationId),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications", runId ?? ""] });
      void queryClient.invalidateQueries({ queryKey: ["decisions"] });
    },
  });
}

/** La risposta di una persona a una richiesta (Accetta / Rifiuta con codice e motivo). Poi si
 * rileggono il run, il registro e le decisioni. */
export function useManualResponse(runId: string | undefined) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      deptId,
      actionId,
      body,
    }: {
      deptId: string;
      actionId: string;
      body: ManualResponse;
    }): Promise<RequestView> => api.manualResponse(deptId, actionId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["run", runId] });
      void queryClient.invalidateQueries({ queryKey: ["vdept"] });
      void queryClient.invalidateQueries({ queryKey: ["decisions"] });
    },
  });
}

/** Accetta in blocco le richieste ferme in attesa di una persona (stessa chiamata di «Accetta», una
 * dopo l'altra). Restituisce quelle che il dipartimento non ha accettato (es. 409: la regola le
 * rifiuterebbe): le altre sono andate. Poi si rileggono run, risorse e decisioni. */
export function useAcceptAll(runId: string | undefined) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (items: { deptId: string; actionId: string }[]): Promise<string[]> => {
      const failed: string[] = [];
      for (const { deptId, actionId } of items) {
        try {
          await api.manualResponse(deptId, actionId, { decision: "accept" });
        } catch {
          failed.push(actionId);
        }
      }
      return failed;
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["run", runId] });
      void queryClient.invalidateQueries({ queryKey: ["vdept"] });
      void queryClient.invalidateQueries({ queryKey: ["decisions"] });
    },
  });
}

/** Le metriche di ogni iterazione del run (0…n), con le stesse chiavi di `useRunMetrics`: una lettura
 * sola per iterazione, condivisa. */
export function useIterationMetrics(run: Run | undefined): (MetricsResponse | undefined)[] {
  const api = useApi();
  const runId = run?.id;
  const iterations = run ? Array.from({ length: run.iteration + 1 }, (_, n) => n) : [];
  const results = useQueries({
    queries: iterations.map((iteration) =>
      metricsQuery(api, runId, iteration, run !== undefined && iterationMayBeReady(run, iteration)),
    ),
  });
  return results.map((result) => result.data);
}

/** Le metriche citate come evidenza (`m.<run>.it<n>.…`): id → numero con la sua provenienza. Quelle che
 * non sono metriche (un arco, una richiesta) o non sono ancora arrivate non ci sono. */
export function useEvidence(
  runId: string | undefined,
  ids: readonly string[],
): ReadonlyMap<string, Measured> {
  const api = useApi();
  const iterations = useMemo(
    () => [...new Set(ids.flatMap((id) => evidenceIteration(id) ?? []))].sort((a, b) => a - b),
    [ids],
  );
  const results = useQueries({
    queries: iterations.map((iteration) => ({
      ...metricsQuery(api, runId, iteration),
      enabled: runId !== undefined,
    })),
  });
  return useMemo(() => {
    const found = new Map<string, Measured>();
    for (const result of results) {
      for (const metric of result.data?.metrics ?? []) found.set(metric.id, metric);
    }
    return found;
  }, [results]);
}
