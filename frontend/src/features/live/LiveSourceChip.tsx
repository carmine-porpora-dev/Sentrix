import { SourceChip } from "@/components/SourceChip";
import { useLiveFlow } from "@/features/live/queries";
import { liveStatus } from "@/features/live/status";
import { formatClock } from "@/lib/format";
import { strings } from "@/i18n/it";

const copy = strings.live;

/** In LIVE, se TomTom non risponde (snapshot, nessun dato o un errore di rete verso il nostro server)
 * il chip giallo della barra superiore lo dice (design 02), con il motivo e, se c'è un ultimo dato, la
 * sua ora. Nessun errore a schermo intero: il resto dell'interfaccia continua a funzionare. */
export function LiveSourceChip() {
  const query = useLiveFlow(true);
  const status = liveStatus(query);
  if (status === "loading" || status === "ok") return null;
  const flow = query.data;
  const hasData = status === "partial";
  const newest = flow?.segments
    .map((s) => s.fetched_at)
    .sort()
    .at(-1);
  const reasons: Record<string, string> = copy.reasons;
  const reason = flow?.degraded_reason
    ? (reasons[flow.degraded_reason] ?? flow.degraded_reason)
    : "";
  return (
    <SourceChip label={copy.sourceChip(copy.source)} title={copy.source}>
      <p>{hasData ? copy.sourceNote.snapshot : copy.sourceNote.unavailable}</p>
      {reason && <p>{reason}</p>}
      {hasData && newest && <p className="font-mono text-xs">{copy.asOf(formatClock(newest))}</p>}
    </SourceChip>
  );
}
