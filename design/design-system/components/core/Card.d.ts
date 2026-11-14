import * as React from 'react';
export interface CardProps{
  variant?:'default'|'nested';
  /** 16 o 20 */
  padding?:16|20;
  clickable?:boolean;
  onClick?:()=>void;
  className?:string;
  style?:React.CSSProperties;
  children?:React.ReactNode;
}
export declare function Card(props:CardProps):JSX.Element;
