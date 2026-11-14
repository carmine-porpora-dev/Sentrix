import * as React from 'react';
export interface MetricCardProps{
  label:string;
  /** Valore (dopo, se c'è `before`) */
  value:string;
  /** Variante prima → dopo: valore iniziale in text-secondary + arrow-right 24px. Badge di default SIMULATO */
  before?:string;
  unit?:string;
  /** tone = significato (migliore/peggiore), non direzione */
  delta?:{tone:'better'|'worse'|'neutral';direction?:'up'|'down';text?:string};
  /** Default: real (o simulated con `before`). null = nessun badge */
  badge?:'real'|'estimate'|'simulated'|'unavailable'|null;
  /** Stessa altezza (146px) della card normale */
  loading?:boolean;
  /** Forza text-kpi-sm (automatico con `before` o 7+ caratteri) */
  compact?:boolean;
  /** Tooltip di provenienza in hover/focus sotto la card */
  provenance?:{title?:string;badge?:'real'|'estimate'|'simulated'|'unavailable'|null;rows:[string,string|string[]][]};
  /** Mostra il tooltip fisso (specimen statici) */
  showProvenance?:boolean;
}
export declare function MetricCard(props:MetricCardProps):JSX.Element;
