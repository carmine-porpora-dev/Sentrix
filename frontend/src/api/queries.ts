import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { queryKeys, useApi } from "@/api/provider";
import type { AuthState, RunState } from "@/api/types";

export const RUN_POLL_MS = 1000;
const FINISHED: readonly RunState[] = ["DONE", "ERROR"];

/** Il run non cambia più: il polling si ferma (07 3). */
export function isRunFinished(state: RunState | undefined): boolean {
  return state !== undefined && FINISHED.includes(state);
}

/** Chi sono (`GET /api/auth/me`): `authenticated` dice se serve il login. */
export function useMe() {
  const api = useApi();
  // senza nuovi tentativi automatici: se il server non risponde l'AuthGate propone «Riprova»
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api.me(),
    staleTime: Infinity,
    retry: false,
  });
}

export function useLogin() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => api.login(password),
    onSuccess: (state: AuthState) => queryClient.setQueryData(queryKeys.me, state),
  });
}

export function useLogout() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.logout(),
    onSuccess: (state: AuthState) => {
      queryClient.setQueryData(queryKeys.me, state);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== queryKeys.me[0] });
    },
  });
}

/** Un run, riletto ogni secondo finché non è `DONE` o `ERROR`. */
export function useRun(runId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.run(runId ?? ""),
    queryFn: () => api.getRun(runId as string),
    enabled: runId !== undefined,
    refetchInterval: (query) => (isRunFinished(query.state.data?.run.state) ? false : RUN_POLL_MS),
  });
}

/** Il nome di un dipartimento come lo scrive il registro (`config/departments.yaml`): è l'unico posto
 * in cui vive. Finché il registro non è arrivato, o per un id che non c'è, si mostra l'id. */
export function useDepartmentName(): (id: string) => string {
  const api = useApi();
  const { data } = useQuery({
    queryKey: queryKeys.departments,
    queryFn: () => api.vdeptRegistry(),
    staleTime: Infinity,
  });
  return useCallback(
    (id: string) => data?.departments.find((department) => department.id === id)?.label ?? id,
    [data],
  );
}
