# fault_retry

harness setup mistake, excluded from production defect counts

fault was armed too early and intercepted opening; target retry after assessment not tested here; evidence preserved; corrected separate run fault_retry_v2

## 开场

未完成开场

## 事件

```json
[
  {
    "kind": "controlled_transport_timeout",
    "note": "one final generation request blocked before provider; not a naturally observed outage"
  }
]
```

完整消息、工具与State见[run.json](run.json)。
