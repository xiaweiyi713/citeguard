# CiteGuard 系统架构

## 总体分层

当前原型按五层组织：

1. `Planner`
   - `OutlinePlanner`
   - `ClaimDecomposer`

2. `Retriever`
   - `BM25LikeRetriever`
   - `DenseLikeRetriever`
   - `HybridRetriever`
   - `MetadataSourceRetriever`
   - `InMemoryMetadataSource`
   - `OpenAlexMetadataSource`
   - `CrossrefMetadataSource`
   - `ArxivMetadataSource`
   - `SemanticScholarMetadataSource`
   - `MultiSourceMetadataSource`

3. `Verifier`
   - `ExistenceVerifier`
   - `MetadataVerifier`
   - `SupportVerifier`
   - `HeuristicSupportBackend`
   - `SentenceTransformerRerankerBackend`
   - `TransformersNLIBackend`
   - `EnsembleSupportBackend`
   - `ContradictionVerifier`
   - `RiskFusion`
   - `UncertaintyGate`

4. `Writer`
   - `ConstrainedWriter`
   - `ConservativeReviser`
   - `AbstentionController`

5. `Audit`
   - `ProvenanceBuilder`
   - `AuditReportBuilder`
   - `GraphVisualizer`

## 端到端流程

```text
topic
  -> outline planning
  -> claim decomposition
  -> retrieval
  -> citation proposal
  -> existence / metadata / support / contradiction verification
  -> risk fusion
  -> uncertainty gate
  -> cite / rewrite / abstain
  -> constrained writing
  -> audit report
```

## 当前设计原则

- 所有生成都围绕 `claim -> citation -> evidence` 展开，而不是围绕整段自由文本展开。
- 每个 verifier 单独可测试，不把判定逻辑藏在 orchestrator 里。
- 写作器只能消费 gate 已经放行的引用。
- 评估脚本只统计最终被选中引用的完整性，避免把淘汰候选混入结果。
- scholarly adapter 优先查本地缓存，再必要时访问远端 API，避免重复 lookup。
- live scholarly adapter 会尽力从 OpenAlex / Crossref / arXiv 的 landing page 抽取结构化 `evidence_chunks`，多源 merge / lookup 时保留这些 chunk。
- `SupportVerifier` 会先对 title、abstract 句子、结构化 `evidence_chunks` 和兼容性的 `evidence_spans` 做 candidate generation，再用 backend 进行 rerank / NLI 判定。
- `build_production_support_backend()` 使用一组可标定的阈值与 `EnsembleSupportPolicy`，支持把 threshold / ensemble weight 的网格搜索结果直接回灌到生产默认值。

## 下一步扩展建议

- 把 `InMemoryMetadataSource` 扩展为 OpenAlex / Crossref / Semantic Scholar 多源路由。
- 将 `SupportVerifier` 从 lexical overlap 升级为 NLI 或 reranker。
- 引入 `ContradictionRetriever`，显式检索反例论文。
- 将 `AgentTask` 扩展为支持用户草稿、章节模板和时间范围限制。
