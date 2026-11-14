import * as React from 'react';
import { RequestCardProps } from './RequestCard';
export interface RequestGroupProps{
  /** Richiesta originale */
  request:RequestCardProps;
  alternatives?:RequestCardProps[];
  /** Controllato; senza, usa defaultOpen */
  open?:boolean;
  defaultOpen?:boolean;
  onToggle?:(open:boolean)=>void;
  /** Pallino "Nuova risposta": solo a gruppo chiuso con alternative */
  unread?:boolean;
}
export declare function RequestGroup(props:RequestGroupProps):JSX.Element;
