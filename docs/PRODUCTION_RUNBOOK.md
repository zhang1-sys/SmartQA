# SmartQA 生产化运行清单

本文档用于把当前本地联调环境升级为真实企业可运行环境。当前免费隧道适合真实联调，不适合作为长期生产入口。

## 1. 推荐生产架构

```text
微信客服 / 企业微信
→ 稳定 HTTPS 域名
→ 反向代理 Nginx / Caddy
→ Flask 后端进程
→ Supabase Postgres/Auth/RLS
→ Dify Workflow + Dataset
→ 内部工作台
```

## 2. 必需条件

- 稳定公网域名和 HTTPS 证书。
- 后端进程守护：Windows 可用 NSSM/任务计划，Linux 可用 systemd。
- `.env` 只放在服务器，不提交到仓库。
- Dify API Key、Dataset Key、Supabase service role、企业微信 Secret 定期轮换。
- 企业微信后台回调 URL 使用稳定域名，不使用临时隧道。

## 3. 启动顺序

1. 启动 Supabase 或确认云端 Supabase 可访问。
2. 启动 Dify，并确认 Workflow 和 Dataset API 可用。
3. 启动 SmartQA 后端。
4. 打开 `/api/system/health` 确认 `supabase.ok=true`、`dify_enabled=true`、`mock_ai_enabled=false`。
5. 打开 `/api/wecom/status` 确认微信客服配置完整。
6. 打开 `/monitor.html` 检查 AI 失败、投递失败、同步失败和待人工积压。
7. 运行 `npm run check:production` 检查生产必备环境项。

## 4. 企业微信策略

- 生产优先使用事件回调。
- 轮询只作为兜底，避免免费隧道、后台事件延迟或回调不稳定导致漏消息。
- 如果出现 `45009 api freq out of limit`，保持后端退避机制，不要手动高频刷新。
- 客户入口使用微信客服链接/二维码；自建应用更适合内部测试和内部助手。

## 5. 日志与审计

- 业务审计进入 Supabase `audit_logs`，内部通过 `audit.html` 查看。
- 异常运营通过 `monitor.html` 查看：
  - Dify/AI 失败
  - 消息投递失败
  - 知识同步失败
  - 待人工会话
  - 高优先级知识盲区
- 可配置企业微信内部告警：
  - `OPERATIONS_ALERTS_ENABLED=true`
  - `OPERATIONS_ALERT_RECIPIENTS=成员UserID1|成员UserID2`
  - `OPERATIONS_ALERT_MIN_SEVERITY=warning`
- `monitor.html` 可手动触发“发送告警”，用于验证内部通知链路。
- 生产建议额外保留 Flask 标准输出日志，至少保留 14-30 天。

## 6. 数据治理

当前已建立 `data_governance_policies` 策略表，默认包括：

- 客户敏感信息脱敏：手机号、邮箱、地址、订单号。
- 会话数据保留：默认 365 天，删除前建议归档。
- 审计日志保留：默认 730 天，按不可篡改记录处理。
- 知识版本保留：发布版本保留，同步任务默认保留 180 天。

`audit.html` 返回内容会经过基础脱敏处理，避免审计页面直接暴露手机号、邮箱和订单号。

## 7. 上线验收

- 内部登录开启：`INTERNAL_AUTH_REQUIRED=true`。
- `npm test` 通过。
- `npm run check:production` 无 critical 失败。
- 真实微信客服发送消息后，客户能收到即时确认和正式回复。
- 客户发送图片/语音/文件时，系统能入库、转人工，并给客户明确兜底回复。
- 工作台能看到客户会话、AI 运行证据、五维质检、转人工原因。
- 知识库新增/修改后，Supabase 和 Dify 同步状态一致。
- 故意制造一次知识同步失败时，`monitor.html` 能看到异常，重试入口可用。
- 故意制造一次运行异常时，企业微信内部告警可发送给管理员。

## 8. 当前免费联调边界

ngrok Free 或 Cloudflare quick tunnel 可以完成真实联调，但 URL 可能变化，稳定性和速率不可控。它适合项目验证和面试展示，不应承诺为企业生产入口。真正落地时需要稳定域名、HTTPS、进程守护和日志保留。
