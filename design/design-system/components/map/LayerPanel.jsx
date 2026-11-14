import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function LayerPanel({layers=[],onToggle}){
  return <div className="nuo-layers" role="group" aria-label="Livelli"><div className="nuo-layers__title">Livelli</div>
    {layers.map((l)=><button key={l.id} type="button" role="checkbox" aria-checked={l.on} className={'nuo-layer'+(l.on?' is-on':'')} onClick={()=>onToggle&&onToggle(l.id)}>
      <span className="nuo-layer__box">{l.on&&<Icon name="check" size={12} stroke={3} />}</span>
      <span className={'nuo-layer__sw'+(l.dashed?' nuo-layer__sw--dashed':'')} style={{'--c':l.color}} /><span className="nuo-layer__name">{l.name}</span></button>)}
  </div>;
}
