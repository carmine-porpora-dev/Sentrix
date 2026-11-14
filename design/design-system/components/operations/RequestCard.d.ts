import * as React from 'react';
export interface RequestCardProps{
  dept?:'traffic'|'police'|'transport'|'comms';
  /** es. REQ-014 */
  code:string;
  status?:'CREATED'|'SENT'|'RECEIVED'|'ACCEPTED'|'REJECTED'|'IN_PROGRESS'|'COMPLETED';
  measure:string;
  rejection?:{code:string;reason:string};
  /** Codice richiesta originale: rende la card un'alternativa */
  alternativeTo?:string;
}
export declare function RequestCard(props:RequestCardProps):JSX.Element;
