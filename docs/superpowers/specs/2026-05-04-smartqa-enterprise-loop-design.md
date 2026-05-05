# SmartQA 企业级闭环版设计

## 目标

将现有 SmartQA 原型升级为可真实联调、可面试展示、接近企业级落地的 AI 客服运营系统。

第一版不推倒重做现有前后端，而是在当前 Flask + 前端页面基础上补齐完整闭环：

1. 客户通过企业微信发送咨询。
2. Flask 接收企业微信回调，完成验签、去重、会话归一和入库。
3. 后端调用 Dify Workflow，由多 Agent 完成意图识别、知识检索、回复生成、质检和决策。
4. 后端将 AI 回复、质检结果、转人工决策、知识盲区写入 Supabase。
5. 系统按决策自动回复企业微信，或在内部工作台标记为待人工处理。
6. 内部人员通过前端工作台查看会话、复盘质检、处理知识盲区。

## 产品定位

SmartQA 是面向建材企业的 AI 客服质检与知识运营平台。

它不是单纯聊天机器人，而是一个围绕客服质量的闭环系统：

```text
客户咨询
→ AI 回复
→ 自动质检
→ 风险拦截
→ 转人工或自动回复
→ 知识盲区沉淀
→ 内部运营补充
→ 看板追踪改进效果
```

面试展示重点：

- 企业微信真实客户入口。
- Dify 多 Agent 工作流。
- Supabase 企业级数据层、Auth、RLS。
- 内部 AI 客服运营工作台。
- 质检和知识运营闭环。

## 范围

### 第一版必须完成

- 企业微信自建应用回调接入，使用 Cloudflare Tunnel 或 ngrok 做公网 HTTPS 联调。
- Supabase 替代 SQLite 作为主业务数据库。
- Supabase Auth 支持一个内部管理员登录。
- Supabase RLS 启用，内部前端只能访问允许的数据。
- Flask 后端使用 Supabase service role 处理企业微信回调、Dify 调用和敏感写入。
- Dify Workflow 定义稳定输入输出契约。
- Dify Workflow 包含意图识别、知识检索、回复生成、质检、决策输出。
- 现有 `chat.html` 升级为内部会话工作台。
- 现有 `dashboard.html` 升级为质检与运营看板。
- 现有 `knowledge.html` 升级为知识库和知识盲区运营页面。
- 保留本地降级模式，方便没有企业微信或 Dify 时验证基础链路。
- 当前实现已升级为企业落地优先：生产默认使用 Supabase + Dify + 企业微信；Mock 仅作为本地降级验证能力，不作为项目目标。

### 第一版暂不做

- 多企业租户。
- 多内部角色和复杂组织权限。
- 客户图片、语音、文件识别。
- Dify Prompt 灰度发布平台。
- 完整工单系统。
- 支付、订单、ERP、CRM 对接。

这些作为后续扩展路线展示。

## 架构

```text
企业微信客户
  ↓
企业微信自建应用回调
  ↓
Flask WeCom Gateway
  - URL 验证
  - 消息验签
  - XML 解析
  - 幂等去重
  - 客户身份归一
  ↓
Supabase
  - conversations
  - messages
  - qa_results
  - knowledge_gaps
  - wecom_contacts
  - audit_logs
  ↓
Dify Workflow
  - Intent Agent
  - Knowledge Retrieval
  - Response Agent
  - QA Agent
  - Decision Node
  ↓
Flask Business Service
  - 保存 AI 结果
  - 判断自动回复或转人工
  - 写审计日志
  - 调企业微信发送消息
  ↓
内部前端工作台
```

## 现有项目改造方式

### 保留

- `frontend/chat.html` 的会话布局。
- `frontend/dashboard.html` 的指标看板布局。
- `frontend/knowledge.html` 的知识库管理布局。
- `frontend/assets/style.css` 的视觉风格。
- `backend/dify_client.py` 的 Dify 客户端思路。
- 当前 CSV 知识库样例数据。
- Mock AI 回复能力。

### 优化

