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

这些指标已经在 [citeguard/benchmark/metrics.py](/Users/xuwenyao/CiteGuard/citeguard/benchmark/metrics.py) 中实现。

`data/eval/support_eval.json` 还包含一个小型、合成 claim-support seed set:
24 条 evidence-level cases 加上 citation-set policy cases。它用于回归测试
title、abstract、metadata snippet 和 full-text scope 下的支撑性判断,并特别加入
hard negatives、contradictions、title-only weak support、source-outage 安全表述和
多引用聚合边界样本。当前脚本输出:

- accuracy
- supported precision / recall / F1
- per-label precision / recall / F1 in `per_label`
- abstention rate
- false-support rate
- misjudged-support rate
- contradiction recall

`scripts/eval_support.py` 默认使用 `--backend fixture`，即直接用 seed gold
labels 生成确定性报告，用来验证数据集、split、provenance、分组指标和报告
schema；这不是模型质量指标。运行 `python3 scripts/eval_support.py --report`
会输出:

- `dataset`: 样本总数、case type 覆盖、evidence scope 覆盖、gold label 覆盖、language 覆盖、split 覆盖和 label source 列表
- `overall`: 与默认脚本相同的整体指标
- `confusion_matrix`: gold label × predicted label 的计数矩阵
- `by_case_type`: 按 direct support、hard negative、contradiction 等类别拆分
- `by_evidence_scope`: 按 title / abstract / full-text 等证据层级拆分
- `by_language`: 按 `en` / `zh` 等语言拆分,用于追踪中文安全边界和 supported 误报
- `by_split`: 按 `train` / `dev` / `test` 拆分,防止把校准集和最终报告混在一起
- `error_bucket_counts` / `error_buckets`: false support、weak false support、missed contradiction、incorrect abstention 等误差桶
- `review_queue`: 将 false support、missed contradiction、weak false support、错误拒绝和错误 abstention 合并去重,按 severity / risk score 排序,并给出 `recommended_action`,供 agent 或 maintainer 优先复核最危险 case
- `review_queue_summary`: 按 severity、bucket 和 `recommended_action` 汇总 `review_queue`,并列出 `top_case_ids` / `critical_case_ids`,供 agent 不遍历完整队列也能决策
- `false_support_analysis`: 汇总 total overcall count、high-risk false-support case ids,并按 case type、evidence scope、language 和 split 分组；每个分组都列出 `false_support_case_ids` 与 `weak_false_support_case_ids`,同时提供 `risk_slices` / `top_risk_slice`,把 contradicted overcalls、hard negatives、full-text boundary、test split 和 non-English overcalls 排成机器可读的复核优先级,用于发布前优先复核最危险的 supported 误报
- `diagnostics`: 当前 backend、是否处于 heuristic 限制模式、需要 NLI 复核的 missed contradiction case ids、false/weak false support case ids、以及面向 threshold/backend 选择的 warnings 和 recommendations
- `quality_gate`: 如果传入 `--quality-gate`,报告会附带保守发布门禁结果,并在失败时以非零状态码退出；失败 payload 包含 `quality_gate.review_queue_case_ids` 和 `quality_gate.critical_review_case_ids`,便于 agent 先复核最高风险样本
- `support_set_policy`: model-free citation-set 聚合边界报告,确认 multiple weak
  citations 仍是 tentative、contradiction 会支配 aggregate verdict、全不足证据会
  abstain
- `cases`: 每条样本的 gold、predicted、correct、case_type、evidence_scope 和 label_source

每条 seed case 都包含 `evidence_scope`、`label_source`、`case_type`、`split` 和可选
`label_notes`。这些字段是后续人工标注 benchmark 的结构基础；当前 seed
set 仍只是维护者合成样本，不能当作最终论文级 benchmark。现有 seed set
已经覆盖 direct support、weak support、hard negative、contradiction、
full-text-required 和 full-text evidence examples。dataset validation 还要求
`test` split 覆盖 `weak_support`、`hard_negative`、`contradiction`、
`full_text_required` 和全部 gold labels,避免最终报告绕过最容易造成 false
support 或 missed contradiction 风险的样本。

