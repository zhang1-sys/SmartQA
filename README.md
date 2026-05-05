# SmartQA — 企业级 AI 客服质检闭环

> 面向建材企业的 AI 客服、自动质检与知识运营系统。

## 项目定位

SmartQA 不是单纯聊天机器人，而是一个可真实联调的企业级 AI 客服运营闭环：

```text
企业微信客户咨询
→ Flask 回调网关
→ Supabase 入库
→ Dify 多 Agent Workflow
→ AI 回复与五维质检
→ 自动回复 / 转人工
→ 内部工作台复盘
→ 知识盲区补充
→ Dify Dataset 同步
→ 运行监控 / 审计 / 告警
→ 看板追踪改进效果
```

**核心能力：**

- 企业微信真实客户入口。
- Dify 多 Agent 协作：意图识别、知识检索、回复生成、质检、决策。
- Supabase Postgres + Auth + RLS，承载企业级数据与权限。
- 内部 AI 客服运营工作台：会话处理、质检复盘、知识盲区运营。
- 运行监控、审计日志、异常告警、数据治理和知识质量检查。
- 本地降级模式保留，便于企业微信或 Dify 暂不可用时验证基础链路。

## 技术架构

```
客户入口：企业微信自建应用
公网联调：Cloudflare Tunnel / ngrok
后端：Python Flask
AI 编排：Dify Workflow（本地 Docker / Dify Cloud / 云服务器自托管）
数据库：Supabase Postgres
权限：Supabase Auth + RLS
前端：现有 HTML/CSS/JS 工作台渐进升级
```

## 当前实现原则

项目后续实现以这份企业级闭环设计为准：

[SmartQA 企业级闭环版设计](docs/superpowers/specs/2026-05-04-smartqa-enterprise-loop-design.md)

配套落地文档：

- [Supabase 设置步骤](docs/SUPABASE_SETUP.md)
- [企业微信真实联调步骤](docs/WECOM_SETUP.md)
- [生产化运行清单](docs/PRODUCTION_RUNBOOK.md)
- [关电脑也能用的云部署方案](docs/CLOUD_DEPLOYMENT.md)
- [Dify Workflow 最终交付规格](dify-workflow/FINAL_WORKFLOW_SPEC.md)
- [Dify Workflow 结构化契约](dify-workflow/structured-workflow-contract.md)
- [Dify Workflow 版本管理](dify-workflow/EXPORT_RUNBOOK.md)

早期试验性设计文档和旧版实施计划已清理，避免和新路线冲突。

## 项目结构

```
SmartQA/
├── docs/                    # 文档
│   └── superpowers/specs/   # 当前权威设计规格
├── frontend/                # 前端界面
│   ├── index.html
│   ├── chat.html            # 内部会话工作台
│   ├── dashboard.html       # 质检与运营看板
│   ├── knowledge.html       # 知识库与盲区运营
│   ├── monitor.html         # 运行监控与异常处理
│   ├── audit.html           # 审计日志
│   ├── wecom.html           # 企业微信联调自检
│   └── assets/
│       ├── style.css
│       └── app.js
├── backend/                 # 后端 API
│   ├── app.py               # Flask 主应用
│   ├── config.py            # 配置
│   ├── db.py                # SQLite 本地降级数据层
│   ├── dify_client.py       # Dify API 封装
│   └── requirements.txt
├── knowledge-base/          # 知识库数据
│   ├── 产品知识表.csv
│   ├── 售后政策表.csv
│   └── generate_templates.py
├── dify-workflow/           # Dify 工作流导出/配置
├── supabase/migrations/     # Supabase 数据库迁移
├── tools/                   # 健康检查、生产检查、Supabase CLI
└── README.md
```

