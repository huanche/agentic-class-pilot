import time
import secrets
from client import *

c=login();manifest=load('manifest');outline=load('outline-result');request=load('outline-request')
if 'jobId' not in manifest:
 sid='arrays_'+secrets.token_hex(7)
 body={'scope':{'type':'course'},'input':{
  'sessionId':sid,'stage':{'id':sid,'name':'一维数组：下标、初始化与循环赋值','createdAt':int(time.time()*1000),'updatedAt':int(time.time()*1000),'languageDirective':outline['languageDirective']},
  'outlines':outline['outlines'],'requirements':request['requirements'],'agents':request['agents'],
  'enableTTS':False,'enableMedia':False,'enableImageGeneration':False,'enableVideoGeneration':False}}
 save('generation-request',body)
 data=call(c,'POST',f"/api/course-space/{manifest['courseId']}/courseware-jobs",json=body)
 save('generation-accepted',data)
 manifest.update(jobId=data['job']['id'],classroomId=sid);save('manifest',manifest)
data=call(c,'GET',f"/api/course-space/{manifest['courseId']}");save('generation-status',data)
for job in data['jobs']:
 if job['id']==manifest['jobId']:print(job['status'],job.get('message'),flush=True)
