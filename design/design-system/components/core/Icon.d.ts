import * as React from 'react';
/** Icona Lucide (stroke 1.5). Richiede lucide UMD caricato in pagina. */
export interface IconProps{
  /** Nome Lucide in kebab-case, es. "traffic-cone" */
  name:string;
  /** px. Base 20, sidebar 22, marker 24 */
  size?:number;
  stroke?:number;
  spin?:boolean;
  className?:string;
  style?:React.CSSProperties;
}
export declare const DEPARTMENTS:Record<'traffic'|'police'|'transport'|'comms',{name:string;icon:string;unit:string}>;
export declare function Icon(props:IconProps):JSX.Element;
