# SmartQA Dify Workflow 最终交付规格

## 目标

本规格用于固化 SmartQA 当前可落地版本的 Dify 多 Agent 工作流。后端只依赖最终 JSON 契约，不依赖 Dify 节点名称；Dify 负责意图识别、知识检索、回复生成、质检和决策。

强事实例外：门店地址、销售电话、联系人、营业时间、导航/自提位置这类企业固定事实由后端 `BusinessFactService` 优先从 Supabase 门店/联系人知识项生成回答，不进入 Dify 生成链路。Dify 仍可检索门店/联系人知识作为一般问答补充，但真实客户外发时以后端强事实结果为准，避免模型被产品品牌产地等知识干扰。

## 生产输入

Dify Workflow 接收后端传入的 `inputs` 和 `query`：

```json
{
  "inputs": {
    "channel": "wecom_kf",
    "conversation_id": "supabase-conversation-id",
    "customer_message": "客户当前消息",
    "conversation_history": [
      {"role": "customer", "content": "上一轮客户消息"},
      {"role": "assistant", "content": "上一轮回复"}
    ],
    "customer_profile": {
      "name": "客户名称",
      "type": "微信客服客户",
      "source": "wecom_kf",
      "memory": {
        "summary": "已知客户摘要",
        "facts": []
      }
    }
  },
  "query": "客户当前消息"
}
```

## 最终输出契约

最终节点只能输出严格 JSON，不允许 Markdown、解释文字或代码块。

```json
{
  "intent": {
    "question_type": "售前咨询",
    "customer_type": "施工方",
    "urgency": "中",
    "sentiment": "中性",
    "entities": ["岩棉板", "100mm", "天津"]
  },
  "knowledge": {
    "hit": true,
    "sources": [
      {"title": "岩棉板", "content": "命中的知识片段"}
    ],
    "gap_question": null
  },
  "answer": "可直接发送给客户的中文回复",
  "qa": {
    "accuracy": 4,
    "completeness": 4,
    "professionalism": 5,
    "empathy": 4,
    "efficiency": 4,
    "overall_score": 4.2,
    "passed": true,
    "risk_level": "low",
    "reason": "回复基于知识库，风险低。",
    "evidence": []
  },
  "decision": {
    "action": "send",
    "reason": "质检通过，允许自动回复。",
    "needs_human": false
  },
  "knowledge_gap": null
}
```

`decision.action` 只允许：

- `send`
- `retry`
- `handoff`
- `no_answer`

## 节点编排

| 顺序 | 节点 | 职责 | 输入 | 输出 |
| --- | --- | --- | --- | --- |
| 1 | Start | 接收后端输入 | query, inputs | 原始上下文 |
| 2 | Intent Agent | 识别意图、情绪、紧急度、实体 | customer_message, history, profile | intent JSON |
| 3 | Risk Router | 判断投诉、赔付、退款、政策承诺等高风险 | intent, customer_message | risk_flags |
| 4 | Knowledge Retrieval | 检索 Dify Dataset：产品、报价、施工、售后、物流；门店/联系人仅作为非强事实补充 | query, entities | knowledge_context |
| 5 | Response Agent | 基于知识库生成客服回复 | message, intent, knowledge_context, risk_flags | answer text |
| 6 | QA Agent | 五维质检和风险判断 | message, knowledge_context, answer | qa JSON |
| 7 | Decision Agent | 决定自动发送、转人工、重试或无答案 | intent, knowledge, qa, risk_flags | decision, knowledge_gap |
| 8 | Output Formatter | 合并为严格 JSON | all previous outputs | final JSON |

## 决策规则

