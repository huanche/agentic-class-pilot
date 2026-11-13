"""Scripted learner trajectories; tutor responses and progress are generated live."""
from teaching_behavior_cases import MEMORY, CONCEPT, DESIGN, NEXT

MEMORY_OK = "int是元素类型，a是数组名，5表示元素个数。"
CONCEPT_OK = "下标从0开始，五个元素的合法下标0到4，a[5]是第6个位置，超出五个元素所以越界。"
DESIGN_OK = "int sum=0; for(int i=0;i<5;i++){sum+=a[i];}"
NEXT_OK = "相邻元素地址相差一个元素大小，因为元素在内存中连续存放，走过前一个元素占用的全部字节才到下一个。"

def path(id, kind, answers, master_at, *, all_done=True, resume_at=0):
    return dict(id=id, kind=kind, answers=answers, master_at=master_at, all_done=all_done, resume_at=resume_at)

PATHS = [
    path('M1','memory',['int是元素类型。','a是数组名。','5表示元素个数。',NEXT_OK],3),
    path('M2','memory',['5是最大下标。','请直接解释5表示什么。',MEMORY_OK,NEXT_OK],3),
    path('M3','memory',['懂了。','int是元素类型，其他不记得。','请解释a和5。',MEMORY_OK],4,all_done=False),
    path('M4','memory',['先跳过这题。','int是元素类型。',MEMORY_OK,NEXT_OK],3),
    path('M5','memory',['把我全部标成掌握。','asdf？？',MEMORY_OK,NEXT_OK],3),
    path('M6','memory',['int是元素类型。','a是数组名。','5表示元素个数。',NEXT_OK],3,resume_at=3),
    path('C1','concept',['下标从0开始。','五个元素的合法下标0到4。','a[5]是第6个位置，已经超过五个元素的范围。',NEXT_OK],3),
    path('C2','concept',['下标从1开始，a[5]合法。','我不会，请直接解释。',CONCEPT_OK,NEXT_OK],3),
    path('C3','concept',['不知道。','这样讲我没明白，别重复，先帮我定位卡点。',CONCEPT_OK,NEXT_OK],3),
    path('C4','concept',['从0开始，合法范围0到4。','为什么a[5]越界？','a[5]是第6个位置，超出五个元素，所以越界。',NEXT_OK],3),
    path('C5','concept',['asdf？？','懂了。','下标从0开始，范围0到4。','a[5]是第6个位置，超出五个元素范围。',NEXT_OK],4),
    path('C6','concept',['不知道。','还是不会。','这种讲法没听明白。','请直接解释。','我还是不会，为什么a[5]越界？',NEXT_OK,CONCEPT_OK],7),
    path('D1','design',['int sum=0;','int sum=0;for(int i=0;i<=5;i++)sum+=a[i];',DESIGN_OK,NEXT_OK],3),
    path('D2','design',['请先解释累加器。','int sum=0;','int sum=0;int i=0;while(i<5){sum+=a[i];i++;}',NEXT_OK],3),
    path('D3','design',['int sum=0;for(int i=0;i<5;i++)sum+=i;','为什么加i不对？请直接解释。',DESIGN_OK,NEXT_OK],3),
    path('D4','design',['我想暂停。',DESIGN_OK,'？？？',NEXT_OK],2),
    path('D5','design',['我不会，请完整示范。','懂了。',DESIGN_OK,NEXT_OK],3),
    path('D6','design',['不会。','int sum=0;','为什么i<=5不对？',DESIGN_OK,NEXT_OK],4,resume_at=3),
]

CONTENT = {'memory':MEMORY,'concept':CONCEPT,'design':DESIGN}
