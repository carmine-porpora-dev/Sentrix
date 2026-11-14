import * as React from 'react';
export interface TextFieldProps{
  label?:string;
  value:string;
  onChange?:(v:string)=>void;
  placeholder?:string;
  /** Testo a destra, es. "persone" */
  suffix?:string;
  mono?:boolean;
  error?:string;
  disabled?:boolean;
  hint?:string;
  id?:string;
  inputMode?:'numeric'|'text';
}
export declare function TextField(props:TextFieldProps):JSX.Element;
