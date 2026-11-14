import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function EventFormRow({icon,label,value,live=false}){
  return <div className="nuo-efr"><Icon name={icon} size={16} /><span className="nuo-efr__label">{label}</span><span className="nuo-efr__value">{live?'—':value}</span></div>;
}
