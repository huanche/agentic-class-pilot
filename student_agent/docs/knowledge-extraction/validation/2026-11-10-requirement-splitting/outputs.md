# 修改前后提取结果

以下均为实际返回，未人工拆分或改写。病例源见test_extraction_requirements_live.py的固定材料；真实课时为原已发布课时快照，输入指纹一致。

## independent_memory

### baseline

```json
[
  {
    "title": "HTTP响应状态码200与404的含义",
    "type": "memory",
    "details": {
      "statement": "HTTP响应状态码用于表示请求的处理结果：200表示请求成功；404表示请求的资源未找到。",
      "requiredElements": [
        "200表示请求成功",
        "404表示请求的资源未找到"
      ]
    }
  }
]
```

### current

```json
[
  {
    "title": "HTTP响应状态码200与404的含义",
    "type": "memory",
    "details": {
      "statement": "HTTP响应状态码200表示请求成功；404表示请求的资源未找到。",
      "requiredElements": [
        "说明状态码200表示请求成功",
        "说明状态码404表示请求的资源未找到"
      ]
    }
  }
]
```

## preserve_cause

### baseline

```json
[
  {
    "title": "循环队列留一个空位以区分队空与队满",
    "type": "concept",
    "details": {
      "explanation": "循环队列中队空的条件是 front 等于 rear。若把所有位置都存满，rear 绕回后也会等于 front，程序就无法分清队列是空还是满。因此约定少用一个存储位置（留一个空位），使队满时 (rear+1)%MAXQSIZE 等于 front，从而与队空条件区分开。",
      "understandingPoints": [
        "队空条件：front 等于 rear。",
        "若存满所有位置，rear 绕回后同样等于 front，导致空、满状态无法区分。",
        "解决办法是约定留一个空位，即队列最多存放 MAXQSIZE-1 个元素。",
        "队满条件：(rear+1)%MAXQSIZE 等于 front。",
        "留一个空位后，队空与队满的判定条件不再相同，程序可以正确区分两种状态。"
      ]
    }
  }
]
```

### current

```json
[
  {
    "title": "循环队列留一个空位区分队空与队满",
    "type": "concept",
    "details": {
      "explanation": "循环队列中队空的条件是 front 等于 rear。若把所有位置都存满，rear 绕回后也会等于 front，程序就无法分清队空和队满。因此约定留一个空位：队满时 (rear+1)%MAXQSIZE 等于 front，与队空时 front 等于 rear 相区分。",
      "understandingPoints": [
        "说明循环队列中队空的条件是 front 等于 rear",
        "解释若把所有位置存满，rear 绕回后也等于 front，导致程序无法区分空和满",
        "说明队满时 (rear+1)%MAXQSIZE 等于 front，从而与队空条件区分开",
        "解释留一个空位为什么能区分队空与队满"
      ]
    }
  }
]
```

## independent_design

### baseline

```json
[
  {
    "title": "构造基于栈的行编辑处理方案",
    "type": "design",
    "details": {
      "capability": "能独立设计并实现一个用栈处理单行文本编辑的方案：普通字符入栈，退格撤销最近输入的一个字符，整行撤销清空当前行。",
      "constraints": [
        "只处理当前行，不涉及跨行撤销",
        "不实现重做功能",
        "退格只撤销最近输入的一个字符",
        "整行撤销需清空当前行全部内容"
      ],
      "successCriteria": [
        "普通字符输入后按顺序保留在栈中",
        "退格操作后最近输入的一个字符被移除，其余字符顺序不变",
        "整行撤销后当前行内容为空",
        "两种撤销操作分别产生正确结果"
      ]
    }
  }
]
```

### current

```json
[
  {
    "title": "构造基于栈的行编辑处理方案",
    "type": "design",
    "details": {
      "capability": "能独立设计并实现一个用栈处理单行编辑的方案：普通字符入栈，退格撤销最近输入的一个字符，整行撤销清空当前行。",
      "constraints": [
        "只处理当前行，不涉及跨行撤销",
        "不涉及重做功能"
      ],
      "successCriteria": [
        "普通字符被压入栈中，成为当前行内容的一部分",
        "退格操作撤销最近输入的一个字符，结果与预期一致",
        "整行撤销操作清空当前行",
        "两种撤销操作分别产生正确结果"
      ]
    }
  }
]
```

## real_lesson

### baseline

