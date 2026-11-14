import * as React from 'react';
export interface AgentTimelineItemProps{
  name:string;
  status?:'waiting'|'running'|'done'|'fallback'|'error';
  /** es. "3,2 s" */
  duration?:string;
  note?:string;
  last?:boolean;
}
export declare function AgentTimelineItem(props:AgentTimelineItemProps):JSX.Element;