- `backend/app.py` 拆成多个模块，避免所有逻辑堆在入口文件。
- SQLite 数据访问逐步替换为 Supabase。
- 前端 API 从固定 `localhost:5000` 升级为可配置。
- 对话页加入“来源渠道、质检结果、AI 决策、转人工状态、闭环动作”。
- 看板页加入“自动解决率、转人工率、低分率、知识盲区处理率”。
- 知识库页加入“从盲区转知识条目”的运营动作。

### 新增后端模块

```text
backend/
  app.py
  config.py
  supabase_client.py
  wecom_gateway.py
  wecom_crypto.py
  dify_client.py
  services/
    conversation_service.py
    ai_orchestration_service.py
    qa_service.py
    knowledge_service.py
    dashboard_service.py
```

## 数据模型

数据库设计遵循 `database-schema-design` 技能的检查清单：业务事实结构化存储，枚举状态显式约束，企业微信消息具备幂等约束，高频查询路径有索引，AI 输出和审计信息保留原始 JSON 以便复盘。

### profiles

内部用户档案，和 Supabase Auth 用户关联。

字段：

- `id uuid primary key`
- `email text`
- `display_name text`
- `role text default 'admin'`
- `created_at timestamptz`

第一版只有一个管理员，但保留 `role` 字段。

约束：

- `id` 引用 `auth.users(id)`。
- `email` 唯一。
- `role` 限制为 `admin`，后续可扩展为 `agent`、`qa_manager`、`knowledge_operator`。

### wecom_contacts

企业微信客户身份映射。

字段：

- `id uuid primary key`
- `external_user_id text`
- `wecom_user_id text`
- `display_name text`
- `channel text default 'wecom'`
- `raw_profile jsonb`
- `created_at timestamptz`
- `updated_at timestamptz`

约束：

- `external_user_id` 唯一。
- `channel` 默认为 `wecom`。

### conversations

会话。

字段：

- `id uuid primary key`
- `channel text`
- `external_conversation_id text`
- `customer_id uuid`
- `customer_name text`
- `customer_type text`
- `status text`
- `assigned_to uuid null`
- `last_message_at timestamptz`
- `created_at timestamptz`
- `updated_at timestamptz`

状态建议：

- `active`
- `ai_replied`
- `needs_human`
- `resolved`

约束：

- `customer_id` 引用 `wecom_contacts(id)`，删除客户时不级联删除会话。
- `assigned_to` 引用 `profiles(id)`，可为空。
- `status` 使用 check 约束限制为上述状态。
- `channel + external_conversation_id` 唯一，用于外部渠道会话幂等。

### messages

消息明细。

字段：

- `id uuid primary key`
- `conversation_id uuid`
- `channel text`
- `direction text`
- `role text`
- `content text`
- `raw_payload jsonb`
- `wecom_msg_id text`
- `dify_message_id text`
- `created_at timestamptz`

`direction`：

- `inbound`
- `outbound`

`role`：

- `customer`
- `assistant`
- `human`
- `system`

约束：

- `conversation_id` 引用 `conversations(id)`，删除会话时级联删除消息仅限开发环境；生产建议软删除。
- `direction` 限制为 `inbound`、`outbound`。
- `role` 限制为 `customer`、`assistant`、`human`、`system`。
- `wecom_msg_id` 唯一且可为空，用于企业微信重复推送去重。

### ai_runs

每次 AI 工作流执行记录。

字段：

- `id uuid primary key`
- `conversation_id uuid`
- `trigger_message_id uuid`
- `dify_conversation_id text`
- `dify_run_id text`
- `input jsonb`
- `output jsonb`
- `decision text`
- `status text`
- `error text`
- `latency_ms integer`
- `created_at timestamptz`

约束：

- `conversation_id` 引用 `conversations(id)`。
- `trigger_message_id` 引用 `messages(id)`。
- `status` 限制为 `pending`、`succeeded`、`failed`。
- `decision` 限制为 `send`、`retry`、`handoff`、`no_answer`。

### qa_results

AI 回复质检结果。

字段：

- `id uuid primary key`
- `message_id uuid`
- `ai_run_id uuid`
- `accuracy integer`
- `completeness integer`
- `professionalism integer`
- `empathy integer`
- `efficiency integer`
- `overall_score numeric`
- `passed boolean`
- `risk_level text`
- `reason text`
- `evidence jsonb`
- `created_at timestamptz`

