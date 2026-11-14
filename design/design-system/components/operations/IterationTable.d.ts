import * as React from 'react';
export interface IterationTableProps{
  /** Intestazioni delle 3 colonne iterazione */
  columns?:string[];
  rows:{metric:string;badge?:'real'|'estimate'|'simulated'|'unavailable';values:string[]}[];
  /** Indice della riga in stato hover forzato (specimen statici) */
  hoverRow?:number;
}
export declare function IterationTable(props:IterationTableProps):JSX.Element;