运行单个 split:

```bash
python3 scripts/eval_support.py --report --split dev
python3 scripts/eval_support.py --report --split test --quality-gate
python3 scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only
python3 scripts/eval_support.py --backend heuristic --report --split test
python3 scripts/eval_support.py --backend production --report --split test
```

`--quality-gate` 默认执行偏保守的 support 安全门槛:

- `max_false_support_rate = 0.0`
- `max_false_support_count = 0`
- `max_weak_false_support_count = 0`
- `min_supported_precision = 1.0`
- `min_contradiction_recall = 1.0`

这些默认值的含义是:任何把非支撑样本判成 `supported`/`weakly_supported`
的结果都会失败,任何 contradiction 漏检也会失败。对 heuristic 或 production
backend 做探索时可以显式调宽阈值,但发布前的 test split 应先检查
`quality_gate.failures` 和相关 case ids。`--review-queue-only` 会输出紧凑
triage payload,包含 `review_queue_summary`、`review_queue`、`false_support_analysis.risk_slices` /
`false_support_analysis.top_risk_slice`、`quality_gate.review_queue_case_ids` 和
`quality_gate.critical_review_case_ids`,适合 agent 或发布脚本只读取最高风险
case 队列和 supported-overcall 优先级。

需要保存可复现实验产物时,给离线 eval 脚本传入 `--output-dir` 和稳定的
`--run-id`:

```bash
python3 scripts/eval_verification.py \
  --output-dir experiments \
  --run-id verification-fixture-v1
python3 scripts/eval_support.py \
  --report \
  --split test \
  --quality-gate \
  --output-dir experiments \
  --run-id support-fixture-test-v1
```

每次运行会写入 `experiments/<run-id>/result.json`、`config.json` 和
`manifest.json`。`result.json` 保存完整指标或报告,`config.json` 保存脚本、
dataset、split、backend 和 quality-gate 阈值等配置快照,`manifest.json`
提供 schema version、生成时间、文件索引和紧凑结果摘要。默认不写
`experiments/`,避免普通 CI 或本地 smoke 命令产生工作树噪音。

生成可复现 baseline comparison table:

```bash
python3 scripts/compare_support_baselines.py \
  --split test \
  --output-dir experiments \
  --run-id support-baselines-test
```

默认比较 `fixture` 和 `heuristic`。`fixture` 是确定性管线/报告 schema
基线,不代表模型质量；`heuristic` 是零模型词面 baseline,用于暴露没有 NLI 时的
限制。输出的 `comparison` 表汇总 accuracy、supported precision/recall/F1、
abstention rate、false-support rate、contradiction recall、error bucket
counts、`total_overcall_count`、high-risk false support case ids、`false_support_risk_slices` / `top_false_support_risk_slice` 和分组级
`false_support_case_ids` / `weak_false_support_case_ids`,以及
`review_queue_case_ids` / `critical_review_case_ids`、`review_queue_by_severity`
和 `review_queue_by_recommended_action`,并为每个 backend 附带 conservative
`quality_gate`。需要模型-backed
行时可显式加入 `--backend production`。顶层 `quality_gates_ok` 汇总所有
backend 和 sidecar gate 的状态；默认命令即使 heuristic baseline 不过 gate 也
会退出 0,因为 comparison table 的目的是暴露限制。发布流程需要强制阻断时可加
`--fail-on-gate`。

backend 约定:

- `fixture`: 默认,完全离线、确定性、用于回归和 CI 报告 schema 验证。
- `heuristic`: 本地词面 baseline,不下载模型,用于快速弱基线。
- `production`: 配置的 reranker/NLI backend,需要 `[models]` extra 和可用的本地
  或可下载模型权重。

约定:

- `train`: 允许用于规则开发和快速实验。
- `dev`: 用于阈值、backend 或 prompt 校准。
- `test`: 用于最终报告；看过 test 失败后不应继续调阈值并把同一结果当最终指标。

