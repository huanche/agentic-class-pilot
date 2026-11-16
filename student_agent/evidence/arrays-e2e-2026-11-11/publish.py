from client import *
c=login();m=load('manifest');course=m['courseId']
data=call(c,'GET',f'/api/course-space/{course}');save('generated-course',data)
job=next(j for j in data['jobs'] if j['id']==m['jobId'])
assert job['status'] in ['review','approved'], 'Only publish a completed job'
artifact=next(a for a in data['artifacts'] if a['jobId']==m['jobId'])
classroom=call(c,'GET',f"/api/classroom?id={m['classroomId']}");save('classroom',classroom)
print('Classroom scenes:',[(s['order'],s['title']) for s in classroom['classroom']['scenes']],flush=True)
if artifact['status']!='published':
    approved=call(c,'PATCH',f"/api/course-space/{course}/artifacts/{artifact['id']}",json={'action':'approve'});save('approval',approved)
    published=call(c,'POST',f'/api/course-space/{course}/publications',json={'kind':'artifact','id':artifact['id'],
       'placement':{'newLessonTitle':'一维数组：下标、初始化与循环赋值','week':1,'lessonNumber':1,'teachingHours':0.1,'resourceType':'courseware'}})
    save('publication',published)
    artifact=published['resource']
m.update(artifactId=artifact['id'],lessonId=artifact['publicationPlacement']['lessonId']);save('manifest',m)
published_content=call(c,'GET',f'/api/v1/courses/{course}/published-content');save('published-content',published_content)
print('Published lesson',m['lessonId'],flush=True)
