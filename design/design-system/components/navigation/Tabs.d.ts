import * as React from 'react';
export interface TabsProps{
  items:{id:string;label:string}[];
  active:string;
  onChange?:(id:string)=>void;
}
export declare function Tabs(props:TabsProps):JSX.Element;
