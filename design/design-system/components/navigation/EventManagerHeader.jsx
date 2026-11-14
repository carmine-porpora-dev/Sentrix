import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function EventManagerHeader({running=false,fixed=false,onToggle}){
  return <div className="nuo-emh"><Icon name="calendar-clock" size={20} style={{color:'var(--color-accent)'}} /><span className="nuo-emh__title">Analisi evento</span>{running&&<span className="nuo-chip nuo-chip--sm" style={{'--c':'var(--color-accent)','--f':'var(--color-state-fill-running)'}}><span className="nuo-dot nuo-dot--pulse" />In corso</span>}<span style={{flex:1}} />
    {!fixed&&<button type="button" className="nuo-emh__btn" aria-expanded="true" aria-label="Comprimi analisi evento" onClick={onToggle}><Icon name="chevron-up" size={20} /></button>}</div>;
}