## 快速开始

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt
python app.py
```

### 2. 打开前端

访问：

```text
http://localhost:5001
```

常用页面：

- `http://localhost:5001/index.html`：统一入口页，明确区分客户公开入口和内部人员入口
- `http://localhost:5001/chat.html`：内部客服工作台
- `http://localhost:5001/customer.html`：网页客户咨询入口
- `http://localhost:5001/dashboard.html`：质检运营看板
- `http://localhost:5001/knowledge.html`：知识库与知识盲区运营
- `http://localhost:5001/monitor.html`：运行监控、失败任务、数据治理和异常告警
- `http://localhost:5001/audit.html`：关键操作审计日志，默认返回脱敏后的元数据
- `http://localhost:5001/wecom.html`：企业微信联调自检与本地模拟

当前已接入 Supabase、Dify Workflow 和 Dify Dataset API。没有企业微信后台参数时，有两条本地联调入口：

- 在 `wecom.html` 用本地模拟消息验证企业微信 Gateway 闭环。
- 在 `customer.html` 用网页客户入口验证“客户提问 → AI 回复 → 内部工作台复盘”的闭环。

权限边界：

- 内部工作台 API 可通过 `INTERNAL_AUTH_REQUIRED=true` 开启 Supabase Auth 保护。
- 统一首页不是内部后台。客户只进入公开咨询入口；客服工作台、看板、知识库、企业微信配置都属于内部人员入口。
- 首页内部入口点击时会先检查登录状态，未登录会跳转 `login.html?next=...`。
- 客户公开入口仅放行 `customer/register`、`customer/history` 和 `channel=web_customer` 的客户消息。
- 内部人员从工作台发送的 `/api/chat` 在认证开启后仍需要登录。

### 3. 本地自检

```bash
npm test
npm run smoke:auth
npm run smoke:loop
npm run check:production
```

自检覆盖：

- 常规咨询进入 Dify 并自动回复。
- 网页客户注册、发消息、历史记录和内部队列展示。
- 投诉、退款、破损等高风险消息转人工。
- 未覆盖的政策问题生成知识盲区。
- 知识盲区一键沉淀为 Supabase 知识条目并同步到 Dify Dataset。
- 企业微信明文回调、重复消息幂等、本地模拟消息闭环。
- 内部登录边界、客户访问 token、运行监控、审计、数据治理和生产配置检查。

`npm run check:production` 会检查生产必备环境项。当前本地联调允许 `APP_ENV=local` 警告；真正上线时应切换稳定域名、HTTPS、进程守护和日志保留策略。

### 4. 云端运行

本地电脑关闭后，本机 Flask、Dify Docker 和临时公网隧道都会停止。要做到关电脑也能用，请按：

[SmartQA 云部署方案](docs/CLOUD_DEPLOYMENT.md)

当前仓库已包含 Render 部署所需的 `render.yaml`、`backend/wsgi.py` 和 Gunicorn 依赖。

## 生产化能力

- **真实客户入口**：微信客服 / 企业微信回调入库，支持即时确认、正式回复、失败转人工和非文本消息兜底。
- **多 Agent 协同**：Dify Workflow 承担意图识别、知识检索、回复生成、五维质检、决策和知识盲区发现，后端只依赖结构化 JSON 契约。
- **内部运营闭环**：工作台查看客户队列、AI 运行证据、五维质检、转人工原因、客户画像和会话摘要。
- **知识运营闭环**：产品知识和盲区条目以 Supabase 为准，发布后同步 Dify Dataset；失败任务可在知识库/监控页重试。
- **可观测性**：`monitor.html` 查看 AI 失败、投递失败、同步失败、待人工积压和高优先级盲区，并可发送企业微信内部告警。
- **治理与审计**：审计元数据脱敏返回，数据治理策略记录客户敏感信息、会话、审计和知识同步任务的保留要求。
- **版本管理**：Dify Workflow 修改前后按 `dify-workflow/EXPORT_RUNBOOK.md` 记录版本、契约、测试和回滚方式。

## 核心指标

| 指标 | 说明 |
|------|------|
| 整体质检均分 | 五维评分加权平均 |
| 自动回复率 | AI 通过质检并自动回复的比例 |
| 转人工率 | 高风险或质检不通过会话占比 |
| 知识盲区数 | 系统发现的未覆盖问题数量 |
| 知识盲区处理率 | 已补充或已处理盲区占比 |

## License

MIT
