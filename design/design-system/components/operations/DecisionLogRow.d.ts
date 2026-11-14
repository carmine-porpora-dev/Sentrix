import * as React from 'react';
export interface DecisionLogRowProps{
  time?:string;
  actor?:'system'|'agent'|'user'|'traffic'|'police'|'transport'|'comms';
  actorLabel?:string;
  decision?:string;
  reason?:string;
  /** Renderizza l'intestazione colonne */
  head?:boolean;
  /** 'wide' = 64/150/resto; 'log' = 56/132/resto (pannello 440px) */
  variant?:'wide'|'log';
  /** Hover forzato (specimen statici) */
  hover?:boolean;
}
export declare function DecisionLogRow(props:DecisionLogRowProps):JSX.Element;
