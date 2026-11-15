import type { Measured } from "@/api/types";
import { MeasuredValue } from "@/components/MeasuredValue";
import { Tag } from "@/components/Tag";
import { tail } from "@/features/metrics/cards";

/** Le evidenze di un'affermazione (07 6): ogni metrica citata si mostra con il suo numero e il
 * tooltip di provenienza (fonte, metodo, input); quella che non è una metrica, o non è ancora arrivata,
 * si mostra con il suo nome e basta. Il numero non lo si ricava: lo si legge dalla metrica. */
export function EvidenceList({
  ids,
  evidence,
}: {
  ids: readonly string[];
  evidence: ReadonlyMap<string, Measured>;
}) {
  if (ids.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-x-space-12 gap-y-1">
      {ids.map((id) => {
        const measured = evidence.get(id);
        const name = id.startsWith("m.") ? tail(id) : id;
        return (
          <Tag as="li" key={id} title={id} mono={false} className="flex items-center gap-1.5">
            <span className="truncate font-mono">{name}</span>
            {measured && <MeasuredValue measured={measured} label={name} className="text-xs" />}
          </Tag>
        );
      })}
    </ul>
  );
}
