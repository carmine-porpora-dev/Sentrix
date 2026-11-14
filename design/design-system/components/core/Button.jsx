import React from 'react';
import { Icon } from './Icon.jsx';
export function Button({variant='solid',icon,loading=false,loadingLabel='Analisi in corso…',disabled=false,block=false,ariaLabel,type='button',onClick,children}){
  const iconOnly=!children&&!loading;
  const cls=['nuo-btn','nuo-btn--'+variant,iconOnly?'nuo-btn--icon':'',block?'nuo-btn--block':'',loading?'is-loading':''].join(' ');
  return <button type={type} className={cls} disabled={disabled} aria-label={ariaLabel} aria-busy={loading||undefined} onClick={loading?undefined:onClick}>
    {loading?<Icon name="loader-2" spin />:icon?<Icon name={icon} />:null}
    {loading?loadingLabel:children}
  </button>;
}
