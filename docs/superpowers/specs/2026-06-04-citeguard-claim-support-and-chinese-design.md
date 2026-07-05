# CiteGuard v2 设计:claim 支撑性核验(深度模式)+ 中文学术场景支持

> **Archived historical design note:** This file records the pre-migration
> design from before the stable public `citeguard.*` package became the
> user-facing API. Mentions of `src.*` are historical compatibility context, not
> current import guidance. Use `docs/public_api_migration.md`,
> `docs/mcp_setup.md`, and `docs/cli_reference.md` for current public APIs.

- **日期**: 2026-06-04
- **状态**: 已确认,待写实现计划
- **依赖**: v1(存在性 + 元数据核验,`src/verification/`)已合并到 main
- **范围**: 新增 claim↔paper 支撑性核验工具,并让整条链路对中文学术场景可用

---

## 1. 背景与目标

v1 解决了"这篇论文存不存在、元数据对不对"。v2 解决 CiteGuard 真正的差异化问题:**"这篇论文是否真的支持你这句话"**(claim-support / 伪支撑引用),并补上中文学术场景的可用性。

**目标**

- 新增独立 MCP 工具 `check_claim_support`:输入 claim 句子 + 引用,判断支撑关系。
- 复用 `src/verifiers/` 已有的 reranker + NLI ensemble,**不重写模型层**。
- 判定**弃权优先**:摘要里没提到 ≠ 不支持,坚持"不冤枉"。
- 让中文标题/claim 能被匹配与判定(当前 `normalize_text` 会把中文删光,中文核验完全失效)。

**非目标(YAGNI,留后续)**

- 全文级支撑、多篇论文共同支撑一个 claim、主动检索反例文献。
- 知网(CNKI)/万方直连:**无开放免费 API,不爬登录/订阅内容**,本期不做(可后续做"凭证式槽位")。
- 重写 `src/verifiers/` 模型层。

---

## 2. 总体结构

```
src/verification/
  support.py        ← 新增:SupportVerdict / SupportResult / SupportDecisionPolicy + assess_support + check_claim_support
  models.py         ← v1 模型(Verdict/VerificationResult),本期不改;支撑模型独立放 support.py,不混入
  resolve.py verify.py ← 复用(支撑核验先 resolve 定位论文)
src/citation/normalizer.py   ← 改:CJK-aware normalize/tokenize(中文匹配修复)
src/verifiers/support_backends.py ← 复用;模型名改为可配置(多语模型)
src/mcp_server/server.py     ← 新增 check_claim_support_tool
src/retrieval/scholarly_clients/chinaxiv.py ← 条件性:ChinaXiv 适配器(spike 后决定)
```

实现按有序四段推进(各段独立可测):**B1 中文匹配 → support 核心 → B2 多语模型 → B3 ChinaXiv spike**。

---

## 3. A 部分:claim 支撑性核验

### 3.1 工具形状

独立工具 `check_claim_support`(不塞进 `verify_citation`)。
- **入参**:`claim`(句子,必填)+ 引用字段(`raw_text`/`title`/`authors`/`year`/`doi`/`arxiv_id`/`venue`)+ 可选 `lang` 提示。
- **流程**:先复用 v1 `resolve_citation` 定位论文 → 取其 `abstract` + `evidence_chunks` → 跑支撑性评估。
- resolve 失败(not_found/ambiguous)→ `SupportResult(verdict=insufficient_evidence)` + 说明"无法定位论文,请补 DOI/arXiv",**不**判成"不支持"。

### 3.2 判定分档(4 档,弃权优先)

`SupportVerdict`:
- `supported` — 证据 span 蕴含该 claim(NLI entailment 主导且过阈)。
- `weakly_supported` — 有相关/部分支撑信号但不够强(reranker/词面命中,或 entailment 中等)。
- `insufficient_evidence` — 摘要未涉及该 claim(NLI neutral 主导 / 无信号)。**弃权,摘要级最常见**。
- `contradicted` — 某证据 span 明确反对该 claim(NLI contradiction 主导且过阈,且该 span 与 claim 主题相关)。

**不设硬性 `unsupported`**:从摘要无法证明"不支持",只能"没提到(insufficient)"或"明确反对(contradicted)"。

