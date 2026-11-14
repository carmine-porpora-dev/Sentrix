import React from 'react';
import { Badge } from '../core/Badge.jsx';
export function FieldHeader({label,badge}){
  return <div className="nuo-fhead"><span className="nuo-field__label">{label}</span>{badge&&<Badge kind={badge} />}</div>;
}