```json
[
  {
    "title": "栈与队列是受限的线性表",
    "type": "concept",
    "details": {
      "explanation": "线性表允许在任意位置插入和删除，取出顺序可自由决定；当插入、删除的位置受到限制后，就得到栈和队列这两种受限线性表，其数据存取顺序也随之改变。",
      "understandingPoints": [
        "线性表：可在任意位置插入/删除，顺序自由",
        "栈：只允许在 top 端操作，后进先出 LIFO",
        "队列：队尾 rear 入、队头 front 出，先进先出 FIFO",
        "限制操作位置是改变存取顺序的根本原因"
      ]
    }
  },
  {
    "title": "栈的定义与核心术语",
    "type": "memory",
    "details": {
      "statement": "栈是仅在一端进行插入和删除的线性表；允许插入和删除的一端为栈顶 Top，另一端为栈底 Bottom；Push 是在栈顶插入元素，Pop 是删除栈顶元素；栈遵循后进先出 LIFO。",
      "requiredElements": [
        "栈：仅在一端插入和删除的线性表",
        "栈顶 Top：允许插入和删除的一端",
        "栈底 Bottom：不允许操作的另一端",
        "Push（入栈）：在栈顶插入元素",
        "Pop（出栈）：删除栈顶元素",
        "后进先出 LIFO：最后入栈的元素最先出栈"
      ]
    }
  },
  {
    "title": "栈的后进先出（LIFO）特性",
    "type": "concept",
    "details": {
      "explanation": "每次 Push 都把新元素加在当前栈顶上方，越晚入栈的元素离栈顶越近，出栈时越早被取走；因此连续入栈后连续出栈，出栈顺序与入栈顺序相反。若采用交替的 Push/Pop，则输出顺序可与入栈顺序相同，这并不违反 LIFO，因为每次 Pop 都严格移除当前栈顶，只是下一个元素尚未入栈。",
      "understandingPoints": [
        "新元素压在当前栈顶上方，成为新的栈顶",
        "连续 Push A、B、C 后连续 Pop，输出为 C、B、A",
        "交替 Push A/Pop A、Push B/Pop B、Push C/Pop C，输出为 A、B、C",
        "常见错误：把队列的 FIFO 套用到栈上，误以为先入的 A 一定先出",
        "判断下一个弹出元素只需盯住当前栈顶，无需回看全部历史"
      ]
    }
  },
  {
    "title": "出栈序列的合法性辨析",
    "type": "concept",
    "details": {
      "explanation": "出栈序列由具体操作序列决定，并且必须满足 LIFO。同样输入 A、B、C，操作不同输出就不同；检验一个排列是否为合法出栈序列，要按 LIFO 逐步验证每一步。",
      "understandingPoints": [
        "Push A、Push B、Push C 后连续 Pop 三次，输出 CBA",
        "Push A、Pop、Push B、Push C、Pop、Pop，输出 ACB",
        "CAB 不可能生成：C 先出栈时 A、B 仍在栈中，栈顶到栈底为 B、A，下一步只能先弹 B 再弹 A",
        "违反后进先出顺序的排列即为不可能序列"
      ]
    }
  },
  {
    "title": "顺序栈的存储结构与空满判断",
    "type": "memory",
    "details": {
      "statement": "顺序栈用一组连续存储单元自栈底到栈顶依次存放元素；base 指向栈底，top 指向栈顶元素的下一位置（下一个可插入位置）；Push 时 top 上移，Pop 时 top 下移；top 等于 base 为空栈，top 减 base 大于等于最大容量 MAXSTACKSIZE 为栈满，再入栈发生上溢。",
      "requiredElements": [
        "连续存储单元，自栈底到栈顶依次存放",
        "base 指向栈底",
        "top 指向栈顶元素的下一位置",
        "Push 使 top 上移，Pop 使 top 下移",
        "元素个数 = top − base",
        "空栈：top == base",
        "栈满：top − base >= MAXSTACKSIZE，再入栈上溢"
      ]
    }
  },
  {
    "title": "用栈实现数制转换（八进制）",
    "type": "concept",
    "details": {
      "explanation": "数制转换基于 N = (N / d 的商) × d + (N mod d)：每轮保留的余数是低位数字，商继续参与下一轮，直到商为 0 停止。由于先得到的是低位余数，直接写出会颠倒顺序，因此用栈暂存余数，再出栈即得高位到低位的正确结果。",
      "understandingPoints": [
        "八进制转换中 d 取 8",
        "1348 转八进制：1348÷8 商 168 余 4；168÷8 商 21 余 0；21÷8 商 2 余 5；2÷8 商 0 余 2",
        "余数依次 Push 入栈为 4、0、5、2，栈顶为 2",
        "Pop 出栈依次得 2、5、0、4，连写为 2504",
        "验证：2×8³ + 5×8² + 0×8 + 4 = 1348",
        "结论：栈用于逆转输出顺序（LIFO）"
      ]
    }
  },
  {
    "title": "用栈实现行编辑的撤销功能",
    "type": "concept",
    "details": {
      "explanation": "行编辑程序中，普通字符入栈（Push），遇到 # 号则弹出前一个字符（Pop），从而即时撤销刚输入的字符；因为刚输入的字符就在栈顶，一次 Pop 即可完成局部修改。",
      "understandingPoints": [
        "规则：普通字符 Push，# 号 Pop 前一个字符",
        "示例 whli##ilr#e (s#*s) 处理后得到 while (*s)",
        "w、h、l、i 入栈后两个 # 依次弹出 i、l，回到 wh",
        "继续输入 i、l、r 后 # 弹出 r，输入 e 得 while",
        "空格、左括号、s 入栈后 # 删去 s，再入 *、s、右括号",
        "结论：栈的 LIFO 特性支持文本输入的即时撤销与编辑"
      ]
    }
  },
  {
    "title": "队列的定义与顺序存储",
    "type": "memory",
    "details": {
      "statement": "队列只允许在一端（队尾 rear）插入、在另一端（队头 front）删除，遵循先进先出 FIFO；顺序存储时 front 指向队头元素，rear 指向队尾元素的下一位置。",
      "requiredElements": [
        "只允许在队尾 rear 插入元素",
        "只允许在队头 front 删除元素",
        "先进先出 FIFO：先入队的元素先出队",
        "front 指向队头元素",
        "rear 指向队尾元素的下一位置（下一个插入位置）",
        "入队：写入 rear 所指位置后 rear 后移；出队：取出 front 所指元素后 front 后移"
      ]
    }
  },
  {
    "title": "循环队列与假溢出的解决",
    "type": "concept",
    "details": {
      "explanation": "顺序队列中 rear 到达数组末端时，即使前面仍有空位也会报溢出，称为假溢出。把存储单元首尾相连构成循环队列，入队位置用 (rear + 1) % MAXQSIZE 计算，可绕回前端空位；为区分空与满，队满时保留一个空位。",
      "understandingPoints": [
        "假溢出示例：front = 3、rear = 8，0~2 空位未用却报溢出",
        "循环队列中 rear = 7、容量 8 时，下次入队位置为 (7+1)%8 = 0",
        "队空：front == rear",
        "队满：rear 加 1 后对 MAXQSIZE 取余等于 front",
        "两个条件都不满足为一般状态：有元素但未满"
      ]
    }
  },
  {
    "title": "链队列的要点",
    "type": "concept",
    "details": {
      "explanation": "链队列用链表实现，front 指向队头、rear 指向队尾；入队只在 rear 后插入，因此不存在队满问题；出队必须先判断队空，队空条件为 front 等于 NULL。链队列本质上是链表操作的子集，只保留队头删除、队尾插入的受限操作。",
      "understandingPoints": [
        "链表实现：front 指向队头，rear 指向队尾",
        "入队：在 rear 后插入，无队满问题",
        "出队：需先判断队空，队空条件为 front == NULL",
        "与顺序循环队列对比：数组下标实现可能队满，链表指针实现不会队满",
        "链队列是链表操作的子集（受限操作）"
      ]
    }
  },
  {
    "title": "栈与队列的对比归纳",
    "type": "concept",
    "details": {
      "explanation": "从规则、插入、删除、类比四项对比栈与队列：栈在栈顶 Push 入、Pop 出，符合 LIFO，像一摞盘子；队列在队尾入队、队头出队，符合 FIFO，像排队窗口。核心结论是栈等于 LIFO，队列等于 FIFO。",
      "understandingPoints": [
        "栈：栈顶 Push 入、Pop 出，后进先出 LIFO",
        "队列：队尾入队、队头出队，先进先出 FIFO",
        "类比：栈像一摞盘子，队列像排队窗口",
        "混淆 LIFO 与 FIFO 是典型错误，需重点辨析"
      ]
    }
  },
  {
    "title": "由操作序列推演出栈序列",
    "type": "design",
    "details": {
      "capability": "能根据给定的 Push/Pop 操作序列（如用 1 表示 Push、0 表示 Pop）逐步模拟栈的变化，正确写出对应的出栈序列，并判断某个排列是否为合法出栈序列。",
      "constraints": [
        "每一步只能对当前栈顶执行 Pop",
        "入栈顺序固定，操作序列按给定顺序执行",
        "判断合法性时须逐步按 LIFO 验证"
      ],
      "successCriteria": [
        "能正确模拟每一步栈内元素与栈顶的变化",
        "给出的出栈序列与操作序列一致",
        "能指出不可能序列并说明违反 LIFO 的具体步骤"
      ]
    }
  },
  {
    "title": "设计整行撤销的栈操作方案",
    "type": "design",
    "details": {
      "capability": "能把行编辑程序中“# 撤销一个字符”的规则扩展为“@ 撤销整行”，并描述实现该功能所需的栈操作。",
      "constraints": [
        "普通字符仍入栈（Push）",
        "# 仍弹出前一个字符（Pop）",
        "@ 需清空当前行已输入的全部字符"
      ],
      "successCriteria": [
        "说明 @ 对应的栈操作（如连续 Pop 至栈空）",
        "给出处理后的正确输出结果",
        "方案与栈的 LIFO 特性一致"
      ]
    }
  }
]
```