### 3.3 判定映射逻辑(核心)

对候选证据 span(title、abstract 分句、`evidence_chunks`)逐条用 ensemble 评估,得到每 span 的 `entailment/contradiction/neutral`(来自 NLI backend 的 `details.probabilities`)与 reranker/heuristic 相关度;聚合:
- `best_entailment` = 各 span entailment 最大值(及其 span)。
- `best_contradiction` = 各 span 中"主题相关(reranker/词面相关度过 floor)且 contradiction 高"的最大值。
- 映射(阈值可配,放在一个 `SupportDecisionPolicy` dataclass 里,给默认值):
  - `best_entailment ≥ ENTAIL_STRONG` 且 `≥ 对应 contradiction + margin` → `supported`
  - 否则 `best_contradiction ≥ CONTRA_STRONG` → `contradicted`
  - 否则 `best_entailment ≥ ENTAIL_WEAK` 或 reranker/heuristic 相关度过弱阈 → `weakly_supported`
  - 否则 → `insufficient_evidence`
- `confidence` = 决定档位的那个分数。

### 3.4 引擎与降级(deep mode 的现实)

- 默认尝试 production ensemble(cross-encoder reranker + NLI);**首跑下载权重慢**,提供已存在的 `scripts/warmup_support_models.py` 预热。
- **模型不可用 → 自动降级 heuristic**:`SupportResult.engine` 如实标 `"heuristic"`,置信度下调,explanation 说明"未加载深度模型,结果较弱";heuristic 模式**不产出 `contradicted`**(词面判不了矛盾),只在 supported/weakly/insufficient 间取值。绝不假装是深度结果。
- `[models]` extra(torch/transformers/sentence-transformers)已在 `pyproject.toml`;文档注明体量、首跑下载、需 Python ≥3.10 环境。

### 3.5 SupportResult 模型

`SupportResult`(frozen + `to_dict()`):
`verdict`(SupportVerdict)、`confidence`、`claim`、`evidence`{`text`,`source_field`,`source_url`}、`nli_scores`{entailment,contradiction,neutral}(无 NLI 时为空/None)、`engine`("ensemble"/"heuristic")、`resolution`{verdict,canonical_record 摘要,sources_checked}、`explanation`、`lang`。

---

## 4. B 部分:中文学术场景支持

### B1 中文匹配修复(基础,必做)

改 `src/citation/normalizer.py`:
- `normalize_text`:正则保留 CJK(至少 `一-鿿`,可含扩展区/全角标点剔除),不再把中文替换成空格;英文(lower + 去标点 + 合并空白)行为不变。
- `tokenize_text`:对连续 CJK 段产出**字符二元组(bigram)**(零依赖中文 IR 常用法,单字过粗、bigram 更判别);latin 段仍按空白分词 + 去停用词。
- `sequence_similarity`(基于 `SequenceMatcher`,字符级):保留 CJK 后对中文天然可用,无需额外改。
- **回归保证**:`src/citation`、`src/retrieval`、`src/verification` 共用这些函数;现有英文测试必须零回归;新增中文用例(中文标题匹配、中文 token 重叠、中英混排)。
- **收益**:解锁对 OpenAlex/Crossref 已收录的大量中文论文的核验(最大且最可靠的中文收益,无需新源)。

### B2 多语/中文支撑模型选项

- `build_production_support_backend(...)` 已接受 `reranker_model_name`/`nli_model_name`;v2 让其**可由环境变量覆盖**:`CITEGUARD_RERANKER_MODEL`、`CITEGUARD_NLI_MODEL`(MCP server 与库入口读取)。
- 文档给出推荐多语模型名(如多语 MiniLM cross-encoder、中文/多语 NLI),由用户自选下载;**不硬编码、不默认拉取重模型**。
- `check_claim_support` 接受可选 `lang` 提示,记录在 `SupportResult.lang`(用于解释与未来按语种选模型;v2 不做自动切换,仅透传 + 文档建议)。

### B3 ChinaXiv 开放源(条件性)

