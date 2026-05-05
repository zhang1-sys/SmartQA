# 企业微信与微信客服真实联调

SmartQA 现在支持两条企业微信相关通道：

- 自建应用：内部成员给 `SmartQA AI客服` 发消息，用于内部测试、内部助手和管理侧通知。
- 微信客服：外部微信客户通过客服链接、二维码、网页入口进入咨询，这是 SmartQA 的真实客户入口。

## 1. 本地 HTTPS 隧道

没有公网服务器时，优先使用 Cloudflare Tunnel quick tunnel：

```powershell
cloudflared tunnel --url http://127.0.0.1:5001
```

拿到 `https://*.trycloudflare.com` 后写入 `.env`：

```text
WECOM_PUBLIC_BASE_URL=https://你的临时域名
```

不要带 `/wecom/callback` 或 `/wecom/kf/callback`。

## 2. 自建应用回调

自建应用用于内部成员消息联调。

```text
URL: https://你的临时域名/wecom/callback
Token: WECOM_TOKEN
EncodingAESKey: WECOM_ENCODING_AES_KEY
```

必需环境变量：

```text
WECOM_CORP_ID=
WECOM_AGENT_ID=
WECOM_SECRET=
WECOM_TOKEN=
WECOM_ENCODING_AES_KEY=
WECOM_PUBLIC_BASE_URL=
```

## 3. 微信客服回调

微信客服用于外部客户真实咨询。

企业微信后台路径通常是：

```text
客户与上下游 -> 微信客服
```

创建客服账号后记录：

```text
WECOM_KF_OPEN_KFID=
```

如果微信客服页面提供独立 Secret，写入：

```text
WECOM_KF_SECRET=
```

如果暂时没有独立 Secret，本地会退回使用 `WECOM_SECRET` 获取 access_token。正式生产建议使用微信客服对应的 Secret。

微信客服事件回调配置优先使用：

```text
URL: https://你的临时域名/wecom/kf/callback
Token: WECOM_TOKEN
EncodingAESKey: WECOM_ENCODING_AES_KEY
```

如果企业微信后台把微信客服事件统一投递到自建应用回调，也可以使用已有自建应用回调：

```text
URL: https://你的临时域名/wecom/callback
```

后端会自动识别 `kf_msg_or_event` 并分发到微信客服处理器。微信客服收到客户消息后，企业微信会推送事件；后端会调用 `kf/sync_msg` 拉取真实消息，再进入 Supabase、Dify、质检、自动回复或人工接管闭环。

## 4. 本地自检

```powershell
Invoke-RestMethod http://127.0.0.1:5001/api/wecom/status | ConvertTo-Json -Depth 6
```

自建应用模拟：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5001/api/wecom/simulate -ContentType 'application/json' -Body '{"from_user":"local-wecom","content":"100mm岩棉板多少钱？"}'
```

微信客服模拟：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5001/api/wecom-kf/simulate -ContentType 'application/json' -Body '{"external_userid":"local-kf-customer","content":"冷补料雨天能施工吗？"}'
```

模拟通过后，客服工作台会出现 `wecom_kf` 渠道会话。

## 5. 真实客户使用方式

客户不直接使用自建应用。真实入口是微信客服：

```text
微信客户 -> 微信客服链接/二维码/网页入口 -> 企业微信微信客服 -> SmartQA
```

内部人员使用：

```text
SmartQA 内部工作台 -> 查看会话、AI质检、人工回复、知识库运营
```

## 6. 当前边界

- 已支持文本消息。
- 已支持加密回调验签和解密。
- 已支持 Dify 回复、五维质检、自动发送、失败转人工。
- 已支持微信客服即时确认：客户消息入库后先发送“已收到，正在查询”，再异步等待 Dify 正式回复。
- 已支持微信客服轮询兜底：事件回调优先，`WECOM_KF_POLL_ENABLED=true` 时会定时调用 `kf/sync_msg`，避免免费隧道或后台事件不稳定导致客户消息丢失。建议本地真实联调使用 `WECOM_KF_POLL_INTERVAL_SECONDS=15` 或更高；如果企业微信返回 `45009 api freq out of limit`，后端会自动退避到 30-300 秒。
- 图片、语音、文件已支持企业级兜底：系统会入库、标记转人工，并回复客户“已收到，转人工处理”。后续可接 OCR、语音转文字或文件解析，把非文本内容也进入 AI 链路。
- Cloudflare quick tunnel URL 会变化；变化后需要同步更新 `.env` 和企业微信后台回调 URL。
