import * as React from 'react';
export interface ProvenanceTooltipProps{
  /** Nome della metrica */
  title:string;
  badge?:'real'|'estimate'|'simulated'|'unavailable'|null;
  /** [etichetta, valore | righe[]]: Fonte, Metodo, Unità, Ora del dato, Assunzioni */
  rows:[string,string|string[]][];
  /** Posizionamento assoluto sotto il genitore (usato da MetricCard) */
  floating?:boolean;
}
export declare function ProvenanceTooltip(props:ProvenanceTooltipProps):JSX.Element;
