import React from 'react';
import { SidebarButton } from './SidebarButton.jsx';
export function Sidebar({ items = [], active, onSelect, brand = 'NUO', height }) {
  return <nav className="nuo-sidebar" style={height ? { height } : undefined} aria-label="Principale">
    <div className="nuo-sidebar__brand" title="Sentrix">{brand}</div>
    <div className="nuo-sidebar__items">{items.map((it) => <SidebarButton key={it.id} icon={it.icon} label={it.label} active={active === it.id} onClick={() => onSelect && onSelect(it.id)} />)}</div>
  </nav>;
}
