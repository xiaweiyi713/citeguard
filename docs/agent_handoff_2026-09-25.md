# CiteGuard Agent 交接（2026-09-25）

## 任务

继续把 CiteGuard 打磨为可实际使用、可审计的引文核验 Skill/MCP。优先修复会误导用户或夸大评测结果的问题，再推进真实数据收集。可以继续实现代码，但不要把 pilot、合成 seed 或自动化模型输出说成真实人工/线上 benchmark。

仓库：`https://github.com/xiaweiyi713/citeguard`

工作分支：`fix/identifier-hit-failure-attribution`

本次代码提交：`4d777381`（此前未提交的全部工作区改动，已推送）
本交接文档应与其后续提交一起推送到同一分支。不要在未检查远端变化时强推，也不要清理其他人的工作区改动。

## 产品与架构

- 核心定位是审慎的引文身份、元数据、claim-support 核验器，不是论文真伪或学术不端判定器。
- Python 包、CLI、MCP、Codex/Claude Code/Cursor Skill 是交付面。当前 MCP 使用 v1 FastMCP API；依赖约束见 `pyproject.toml`，不要直接升级到未经兼容验证的 SDK v2。
- `citeguard/contracts/v1/` 是面向 agent 的稳定输出契约。`not_found`、源故障、证据不足必须保持保守措辞和可操作的 `next_action`。
- 主要入口：`README.md`、`docs/architecture.md`、`docs/mcp_setup.md`、`skills/citeguard-verify/SKILL.md`、`docs/release_checklist.md`。

## 已完成且本次验证通过

- 有界 `audit-document` 支持文档依赖快照、LaTeX/BibTeX 依赖检查、并发修改/软链接防护及可追溯的 HTML 审阅输出。
- CLI/MCP 结构化错误、源健康/限流诊断、离线 smoke、Skill 安装/状态与触发评测输入绑定均有契约和测试。
- 人工支持评测已具备 gold-free 候选集、v3 盲化 packet、双人标注合并、第三人仲裁与审慎晋级流程；但真实人工标注尚不存在。
- 线上检索已具备已知真实记录收集、带时间/地区/源版本的观测产物与纵向汇总；但仍只是 pilot。
- 本地执行：`python -m unittest discover -s tests -q` 为 **784 tests OK**；`ruff check .` 通过；`python -m mypy citeguard/` 通过（93 source files）；`scripts/release_package_gate.py --skip-install-smoke --release-claim-mode development` 的 `ok=true`。这次未重新运行 wheel/sdist 安装 smoke，也未申请 software/human-benchmark 发布授权。

## 当前证据边界（以 2026-09-25 本地审计为准）

| 项目 | 当前状态 | 达标目标/限制 |
|---|---|---|
| Seed support eval | 54 条，`human_reviewed=0`；35 条高风险未人工复核 | 只能作为回归 fixture |
| Real-source human support | 12 条公开摘要候选，packet 校验通过；campaign 审计中合格双人标注为 0、test 未冻结 | 250-300 条；中英文各至少 100，CS/生医各至少 75；至少 50 条独立复核的冻结 test |
| Live retrieval | 12 条 pilot（DOI/arXiv/title 各 4），已有两次 2026-08-07 观测产物 | 至少 200 条：DOI 50、arXiv 50、title 100；每条至少 3 个不同时间的合格观测 |
| Skill trigger | 132 条中英文测试请求，suite 合法 | Codex/Claude/Cursor 的真实客户端预测尚未收集；模板不算结果 |
| Release claim | development 模式门槛通过 | `software` 需新鲜 automated review；`human-benchmark` 还需真实人工证据和严格门槛 |

注意：两个 live pilot 观测都发生在同一天，不能仅凭这些产物宣称跨期可靠性。`CITEGUARD_MAILTO`、`SEMANTIC_SCHOLAR_API_KEY`、`CITEGUARD_OA_FULLTEXT`、`CITEGUARD_REMOTE_EVIDENCE` 在本次本机环境均未设置。开展新的联网采集前先配置合法联系邮箱、确认来源使用条件；不要通过抓取付费数据库或受限全文补齐样本。

