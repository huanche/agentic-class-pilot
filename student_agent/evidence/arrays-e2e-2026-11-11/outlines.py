import json
from client import *

c=login();manifest=load('manifest')
extraction=load('material-extraction')['extraction']
selected=[p for p in extraction['chunks'] if 4 <= p['page'] <= 11]
text='\n\n'.join(f"第{p['page']}页\n{p['text']}" for p in selected)
requirements={'targetDurationMinutes':3,'webSearch':False,'interactiveMode':False,
 'requirement':'根据提供的第7章数组PPT第4至11页，制作一节约3分钟的中文C语言短课。最多4页且全部普通slide，不生成PBL、网页交互、测验页、图片或视频。只讲一维数组：定义与下标从0到n-1；用int a[5]={1,2}解释其余补0、越界不可访问；用for循环逐项赋值示范，再给出独立编写int a[5]生成1、3、5、7、9的具体构造任务与成功标准。不要讲二维数组、字符串、排序、memset、memcpy，不把PPT后半章当作已经讲过。每页内容简洁，总讲解约3分钟。'}
body={'requirements':requirements,'pdfText':text,'agents':[{'id':'teacher','name':'数组教师','role':'teacher','persona':'简洁清楚的C语言教师，先示范再给具体构造任务。'}]}
save('outline-request',body)
events=[]
with c.stream('POST','/api/generate/scene-outlines-stream',json=body,timeout=300) as response:
 print('outline HTTP',response.status_code,flush=True);response.raise_for_status()
 for line in response.iter_lines():
  if line.startswith('data:'):
   try:event=json.loads(line[5:].strip())
   except json.JSONDecodeError:continue
   events.append(event);save('outline-events',events)
   print('outline event',event.get('type'),event.get('index',''),flush=True)
done=next(e for e in reversed(events) if e.get('type')=='done')
save('outline-result',done)
print('outline pages',len(done['outlines']),flush=True)
