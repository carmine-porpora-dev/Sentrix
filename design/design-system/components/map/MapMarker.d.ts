import * as React from 'react';
export interface MapMarkerProps{
  dept?:'traffic'|'police'|'transport'|'comms';
  state?:'normal'|'accepted'|'rejected';
}
export declare function MapMarker(props:MapMarkerProps):JSX.Element;