- 已初步调研:ChinaXiv 是中科院正规开放预印本平台,但**未能确认可用的开放 OAI/API 端点**。
- 实现期先做**可行性 spike**(确认是否有可访问、可解析的开放端点)。
  - 确认可用 → 实现一个标准 `MetadataSource` 适配器 `ChinaxivMetadataSource`,接入 `build_live_metadata_source` 的 source 名表,带单元测试(用 Fake HTTP client,不联网)。
  - 确认不可用 → 只交付**可插拔槽位 + 文档**(说明如何在确认端点后接入),`source` 名表里不默认启用。
- **红线**:绝不爬取登录/订阅内容;只用公开、允许的元数据接口。

---

## 5. 接线:MCP / 库 / skill / 文档

- **MCP**:新增 `check_claim_support_tool(claim, raw_text/title/authors/year/doi/arxiv_id/venue, lang="")`,返回 `SupportResult.to_dict()`。模型名/源经 env 配置(§B2)。
- **库导出**:`src/verification/__init__.py` 增 `check_claim_support`、`assess_support`、`SupportResult`、`SupportVerdict`、`SupportDecisionPolicy`。
- **skill**(`skills/citeguard-verify/SKILL.md`)增条:写完"论断 + 引用"后可调 `check_claim_support`;
  - `insufficient_evidence` 必须呈现为"摘要无法确认,需看全文/人工",**不得**说成"不支持";
  - `contradicted` 高亮警示;
  - 注明深度模式需模型、首跑慢;`engine=heuristic` 时说明结论较弱。
- **README**:新增"Claim support (deep mode)"小节(英文)+ 中文说明;补"Chinese / 中文支持"说明(匹配已支持中文;推荐多语模型;知网/万方为何不直连)。

---

## 6. 可信度:测试与评测

- **单测(CI 安全、无模型、无网络)**:
  - 支撑判定映射:喂**合成的 per-span 评估**(构造带 `probabilities` 的 `SupportAssessment`),覆盖 supported/weakly/insufficient/contradicted/heuristic 降级不产出 contradicted。复用现有 `combine_support_assessments` 测试风格。
  - 中文匹配:`normalize_text`/`tokenize_text`/`sequence_similarity` 的中文与中英混排用例;`InMemoryMetadataSource` 上中文标题可被检索/匹配。
  - `check_claim_support` 端到端:用 `InMemoryMetadataSource` + 注入的合成 backend(无模型)走通 resolve→assess 全链路。
- **模型版 eval 脚本(本地跑,需 `[models]`)**:小数据集(claim, paper abstract, gold label,含中英文样例),指标:support P/R、contradiction 检出,及关键的**误判率**(把真支持判成 insufficient/contradicted 的比例)。复用 `examples/support_calibration_examples.json` 思路,产出到 `experiments/`。

---

## 7. 关键决策记录

| 决策点 | 结论 |
|---|---|
| v2 首功能 | claim 支撑性核验(深度模式) |
| 工具形状 | 独立 `check_claim_support`,内部先 resolve |
| 判定分档 | 4 档,弃权优先,不设硬性 unsupported |
| 引擎 | 复用现有 ensemble;模型不可用自动降级 heuristic 并如实标注 |
| 证据范围 | 摘要级(title+abstract+evidence_chunks);全文留后续 |
| 中文信源 | 不直连知网/万方;改为中文匹配修复 + 多语模型 + ChinaXiv 条件接入 |
| 中文匹配 | `normalizer` CJK-aware:保留 CJK + 字符 bigram 分词 |
| ChinaXiv | 先 spike;能用才接,不能用只留槽位 |

---

## 8. 实现顺序(供 writing-plans 参考)

1. **B1 中文匹配修复**(基础,先做以解锁后续中文用例,且独立可测)。
2. **support 核心**:`SupportVerdict`/`SupportResult`、`assess_support`(判定映射)、`check_claim_support`(resolve+assess)、库导出、单测(合成 backend)。
3. **B2 多语模型选项**:env 配置 + `lang` 透传 + 文档。
4. **MCP 工具 + skill + README**。
5. **B3 ChinaXiv spike**(放最后;结果决定"接入"还是"留槽位")。
6. 模型版 eval 脚本 + 小数据集。