约束：

- `message_id` 引用 `messages(id)` 且唯一，保证一条 AI 回复只有一份最终质检结果。
- `ai_run_id` 引用 `ai_runs(id)`。
- 五个评分字段 check 约束为 1 到 5。
- `overall_score` check 约束为 1 到 5。
- `risk_level` 限制为 `low`、`medium`、`high`。

### knowledge_gaps

知识盲区。

字段：

- `id uuid primary key`
- `conversation_id uuid`
- `message_id uuid`
- `question text`
- `category text`
- `priority text`
- `frequency integer`
- `status text`
- `suggested_answer text`
- `created_by uuid null`
- `resolved_at timestamptz null`
- `created_at timestamptz`
- `updated_at timestamptz`

状态建议：

- `open`
- `drafted`
- `added_to_kb`
- `ignored`

约束：

- `conversation_id` 引用 `conversations(id)`。
- `message_id` 引用 `messages(id)`。
- `created_by` 引用 `profiles(id)`，系统自动发现时可为空。
- `priority` 限制为 `low`、`medium`、`high`。
- `status` 限制为上述状态。
- 可用 `question_hash` 或 `lower(question)` 唯一索引降低重复盲区；第一版可先用后端归并。

### audit_logs

审计日志。

字段：

- `id uuid primary key`
- `actor_type text`
- `actor_id text`
- `action text`
- `target_type text`
- `target_id uuid`
- `metadata jsonb`
- `created_at timestamptz`

约束：

- `actor_type` 限制为 `system`、`admin`、`wecom`、`dify`。
- `target_type` 使用文本保留扩展性。

## 数据库索引计划

索引从实际读写路径出发，而不是盲目给每个字段加索引。

### 必要索引

- `profiles(email)` unique：登录用户档案查询。
- `wecom_contacts(external_user_id)` unique：企业微信客户身份归一。
- `conversations(channel, external_conversation_id)` unique：外部渠道会话幂等。
- `conversations(status, last_message_at desc)`：工作台按状态和最近消息排序。
- `conversations(customer_id, last_message_at desc)`：查客户历史会话。
- `messages(conversation_id, created_at)`：加载单个会话消息流。
- `messages(wecom_msg_id)` unique where `wecom_msg_id is not null`：企业微信消息去重。
- `ai_runs(conversation_id, created_at desc)`：查看会话 AI 运行历史。
- `qa_results(message_id)` unique：按回复查质检。
- `qa_results(created_at desc)`：看板统计。
- `qa_results(passed, created_at desc)`：低分/不通过案例列表。
- `knowledge_gaps(status, priority, updated_at desc)`：知识运营待办列表。
- `audit_logs(target_type, target_id, created_at desc)`：对象审计追踪。

### 派生数据原则

- `overall_score` 是从五维评分派生，但为了看板查询性能和复盘稳定性，落库保存。
- `dashboard` 指标通过 SQL 聚合生成，第一版不单独建缓存表。
- Dify 检索片段和模型输出保存在 `ai_runs.output`，但不作为业务状态唯一来源；业务状态必须落在结构化字段里。

## 数据迁移与回滚

### 迁移

第一版采用 Supabase SQL migration：

1. 创建枚举或 check 约束。
2. 创建主表、外键、索引。
3. 启用 RLS。
4. 创建内部管理员 profile。
5. 可选：从现有 SQLite demo 数据迁移部分会话、消息、质检结果作为演示数据。

### 回滚

- 表结构迁移在开发期可以 drop/recreate。
- 进入演示稳定期后，禁止直接 drop 业务表，改用新增 migration。
- 从 SQLite 迁移来的 demo 数据可重复生成，不作为权威数据。

### 数据保留与隐私

- 企业微信原始 payload 存在 `raw_payload`，用于调试和审计。
- 面试演示数据避免使用真实客户手机号、地址、订单号。
- 后续接真实企业客户时，需要增加脱敏策略和数据保留周期。

## Supabase 权限设计

### Auth

第一版只创建一个内部管理员账号，用于登录内部工作台。

### RLS 原则

