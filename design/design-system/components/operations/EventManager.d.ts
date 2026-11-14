import * as React from 'react';
export interface EventManagerProps{
  /** Testo del campo affluenza (formato it-IT) */
  attendance?:string;
  onAttendanceChange?:(v:string)=>void;
  closures?:string[];
  stops?:string[];
  onRemoveClosure?:(i:number)=>void;
  onRemoveStop?:(i:number)=>void;
  onAnalyze?:()=>void;
  analyzing?:boolean;
}
export declare function EventManager(props:EventManagerProps):JSX.Element;
