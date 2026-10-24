"""Read-only evidence from the CLI's documented exported transcript.

An ERROR is never accepted just because response text exists. Only a completed
current turn with an identical *older* error and no current error is eligible.
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path


def exported_content_matches(row,full):
    body=row.get('content')
    if not isinstance(body,str):return False
    if body==full:return True
    if 'content' not in row.get('truncated_fields',[]):return False
    markers=list(re.finditer(r'\n<truncated (\d+) bytes>\n',body))
    if len(markers)!=1:return False
    marker=markers[0];head=body[:marker.start()];tail=body[marker.end():]
    if not head or not tail or not full.startswith(head) or not full.endswith(tail):return False
    middle=full[len(head):len(full)-len(tail)]
    return len(middle.encode('utf-8'))==int(marker.group(1))


def historical_error_evidence(run,end,exit_code,sent,transcript_path=None,completed_tool_steps=None,completed_responses=None):
    if exit_code!=0 or end.get('status')!='ERROR' or end.get('denied_actions'):return None
    error=end.get('error');response=end.get('response')
    if not isinstance(error,str) or not error.strip() or not isinstance(response,str) or not response.strip():return None
    cid=end.get('conversation_id')
    if cid!=(run.get('_conversation') or run.get('thread_id')):return None
    try:
        if str(uuid.UUID(cid))!=cid:return None
        path=Path(transcript_path) if transcript_path else Path.home()/'.gemini'/'antigravity-cli'/'brain'/cid/'.system_generated'/'logs'/'transcript.jsonl'
        rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if not rows or any(not isinstance(r,dict) for r in rows):return None
        anchors=[]
        for i,row in enumerate(rows):
            if row.get('type')!='USER_INPUT' or row.get('source')!='USER_EXPLICIT':continue
            body=row.get('content','')
            exact=body==sent or body.startswith('<USER_REQUEST>\n'+sent+'\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n')
            if not exact and isinstance(body,str):
                boundary='\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n'
                if boundary in body:
                    wrapped='<USER_REQUEST>\n'+sent+body[body.rfind(boundary):]
                    exact=exported_content_matches(row,wrapped)
                else:exact=exported_content_matches(row,sent)
            if not exact:continue
            stamp=datetime.fromisoformat(row['created_at'].replace('Z','+00:00')).timestamp()
            if stamp<float(run['started'])-2:continue
            if run.get('finished') and stamp>float(run['finished'])+2:continue
            anchors.append(i)
        if len(anchors)!=1:return None
        start=anchors[0]
        stop=next((i for i in range(start+1,len(rows)) if rows[i].get('type')=='USER_INPUT'),len(rows))
        turn=rows[start:stop]
        handled_tools=[];finished_background=[]
        completed=set(completed_tool_steps or [])
        for row in turn:
            if row.get('type')=='ERROR_MESSAGE':return None
            if row.get('status')=='DONE':continue
            if row.get('type')=='GENERIC' and row.get('source')=='MODEL' and row.get('status')=='RUNNING' and row.get('step_index') in completed:
                finished_background.append(row['step_index']);continue
            # CLI distinguishes recoverable tool errors from system/model failures.
            body=row.get('content','')
            if row.get('type')!='GENERIC' or row.get('source')!='MODEL' or row.get('status')!='ERROR' or not isinstance(body,str):return None
            if 'Encountered error in step execution:' not in body:return None
            if error.strip() in body or 'malformed function call' in body.lower() or 'function call is empty' in body.lower():return None
            handled_tools.append(row.get('step_index'))
        last=turn[-1]
        if last.get('type')!='PLANNER_RESPONSE' or last.get('source')!='MODEL' or not isinstance(last.get('content'),str):return None
        if last['content'].strip()!=response.strip():
            if not exported_content_matches(last,response.strip()):return None
            streamed=(completed_responses or {}).get(last.get('step_index'))
            if not isinstance(streamed,str) or streamed.strip()!=response.strip():return None
        older=[r for r in rows[:start] if r.get('type')=='ERROR_MESSAGE' and r.get('source')=='SYSTEM' and isinstance(r.get('content'),str) and error.strip() in r['content']]
        if not older:return None
        return {'source':'official_exported_transcript','conversation_id':cid,'historical_error_step':older[-1].get('step_index'),'user_step':rows[start].get('step_index'),'final_step':last.get('step_index'),'exit_code':exit_code,'current_system_error':False,'handled_tool_error_steps':handled_tools,'stream_confirmed_completed_steps':finished_background}
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None
