import * as React from 'react';
export interface ButtonProps{
  variant?:'solid'|'stroke'|'ghost';
  /** Nome icona Lucide a sinistra */
  icon?:string;
  loading?:boolean;
  loadingLabel?:string;
  disabled?:boolean;
  block?:boolean;
  /** Obbligatorio se solo icona */
  ariaLabel?:string;
  type?:'button'|'submit';
  onClick?:()=>void;
  children?:React.ReactNode;
}
export declare function Button(props:ButtonProps):JSX.Element;
