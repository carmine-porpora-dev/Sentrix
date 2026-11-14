import React from 'react';
export function Tooltip({content,placement='top',open=false,children}){
  return <span className={'nuo-tip'+(placement==='bottom'?' nuo-tip--bottom':'')+(open?' nuo-tip--open':'')}>{children}<span className="nuo-tip__bubble" role="tooltip">{content}</span></span>;
}
