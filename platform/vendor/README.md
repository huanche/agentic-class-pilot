# 外部参考源码

## FastAPI LangGraph Agent 模板

- 上游：https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template
- 本地目录：`vendor/fastapi-langgraph-agent-production-ready-template/`
- 拉取日期：2026-09-15
- 上游分支：`master`
- 固定提交：`36c7e2b87bc2e60ee230348e857e6c9d9570a46e`
- 许可证：MIT，Copyright (c) 2025 Wassim EL BAKKOURI；复制或改编源码时保留上游版权与许可声明。

这是独立 Git 克隆，主仓库忽略该目录，Docker 构建也排除 vendor。主项目的适配代码后续写入主仓库并由 `lzm` 分支管理；参考仓库内的改动不会由 `lzm` 跟踪。

新环境从主项目根目录恢复（目标目录尚不存在时）：

```powershell
git clone https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template.git vendor/fastapi-langgraph-agent-production-ready-template
git -C vendor/fastapi-langgraph-agent-production-ready-template checkout --detach 36c7e2b87bc2e60ee230348e857e6c9d9570a46e
```

当前仅下载、检查源码，没有安装模板依赖、配置密钥、启动服务或执行迁移。适配方案见 [LangGraph 接入方案](../docs/langgraph-integration-plan.md)。
