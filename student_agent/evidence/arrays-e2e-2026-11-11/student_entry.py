import time
from client import *
teacher=login();m=load('manifest');course=m['courseId']
platform_course=call(teacher,'GET',f'/api/v1/courses/{course}')
student=login('student')
joined=student.post('/api/v1/enrollments/join',json={'code':platform_course['enroll_code']})
assert joined.status_code in [200,409], joined.text
save('student-enrollment',{'status':joined.status_code,'body':joined.json()})
workspace=call(student,'POST',f'/api/v1/courses/{course}/student-workspace',json={});save('student-workspace',workspace)
if 'studentSessionId' in m:
 view=call(student,'GET',f"/api/session/{m['studentSessionId']}")
else:
 view=call(student,'POST','/api/session/start',json={'course_id':course});save('student-catalog',view)
 view=call(student,'POST',f"/api/session/{view['sessionId']}/begin/{m['lessonId']}",json={})
 m['studentSessionId']=view['sessionId'];save('manifest',m)
save('student-begin',view)
for _ in range(50):
 print('preparation',view['preparation'],flush=True)
 if view['preparation'] in ['ready','partial','error']:break
 time.sleep(3);view=call(student,'GET',f"/api/session/{view['sessionId']}")
save('student-prepared',view)
print('public keys',list(view),flush=True)
assert view['preparation'] in ['ready','partial'],view.get('preparationError')
