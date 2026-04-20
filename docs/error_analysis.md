# CiteGuard 错误分析框架

## 建议记录的错误类型

1. `phantom_citation`
   - 引用不存在

2. `metadata_blend`
   - 多篇论文元数据被错误混拼

3. `unsupported_real_citation`
   - 引用了真实论文，但不支撑 claim

4. `over_abstention`
   - 有足够证据但系统仍选择 abstain

5. `under_abstention`
   - 证据不足却仍然放行引用

## 当前最值得追踪的调试信号

- `SupportVerifier.details.overlap_terms`
- `MetadataVerifier.details`
- `risk_score`
- `candidate_attempts`
- `selected_citation_ids`

## 建议的分析维度

- 新近论文 vs 经典论文
- 计算机领域 vs 长尾专业领域
- 单引用 claim vs 多引用 claim
- 强断言 claim vs 保守表述 claim
