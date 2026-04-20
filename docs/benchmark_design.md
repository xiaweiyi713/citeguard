# CiteGuardBench 设计说明

## 目标

`CiteGuardBench` 用来评估科研写作 Agent 在引用完整性上的真实表现，而不仅仅是写作流畅度。

## 当前原型指标

- `PCR`: Phantom Citation Rate
- `MCR`: Metadata Corruption Rate
- `CSR`: Claim Support Rate
- `UCR`: Unsupported Citation Rate
- `AU`: Abstention Utility
- `RIS`: Reference Integrity Score

这些指标已经在 [src/benchmark/metrics.py](/Users/xuwenyao/CiteGuard/src/benchmark/metrics.py) 中实现。

## 推荐任务构成

1. `Citation Existence Verification`
   - 判断引用是否真实存在

2. `Metadata Consistency`
   - 判断标题、作者、年份、venue 是否被错误拼接

3. `Claim Support Verification`
   - 判断引用是否真正支撑 claim

4. `Falsification-First Writing`
   - 给定主题，生成带引用文本并评估最终输出质量

## 当前原型限制

- 当前 `SupportVerifier` 已支持 heuristic baseline 与真实 reranker / NLI backend，但标定集仍偏小，需要扩展为更正式的人工标注 dev/test 划分。
- 目前 benchmark builder 仍是轻量版本，后续需要加入人工标注样本与 harder negatives。
- 目前 demo 评测使用内置语料，还没有接入大规模真实 academic corpus。
