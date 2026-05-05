# SmartQA Dify Workflow 结构化契约

本文件是后端对接 Dify 的唯一工作流契约。Dify 最终输出必须是 JSON，不要输出 Markdown 解释。

## Workflow 输入

后端通过 `/chat-messages` 传入：

```json
{
  "inputs": {
    "channel": "wecom",
    "conversation_id": "uuid-or-local-id",
    "customer_message": "客户当前消息",
    "conversation_history": [
      {"role": "customer", "content": "上一轮客户消息"},
      {"role": "assistant", "content": "上一轮AI回复"}
    ],
    "customer_profile": {
      "name": "客户名称",
      "type": "未知",
      "source": "wecom"
    }
  },
  "query": "客户当前消息",
  "response_mode": "blocking",
  "user": "smartqa-system"
}
```

## Workflow 输出

最终 LLM / Template 节点输出：

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
        "title": "产品知识库",
        "content": "命中的知识片段"
      }
    ],
    "gap_question": null
  },
  "answer": "给客户发送的最终回复",
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

## 多 Agent 协作定位

SmartQA 的“多 Agent”不是多个闲聊机器人，而是多个职责清晰的工作流节点协作：

- Intent Agent：识别客户意图、客户类型、紧急度、情绪和实体。
- Retrieval / Knowledge Agent：从 Dify Dataset 检索产品、价格、施工、售后政策知识。
- Response Agent：基于知识库生成可直接发送给客户的回复。
- QA Agent：按五维质量标准评估回复。
- Decision Agent / Node：决定自动发送、重试、转人工或生成知识盲区。
- Formatter：输出后端可解析的严格 JSON。

后端负责会话记忆、Supabase 落库、企业微信投递、审计和运营闭环。Dify 负责 AI 推理、RAG 和多节点编排。

## 推荐节点

1. Start
2. Intent Agent
3. Risk Router
4. Knowledge Retrieval
5. Response Agent
6. QA Agent
7. Decision Node
8. Output Formatter

## Intent Agent Prompt

```text
你是建材行业客服意图分类专家。请分析客户当前消息和历史对话，输出 JSON。

分类维度：
- question_type: 售前咨询 / 售后支持 / 技术问题 / 投诉 / 闲聊 / 未知
- customer_type: 施工方 / 经销商 / 甲方 / 散户 / 未知
- urgency: 高 / 中 / 低
- sentiment: 正面 / 中性 / 负面
- entities: 客户提到的产品、规格、城市、数量、订单线索

只输出 JSON：
{
  "question_type": "...",
  "customer_type": "...",
  "urgency": "...",
  "sentiment": "...",
  "entities": []
}
```

## Response Agent Prompt

```text
你是建材行业资深客服。请基于知识库内容回答客户问题。

要求：
1. 涉及价格、参数、售后承诺时，只能引用知识库或明确说明需要人工核算。
2. 知识库未覆盖时，不要编造。
3. 投诉或负面情绪先安抚，再收集关键信息。
4. 回复要简洁、专业、可直接发给客户。

输入：
- 客户消息：{{customer_message}}
- 意图结果：{{intent_result}}
- 知识库内容：{{knowledge_context}}
- 历史对话：{{conversation_history}}

输出纯文本回复。
```

## QA Agent Prompt

```text
你是 AI 客服质检员。请根据客户原文、知识库内容、AI 回复进行五维评分。

评分维度：
- accuracy: 准确性，是否基于事实和知识库
- completeness: 完整性，是否回答了主要问题
- professionalism: 专业度，术语和表达是否规范
- empathy: 同理心，是否照顾客户情绪
- efficiency: 效率，是否直接解决问题

每项 1-5 分。任一维度低于 3 分则 passed=false。

risk_level:
- high: 投诉、赔偿、退款、政策承诺、高风险错误
- medium: 信息不足、可能需要人工确认
- low: 常规咨询且回复可靠

只输出 JSON：
{
  "accuracy": 4,
  "completeness": 4,
  "professionalism": 5,
  "empathy": 4,
  "efficiency": 4,
  "overall_score": 4.2,
  "passed": true,
  "risk_level": "low",
  "reason": "原因",
  "evidence": []
}
```

## Output Formatter Prompt

```text
你是工作流输出格式化器。请把上游节点结果合并成严格 JSON。

决策规则：
1. 投诉 + 负面情绪，action=handoff。
2. qa.passed=false，action=handoff。
3. qa.risk_level=high，action=handoff。
4. 知识库未命中且涉及价格、承诺、政策，action=no_answer，并生成 knowledge_gap。
5. 其他质检通过场景，action=send。

最终只输出 JSON，不要 Markdown。
字段必须完全符合 SmartQA Workflow 输出契约。
```

## 五维质检标准

- accuracy 准确性：回复是否基于知识库、客户原文和事实；不得编造价格、库存、参数、售后承诺。
- completeness 完整性：是否覆盖客户核心问题，并给出下一步动作，如补充面积、城市、规格或转人工核价。
- professionalism 专业度：建材术语、单位、产品参数、施工边界和政策表达是否规范。
- empathy 同理心：遇到投诉、破损、退款、催促时是否先承接情绪，再收集关键信息。
- efficiency 效率：是否直接、清晰、可执行，避免空话和过长解释。

评分为 1-5 分：

- 5：可直接代表企业发送。
- 4：可靠，允许自动发送。
- 3：基本可用但建议关注。
- 2：有明显缺口，建议拦截或转人工。
- 1：严重风险，不允许自动发送。

自动发送建议：

- 任一维度低于 3：`passed=false`，转人工。
- `risk_level=high`：转人工。
- 涉及价格、库存、赔付、退款、特殊政策且知识库无依据：`no_answer` 或转人工。
- 常规产品咨询且质检通过：`send`。

## 失败降级

- Dify 超时或返回非 JSON：后端记录 `ai_runs.status=failed`，进入监控页。
- 回复被后端安全规则拦截：记录决策原因，必要时生成知识盲区。
- 企业微信投递失败：消息保留在 Supabase，投递状态标记为 failed，进入运行监控。
- 知识同步失败：知识仍以 Supabase 为准，Dify 同步状态为 failed，可在知识库页或监控页重试。