运行 `python3 scripts/eval_support.py --validate-only` 可只验证数据集 schema、
provenance 和最小覆盖面,不加载 support 模型。当前 seed set 要求覆盖:

- gold labels: `supported`, `weakly_supported`, `insufficient_evidence`, `contradicted`
- case types: `direct_support`, `weak_support`, `hard_negative`,
  `unrelated_negative`, `contradiction`, `full_text_required`
- evidence scopes: `title`, `abstract`, `metadata_snippet`, `full_text`
- splits: `train`, `dev`, `test`

这不是说 seed set 已经足够大,而是让后续扩充 benchmark 时不会丢掉最关键的
安全回归面。

如果提供 label provenance sidecar,可以一起校验:

```bash
python3 scripts/eval_support.py --validate-only --label-sidecar data/eval/support_eval_label_sidecar.json
```

默认 sidecar gate 要求 coverage 为 `1.0`,也就是随仓库提交的 sidecar 必须覆盖
当前 dataset 的所有 case。当前 synthetic seed set 的 `human_reviewed` 仍为 0,
所以默认 `--min-human-reviewed` 是 0；开始人工标注后可以显式提高门槛:

```bash
python3 scripts/eval_support.py \
  --validate-only \
  --label-sidecar data/eval/support_eval_label_sidecar.json \
  --min-human-reviewed 10 \
  --min-high-risk-reviewed 5 \
  --min-high-risk-reviewed-by-language zh=2 \
  --min-dual-annotated 10 \
  --max-unresolved-disagreements 0 \
  --min-raw-dual-agreement-rate 0.8 \
  --max-supported-disagreements 0
```

sidecar 用于保存不适合塞进 compact seed case 的标注元数据,例如
`annotator_count`、`annotator_labels`、`adjudication_status`、`adjudicator`、
`disagreement` 和 `source_locator`。sidecar validation 还输出
`label_maturity`,汇总 `reviewed_fraction`、`dual_annotated_count`、
`raw_dual_agreement_rate`、`adjudicated_count`、
`resolved_disagreement_count`、`unresolved_disagreement_count`、
`dual_label_pair_counts`、`dual_disagreement_label_pair_counts` 和
`supported_disagreement_case_ids`,用于判断人工标注成熟度而不只看 coverage。
validation 同时输出 `high_risk_review`,统计 contradiction、hard_negative、
full_text_required 和 contradiction_set 的 reviewed/unreviewed 覆盖情况,并包含
`case_count_by_language`、`reviewed_by_language` 和
`unreviewed_by_language`,以及 `reviewed_case_ids_by_language` 和
`unreviewed_case_ids_by_language`,用于发现中文/英文高风险样本是否仍缺人工复核。
dataset validation 也输出 `languages` 和 `test_split`,列出测试集中的
case type、evidence scope、language、gold label 覆盖及 required coverage,用于确认最终测试集不是只在
train/dev 中覆盖高风险样本。
任何 supported-label disagreement 都应优先复核,因为把不充分证据误标成
`supported` 是最危险的 benchmark 误差。`label_sidecar_gate` 可显式要求
`--min-high-risk-reviewed`、`--min-high-risk-reviewed-by-language`、
`--min-dual-annotated`、
`--max-unresolved-disagreements`、`--min-raw-dual-agreement-rate` 和
`--max-supported-disagreements`,让发布报告在高风险样本评审不足、语言高风险样本评审不足、
双标不足、分歧未解决、一致率过低或 supported-label 分歧未清零时以机器可读
failure code 失败。gate metrics 还包括 `high_risk_case_count_by_language`、
`high_risk_reviewed_by_language` 和 `high_risk_unreviewed_by_language`,便于
agent 不展开 sidecar summary 也能判断语言覆盖缺口。validation 还会检查 status consistency:
`not_human_reviewed` 不能携带 annotator label,`dual_annotator_agreed` 的
annotator labels 必须一致,`dual_annotator_adjudicated` 必须记录 resolved
disagreement 和 adjudicator,`published_benchmark` 必须有 source locator,避免
坏 sidecar 虚高 `label_maturity`。当前随仓库提交的
`support_eval_label_sidecar.json` 覆盖所有 evidence-level 和 citation-set
synthetic seed cases,记录每条样本当前 gold label 的 provenance 占位。
`human_reviewed` 为 0,不能当作人工评审 benchmark；它的作用是固定未来人工标注
数据的结构、覆盖率和 CI 校验入口。

