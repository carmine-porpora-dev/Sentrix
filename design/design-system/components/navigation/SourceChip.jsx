import React,{useState,useEffect,useRef} from 'react';
import { Icon } from '../core/Icon.jsx';
export function SourceChip({sources=[],defaultOpen=false}){
  const [open,setOpen]=useState(defaultOpen);
  const ref=useRef(null);
  useEffect(()=>{const h=(e)=>{if(e.type==='keydown'?e.key==='Escape':ref.current&&!ref.current.contains(e.target))setOpen(false)};document.addEventListener('mousedown',h);document.addEventListener('keydown',h);return()=>{document.removeEventListener('mousedown',h);document.removeEventListener('keydown',h)}},[]);
  if(!sources.length)return null;
  const text=sources.length===1?'Fonte non disponibile: '+sources[0]:sources.length+' fonti non disponibili';
  return <div className="nuo-src" ref={ref}>
    <button type="button" className="nuo-srcchip" aria-expanded={open} onClick={()=>setOpen(!open)}><Icon name="triangle-alert" size={16} />{text}<Icon name="chevron-down" size={16} /></button>
    {open&&<div className="nuo-pop" role="dialog">{sources.map((s)=><div key={s}><b>{s}</b><span>Non disponibile. Si usano gli ultimi dati noti.</span></div>)}</div>}
  </div>;
}
