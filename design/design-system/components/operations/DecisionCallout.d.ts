import * as React from 'react';
export interface DecisionCalloutProps{
  title?:string;
  /** Testo della misura che richiede la decisione */
  measure:string;
  /** Slot per i pulsanti di decisione (non ancora definiti: domanda aperta 25) */
  children?:React.ReactNode;
}
export declare function DecisionCallout(props:DecisionCalloutProps):JSX.Element;
