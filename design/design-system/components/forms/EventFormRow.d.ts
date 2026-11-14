import * as React from 'react';
export interface EventFormRowProps{
  /** Icona Lucide 16px */
  icon:string;
  label:string;
  /** Valore in Geist Mono (es. data, finestra oraria, quota modale) */
  value:string;
  /** In LIVE il valore è "—" */
  live?:boolean;
}
export declare function EventFormRow(props:EventFormRowProps):JSX.Element;
