import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function EventManagerRail({running=false,open=false,onToggle,className=''}){
  return <button type="button" className={'nuo-rail '+className} aria-expanded={open} aria-label="Analisi evento" onClick={onToggle}>
    {running&&<span className="nuo-loadbar" />}
    <span className="nuo-rail__row"><Icon name="calendar-clock" size={20} style={{color:'var(--color-accent)'}} /><Icon name={open?'chevron-up':'chevron-down'} size={20} style={{color:'var(--color-text-secondary)'}} /></span>
    {running&&<span className="nuo-chip nuo-chip--sm" style={{'--c':'var(--color-accent)','--f':'var(--color-state-fill-running)'}}><span className="nuo-dot nuo-dot--pulse" />In corso</span>}
  </button>;
}
