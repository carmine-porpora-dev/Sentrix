import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function ErrorCallout({message,instruction}){
  return <div className="nuo-callout nuo-callout--error" role="alert"><Icon name="triangle-alert" size={24} style={{color:'var(--color-danger)'}} />
    <div className="nuo-callout__body"><div className="nuo-callout__msg">{message}</div>{instruction&&<div className="nuo-callout__ins">{instruction}</div>}</div></div>;
}