扩充人工标注集时遵循
[`docs/support_labeling_guidelines.md`](/Users/xuwenyao/CiteGuard/docs/support_labeling_guidelines.md):
优先收集 hard negatives、contradiction examples 和 abstract/full-text scope
边界样本，并保留分歧处理记录。

开始一轮人工标注前,先生成完整 sidecar 草稿:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --include-context \
  --output data/eval/support_eval_label_sidecar.draft.json
```

这个脚本会保留已有审定记录,并为新增或缺失 case 补上
`not_human_reviewed` 占位,让覆盖率和待标注项一眼可见。
这个 sidecar 草稿用于维护者回填 provenance,不应直接发给独立标注员,因为它包含
dataset gold / adjudicated label。盲标时改用 annotation packet:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --priority high \
  --split test \
  --limit 10 \
  --output experiments/support-label-packet-high-risk-test.json \
  --instructions-output experiments/support-label-packet-high-risk-test-instructions.md
```

`--annotation-packet` 输出 claim、evidence、evidence_scope、case_type、split、
priority、source locator、非 gold 的 `review_focus` 边界提示和空白
annotation 字段,但不会输出 `gold`、`adjudicated_label`、`annotator_labels`
或 `label_notes`。`review_focus` 只提示标注员检查哪类 support 边界,例如
full-text 缺口、主题相关但过度宣称、或 source outage 推断,不能当作 label
hint。需要一行一个样本时可加 `--packet-format jsonl`。`--instructions-output`
会同时生成给独立标注员使用的 Markdown instruction sheet,说明允许标签、保守标注
规则和不可修改字段,但不暴露隐藏 gold/adjudication 字段。标注员必须填写
`annotation.annotator_id`;缺失
annotator id 的行会进入 `merge_report.skipped`,同一个 case 里重复的
annotator id 会作为 `duplicate_annotator` conflict 报告,不能算作双人标注。
标注员返回填好的 packet 后,用保守 merge 回填 sidecar:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --merge-annotation-packet experiments/completed-support-label-packet.json \
  --output data/eval/support_eval_label_sidecar.merged.json
```

merge 只会应用与当前 dataset gold 一致的标签:单个一致标签写为
`single_annotator`,两个或以上一致标签写为 `dual_annotator_agreed`。如果
annotator 之间有分歧,或标注结果与当前 gold 冲突,命令会在
`merge_report.conflicts` 中列出并返回非零状态码,不会静默改写 sidecar。
这些冲突还会进入 `merge_report.adjudication_queue`,保留 packet id、
packet case index、annotator id、标签、rationale、confidence 和空白
adjudication template。template 带有 `source_packet_ids`,后续
`--apply-adjudications` 会把它写入 `adjudication_report.source_packet_ids`
和 sidecar notes,方便维护者把真实分歧转成显式裁决记录,而不是把冲突静默
折叠成 benchmark label。
讨论后需要显式回填 adjudication:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.merged.json \
  --apply-adjudications experiments/resolved-support-label-adjudications.json \
  --output data/eval/support_eval_label_sidecar.adjudicated.json
```

adjudication 行必须包含 `case_id`、`annotator_labels`、`adjudicated_label`
和 `adjudicator`。若 adjudicated label 与当前 dataset gold 不一致,命令会输出
`adjudication_report.conflicts` 并返回非零,要求先人工审查 dataset gold。

