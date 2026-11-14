import * as React from 'react';
export interface RunStatusProps{
  state?:'INTAKE'|'ANALYZE'|'RECONCILE'|'PLAN'|'DISPATCH'|'AWAIT'|'REPLAN'|'VERIFY'|'DONE'|'ERRORE'|'DECISIONE';
  /** Indice tacca corrente (0–8) per ERRORE e DECISIONE */
  step?:number;
}
export declare function RunStatus(props:RunStatusProps):JSX.Element;