### current

```json
[
  {
    "title": "栈与队列作为受限线性表",
    "type": "concept",
    "details": {
      "explanation": "线性表允许在任意位置插入和删除，取出顺序由使用者自由决定；当插入、删除的位置受到限制后，数据存取顺序就随之改变，由此得到栈和队列这两种受限线性表。栈只允许在 top 端操作，是后进先出 LIFO；队列从队尾入、队头出，是先进先出 FIFO。",
      "understandingPoints": [
        "说明线性表允许任意位置插入、删除，而栈和队列对插入删除位置作了限制",
        "解释插入、删除位置受限后，数据存取顺序会发生变化",
        "指出栈只在 top 端操作、队列在队尾入队头出，从而分别形成 LIFO 与 FIFO"
      ]
    }
  },
  {
    "title": "栈的定义与核心术语",
    "type": "memory",
    "details": {
      "statement": "栈是仅在一端进行插入和删除的线性表；允许插入和删除的一端称为栈顶 Top，不允许操作的另一端称为栈底 Bottom；Push（入栈）是在栈顶插入元素，Pop（出栈）是删除栈顶元素；栈的特性是后进先出 LIFO，最后入栈的元素最先出栈。",
      "requiredElements": [
        "说出栈是仅在一端进行插入和删除的线性表",
        "指出栈顶 Top 是允许插入和删除的一端，栈底 Bottom 是不允许操作的另一端",
        "说明 Push 是在栈顶插入元素、Pop 是删除栈顶元素",
        "说出栈遵循后进先出 LIFO，最后入栈的元素最先出栈"
      ]
    }
  },
  {
    "title": "栈的 Push/Pop 过程与出栈序列推演",
    "type": "concept",
    "details": {
      "explanation": "每次 Push 都把新元素加在当前栈顶上方，top 因此向上移动，越晚入栈的元素离栈顶越近，出栈时越早被取走，这是 LIFO 的空间基础。连续 Push A、B、C 后连续 Pop 三次，输出依次为 C、B、A，与入栈顺序相反。若采用交替模式 Push A、Pop A、Push B、Pop B、Push C、Pop C，输出为 A、B、C，这并不违反 LIFO，因为每次 Pop 都严格移除当前栈顶，只是下一个元素尚未入栈。把 1/0 操作序列转译为出栈序列时，1 表示 Push、0 表示 Pop，每一步只需盯住当前栈顶即可判断下一个弹出的元素。",
      "understandingPoints": [
        "说明 Push 使新元素位于原栈顶之上、top 上移，因此后入栈者离栈顶更近、更早出栈",
        "根据连续入栈再连续出栈的操作，得出出栈顺序与入栈顺序相反",
        "解释交替 Push/Pop 得到 A、B、C 并不违反 LIFO，因为每次 Pop 都移除当前栈顶",
        "把 1/0 操作序列转译为出栈序列，并逐步依据当前栈顶判断弹出元素",
        "指出把队列的 FIFO 套用到栈上、认为先入的 A 一定先出是常见错误"
      ]
    }
  },
  {
    "title": "合法出栈序列的判定",
    "type": "concept",
    "details": {
      "explanation": "同样输入 A、B、C，操作序列不同，输出就不同，因此并非所有排列都能作为出栈序列。Push A、Push B、Push C 后连续 Pop 三次得到 CBA；Push A、Pop、Push B、Push C、Pop、Pop 得到 ACB。CAB 不可能生成：要让 C 第一个出栈，A、B 必须仍压在栈中，栈顶到栈底为 B、A，按 LIFO 下一步只能先弹 B 再弹 A。所以出栈序列由具体操作序列决定，并且必须满足 LIFO，检验一个序列是否合法要按 LIFO 逐步验证。",
      "understandingPoints": [
        "说明出栈序列由具体操作序列决定，同样输入在不同操作下输出不同",
        "按操作步骤推演出 CBA 与 ACB 两个合法出栈序列",
        "解释 CAB 为什么不可能生成：C 先出栈时 A、B 仍在栈中，只能先 B 后 A",
        "说明检验出栈序列是否合法要按 LIFO 逐步验证"
      ]
    }
  },
  {
    "title": "顺序栈的存储结构与空满判断",
    "type": "concept",
    "details": {
      "explanation": "顺序栈用一组连续存储单元，自栈底到栈顶依次存放元素。base 指向栈底，top 指向栈顶元素的下一位置，即下一个可插入的位置；因此 top − base 等于当前元素个数（如 base 在下标 0、top 在下标 3 时有 3 个元素）。Push 时 top 上移，Pop 时 top 下移。栈中没有元素时 top 回落到 base，故 top 等于 base 为空栈；当 top − base 大于等于最大容量 MAXSTACKSIZE 时栈满，再入栈会发生上溢。",
      "understandingPoints": [
        "说明顺序栈用连续存储单元自栈底到栈顶依次存放元素",
        "说明 base 指向栈底、top 指向栈顶元素的下一位置",
        "用 top − base 计算当前栈中元素个数",
        "说明 Push 使 top 上移、Pop 使 top 下移",
        "用 top 等于 base 判断空栈",
        "用 top − base 大于等于最大容量判断栈满，并说明此时再入栈会上溢"
      ]
    }
  },
  {
    "title": "用栈实现数制转换（八进制）",
    "type": "concept",
    "details": {
      "explanation": "转换基于 N = (N / d 的商) × d + (N 对 d 的余数)，每轮得到的余数是低位数字，商继续参与下一轮，八进制中 d 取 8。例如 1348 转八进制：1348÷8 商 168 余 4，168÷8 商 21 余 0，21÷8 商 2 余 5，2÷8 商 0 余 2，商为 0 时停止。余数依次入栈为 4、0、5、2（栈顶为 2），出栈得到 2、5、0、4，连写即 2504。栈在这里用于逆转输出顺序，使低位余数最后输出。",
      "understandingPoints": [
        "说明按 N 除以 d 取商与余数、商继续参与下一轮、余数为低位数字的转换原理",
        "按步骤求出 1348 转八进制过程中依次产生的余数 4、0、5、2，并在商为 0 时停止",
        "说明余数依次入栈、再出栈得到 2、5、0、4 从而写出结果 2504",
        "解释栈在此处的作用是逆转输出顺序，使低位余数最后输出"
      ]
    }
  },
  {
    "title": "用栈实现行编辑的撤销",
    "type": "concept",
    "details": {
      "explanation": "行编辑程序中，普通字符入栈（Push），遇到 # 号则弹出前一个字符（Pop）。示例 whli##ilr#e (s#*s) 的处理：w、h、l、i 入栈，两个 # 依次弹出 i、l 回到 wh；再入 i、l、r 得 whilr；下一个 # 弹出 r，输入 e 得 while；空格、左括号、s 入栈后遇 # 删去 s，再入 *、s、右括号，最终得到 while (*s)。因为刚输入的字符就在栈顶，# 一次弹出即可完成局部修改，栈的 LIFO 特性支持文本输入的即时撤销。",
      "understandingPoints": [
        "说明行编辑规则：普通字符入栈，遇到 # 弹出前一个字符",
        "按步骤处理 whli##ilr#e (s#*s) 并得到 while (*s)",
        "解释栈的 LIFO 特性为什么能支持即时撤销：刚输入的字符位于栈顶"
      ]
    }
  },
  {
    "title": "队列的定义与顺序存储下的入队出队",
    "type": "memory",
    "details": {
      "statement": "队列只允许在一端（队尾 rear）插入元素、在另一端（队头 front）删除元素，遵循先进先出 FIFO。顺序存储时 front 指向队头元素，rear 指向队尾元素的下一位置；入队时先把新元素写入 rear 所指位置再让 rear 后移，出队时先取出 front 所指元素再让 front 后移。",
      "requiredElements": [
        "说出队列在队尾 rear 插入、在队头 front 删除，遵循先进先出 FIFO",
        "说明顺序存储中 front 指向队头元素、rear 指向队尾元素的下一位置",
        "说明入队是写入 rear 所指位置后 rear 后移，出队是取出 front 所指元素后 front 后移"
      ]
    }
  },
  {
    "title": "循环队列与假溢出的解决",
    "type": "concept",
    "details": {
      "explanation": "顺序队列中 front 指向 3、rear 指向 8 时，0~2 三个空位仍未使用却因 rear 超出末端而报溢出，这就是假溢出。循环队列把存储单元首尾相连：front 指向 2、rear 指向 7 时，下次入队位置用 (7+1) % 8 = 0 绕回最前面的空位。循环队列中 front 等于 rear 表示队空；队满则需留一个空位来区分空和满，判断式为 (rear + 1) % MAXQSIZE 等于 front；两个条件都不满足即为一般状态（有元素但未满）。",
      "understandingPoints": [
        "说明顺序队列中前面有空位却因 rear 超出末端而报溢出即为假溢出",
        "说明循环队列首尾相连，入队位置用 (rear + 1) % MAXQSIZE 计算从而绕回首端",
        "用 front 等于 rear 判断队空",
        "解释留一个空位以区分空和满，并用 (rear + 1) % MAXQSIZE 等于 front 判断队满",
        "说明既不队空也不队满时为一般状态"
      ]
    }
  },
  {
    "title": "链队列的要点与空判断",
    "type": "concept",
    "details": {
      "explanation": "链队列用链表实现，front 指向队头、rear 指向队尾。入队只在 rear 之后插入，因此不存在队满问题；出队必须先判断队空，队空判断由顺序循环队列的 front 等于 rear 变为 front 等于 NULL。链队列本质上是链表操作的子集，只保留队头删除、队尾插入的受限操作。",
      "understandingPoints": [
        "说明链队列用链表实现，front 指向队头、rear 指向队尾",
        "说明入队只在 rear 之后插入，因此没有队满问题",
        "说明出队需先判断队空，且队空条件为 front 等于 NULL",
        "说明链队列是链表操作的子集，只保留队头删除与队尾插入"
      ]
    }
  },
  {
    "title": "栈与队列的对比",
    "type": "concept",
    "details": {
      "explanation": "从规则、插入、删除、类比四项对比：栈在栈顶 Push 入、Pop 出，符合 LIFO，像一摞盘子；队列在队尾入队、队头出队，符合 FIFO，像排队窗口。核心结论是栈等于 LIFO、队列等于 FIFO。",
      "understandingPoints": [
        "从插入端、删除端和存取规则区分栈与队列",
        "用一摞盘子与排队窗口的类比说明 LIFO 与 FIFO",
        "指出混淆 LIFO 和 FIFO 是常见错误"
      ]
    }
  },
  {
    "title": "设计合法出栈序列并说明对应操作",
    "type": "design",
    "details": {
      "capability": "给定一组入栈元素，用 1（Push）和 0（Pop）设计操作序列，使栈产生指定的合法出栈序列，并说明每一步的栈顶情况",
      "constraints": [
        "只能使用 Push 与 Pop 两种操作，且 Pop 只能作用于当前栈顶",
        "所设计的操作序列必须满足 LIFO，不得出现不可能序列"
      ],
      "successCriteria": [
        "给出的 1/0 操作序列能逐步执行并得到目标出栈序列",
        "每一步 Pop 弹出的都是当前栈顶元素，符合 LIFO",
        "能说明该出栈序列与操作序列的对应关系，并区分二者"
      ]
    }
  },
  {
    "title": "改造行编辑规则以撤销整行",
    "type": "design",
    "details": {
      "capability": "把行编辑程序中 '#' 撤销一个字符的规则改为 '@' 撤销整行，并描述相应的栈操作",
      "constraints": [
        "普通字符仍入栈，'#' 仍弹出前一个字符",
        "'@' 需要清空当前行已输入的全部字符"
      ],
      "successCriteria": [
        "说明 '@' 对应的栈操作是连续弹出直至栈空",
        "改造后的规则能正确处理含 '#' 与 '@' 的输入并得到正确结果"
      ]
    }
  }
]
```
