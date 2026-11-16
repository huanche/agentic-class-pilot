import time
from client import *
c=login();m=load('manifest');last=None
for _ in range(120):
 response=c.get(f"/api/course-space/{m['courseId']}");response.raise_for_status();data=response.json()
 job=next(j for j in data['jobs'] if j['id']==m['jobId']);save('generation-status',data)
 progress=(job['status'],job.get('message'))
 if progress!=last:print(*progress,flush=True);last=progress
 if job['status'] in ['review','approved','failed','cancelled']:
  print('generation terminal',job['status'],job.get('error',''),flush=True)
  break
 time.sleep(5)
else:raise SystemExit('Generation did not finish in ten minutes')
if job['status'] not in ['review','approved']:raise SystemExit(1)