## 优先接手任务

1. **先审计 live 观测汇总输入校验。** `citeguard/benchmark/live_retrieval.py` 的 `_observe_case` 会根据 canonical identity、verdict 和源失败详情生成 `status`、`identity_match`、`source_limited`、`rate_limited`；但 `_validate_observation_artifact` 目前主要检查字段类型和枚举，未明显重新计算并核对这些派生关系。`_summarize_attempts` 信任输入字段，存在被不一致的归档行抬高合格分母/准确率的潜在风险。先在 `tests/test_live_retrieval_benchmark.py` 添加篡改归档行的失败测试（错误 canonical record 却标成正确；outage 却标成 eligible；无穷/NaN 延迟；失败详情与限流标志不一致），确认后按 `_observe_case` 的同一规则修复。保留对现有真实 pilot 产物的兼容性，验证不应伪造新观测。
2. **补齐交付级 smoke。** 在本地/CI 的干净 venv 中重新跑 wheel 与 sdist 安装、CLI 和真实 MCP stdio smoke；核查各客户端 Skill 的安装路径与启用状态。现有 development gate 不等于发布许可。
3. **组织真实人工标注。** 依照 `docs/human_benchmark_protocol.md` 保留源权利、盲化、两名独立 reviewer、第三人仲裁、curator 审核及原始包归档。公开的 12 条 pilot catalog 可与 review ID 关联，不能作为真正盲评任务直接分发。没有真人参与时只能保持 `human_reviewed=0`。
4. **扩展 live 记录并定时观测。** 依照 `docs/live_retrieval_benchmark_protocol.md` 人工确认 canonical identity，先平衡 DOI/arXiv/title，再分别从明确记录的地区和时间归档观测。源限流/超时要统计为可用性问题，不能等同于引文伪造或身份错误。
5. **采集 Skill 前向测试。** 按 `docs/release_checklist.md` 使用实际安装的 Skill 目录生成 Codex、Claude、Cursor 各自模板，收集真实客户端决策，保留 request/dataset/Skill digest、客户端版本和时间戳。不得用模板、自评或模型模拟预测替代真实客户端结果。
6. **最后提高发布门槛。** 只有在相应数据和 provenance 实际齐备、审计通过后，才上调 human-review/高风险复核阈值并讨论 benchmark 宣称。普通软件发布与研究级评测宣称应继续分开。

## 下一位 Agent 的最小验证命令

```bash
git status --branch --short
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check .
.venv/bin/python -m mypy citeguard/
.venv/bin/python scripts/audit_human_support_candidates.py --strict
.venv/bin/python scripts/audit_human_support_benchmark.py
.venv/bin/python scripts/audit_live_retrieval_benchmark.py
.venv/bin/python scripts/eval_skill_trigger.py --validate-only
.venv/bin/python scripts/release_package_gate.py --skip-install-smoke --release-claim-mode development
```

审计脚本的普通模式可在 collection incomplete 时返回 0；务必查看 `status`、`benchmark_claim_safe`、`deficits`，不要只看进程退出码。完整发布命令及产物要求见 `docs/release_checklist.md`。

## 约束与验收

- 不改写、删除或凭空补造已归档的观测、人工标注、客户端预测。对数据缺口如实报告。
- 不把 `not_found` 或所有来源故障解释成 fabricated citation；不把 abstract-only 证据升级为全文支持。
- 不把未经授权的全文、私有稿件、reviewer 私密信息提交到 GitHub；真实 campaign 的原始映射与私有 packet 使用受控存储。
- 改动需有针对性测试、Ruff、mypy 和相应 release gate；影响打包/MCP 时加做干净环境安装及 stdio smoke。
- 第一阶段验收：不一致的 live observation artifact 被明确拒绝，合法 pilot 产物仍可汇总，全部既有测试通过，文档/门槛措辞与实现一致。
