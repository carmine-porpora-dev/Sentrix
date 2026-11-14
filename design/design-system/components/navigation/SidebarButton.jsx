import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function SidebarButton({icon,label,active=false,onClick}){
  return <button type="button" className={'nuo-sbtn'+(active?' is-active':'')} aria-label={label} title={label} aria-current={active?'page':undefined} onClick={onClick}><Icon name={icon} size={22} /></button>;
}
