import React from 'react';
import { Icon } from './Icon.jsx';
export function EmptyState({icon,title,tone='neutral',children,className=''}){
  const ic=icon||(tone==='success'?'circle-check':'inbox');
  return <div className={'nuo-empty nuo-empty--'+tone+' '+className}><Icon name={ic} size={48} stroke={1.5} /><div className="nuo-empty__title">{title}</div>{children&&<div className="nuo-empty__text">{children}</div>}</div>;
}
