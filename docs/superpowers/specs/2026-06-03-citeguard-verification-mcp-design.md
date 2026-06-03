# CiteGuard v1 设计:可接入 Agent 的引用核验能力

- **日期**: 2026-06-03
- **状态**: 已确认,待写实现计划
- **范围**: v1(防幻觉:存在性 + 元数据核验),交付为分层架构 + MCP server(主) + Claude Code Skill(辅)

---

## 1. 背景与重定位

CiteGuard 原定位是"科研写作中的引用证伪原型系统"(falsification-first writing agent)。代码审阅结论:

- **扎实的一半 = 验证**:`support_backends.py` 真接线了 NLI + cross-encoder reranker + 词面启发式的可标定 ensemble;有真实的多源学术适配器(OpenAlex / Crossref / arXiv / Semantic Scholar)、存在性与元数据校验、审计/provenance 输出。
- **空壳的一半 = 写作**:`outline_planner` / `claim_decomposer` / `constrained_writer` 全是模板,**链路中没有任何 LLM 在生成**;`contradiction_verifier` 是关键词启发式;benchmark 是合成玩具(`expected_action` 恒为 `cite`、无负例、无人工标注)。

**重定位决策**:不再做"又一个会写论文的 Agent",而是把强的那一半做成**可被主流 agent(Claude Code / Codex / Cursor 等)接入的"怀疑型审稿人"核验能力**。写作交给宿主 agent,CiteGuard 专职核验。此定位:

1. 只用到项目强项,绕开弱项与拥挤赛道;
2. 价值主张清晰——宿主 agent 写综述时照样编引用,这是它们"想调但调不准"的能力;
3. 分发成本低(加一个 MCP server / 装一个 skill),远易于让人接受一整套写作 Agent。

## 2. 目标与非目标

### v1 目标
- 给定一条或一批引用,判定其**是否真实存在**、**元数据是否正确**,并在可信时给出**改正建议**。
- 秒回、零配置即用(不下模型)、不冤枉人(不把"源不可达"误升级为"伪造")。
- 跨 agent 可接入(MCP),在 Claude Code 上有主动、丝滑的体验(Skill)。
- 用一个小而诚实的评测集,把"工具值得信"从口号变成数字。

### v1 非目标(明确不做 / 推迟到 v2)
- 支撑性(claim ↔ evidence 的 NLI/entailment)判定 → **v2 深度模式**。
- 矛盾性检测(现关键词启发式不可用,需重做)→ v2。
- 写作 / 章节规划 / claim 分解 / 受约束生成 → 移出关键路径(代码保留在仓库,不删,标记 v2)。
- 研究级大规模 benchmark、跨领域 ablation、人工评测 → 后续阶段。

## 3. 架构:三层

```
citeguard/            核心核验库(收拾现有 src/,纯逻辑,可独立测试,唯一真相源)
  ├─ normalize        自由文本/字段 → 归一化引用;抽取 DOI / arXiv id
  ├─ sources          OpenAlex · Crossref · arXiv · Semantic Scholar 适配器(复用现有)
  ├─ resolve          标识符优先 + 跨源检索 + 候选打分匹配
  ├─ existence        存在性判定(复用/重构现有 existence_verifier)
  ├─ metadata         逐字段比对 + 改正记录(复用/重构现有 metadata_verifier + normalizer)
  └─ cache            本地缓存(SQLite,按 DOI / 归一化标题做键)

citeguard-mcp/        MCP server(主交付物):暴露工具,调用核心库
citeguard-skill/      Claude Code Skill(薄、可选):何时调 + 结果如何呈现
```

- 核心库不耦合任何"形态";MCP / 未来 CLI / web / benchmark 复用同一条代码路径——**评测测的就是工具真跑的逻辑**。
- v1 关键路径不含 planner / writer / claim / contradiction / 支撑性 NLI。

## 4. 工具面(刻意极简:2 个工具)

### 4.1 `verify_citation` — 单条核验
- **入参**:自由文本引用字符串,和/或结构化字段(`title` / `authors` / `year` / `doi` / `arxiv_id` / `venue`)。
- **出参**:
  - `verdict`:`verified` | `metadata_mismatch` | `not_found` | `ambiguous`
  - `confidence`:0–1
  - `canonical_record`:解析到的权威记录(命中时)
  - `field_diffs`:逐字段差异(命中但元数据有错时)
  - `suggested_citation`:高置信解析出"应是哪篇"时给出的改正后规范引用
  - `explanation`:人话解释
  - `sources_checked` / `sources_reachable`:查了哪些源、哪些可达

