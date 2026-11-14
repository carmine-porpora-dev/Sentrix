import * as React from 'react';
export interface SidebarProps{
  items:{id:string;icon:string;label:string}[];
  active?:string;
  onSelect?:(id:string)=>void;
  /** Sigla provvisoria al posto del logo */
  brand?:string;
  /** Altezza CSS opzionale (di default riempie il contenitore) */
  height?:string|number;
}
export declare function Sidebar(props:SidebarProps):JSX.Element;
