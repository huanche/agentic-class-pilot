import time
import uuid
from client import *

def command(client, view, kind, text=None, label=None):
    sid=view['sessionId']
    body={'commandId':uuid.uuid4().hex,'type':kind,'payload':{'text':text} if text is not None else {},
          'expectedStateVersion':view['stateVersion'],'contentGeneration':view['contentGeneration']}
    started=time.monotonic()
    response=client.post(f'/api/session/{sid}/commands',json=body)
    data=response.json()
    trace={'body':body,'initialStatus':response.status_code,'responses':[data]}
    for _ in range(50):
        if data.get('status') not in ['pending','processing']:break
        time.sleep(2)
        data=call(client,'POST',f"/api/session/{sid}/commands/{body['commandId']}/status",json={})
        trace['responses'].append(data)
    trace['elapsedSeconds']=round(time.monotonic()-started,2)
    save(label or f'command-{kind}-{body["commandId"]}',trace)
    print(kind,'HTTP',response.status_code,'command',data.get('status'),'seconds',trace['elapsedSeconds'],flush=True)
    if data.get('status')!='completed':raise RuntimeError(str(data.get('failure') or data)[:800])
    return data['sessionView'],body

def snapshot(sid, label):
    import psycopg
    with psycopg.connect(CONFIG['STUDENT_DATABASE_URL']) as db:
        row=db.execute('SELECT snapshot FROM student.student_sessions WHERE session_key=%s',(sid,)).fetchone()
    assert row
    # Retain the actual learning state, not credentials or unrelated identity.
    data={k:row[0].get(k) for k in ['dialogue','lessonId','videoRevision','phase','contentRef','flowVersion','feedback','stateVersion']}
    save(label,data)
    return data