### 4.2 `audit_citations` — 批量核验
- **入参**:一组引用,或一段含参考文献的文本(自动抽取)。
- **出参**:逐条 `verify_citation` 结果 + 汇总(`verified` / `not_found` / `metadata_mismatch` / `ambiguous` 各计数)。

> 设计取舍:不单列"只解析不判断"的工具,`resolve` 能力折叠进 `verify_citation` 的 `suggested_citation`。工具面越小,agent 越不易用错。

## 5. 核验流水线(单条)

1. **归一化**:自由文本拆字段;抽取 DOI / arXiv id。
2. **标识符优先**:有 DOI / arXiv id → 直接解析(最高置信度)。
3. **检索**:否则 title + author + year 跨源检索(OpenAlex 主、Crossref 次、arXiv 管预印本、S2 有 key 才用)。
4. **打分匹配**:标题相似度 + 作者重合 + 年份接近度,产出候选排序。
5. **判定**:
   - 强匹配 → 逐字段比对 → `verified`(全对)或 `metadata_mismatch`(给 `field_diffs` + `suggested_citation`)
   - 弱 / 无匹配 → `not_found`(高风险标记)
   - 多个都很像 → `ambiguous`(请人确认,附候选)

## 6. 防误判红线

- **源不可达 ≠ 不存在**:任一 API 故障/超时,如实降低 `confidence`,在 `explanation` 说明"在 X 源未能核实",**绝不**升级为"伪造"。输出永远带 `sources_checked` / `sources_reachable`。
- **`not_found` 的措辞**为"在 {sources} 中无法核实"(高风险标记),而非"此文系伪造"。判断分寸交还给宿主 agent / 用户。

## 7. 性能策略

- 纯 API + 字符串匹配,**不加载任何 ML 模型**,无 HuggingFace 权重下载。
- **本地缓存**(SQLite,键 = DOI / 归一化标题):批量审计与重复运行命中缓存即返回。
- **并发查源 + 单源超时**:慢源 / 挂源自动降级,不阻塞整体返回。
- **礼貌访问**:OpenAlex 带 `mailto`、Crossref 带 `User-Agent`,遵守各源速率限制。

## 8. 可信度证明(轻量,纳入 v1)

- 构造小评测集(约 50–100 条,带 ground truth),覆盖四类:
  - (a) 真实且元数据正确
  - (b) 真实但元数据被污染(错年份/错作者/拼接)
  - (c) LLM 编造的假引用
  - (d) 模糊(易混淆的近似条目)
- 指标:**伪造检出 Precision/Recall、元数据错误检出率、误伤率(真论文被误判 `not_found` 的比例)**。
- 复用现有 `benchmark/metrics.py` 与 benchmark 脚手架;评测跑的是核心库,与 MCP 工具同一代码路径。

## 9. Claude Code Skill 行为(配角)

- **触发**:用户在写 related work / 贴了参考文献 / 要求"帮我查查引用"。
- **动作**:对草稿引用调 `audit_citations`,用紧凑表格呈现(`✓` / `⚠ 元数据` / `✗ 查无此文`),改正建议就地给出。
- **底线**:**只提议,不偷偷改**;不确定就如实说"查不准"。

## 10. 语言约定

- 面向 agent / 用户的**工具描述、`verdict`、README**:英文(跨 agent、国际受众)。
- 本设计 spec 与团队内部讨论文档:中文。

## 11. 关键决策记录(本次确认)

| 决策点 | 结论 |
|---|---|
| 项目定位 | 从"写作 Agent"重定位为"可接入 agent 的引用核验能力" |
| 交付形态 | 分层:核心库 + MCP server(主) + CC Skill(辅) |
| v1 能力边界 | 仅防幻觉(存在性 + 元数据);支撑性/矛盾性推迟到 v2 |
| 发现问题后的动作 | 报警 + 建议修正(由 agent/用户决定是否采纳),不自动改 |
| 性能 | 零模型依赖、秒回、本地缓存、并发降级 |
| 可信度 | v1 即纳入小型诚实评测集与误伤率指标 |

## 12. v2 展望(非本期范围)

- 支撑性"深度模式":复用现有 NLI + reranker ensemble,设计成异步 / 可选,解决延迟与首启动。
- 重做 contradiction 检测(替换关键词启发式)。
- 扩大评测集、跨领域 slices、verifier ablation、error analysis。