查看人工标注待办清单:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --audit
```

`--audit` 输出 coverage、human-reviewed 数量、按 case type / language /
split 统计的未审阅样本,完整 `unreviewed` 列表,以及只包含 contradiction、
hard_negative 和 full_text_required 的 `high_risk_unreviewed` /
`high_risk_unreviewed_count` / `high_risk_unreviewed_by_language`。优先审阅
contradiction、hard_negative 和 full_text_required 样本,因为这些最能暴露
false support、过度支撑和 abstract/full-text 边界问题。`recommended_packets`
会给出机器可读的下一批 annotation-packet 命令,覆盖 balanced high-risk
first review、按语言 high-risk review,以及存在 `single_annotator` case 时的二审
packet。
需要在分配标注前阻断某个语言的高风险缺口时,使用
`--fail-on-high-risk-unreviewed-language zh`;audit 输出的 `audit_gate.failures`
会列出 `high_risk_unreviewed_by_language` 的 failure code 和 case ids。

为第一轮人工标注生成更小的盲标 high-risk test packet:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --priority high \
  --split test \
  --output experiments/support-label-packet-high-risk-test.json \
  --instructions-output experiments/support-label-packet-high-risk-test-instructions.md
```

`--priority` 可重复使用,取值为 `high`、`medium` 或 `normal`;`--split`
、`--case-type` 和 `--lang` 也可重复使用。需要给标注员分配更小的确定批次时,
可以重复传 `--case-id` 点名稳定 case id,或用 `--lang zh` 生成中文专项
复核包,并用 `--limit` 截取过滤后的前 N 条:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --priority high \
  --split test \
  --limit 3 \
  --output experiments/support-label-packet-high-risk-test-batch1.json \
  --instructions-output experiments/support-label-packet-high-risk-test-batch1-instructions.md
```

当某个 backend 的 support quality gate 失败时,可以直接把它的
`review_queue` 转成盲标 packet,让人工复核从最危险的失败样本开始:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --from-review-queue \
  --review-backend heuristic \
  --split test \
  --output experiments/support-label-packet-review-queue-test.json \
  --instructions-output experiments/support-label-packet-review-queue-test-instructions.md
```

`--from-review-queue` 会先运行 support eval report,按 `review_queue` 顺序选出
case,再套用 `--split`、`--lang`、`--limit`、`--unreviewed-only` 等常规过滤。
导出的 packet 只增加 `review_queue_rank` 作为分配优先级,不会暴露 dataset
gold、adjudicated label、annotator labels 或 backend prediction。标注员仍应只根据
packet 中的 claim/evidence/evidence_scope 独立标注。

过滤只影响导出的标注 packet 或 audit 视图,不会把未选中的 case 从原始
dataset 或正式 sidecar 中删除。
用 `--unreviewed-only` 可以在已有 sidecar 人工复核记录时只导出尚未审阅的
case；用 `--review-status single_annotator` 可以导出已经有一名 reviewer、
需要第二名 reviewer 的 case。用 `--limit-per-language`、`--limit-per-case-type` 和
`--limit-per-evidence-scope` 可以生成更均衡的小批次,避免第一轮 high-risk
packet 只覆盖一种语言、风险类型或证据层级。每个 packet 都带确定性的
`packet_id` 和 `packet_summary`,记录 case ids 以及按语言、case type、
evidence scope、split、priority、当前 review status 的计数,包括
`case_count_by_language`、`case_count_by_case_type`、
`case_count_by_evidence_scope` 和 `case_count_by_review_status`,便于归档、分配二审
或 adjudication 批次,并用于发布前审计。

需要把人工标注成熟度作为发布阻断条件时,加上:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --audit \
  --fail-on-high-risk-unreviewed \
  --fail-on-high-risk-unreviewed-language zh
```

当前 synthetic seed set 会因为高风险样本未人工审阅而失败；这是有意设计,
用于防止把未审 seed set 误称为 human-reviewed benchmark。开始真实标注后,
先清掉 high-risk 未审样本,再提高 `eval_support.py --min-high-risk-reviewed`
和 `--min-human-reviewed` 门槛。

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