- 所有主业务表启用 RLS。
- 内部登录用户可以读取业务数据。
- 内部登录用户可以更新允许的运营字段，例如会话状态、知识盲区状态。
- 前端不能直接插入企业微信原始消息、AI 结果、质检结果。
- 企业微信回调、Dify 结果写入、审计日志写入都通过 Flask 后端 service role 完成。

### Service Role 使用边界

Service role key 只存在后端环境变量里，不暴露给前端。

后端用 service role 处理：

- 企业微信回调入库。
- Dify 调用结果入库。
- 自动回复消息记录。
- 审计日志。
- 系统级状态变更。

## 企业微信接入

### 接入方式

使用企业微信自建应用。

由于当前没有公网服务器、域名、HTTPS，第一版使用 Cloudflare Tunnel 或 ngrok 暴露本地 Flask：

```text
企业微信回调 URL
→ https://temporary-tunnel-domain/wecom/callback
→ localhost:5000/wecom/callback
```

### 后端接口

```text
GET /wecom/callback
```

用于企业微信 URL 验证。

```text
POST /wecom/callback
```

用于接收客户消息。

### 必要配置

环境变量：

- `WECOM_CORP_ID`
- `WECOM_AGENT_ID`
- `WECOM_SECRET`
- `WECOM_TOKEN`
- `WECOM_ENCODING_AES_KEY`

### 消息处理流程

1. 校验签名。
2. 解密 XML。
3. 提取客户、消息 ID、消息内容。
4. 根据企业微信用户 ID 查找或创建 `wecom_contacts`。
5. 查找或创建 `conversations`。
6. 写入 inbound `messages`。
7. 调用 Dify Workflow。
8. 保存 `ai_runs`、outbound `messages`、`qa_results`、`knowledge_gaps`。
9. 如果决策是 `send`，调用企业微信发送 AI 回复。
10. 如果决策是 `handoff`，只在工作台标记待人工，不自动回复或发送安抚话术。

## Dify Workflow 设计

### 输入契约

后端调用 Dify 时传入：

```json
{
  "channel": "wecom",
  "conversation_id": "uuid",
  "customer_message": "客户原文",
  "conversation_history": [
    {
      "role": "customer",
      "content": "..."
    },
    {
      "role": "assistant",
      "content": "..."
    }
  ],
  "customer_profile": {
    "name": "客户名称",
    "type": "未知",
    "source": "wecom"
  }
}
```

### 输出契约

Dify 必须返回可解析 JSON：

```json
{
  "intent": {
    "question_type": "售前咨询",
    "customer_type": "施工方",
    "urgency": "中",
    "sentiment": "中性",
    "entities": ["岩棉板", "100mm"]
  },
  "knowledge": {
    "hit": true,
    "sources": [
      {
        "title": "产品知识表",
        "content": "..."
      }
    ],
    "gap_question": null
  },
  "answer": "给客户的最终回复",
  "qa": {
    "accuracy": 4,
    "completeness": 4,
    "professionalism": 5,
    "empathy": 4,
    "efficiency": 4,
    "overall_score": 4.2,
    "passed": true,
    "risk_level": "low",
    "reason": "回复引用了知识库参数，语气专业。",
    "evidence": []
  },
  "decision": {
    "action": "send",
    "reason": "质检通过，风险低。",
    "needs_human": false
  },
  "knowledge_gap": null
}
```

`decision.action` 取值：

- `send`
- `retry`
- `handoff`
- `no_answer`

### 节点设计

1. Start Node
2. Intent Agent
3. Risk Router
4. Knowledge Retrieval
5. Response Agent
6. QA Agent
7. Decision Node
8. Output Formatter

### 决策规则

- 投诉 + 负面情绪：转人工。
- 任一质检维度低于 3：重试一次。
- 重试后仍低于 3：转人工。
- 知识库未命中且问题涉及价格、承诺、政策：不编造，转人工或生成知识盲区。
- 质检通过且风险低：自动回复企业微信。

## 内部工作台

内部工作台和运营闭环合并为一个后台。

### 会话工作台

基于现有 `frontend/chat.html` 升级。

新增：

