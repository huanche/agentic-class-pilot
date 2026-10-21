# Integration contracts

此目录记录当前跨服务接口。契约是调用方依赖的公开行为，不能只凭提供方的内部表结构推测。业务接口实现没有在本批修改。

| 文件 | 范围 |
| --- | --- |
| `internal-teacher-api.yaml` | 教师侧使用的 6 个平台端点，包括共享模型配置 |
| `internal-student-api.yaml` | 学生侧使用的 4 个平台端点，包括共享模型配置 |
| `learning-context.schema.json` | 已有 `schemaVersion=1` 的学习上下文，允许新增可选字段 |
| `routing.yaml` | 网关路由清单，生成三份 Caddy 路由片段 |

模型配置端点返回解密后的用户凭据，仅供可信后端调用。测试使用合成数据，禁止把真实响应、令牌、Cookie 或密钥存成 fixture 或 CI 输出。

## 本地校验

开发校验器与应用依赖隔离，不要为了运行检查修改三端的依赖文件。在仓库根目录安装到被 Git 忽略的目录：

```powershell
uv pip install --python .\platform\.venv\Scripts\python.exe --target .\.runtime\contract-tools -r contracts/requirements-dev.txt
```

安装后，在 PowerShell 中执行以下检查；退出脚本块时恢复原有 `PYTHONPATH`：

```powershell
& {
  $contractPreviousPath = $env:PYTHONPATH
  try {
    $env:PYTHONPATH = (Join-Path $PWD '.runtime\contract-tools')
    & .\platform\.venv\Scripts\python.exe scripts/check_integration_contracts.py
    if ($LASTEXITCODE -ne 0) { throw 'Integration contracts failed' }
    & .\platform\.venv\Scripts\python.exe platform/scripts/gen_routing.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Generated routing drifted' }
    & .\platform\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -p test_integration_contracts.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Contract regressions failed' }
  } finally {
    $env:PYTHONPATH = $contractPreviousPath
  }
}
```

`integration-contracts.yml` 在相关 PR 和 push 上运行同样的检查，无部署步骤、仓库写权限、数据库或应用配置。是否作为 main 的必需检查，由仓库保护规则决定，本批没有修改 GitHub 设置。

## 检查能力与限制

新入口为 `scripts/check_integration_contracts.py`。原 `platform/scripts/check_contracts.py` 保留兼容，只有路径/请求头字符串存在性检查，不作为完整契约验收依据。

新检查包括 OpenAPI 3.1 合法性、唯一操作标识、实际注册的路由及 HTTP 方法、处理函数自身声明的认证头、路径参数、请求模型字段/必填/类型/可空性及已声明长度约束、可以静态确定的成功响应键。当前 teacher_bridge、student_bridge、user_model_config 三组提供方模块的内部路由必须至少在一份契约中覆盖；新增内部接口模块时要同步扩展检查范围。类型分析遇到不支持的新写法应扩展工具，不能默默跳过。

回归测试验证两个真实学生授权分支、文本/课件两类学习上下文的真实处理函数输出，以及平台签发与学生验签的独立密钥/旧密钥回落兼容性。执行时只加载选定函数体，以测试替身代替数据库和外围依赖，不导入应用、不读取 `.env`、不启动 lifespan、不调用模型或网络。

静态声明一致不等于认证实际执行正确，也不证明所有数据库字段、响应值及故障行为。调用代码仍为原实现；生成客户端、实际接口切换和真实业务联调仍是后续工作。

## 兼容规则

- 学习上下文版本仍为 1；已知旧格式缺少 `lessons`，必须继续兼容。
- `lessons` 缺失与 `lessons: []` 含义不同。明确为空的发布目录不能回退到课程级的旧课堂。
- 保留现有字段和语义；新增可选字段应被旧消费者忽略。
- 删除字段、改类型、改变空目录/下架语义等是破坏性变更，不能只修改文档或版本字符串后直接切换。
- 未来发布事件尚未定稿，本批不创建一个没有提供方、幂等和下架规则支撑的正式事件契约。
