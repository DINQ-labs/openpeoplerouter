# OpenPeopleRouter

面向 Agent 的开源找人路由：一个 MCP 入口，连接用户自己的数据供应商账号。
支持招聘、科研合作、达人合作、专家访谈、商务拓展等场景。

## 开源策略

- 用户自行申请、配置和维护供应商 API Key，直接向供应商付费。
- 保留统一能力工具、供应商路由、接口目录和 `find_tool → endpoint → call_tool`。
- 去掉 DINQ 登录、用户系统、积分钱包、加价和支付网关依赖。
- DINQ 是可选的付费供应商，用用户自己的 DINQ Key 接入；必须明确指定 `vendor="dinq"`。
- 单独仓库、独立安装和部署，不引用或修改商业版 MCP 工程。

## 开始使用

```bash
uv sync
cp .env.example .env
# 编辑 .env，只填自己需要的供应商 Key。
uv run openpeoplerouter providers
uv run openpeoplerouter check
uv run openpeoplerouter serve
```

默认通过 stdio 接入 MCP 客户端。配置示例、HTTP 和 Docker 部署见 [README](README.md)。
设置 `OPENPEOPLEROUTER_PROVIDERS` 可以限制允许调用的供应商。
服务端的 Key 不需要粘贴给 Agent；`providers` 只显示配置状态。

首版包含 8 类统一能力、29 家直接 HTTP 供应商的 1,641 个接口定义，另有可选的 DINQ 接入。
目录存在不代表你的账号已经开通，也不代表这些接口已经逐一实测。
原商业版依赖内部服务的 GitHub、Hugging Face、Firecrawl、Apify 等条目没有直接照搬；
需要通过公开供应商目录中适合的接口，或明确选择 DINQ 使用对应能力。

先用统一能力工具；只有统一能力不能满足需求时，才用 `find_tool` 找其他接口。
一次任务可能调用多个接口，实际费用按供应商账单计算。本项目没有中央积分限额。

这是单一拥有者的自托管服务，连接到同一实例的客户端共用该实例配置的供应商 Key。
需要多人账号隔离、托管服务或支付系统时，应另建服务层。

## 相关开源项目

**[OpenMailConnect](https://github.com/DINQ-labs/openmailconnect)**：独立、自托管的
Gmail / SMTP 邮件 MCP，由 DINQ Labs 维护，采用 Apache-2.0 许可证。
支持 Gmail 搜索、阅读、会话、草稿与发送，以及 SMTP 发送。
可以用 OpenPeopleRouter 找人，用 OpenMailConnect 操作自己的邮箱；两者可分别配置到同一个 MCP 客户端。

OpenMailConnect 是可选的独立项目，不随 OpenPeopleRouter 安装。
请按其[安装指南](https://github.com/DINQ-labs/openmailconnect#install)配置自己的
Gmail OAuth 应用或 SMTP 凭据，无需 DINQ 账号或 PeopleRouter 积分。发送邮件须经用户授权。

## 许可证

代码采用 Apache-2.0，保留上游目录归属说明；供应商的数据与服务条款不随代码开源。
