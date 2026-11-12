import json
import secrets
import time
from pathlib import Path
from client import *

admin = login('admin')
account_path = PRIVATE / 'accounts.json'
if account_path.exists():
    accounts = json.loads(account_path.read_text(encoding='utf-8'))
else:
    suffix = secrets.token_hex(4)
    accounts = {}
    for role in ['teacher', 'student']:
        account = {'email': f'arrays-{role}-{suffix}@example.com', 'password': secrets.token_urlsafe(24)}
        user = call(admin, 'POST', '/api/v1/users/', json={**account,'role':role,'full_name':f'数组本地测试{role}'})
        account['id'] = user['id']; accounts[role] = account
        account_path.write_text(json.dumps(accounts, ensure_ascii=False), encoding='utf-8')
teacher = login('teacher')
if (OUT/'manifest.json').exists():
    manifest = load('manifest')
else:
    data = call(teacher, 'POST', '/api/course-space', json={'title':'数组短课｜本地完整流程测试 2026-11-11','subject':'C语言程序设计','description':'用户数组PPT的独立本地测试课，不影响已有课程。'})
    manifest = {'courseId':data['course']['id']}
    save('manifest',manifest)
course = manifest['courseId']
if 'materialId' not in manifest:
    ppt = Path('D:/wx history/xwechat_files/wxid_6fuqyikcb7ug32_1b9a/msg/file/2026-11/第07章  数组.pptx')
    with ppt.open('rb') as handle:
        data = call(teacher,'POST',f'/api/course-space/{course}/materials',files={'file':(ppt.name,handle,'application/vnd.openxmlformats-officedocument.presentationml.presentation')},data={'purpose':'course-material'})
    manifest['materialId'] = data['material']['id']; save('manifest',manifest)
material = manifest['materialId']
call(teacher,'POST',f'/api/course-space/{course}/materials/{material}/parse')
for _ in range(20):
    data = call(teacher,'GET',f'/api/course-space/{course}')
    save('course',data)
    mat = next(m for m in data['course']['materials'] if m['id']==material)
    print('material status',mat['status'],flush=True)
    if mat['status'] in ['ready','failed']: break
    time.sleep(2)
save('providers',call(teacher,'GET','/api/server-providers'))
print('course/material',course,material)
