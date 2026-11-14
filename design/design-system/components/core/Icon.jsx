import React from 'react';
export const DEPARTMENTS={traffic:{name:'Traffic Control',icon:'traffic-cone',unit:'agenti disponibili'},police:{name:'Municipal Police',icon:'shield',unit:'pattuglie disponibili'},transport:{name:'Transport Control',icon:'bus',unit:'mezzi disponibili'},comms:{name:'Public Communication',icon:'megaphone',unit:'canali disponibili'}};
const ALIAS={'loader-2':'loader-circle','alert-triangle':'triangle-alert'};
const pascal=(s)=>s.split('-').map((p)=>p.charAt(0).toUpperCase()+p.slice(1)).join('');
export function Icon({name,size=20,stroke=1.5,spin=false,className='',style}){
  const L=typeof window!=='undefined'?window.lucide:null;
  const icons=(L&&L.icons)||{};
  const raw=icons[pascal(name)]||icons[pascal(ALIAS[name]||name)];
  const node=raw&&raw[0]==='svg'?raw[2]:raw;
  return <svg className={'nuo-icon '+(spin?'nuo-spin ':'')+className} style={style} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{node?node.map((n,i)=>React.createElement(n[0],{key:i,...Object.fromEntries(Object.entries(n[1]).map(([k,v])=>[k.replace(/-([a-z])/g,(m,c)=>c.toUpperCase()),v]))})):null}</svg>;
}
