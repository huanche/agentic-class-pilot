# fault_retry_v2

controlled retry checks passed; teaching false mastery remains

one injected timeout before transport send after real assessment; exact same input retry; caller State unchanged and one assessment committed; not real provider outage or HTTP command dedup proof

## 开场

我们先看一个具体情形：一个顺序队列的数组长度为 8，下标是 0~7。现在 front = 3、rear = 8，此时 rear 已经超出数组末端。请你说说：这种情况下队列里还有没有空位？为什么它却会报“溢出”？

## 输入 1：循环队列与假溢出的解决

学生：
队列里应该还有空位，因为数组下标只到 7，rear = 8 已经越界了，但前面 0、1、2 这些位置可能还空着。可我不太确定这里说的“溢出”是不是因为 rear 不能再往后加，而不是队列真的满了。

导师：
你前面说的方向是对的：rear=8 已经越界，而 0、1、2 这些前端位置可能还空着。把这两件事连起来看——队列并没有真正装满，只是 rear 不能再往后移动了，这种“前端有空位却报溢出”的现象就叫“假溢出”。现在请你用一句话概括：为什么 front=3、rear=8 时属于假溢出，而不是队列真的满了？

结果：partial

## 输入 2：循环队列与假溢出的解决

学生：
因为真正占用的位置只是从 front=3 到 rear 前面这一段，rear=8 只是越过了数组末端，而 0、1、2 这些位置还空着，所以不是队列真的满了，只是 rear 不能再往后走造成的假溢出。

导师：
上一问你说得很清楚：rear=8 只是越过了数组末端，0、1、2 还空着，所以是假溢出，不是真满。这一点已经掌握，我们进入新内容。

链队列用链表实现，front 指向队头结点，rear 指向队尾结点。先想一个关键问题：入队时新结点插在 rear 后面，那链队列会不会像顺序循环队列那样出现“队满”？请说说你的判断和理由。

结果：mastered

## 输入 3：链队列的实现要点

学生：
我觉得链队列不会像顺序循环队列那样出现“队满”，因为它是用链表结点连起来的，入队时只要在 rear 后面接一个新结点就行，不像数组长度固定、rear 会撞到下标末端。不过我还不太确定链队列是不是完全不用考虑满，可能还要看内存分配会不会失败。

导师：
你最后这段判断很到位：链队列的“满”不是结构上的容量上限，而是内存分配失败这种外部限制，这一点你已经说清楚了。

今天两个要点都收束了：一是顺序循环队列的假溢出——前端有空位、rear 却越界，所以要用取模把 rear 绕回数组开头；二是链队列靠结点动态连接，入队只需在 rear 后接新结点，不存在顺序队列那种队满。

课后可以再巩固一下循环队列判空、判满的条件式，以及链队列出队时队头指针的维护，这两处今天没有展开。

结果：mastered

## 事件

```json
[
  {
    "kind": "controlled_transport_timeout",
    "note": "one final generation request blocked before provider; not a naturally observed outage"
  },
  {
    "kind": "retry_same_answer",
    "failureType": "SessionError",
    "inputSessionUnchanged": true,
    "exactlyOneAssessmentAfterRetry": true
  }
]
```

完整消息、工具与State见[run.json](run.json)。
