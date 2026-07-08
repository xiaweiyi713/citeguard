# CiteGuard

[![CI](https://github.com/xiaweiyi713/citeguard/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaweiyi713/citeguard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

中文 · [English →](README.en.md)

**CiteGuard 是一个"证伪优先"的引用核验工具**:面向 agent 写作工作流,对每条引用核对三件事——**这篇论文存不存在**、**元数据(标题/作者/年份/venue/DOI)对不对**、**它到底支不支持你写的那句话**——直接查询 OpenAlex / Crossref / arXiv / Semantic Scholar 等真实学术库,可作为 **MCP 工具**被 Claude Code、Codex、Cursor 等主流 agent 直接调用。

LLM 写作助手会幻觉参考文献:编造不存在的论文、拼错真实论文的元数据、引用与论点无关的真论文。CiteGuard 扮演那个"多疑的审稿人":它把每条引用当作 `论点 → 引用 → 证据` 问题去**证伪**;拿不准的时候明确说"查不准",而不是猜一个答案。

> **状态:** Alpha(`v0.1.0`)。当前积极开发的产品面是 `citeguard.*` 审计包、CLI、MCP server、批量工作流、缓存回放与发布门禁;历史遗留的写作 agent 实验仅保留在源码签出中,不属于发布包。

---

## 看看效果

![CiteGuard 对照 OpenAlex 与 arXiv 核验两条引用](docs/assets/demo_verify.svg)

源码签出场景还可以运行 `python3 scripts/demo_verify.py` 看实时效果(会真实访问 OpenAlex + arXiv);已安装包场景请优先使用 `citeguard` / `citeguard-mcp` 入口。

```text
Verifying 2 citations against OpenAlex + arXiv ...

[OK] VERIFIED           (confidence 0.7)
    Vaswani et al., "Attention Is All You Need", arXiv:1706.03762
    sources checked: openalex, arxiv
    Citation resolves to a real record and the provided metadata matches.

[X] NOT_FOUND          (confidence 0.8419)
    (LLM-fabricated) "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"
    sources checked: openalex, arxiv
    Could not be verified in openalex, arxiv.
```

> 输出为实时采集,置信度与匹配到的记录会随源数据漂移。

---

## 它做什么

CiteGuard 对照 **OpenAlex、Crossref、arXiv、Semantic Scholar** 回答两个问题。

### 1. 论文存在吗?元数据对吗?

`verify_citation` / `audit_citations` 解析引用(标识符优先,否则按标题检索),逐字段比对你提供的元数据:

| 判定 | 含义 |
|---|---|
| `verified` | 论文存在,你提供的元数据全部吻合 |
| `metadata_mismatch` | 论文存在但某字段不符——附**修正后的引用建议** |
| `not_found` | 在所查源中无法核实(标记高风险,但**不**断言伪造) |
| `ambiguous` | 多个候选难以区分——要求提供 DOI / arXiv id 消歧 |

### 2. 论文支持这个论点吗?(深度模式)

`check_claim_support` 先解析论文,再用 reranker + NLI 集成判断其摘要与你的论点句的关系:

| 判定 | 含义 |
|---|---|
| `supported` | 摘要蕴含该论点 |
| `weakly_supported` | 有部分/相关证据,但不够强 |
| `insufficient_evidence` | 摘要未涉及该论点——**弃权**,不等于"不支持" |
| `contradicted` | 摘要与论点相矛盾 |

支撑性结果带机器可读的 `evidence_scope` 字段,agent 不会把摘要级证据当成全文结论。全文级支撑为可选:调用方可通过 CLI/MCP/JSON 提供合法摘录或本地 text/PDF 文件(PDF 解析需 `pip install "citeguard[pdf]"`);CiteGuard 不抓取受限源、不下载远程全文、不绕过付费墙。

两条守护原则保证它"诚实":**源不可达永远不会升级成"伪造"**(只降低置信度,设置 `outage_limited=true` 并上报 `sources_available` / `sources_failed` / `source_failure_mode`);`insufficient_evidence` / `not_found` 一律表述为"无法确认",最终裁决留给人或宿主 agent。

---

## 快速上手

**核心库零第三方依赖**,运行于 Python ≥ 3.9。

已发布包安装:

```bash
python -m pip install citeguard
python -m pip install "citeguard[mcp]"     # + MCP server(需要 Python >= 3.10)
python -m pip install "citeguard[models]"  # + 支撑性深度模式的 reranker/NLI 模型栈(较重)
python -m pip install "citeguard[api]"     # + FastAPI 接口
```

源码签出场景:`python -m pip install -e .`(extras 同上)。

先检查本地配置,再从命令行核验引用:

```bash
citeguard status                          # 本地就绪状态;加 --check-sources 做实时源探测

citeguard verify \
  --title "Attention Is All You Need" \
  --author "Ashish Vaswani" \
  --year 2017 \
  --arxiv-id 1706.03762

citeguard audit examples/citations.json                  # 批量:JSON 数组或 .jsonl
citeguard audit examples/references.md --high-risk-only  # 提取并审计参考文献文件

citeguard support \
  --claim "The Transformer relies entirely on attention." \
  --title "Attention Is All You Need" \
  --arxiv-id 1706.03762

citeguard support-audit examples/claim_citations.json    # 批量"论点/引用"对
citeguard support-audit examples/claim_citations.jsonl --high-risk-only
citeguard support-set examples/citations.json \
  --claim "Citation auditing should verify existence, metadata, and claim support."

citeguard extract examples/references.md                 # 从文稿中提取引用候选
citeguard counterevidence --claim "The Transformer relies entirely on attention."
```

提取支持 Markdown/纯文本参考文献、LaTeX `\bibitem`、BibTeX、编译产物 `.bbl`、LaTeX `\bibliography{refs}` / `\addbibresource{refs.bib}` 外链(含 `\input{...}` / `\include{...}` 子文件)以及 `.docx`——全部只用标准库(即 Markdown/LaTeX/BibTeX/BBL/DOCX 引用提取)。提取行保留 `source_path` / `source_locator` / 行号范围,审计结果可回指原始参考文献条目。

所有命令输出 JSON,带稳定的 `next_action` 枚举、风险排序和机器可读错误。完整 CLI 说明(含 `cache` 检查/导出/清理与离线 fixture 回放)见 [docs/cli_reference.md](docs/cli_reference.md);agent 侧完整字段契约见 [docs/agent_output_contract.md](docs/agent_output_contract.md)。

### 作为 agent 工具接入(MCP)——推荐路径

已发布包:

```bash
python -m pip install "citeguard[mcp]"   # 需要 Python >= 3.10
citeguard-mcp                            # stdio 传输
```

源码签出:

```bash
python -m pip install -e ".[mcp]"
citeguard-mcp
```

在任意 MCP 客户端中注册(以 Claude Code 为例):

```json
{
  "mcpServers": {
    "citeguard": { "command": "citeguard-mcp" }
  }
}
```

| 工具 | 用途 |
|---|---|
| `citeguard_status_tool` | 不做实时查询,检查 MCP/Python 就绪度、缓存、源配置与模型依赖状态 |
| `verify_citation_tool` | 核验单条引用;返回判定、规范记录、逐字段差异、修复建议与所查源 |
| `audit_citations_tool` | 批量核验引用;逐条报告 + 判定计数汇总 |
| `check_claim_support_tool` | 判断某篇论文是否支持某论点句(深度模式) |
| `check_claim_support_set_tool` | 判断一组引用是否共同支持一个论点 |
| `search_counterevidence_tool` | 检索潜在反证线索;仅为复核线索,不构成矛盾判定 |
| `audit_claim_support_tool` | 批量判断"论点/引用"对并汇总支撑判定 |

连接后先调一次 `citeguard_status_tool`——它在不发起实时查询的前提下报告源健康、缓存与模型就绪状态;详见 [docs/mcp_setup.md](docs/mcp_setup.md) 与 [docs/agent_output_contract.md](docs/agent_output_contract.md)。

支持 skill 的 agent 客户端可使用 [`skills/citeguard-verify/SKILL.md`](skills/citeguard-verify/SKILL.md),让 CiteGuard 在你写作时**主动**核验引用(呈现结果而不静默改动你的文本),适用于 Codex、Claude Code、Cursor 等 MCP 客户端。

### 作为 Python 库

```python
from citeguard.retrieval.scholarly_clients import build_live_metadata_source
from citeguard.verification import parse_citation, verify_citation, check_claim_support

source = build_live_metadata_source(["openalex", "arxiv"], mailto="you@example.com")

result = verify_citation(parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762"), source)
print(result.verdict.value, result.confidence)          # -> verified 0.7

support = check_claim_support("The Transformer relies entirely on attention.",
                              parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762"),
                              source)
print(support.verdict.value, support.engine)
```

---

## 配置

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `CITEGUARD_SOURCES` | `openalex,crossref,arxiv` | 查询哪些源(另支持 `semantic_scholar` / `s2`);未知源名直接报配置错误 |
| `CITEGUARD_MAILTO` | — | OpenAlex/Crossref 礼貌池的真实联系邮箱;未设置则不发送 `mailto` |
| `SEMANTIC_SCHOLAR_API_KEY` | — | 可选,改善 Semantic Scholar 访问 |
| `CITEGUARD_CACHE` | `data/logs/verification_cache.sqlite` | 本地 SQLite 解析缓存 |
| `CITEGUARD_FIXTURE_CITATIONS` | — | JSON/JSONL 引用 fixture,用于确定性离线运行 |
| `CITEGUARD_HTTP_TIMEOUT` | `10` | 实时学术 API 调用超时(秒) |
| `CITEGUARD_REMOTE_EVIDENCE` | `0` | 设为 `1` 时额外抓取落地页摘要片段 |
| `CITEGUARD_RERANKER_MODEL` / `CITEGUARD_NLI_MODEL` | 英文模型 | 支撑性深度模式模型——非英文论点请配置多语模型 |

完整运行时契约(重试/退避、证据超时、缓存路径、远程证据边界)见 [docs/configuration.md](docs/configuration.md)。

支撑性深度模式首次使用时下载模型权重,可用 `python3 scripts/warmup_support_models.py` 预下载。未安装 `[models]` 时,支撑性检查运行带标注的 `heuristic` 引擎(永不输出 `supported` 或 `contradicted`);`citeguard status` 会报告 `support_models.engine=heuristic_fallback` 与 `next_action=install_or_configure_dependency`。

---

## 中文支持

文本匹配对 CJK 友好(中文字符保留并按字符 bigram 分词,**零额外依赖**),中文标题与论点可直接对照 OpenAlex/Crossref 中已收录的大量中文论文核验。判定中文论点的支撑性时,请将 `CITEGUARD_RERANKER_MODEL` / `CITEGUARD_NLI_MODEL` 指向多语模型。

知网(CNKI)与万方**未**接入:两者没有开放/免费 API,我们不爬取受限内容。ChinaXiv 可行性调研结论为 NO-GO(其 OAI 端点受访问限制)——见 [`docs/chinaxiv_spike.md`](docs/chinaxiv_spike.md);可插拔的源接口保留,一旦出现开放端点即可添加适配器。

---

## 解析流程

1. **解析**输入;自由文本中的 DOI / arXiv id / 年份会被自动提取。
2. **标识符优先**:DOI 或 arXiv id 可确定性解析论文。
3. **否则按标题检索**所选源,以标题为主的匹配分对候选打分。
4. **只比对你实际提供的字段**,逐字段给出差异。
5. **给出判定**(存在性/元数据,或基于摘要级证据的支撑性)。

---

## 边界与已知限制

**当前能力范围:** 存在性 + 元数据核验、摘要级支撑性核验、用户提供的本地全文证据文件、多引用论点检查、多源适配器、SQLite 缓存、Markdown/LaTeX/BibTeX/BBL/DOCX 参考文献提取、MCP server、Claude Code skill、离线 eval。

**已知限制**

- **标识符是可靠路径。** 有 DOI 或 arXiv id 时解析是确定性的——能提供就提供。
- **仅按标题匹配是尽力而为。** 同一标题可能对应多条记录(如原始论文 + 年份不同的再版);无标识符时,正确的引用也可能匹配到同名记录而在 `year`/`venue` 上报 `metadata_mismatch`。请把仅标题匹配下的年份/venue 不符当作"待确认"。
- **支撑性判定默认是摘要级的,除非你提供全文证据。** 它判断摘要、采集到的元数据片段和你提供的合法本地 text/PDF 证据;弃权(`insufficient_evidence`)常见且符合设计。
- **支撑性 eval 是合成种子 fixture**,按 train/dev/test 切分——是回归夹具,不是最终人工评审基准。

**尚未实现:** 自动全文获取、跨论文全文多跳综合、反证判定(counter-evidence verdicting)、大规模人工评审基准。见 [ROADMAP.md](ROADMAP.md)。

---

## 测试与复现

```bash
python3 -m unittest discover -s tests -v   # 完整单测套件;MCP stdio 冒烟在缺 SDK 时自动跳过
python3 scripts/smoke_mcp.py --require-sdk # MCP stdio 冒烟;MCP SDK 需要 Python 3.10+
python3 scripts/eval_verification.py       # 离线确定性的存在性/元数据 eval
python3 scripts/eval_support.py --report --split test --quality-gate
python3 scripts/release_package_gate.py    # 完整发布门禁;发布前加 --require-build-tools
```

单测与 eval 全部离线,在 CI 中运行。eval 数据集位于 [`data/eval/`](data/eval/)。支撑性 eval 工作流——指标、质量门禁、标注溯源 sidecar、盲评标注包——见 [docs/support_eval.md](docs/support_eval.md);发布冒烟与发布流程见 [docs/release_checklist.md](docs/release_checklist.md)。

---

## 项目结构

```text
citeguard/
  verification/   # 核心:解析、消解、核验、审计、缓存、支撑性、eval
  cli.py          # 零依赖 `citeguard` 命令:status/verify/audit
  runtime.py      # 共享的环境、源、缓存与状态配置
  mcp/            # FastMCP server,暴露状态 + 核验工具
  retrieval/      # 学术源适配器(OpenAlex/Crossref/arXiv/Semantic Scholar)+ 检索器
  verifiers/      # 存在性/元数据 + reranker+NLI 支撑性集成
  citation/ graph/ audit/                 # 共享模型与工具
  orchestrator/ planner/ writer/ benchmark/ api/   # 源码签出实验与 benchmark/API 工具
skills/citeguard-verify/   # 可复用的 Codex/Claude/Cursor agent skill
scripts/                   # demo + eval + 语料/模型工具
data/eval/                 # 离线基准
docs/                      # 发布文档、架构、benchmark 笔记、调研笔记
tests/                     # unittest 套件
```

新代码请从 `citeguard` 或 `citeguard.*` 导入。源码签出保留旧 import 的兼容 shim(触发 `DeprecationWarning`),发布包只暴露 `citeguard.*` 产品面;见 [`docs/public_api_migration.md`](docs/public_api_migration.md)。

---

## 文档

- 安装与参考: [`docs/configuration.md`](docs/configuration.md) · [`docs/mcp_setup.md`](docs/mcp_setup.md) · [`docs/cli_reference.md`](docs/cli_reference.md) · [`docs/agent_output_contract.md`](docs/agent_output_contract.md) · [`docs/error_codes.md`](docs/error_codes.md) · [`docs/public_api_migration.md`](docs/public_api_migration.md)
- 基准评测: [`docs/support_eval.md`](docs/support_eval.md) · [`docs/benchmark_design.md`](docs/benchmark_design.md) · [`docs/benchmark_todo.md`](docs/benchmark_todo.md) · [`docs/support_labeling_guidelines.md`](docs/support_labeling_guidelines.md)
- 发布与安全: [`docs/release_checklist.md`](docs/release_checklist.md) · [`docs/security_compliance.md`](docs/security_compliance.md)
- 架构: [`docs/architecture.md`](docs/architecture.md) · 路线图: [`ROADMAP.md`](ROADMAP.md) · ChinaXiv 调研: [`docs/chinaxiv_spike.md`](docs/chinaxiv_spike.md)

## 引用

学术使用请引用 [`CITATION.cff`](CITATION.cff) 中的软件记录。

## 贡献

见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。基于 [MIT License](LICENSE) 发布。