1. 常规产品咨询，知识命中且 `qa.passed=true`，输出 `send`。
2. 门店地址、销售电话、联系人、营业时间、导航/自提位置问题由后端强事实拦截并直接 `send`，不依赖 Dify 输出。
2. 投诉、退款、赔偿、货损、威胁投诉、强政策承诺，输出 `handoff`。
3. 任一质检维度低于 3，输出 `handoff`。
4. `qa.risk_level=high`，输出 `handoff`。
5. 涉及价格、库存、交期、运费、上楼费、对公账户、赔付金额且知识未命中，输出 `no_answer`，并生成 `knowledge_gap`。
6. Dify 内部需要重新生成但仍可自动处理时，输出 `retry`。
7. 不允许编造公司地址、电话、价格、库存、资质、质保、赔付承诺。

## 五维质检准则

| 维度 | 5分 | 3分 | 1分 |
| --- | --- | --- | --- |
| accuracy | 完全基于知识库和客户原文 | 有轻微信息缺口但无明显错误 | 编造价格、参数、电话、承诺 |
| completeness | 回答核心问题并给出下一步 | 回答部分问题 | 没有解决客户问题 |
| professionalism | 术语、单位、边界清晰 | 表达基本可读 | 表达混乱或不符合建材行业 |
| empathy | 投诉/售后先安抚再收集信息 | 语气中性 | 冷漠、推诿、激化矛盾 |
| efficiency | 简洁、可执行、可直接发送 | 略啰嗦 | 空话多、让客户反复补充无关信息 |

自动发送门槛：

- 每项 >= 3。
- `passed=true`。
- `risk_level` 不是 `high`。
- 高风险业务有明确知识依据或人工边界。

## 知识库边界

Supabase 是权威数据源，Dify Dataset 是检索执行层。前端知识库保存后必须同步 Dify。若直接在 Dify 手工改知识，需要回填 Supabase，否则下次同步会被 Supabase 覆盖。

当前 Dataset 至少包含：

- 产品知识：保温、防水、粘接、砂浆、修补、聚氨酯等。
- 门店知识：鑫源保温防水防火批发门店地址、自提、营业时间、联系人。
- 联系方式：销售咨询联系人。
- 物流规则：无电梯配送、上楼费、人工搬运人工核算边界。
- 报价规则：面积不足、规格不足时的追问和人工确认边界。
- 售后规则：破损、少货、错发、投诉退款必须转人工。

## 验收用例

| 场景 | 客户消息 | 期望 |
| --- | --- | --- |
| 产品报价 | 100mm岩棉板多少钱？ | 命中产品知识，给参考价/条件，必要时追问城市和数量，`send` |
| 门店地址 | 你们门店在哪？ | 返回天津滨海新区门店地址、导航关键词、营业时间、电话，`send` |
| 销售电话 | 找谁报价？ | 返回销售电话和服务时间，要求补充产品规格数量地址，`send` |
| 无电梯配送 | 天津武清没有电梯能送吗？ | 追问楼层、数量、进车/叉车条件，上楼费人工核算，`send` 或 `handoff` |
| 货损投诉 | 货破损了，不处理我就投诉退款 | 安抚、收集凭证、转人工，`handoff` |
| 未知价格 | 某未知材料多少钱？ | 不编造，生成知识盲区，`no_answer` 或 `handoff` |
| 乱码/非文本 | ??? 或图片语音 | 不猜测，提示重发或转人工，`handoff` |

## 后端兜底

后端会二次校验：

- Dify 超时或非 JSON：记录 `ai_runs.status=failed`，转人工。
- 输出字段缺失：使用保守默认结构，转人工。
- 投诉、退款、赔偿、破损等高风险：后端会强制转人工或生成知识盲区。
- 知识同步失败：Supabase 保留权威数据，知识页可重试 Dify 同步。

## 发布与回滚

发布前：

1. 导出 Dify Workflow DSL 或截图保存到 `dify-workflow/backups/`。
2. 更新 `workflow-version.json`。
3. 跑 `npm test` 和 `npm run check:production`。
4. 用微信客服真实发 3 条消息：产品报价、门店地址、售后投诉。

回滚：

1. 恢复上一个 Dify Workflow DSL。
2. 保持最终 JSON 契约不变。
3. 运行 `npm test`。
4. 打开 `/monitor.html`，确认 AI 失败、投递失败、同步失败、待人工异常都可观测。
