import React,{useState} from 'react';
import { Icon } from '../core/Icon.jsx';
import { RequestCard } from './RequestCard.jsx';
export function RequestGroup({request,alternatives=[],open,defaultOpen=false,onToggle,unread=false}){
  const [o,setO]=useState(defaultOpen);
  const isOpen=open!==undefined?open:o;
  const n=alternatives.length;
  const toggle=()=>{setO(!isOpen);onToggle&&onToggle(!isOpen)};
  return <div className="nuo-rg"><RequestCard {...request} />
    {n>0&&<button type="button" className="nuo-rg__toggle" aria-expanded={isOpen} onClick={toggle}>
      <Icon name="corner-down-right" size={16} /><span>{n===1?'1 alternativa':n+' alternative'}</span>
      {!isOpen&&unread&&<span className="nuo-rg__new"><i />Nuova risposta</span>}
      <Icon name={isOpen?'chevron-up':'chevron-down'} size={20} style={{marginLeft:'auto'}} /></button>}
    {n>0&&isOpen&&<div className="nuo-rg__alts">{alternatives.map((a)=><RequestCard key={a.code} {...a} alternativeTo={a.alternativeTo||request.code} />)}</div>}
  </div>;
}
