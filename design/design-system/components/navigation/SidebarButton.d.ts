import * as React from 'react';
export interface SidebarButtonProps{
  icon:string;
  /** aria-label e title */
  label:string;
  active?:boolean;
  onClick?:()=>void;
}
export declare function SidebarButton(props:SidebarButtonProps):JSX.Element;
