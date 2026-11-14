import * as React from 'react';
export interface LayerPanelProps{
  layers:{id:string;name:string;color:string;on:boolean;dashed?:boolean}[];
  onToggle?:(id:string)=>void;
}
export declare function LayerPanel(props:LayerPanelProps):JSX.Element;