- 渠道标识：企业微信、内部测试。
- 会话状态：AI 已回复、待人工、已解决。
- AI 决策原因。
- 每条 AI 回复下展示真实质检结果。
- 操作按钮：标记已解决、转人工、加入复盘、创建知识盲区。

### 质检看板

基于现有 `frontend/dashboard.html` 升级。

新增指标：

- 总会话数。
- 自动回复数。
- 自动解决率。
- 转人工率。
- 平均质检分。
- 低分会话数。
- 知识盲区数。
- 知识盲区处理率。

### 知识运营

基于现有 `frontend/knowledge.html` 升级。

新增：

- 知识盲区列表。
- 盲区详情。
- 建议答案草稿。
- 标记已补充。
- 忽略盲区。
- 链接回原始会话。

第一版不强制自动写入 Dify 知识库；可以先在页面生成补充内容，由内部人员复制到 Dify 临时知识库。后续再接 Dify Dataset API。

## API 设计

### 内部前端 API

```text
GET /api/conversations
GET /api/conversations/:id
PATCH /api/conversations/:id/status

GET /api/dashboard

GET /api/knowledge-gaps
PATCH /api/knowledge-gaps/:id

GET /api/knowledge
POST /api/knowledge

POST /api/test-chat
```

### 企业微信 API

```text
GET /wecom/callback
POST /wecom/callback
```

### 配置 API

```text
GET /api/system/health
```

返回：

- Supabase 连接状态。
- Dify 配置状态。
- 企业微信配置状态。
- 当前是否 Mock 模式。

## 错误处理

- 企业微信重复消息：通过 `wecom_msg_id` 幂等处理。
- Dify 调用失败：记录 `ai_runs.status = failed`，工作台显示待人工。
- Supabase 写入失败：后端返回错误并写本地日志。
- 企业微信发送失败：保留 AI 输出，但标记 outbound message 为 failed。
- Dify 返回非 JSON：后端尝试提取 JSON；失败则标记工作流异常并转人工。

## 测试与演示

### 本地开发演示

- Flask 本地运行。
- 前端访问本地页面。
- Supabase 使用真实项目。
- Dify 使用本地 Docker。
- 企业微信通过隧道回调到本地。

### Mock 演示

保留 Mock 模式：

- 无 Dify Key 时返回模拟 AI 结果。
- 无企业微信回调时使用 `POST /api/test-chat` 模拟客户消息。
- Mock 数据仍写入 Supabase，保证看板闭环可展示。

### 面试演示脚本

1. 在企业微信发送“100mm 岩棉板多少钱？”
2. 工作台出现新会话。
3. AI 自动回复，质检通过。
4. 看板指标变化。
5. 再发送“上次货破损你们不管吗？”
6. 系统识别投诉，转人工。
7. 质检复盘显示风险原因。
8. 知识盲区页面展示未覆盖问题。
9. 内部人员补充知识或标记处理。

## 实施阶段

### 阶段 1：工程整理

- 保留现有 UI。
- 拆分后端模块。
- 增加配置管理和健康检查。

### 阶段 2：Supabase 接入

- 建表。
- 配置 Auth。
- 启用 RLS。
- 替换 SQLite 读写路径。

### 阶段 3：Dify 契约和 Workflow

- 定义 Workflow 输入输出。
- 搭建 Dify 节点。
- 后端解析结构化结果。
- 保留 Mock fallback。

### 阶段 4：企业微信真实联调

- 实现回调验签。
- 实现消息接收。
- 实现自动回复。
- 使用隧道完成联调。

### 阶段 5：内部工作台升级

- 会话状态和质检展示。
- 转人工和已解决操作。
- 知识盲区处理。
- 看板指标升级。

### 阶段 6：面试包装

- 写 README。
- 写架构图。
- 准备演示脚本。
- 准备 PRD 和复盘文档。

## 成功标准

第一版完成后，应满足：

- 企业微信真实消息能进入系统。
- AI 回复来自 Dify Workflow。
- 每条 AI 回复有质检结果。
- 高风险消息不会盲目自动回复。
- Supabase 中能查到完整会话、消息、AI 运行、质检和盲区数据。
- 内部前端能完成会话处理、质检复盘和知识盲区处理。
- 无企业微信或 Dify 时仍可用 Mock 模式演示闭环。
