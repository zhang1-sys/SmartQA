# SmartQA Dify 聚合知识导入记录

## 目的

Dify Cloud 免费版对知识库文档数、请求频率和索引任务有明显限制。SmartQA 的结构化知识仍以 Supabase `knowledge_items` 为权威源，Dify Dataset 只作为 Workflow 的检索执行层。

因此本目录把 Supabase 中的 130 条结构化知识聚合成 8 个高质量 Markdown 文档，再导入 Dify Cloud Dataset，供 Workflow 的 `Knowledge Retrieval` 节点检索。

## 当前文档

- `01-store-contacts.md`：门店地址与联系人
- `02-pricing-logistics-aftersales.md`：报价、物流配送与售后规则
- `03-insulation-products-part01/02/03.md`：保温材料产品知识
- `04-waterproof-products-part01/02/03.md`：防水材料产品知识
- `05-mortar-adhesive-products-part01/02.md`：砂浆与粘接材料产品知识
- `06-repair-cold-patch-products.md`：修补材料与冷补料产品知识
- `07-polyurethane-sealant-products.md`：聚氨酯、发泡和密封材料知识
- `08-accessory-products.md`：辅材及其他产品知识

## 导出与导入

生成聚合文档：

```bash
python tools/export_dify_aggregate_docs.py
```

导入或更新 Dify Cloud Dataset：

```bash
python tools/import_dify_aggregate_docs.py
```

导入报告保存在：

```text
dify-workflow/aggregate-docs/import-report.json
```

## Workflow 连接

Dify Cloud App `SmartQA 智能客服` 已发布的工作流结构：

```text
Start
-> Knowledge Retrieval
-> Triage Agent
-> Response Agent
-> Governance Agent
-> Answer
```

`Knowledge Retrieval` 绑定 Dataset：

```text
SmartQA 企业知识库
fde21b8b-1133-4f13-a34c-fd0a7e452a62
```

查询变量使用：

```text
Start.customer_message
```

后续 Agent 同时读取：

- 后端 Supabase 预检索上下文：`knowledge_context`
- Dify Knowledge Retrieval 结果：`knowledge_retrieval.result`

门店地址、电话、联系人、营业时间等强事实仍以后端 `BusinessFactService` 从 Supabase 生成的答案为准。
