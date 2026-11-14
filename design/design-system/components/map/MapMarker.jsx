import React from 'react';
import { Icon, DEPARTMENTS } from '../core/Icon.jsx';
export function MapMarker({dept='traffic',state='normal'}){
  const c=state==='accepted'?'var(--color-status-accepted)':state==='rejected'?'var(--color-status-rejected)':'var(--color-accent)';
  return <span className="nuo-marker" style={{'--c':c}}>
    <span className="nuo-marker__body"><Icon name={DEPARTMENTS[dept].icon} size={24} /></span><span className="nuo-marker__tail" />
    {state!=='normal'&&<span className="nuo-marker__badge"><Icon name={state==='accepted'?'check':'x'} size={12} stroke={3} /></span>}
  </span>;
}
