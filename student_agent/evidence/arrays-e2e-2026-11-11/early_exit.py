import secrets
import time
from student_tools import *

accounts=json.loads((PRIVATE/'accounts.json').read_text(encoding='utf-8'))
if 'student2' not in accounts:
 admin=login('admin');account={'email':f'arrays-exit-{secrets.token_hex(4)}@example.com','password':secrets.token_urlsafe(24)}
 user=call(admin,'POST','/api/v1/users/',json={**account,'role':'student','full_name':'数组提前退出测试学生'})
 account['id']=user['id'];accounts['student2']=account
 (PRIVATE/'accounts.json').write_text(json.dumps(accounts,ensure_ascii=False),encoding='utf-8')
m=load('manifest');teacher=login();course=call(teacher,'GET',f"/api/v1/courses/{m['courseId']}")
c=login('student2');r=c.post('/api/v1/enrollments/join',json={'code':course['enroll_code']});assert r.status_code in [200,409]
if 'earlySessionId' not in m:
 v=call(c,'POST','/api/session/start',json={'course_id':m['courseId']})
 v=call(c,'POST',f"/api/session/{v['sessionId']}/begin/{m['lessonId']}",json={})
 m['earlySessionId']=v['sessionId'];save('manifest',m)
else:v=call(c,'GET',f"/api/session/{m['earlySessionId']}")
for _ in range(30):
 if v['preparation']=='ready':break
 time.sleep(2);v=call(c,'GET',f"/api/session/{v['sessionId']}")
v,_=command(c,v,'start_discussion',label='early-open');save('early-opening',v)
original_question=v['currentTaskPublic']['question']
v,_=command(c,v,'submit_answer','int a[5]有5个int元素，a是数组名，5是元素个数，其他我还没说清。',label='early-partial')
snapshot(v['sessionId'],'early-before-exit')
v,_=command(c,v,'finish',label='early-finish');save('early-feedback',v['feedback'])
print('early counts',v['feedback']['counts'],flush=True)
c=login('student2');v=call(c,'POST','/api/session/resume',json={'course_id':m['courseId'],'lesson_id':m['lessonId']})
save('early-resume',v)
v,_=command(c,v,'continue_after_class',label='early-continue');save('early-continued',v)
save('early-task-check',{'sameOriginalQuestion':v['currentTaskPublic']['question']==original_question,'postclassStage':v['postclassStage']})
print('continued',v['postclassStage'],v['messages'][-1]['text'],flush=True)
v,_=command(c,v,'postclass_answer','存储类型 数据类型 数组名[整型常量表达式]; 是完整格式。存储类型说明存储特性，数据类型决定元素类型，数组名是合法标识符，方括号的整型常量表达式给出元素个数。int a[5]; 表示数组a有5个int元素。',label='early-postclass-complete-memory')
print('postclass reply',v['messages'][-1]['text'],flush=True)
v,_=command(c,v,'finish',label='early-postclass-exit');save('early-final-feedback',v['feedback']);snapshot(v['sessionId'],'early-final-snapshot')
print('after exit',v['postclassStage'],v['feedback']['counts'],flush=True)
