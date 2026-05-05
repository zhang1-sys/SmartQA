# Dify Workflow 版本管理

## 当前版本

- 当前生产契约：`FINAL_WORKFLOW_SPEC.md`
- 历史结构化契约：`structured-workflow-contract.md`
- 当前版本登记：`workflow-version.json`
- 当前状态：active

## 每次修改 Dify 节点前

1. 记录修改目的：例如降低误转人工、补充价格边界、优化质检标准。
2. 确认后端输出契约没有变化：
   - `intent`
   - `knowledge`
   - `answer`
   - `qa`
   - `decision`
   - `knowledge_gap`
3. 在 Dify 页面复制/导出当前 Workflow DSL 或截图，保存到 `dify-workflow/backups/`。
4. 更新 `workflow-version.json`，追加版本号、日期、变更摘要和回滚说明。

## 每次修改 Dify 节点后

1. 用 Dify 控制台测试常规产品咨询。
2. 测试价格/库存/售后政策等高风险问题。
3. 测试知识库未命中问题。
4. 测试门店地址、销售电话、售后投诉三类真实企业知识。
5. 运行：

```powershell
npm test
```

6. 打开内部工作台确认：
   - AI Run 有 Dify ID
   - 五维质检有分数和原因
   - decision 合理
   - 知识盲区能进入知识库运营队列

## 回滚原则

- 后端不依赖 Dify 节点名称，只依赖最终 JSON 契约。
- 如果 Dify 返回非 JSON 或字段缺失，后端会记录失败并转人工。
- 回滚时优先恢复上一版 Dify Workflow，再运行 `npm test` 和真实微信客服文字联调。
