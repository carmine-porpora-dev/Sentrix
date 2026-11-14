import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function MapToggle({after=false,onAfterChange,iteration=1,onIterationChange,iterations=2}){
  const step=(d)=>onIterationChange&&onIterationChange(((iteration-1+d+iterations)%iterations)+1);
  return <div className="nuo-maptoggle">
    <div className="nuo-mt"><button type="button" className={'nuo-mt__lbl'+(!after?' is-on':'')} onClick={()=>onAfterChange&&onAfterChange(false)}>Prima</button>
      <button type="button" role="switch" aria-checked={after} aria-label="Prima / Dopo" className="nuo-mt__tr" onClick={()=>onAfterChange&&onAfterChange(!after)}><span className={'nuo-track'+(after?' is-on':'')} /></button>
      <button type="button" className={'nuo-mt__lbl'+(after?' is-on':'')} onClick={()=>onAfterChange&&onAfterChange(true)}>Dopo</button></div>
    <div className="nuo-mt" style={{padding:'0 5px'}}><button type="button" className="nuo-mt__arrow" aria-label="Iterazione precedente" onClick={()=>step(-1)}><Icon name="chevron-left" /></button>
      <span className="nuo-mt__it">Iterazione {iteration}</span>
      <button type="button" className="nuo-mt__arrow" aria-label="Iterazione successiva" onClick={()=>step(1)}><Icon name="chevron-right" /></button></div>
  </div>;
}
