import React from 'react';
export function ModeSelector({value='live',onChange}){
  const M=[['live','LIVE','Dati reali'],['scenario','SCENARIO','Simulazione']];
  return <div className="nuo-modes" role="radiogroup" aria-label="Modalità">
    {M.map(([k,n,s])=><button key={k} type="button" role="radio" aria-checked={value===k} className={'nuo-mode nuo-mode--'+k+(value===k?' is-active':'')} onClick={()=>onChange&&onChange(k)}><span className="nuo-mode__name">{n}</span><span className="nuo-mode__sub">{s}</span></button>)}
  </div>;
}
