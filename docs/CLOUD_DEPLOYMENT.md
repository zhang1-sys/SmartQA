# SmartQA 云部署方案

## 结论

如果电脑关闭，本地 Flask、Dify Docker、本地前端和 ngrok/Cloudflare Quick Tunnel 都会停止。Supabase 云数据库仍然保留数据，但客户入口和内部工作台不能继续服务。

要做到关电脑也能用，需要把运行时放到云端：

```text
微信客服 / 企业微信
→ 云端 Flask + 前端静态页面
→ Supabase 云数据库
→ Dify Cloud 或云服务器自建 Dify
→ 企业微信回调 URL 使用云端 HTTPS 地址
```

## 推荐路径 A：最低成本面试版

适合当前个人免费账号和面试展示。

- Flask + 前端：Render Free Web Service。
- 数据库：继续用 Supabase。
- Dify：Dify Cloud 免费版，或继续本地 Dify 但本地关闭后 AI 会不可用。
- 企业微信回调：使用 Render 自动 HTTPS 域名。

限制：

- 免费 Web 服务可能休眠，首次访问有冷启动延迟。
- Dify Cloud 免费版有消息数、文档数、知识库存储和 API 调用限制。
- 适合真实联调和面试展示，不适合承诺生产 SLA。

## 推荐路径 B：更接近企业落地

适合后续真的给企业长期开。

- 一台轻量云服务器运行 Flask + Dify Docker。
- Supabase 继续作为云数据库。
- Cloudflare Tunnel 或 Nginx + HTTPS 域名暴露服务。
- systemd / Docker Compose 做进程守护。

优点：

- 不会因为免费平台休眠导致企业微信回调超时。
- Dify 自托管容量更可控。
- 更接近企业内部部署或私有化交付。

缺点：

- 需要服务器、域名或固定 HTTPS 入口。
- 通常不是完全免费。

## Render 部署步骤

### 1. 推送到 GitHub

Render 需要从 GitHub/GitLab/Bitbucket 仓库部署。仓库里已经包含：

- `render.yaml`
- `backend/wsgi.py`
- `backend/requirements.txt`

### 2. 创建 Web Service

在 Render 新建 Blueprint 或 Web Service：

- Build Command:

```bash
pip install -r backend/requirements.txt
```

- Start Command:

```bash
cd backend && gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

- Health Check Path:

```text
/api/system/health
```

### 3. 配置环境变量

必须配置：

```text
APP_ENV=staging
FLASK_DEBUG=false
INTERNAL_AUTH_REQUIRED=true
MOCK_AI_ENABLED=false
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
CUSTOMER_ACCESS_TOKEN_SECRET=一个新的长随机字符串
DIFY_API_URL=https://api.dify.ai/v1 或你的云端 Dify /v1 地址
DIFY_API_KEY=...
DIFY_DATASET_ID=...
DIFY_DATASET_API_KEY=...
WECOM_CORP_ID=...
WECOM_AGENT_ID=...
WECOM_SECRET=...
WECOM_KF_SECRET=...
WECOM_KF_OPEN_KFID=...
WECOM_TOKEN=...
WECOM_ENCODING_AES_KEY=...
WECOM_PUBLIC_BASE_URL=https://你的-render域名.onrender.com
WECOM_KF_POLL_ENABLED=true
WECOM_KF_POLL_INTERVAL_SECONDS=15
WECOM_KF_WELCOME_ENABLED=true
WECOM_KF_WELCOME_TEXT=您好，欢迎咨询鑫源保温防水防火批发。门店地址：天津市滨海新区厦门路环渤海建材市场L区33号，营业时间 7:30-18:30，销售电话：13512490668、13682003881。您也可以直接发送产品名称、规格、数量和项目地址，我会帮您查询产品参数、配送规则和报价前置条件；最终价格、库存和售后处理由人工同事确认。
```

不要把 `.env` 提交到 GitHub。

### 4. 修改企业微信回调

部署成功后，把企业微信后台回调地址改为：

```text
https://你的-render域名.onrender.com/wecom/callback
https://你的-render域名.onrender.com/wecom/kf/callback
```

Token 和 EncodingAESKey 必须和环境变量一致。

### 5. 验证

打开：

```text
https://你的-render域名.onrender.com/api/system/health
https://你的-render域名.onrender.com/wecom.html
https://你的-render域名.onrender.com/monitor.html
```

检查：

- `supabase.ok=true`
- `dify_enabled=true`
- `mock_ai_enabled=false`
- `wecom_enabled=true`
- `wecom_kf_enabled=true`
- 监控页无 AI 失败、投递失败、同步失败和待人工积压。

## Dify Cloud 迁移要点

1. 在 Dify Cloud 创建 Workflow 应用。
2. 按 `dify-workflow/FINAL_WORKFLOW_SPEC.md` 搭建节点和最终 JSON 输出。
3. 创建 Dataset，并导入当前知识库。
4. 将云端 Workflow API Key 和 Dataset API Key 写入部署平台环境变量。
5. 用以下用例测试：
   - `100mm岩棉板多少钱？`
   - `你们门店在哪？`
   - `找谁报价？`
   - `货破损了，不处理我就投诉退款`

## 当前项目状态

当前本地联调已经完成：

- 运行监控告警为 0。
- 知识库 129 条已同步 Dify。
- 高优先级知识盲区为 0。
- Dify 工作流最终规格已固化到 `dify-workflow/FINAL_WORKFLOW_SPEC.md`。

下一步是把仓库推到 GitHub，并在 Render/Dify Cloud/Supabase/企业微信之间完成云端环境变量和回调地址切换。
