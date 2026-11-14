import React from 'react';
const L=[['Scorrevole','var(--color-map-congestion-1)'],['Rallentata','var(--color-map-congestion-2)'],['Intensa','var(--color-map-congestion-3)'],['Satura','var(--color-map-congestion-4)']];
export function MapLegend(){
  return <div className="nuo-legend">{L.map((l)=><span className="nuo-legend__i" key={l[0]}><span className="nuo-legend__sw" style={{'--c':l[1]}} />{l[0]}</span>)}</div>;
}
