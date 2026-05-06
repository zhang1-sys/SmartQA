# SmartQA 人工回复闭环

## 目标

内部客服在 `chat.html` 中接管会话后，人工回复必须同时完成：

- 写入 Supabase `messages`
- 尝试外发到对应渠道
- 更新投递状态
- 写入审计日志
- 在工作台提示客服投递结果

## 支持渠道

- `wecom_kf`：调用微信客服 `kf/send_msg`
- `wecom`：调用企业微信自建应用 `message/send`
- `web_customer` / `internal`：只写入会话记录，不主动外发

## 数据记录

人工回复写入 `messages`：

- `role = human`
- `direction = outbound`
- `delivery_status = stored | sent | failed`
- `delivery_error`：外发失败原因
- `delivered_at`：外发成功时间

审计日志写入 `audit_logs`：

- `action = conversation.human_replied`
- `metadata.delivery_status`
- `metadata.delivery_error`
- `metadata.delivery_target_present`

## 排障

如果工作台提示“外发失败”：

1. 打开 `monitor.html` 查看失败投递。
2. 检查企业微信/微信客服 access token 是否可获取。
3. 检查客户会话是否仍在可回复窗口内。
4. 检查 `wecom_contacts.external_user_id` 和会话 `external_conversation_id` 是否完整。

如果提示“未找到微信客户标识”：

1. 确认该会话来自 `wecom` 或 `wecom_kf`。
2. 确认会话已关联 `customer_id`。
3. 确认 `wecom_contacts.raw_profile.open_kfid` 或会话 external id 中包含 open_kfid。
