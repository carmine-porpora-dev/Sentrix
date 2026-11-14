import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function DecisionCallout({title='Decisione umana richiesta',measure,children}){
  return <div className="nuo-callout nuo-callout--decision" role="alert"><Icon name="triangle-alert" size={28} style={{color:'var(--color-warning)'}} />
    <div className="nuo-callout__body"><div className="nuo-callout__title">{title}</div><div className="nuo-callout__msg">{measure}</div>{children}</div></div>;
}
