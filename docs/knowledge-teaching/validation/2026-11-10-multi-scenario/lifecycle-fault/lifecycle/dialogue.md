# lifecycle

lifecycle checks passed at in-memory service only; teaching false mastery remains

JSON roundtrip and service finish/start_postclass; not persistence/HTTP/browser concurrency proof

## 开场

我们先看一个具体场景：一个长度为 8 的顺序队列，front = 3、rear = 8。此时 0~2 号位置其实是空的，但 rear 已经到达数组末端。请你说说：这种情况下如果还要入队，会发生什么？为什么说这是“假”溢出？

## 输入 1：循环队列与假溢出的解决

学生：
如果还要入队，rear 已经是 8，已经到数组末端了，按我现在的理解就没法再往后放，会像是“满了”。但 0~2 号位置明明还空着，所以这不是真的没空间，只是 rear 走到头了，我觉得这就是“假”溢出的意思。

导师：
你对假溢出的解释很清楚：rear 走到数组末端并不代表真的没空间，0~2 号位置还空着，只是 rear 没法继续往后走。这一点已经掌握。

接下来看链队列。链队列用链表实现，front 指向队头，rear 指向队尾。请你想一想：入队时新结点应该接在哪个位置？为什么链队列不会出现“队满”的问题？

结果：mastered

## 输入 2：链队列的实现要点

学生：
入队应该接在队尾，也就是把新结点接到 rear 指向的结点后面，再让 rear 指向新结点。链队列不会像数组那样受固定长度限制，因为结点是动态申请出来的，只要内存还能分配就能继续接，所以我觉得不会出现数组队列那种“队满”。

导师：
你最后这段把链队列入队的两个关键点说清楚了：新结点接到 rear 所指结点之后，再让 rear 指向新结点；同时结点动态申请，所以不像数组队列那样有固定容量导致的“队满”。这两点都掌握得不错。

今天的内容到这里：循环队列部分，你已经能说明假溢出的本质是 rear 走到数组末端、前面空位没用上，而不是存储空间真的耗尽；链队列部分，入队操作和“无固定队满”的原因也讲清楚了。后续复习时，可以再把循环队列中 front、rear 的移动与判空、判满条件连起来过一遍，把这两块知识串成完整流程。

结果：mastered

## 事件

```json
[
  {
    "kind": "serialize_restore",
    "stateEqual": true
  },
  {
    "kind": "early_finish",
    "feedback": {
      "schemaVersion": 4,
      "typedTeaching": true,
      "points": [
        {
          "id": "knowledge:da03b80ddc830e5dede5",
          "title": "循环队列与假溢出的解决",
          "category": "mastered",
          "label": "已掌握",
          "status": "mastered",
          "knownParts": [
            "rear 到达数组末端后再入队会表现为溢出",
            "0~2 号空位未被使用，实际仍有空间",
            "假溢出的本质是 rear 走到头而非存储空间耗尽"
          ],
          "gaps": [],
          "evidence": "学生说明 rear=8 已到数组末端，再入队会像“满了”而报溢出，同时指出 0~2 号位置仍空着，因此不是真的没空间，只是 rear 走到头了，正确解释了假溢出的含义。",
          "suggestion": ""
        },
        {
          "id": "knowledge:43d48a066a36dd17cedb",
          "title": "链队列的实现要点",
          "category": "not_assessed",
          "label": "尚未学习／评估",
          "status": "unseen",
          "knownParts": [],
          "gaps": [],
          "evidence": "",
          "suggestion": "从这个知识点的第一问开始学习。"
        }
      ],
      "counts": {
        "mastered": 1,
        "needs_review": 0,
        "not_assessed": 1
      },
      "endedEarly": true,
      "summary": "本课 2 个知识点：1 个已掌握，0 个待巩固，1 个尚未学习／评估。"
    }
  },
  {
    "kind": "postclass_pause_resume",
    "sameTask": true,
    "sameAssessments": true
  }
]
```

完整消息、工具与State见[run.json](run.json)。
