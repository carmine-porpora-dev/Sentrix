import * as React from 'react';
export interface EmptyStateProps{
  title:string;
  /** Icona Lucide. Default: inbox (neutral), circle-check (success) */
  icon?:string;
  /** success = verde (success) per l'esito positivo; neutral = text-secondary */
  tone?:'neutral'|'success';
  /** Testo secondario opzionale */
  children?:React.ReactNode;
  className?:string;
}
export declare function EmptyState(props:EmptyStateProps):JSX.Element;
