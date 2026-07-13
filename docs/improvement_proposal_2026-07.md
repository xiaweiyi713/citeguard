# CiteGuard 改进企划书(2026-07-13)

> **目标**:把 CiteGuard 从"功能完备"推进到"真正可以落地好用"的 MCP / skill。
> **依据**:对 main(`citationguard` v0.1.1)的完整重读 + 线上 MCP 实测 + 本地复现。所有结论均附第一手证据(实测数字或 `file:line`),无一条来自臆测。

---

## 0. 摘要

工程底盘已经相当强:PyPI + MCP registry 双发布、7 个 MCP 工具 + status 自诊断、CLI 全家桶、6 种参考文献格式提取(含 GB/T 7714)、DOI 注册表兜底、545 个测试、CI 七道门禁、合规红线(知网/万方黑名单、OA-only、polite pool)。**"能用"已经达成。**

但按"好用、可信"的落地标准实测,存在**两个 P0 级断层**:

1. **信任断层**:给出完全正确的引用(Attention Is All You Need + 正确 arXiv id + 2017),线上 MCP 返回 `metadata_mismatch`,匹配到 OpenAlex 的盗版镜像记录(year=2025、DOI `10.65215/*`),且 `suggested_citation` 会**把用户正确的引用改错**。一个核验工具在旗舰论文上翻车,比没有工具更糟。
2. **速度断层**:全包无任何并发,多源串行查询;MCP 路径单条 verify 约 15–30s,库路径默认配置下实测 **106.6s**。批量审计 30 条参考文献将是 10 分钟级——交互式 agent 场景不可用。

本企划书给出根因链(已闭合)、按 P0/P1/P2 分级的改进项(每项带验收标准)、三个里程碑,以及明确不做的事。

---

## 1. 现状盘点:已经做对的(保持,不动)

| 维度 | 现状 |
|---|---|
| 发布 | PyPI `citationguard` 0.1.1(trusted publishing workflow)+ MCP 官方 registry(`io.github.xiaweiyi713/citeguard`) |
| MCP 面 | 7 工具:status / verify / audit / claim-support / support-set / support-audit / counterevidence;status 含源健康、缓存、模型就绪自诊断 |
| CLI | verify / audit / support / support-audit / support-set / extract / counterevidence / status / cache,JSON 输出 + `next_action` 枚举 + 机器可读错误 |
| 提取 | Markdown / 纯文本 / BibTeX / `.bbl` / LaTeX 外链(`\bibliography` 等)/ `.docx` / **GB/T 7714 中文著录**,零依赖,行号可回溯 |
| 诚实性 | `not_found` ≠ 伪造;`outage_limited` / `sources_failed` / `source_failure_mode` 全链路透出;DOI 注册表兜底(开放源查不到但 DOI 已注册 → 明确说明) |
| 合规 | cnki/wanfang/cqvip 域名硬黑名单;远程证据默认关;OA-only 全文;polite mailto/UA |
| 质量基建 | 545 tests;CI:ruff + mypy(增量)+ 单测 + 核验 eval + support eval 质量门 + baseline 对比 + wheel/sdist 安装冒烟 + release 元数据门 |
| 文档 | cli_reference / mcp_setup / agent_output_contract / error_codes / security_compliance / support_labeling 等约 15 篇 |

---

## 2. 实测发现与根因(证据)

### 2.1 [P0] 信任断层:正确引用被判错,还给出有害"修正"

**现象**(线上 MCP `verify_citation_tool`,入参 title + `arxiv_id=1706.03762` + `year=2017`,全部正确):

```
verdict: metadata_mismatch   confidence: 0.88
canonical: openalex:W2626778328  year=2025  doi=10.65215/2q58a426
           (open_access.pdf_url = langtaosha.org.cn —— 盗版镜像记录)
suggested_citation: "... (2025). Attention Is All You Need."   ← 会把正确引用改错
sources_responded: ["openalex"]      ← 用户给的 arXiv id 没起作用
outage_limited: false, source_failure_mode: "none"  ← 系统自认一切正常
```

**复现**(本地,同一代码路径):multi(openalex,crossref,arxiv)→ 同样误判;**arxiv 单源 → `verified`,year=2017,arxiv=1706.03762v7,完全正确**。问题锁定在多源聚合层。

**根因链(三个,全部已定位)**:

1. **标识符查询静默失败后无声降级**——[`arxiv.py:55-72`](../citeguard/retrieval/scholarly_clients/arxiv.py):`lookup` 先按 `id_list` 查,失败/空返回(`HTTPClient` 失败时返回 `""`,`_parse_entries("")` 返回 `[]`)就**静默落到标题搜索**;标题搜索也弱则返回 `None`,且因最后一个 HTTP 请求成功而不记任何失败。实测中 arXiv 既不在 `sources_responded` 也不在 `sources_failed`——**调用方给的权威标识符被无声丢弃,系统还报告"一切正常"**。
2. **"标识符优先"只是涌现性质,不是被强制的不变量**——[`resolve.py:57-115`](../citeguard/verification/resolve.py):`verification_match_score` 确实给 id 命中打 1.0 分,但前提是那条记录**能活着进入候选池**。arXiv 记录一丢,候选池里只剩 OpenAlex 的同名污染记录(标题分 0.7 + 作者 0.18 = 0.88 > STRONG_MATCH),`metadata_mismatch` 就这样产生。README 承诺的 "identifier-first: definitive" 在端到端层面并未兑现。
3. **污染记录无任何防御**:OpenAlex 存在被劫持/镜像的重复记录(本例:`10.65215/*` 前缀 DOI、正文托管在 langtaosha.org.cn、year=2025)。当前逻辑对"同名记录跨源年份冲突"没有降级处理,反而自信地输出 mismatch + 有害修正。

**附带发现的确定性 bug**——[`multi_source.py:96-105`](../citeguard/retrieval/scholarly_clients/multi_source.py):`_rank` 中 `0.20 * source_score` 直接使用 OpenAlex **未归一化的原始 relevance_score**(本例实测 `15329.672`),导致搜索排序几乎完全被单源原始分主导,标题相似度/完整度权重形同虚设。

### 2.2 [P0] 速度断层:全串行 + 库路径默认开启证据抓取

**实测数字**:

| 场景 | 耗时 |
|---|---|
| MCP status 单源探测(remote evidence 已关) | openalex 5.8s / crossref 3.6s / arxiv 4.1s |
| MCP 单条 verify(3 源串行 lookup+search) | 估 15–30s |
| 本地库路径 multi verify(factory 默认) | **106.6s** |
| 本地库路径 arxiv 单源 verify | 24.4s |
| 推算:audit 30 条参考文献 | 分钟~十分钟级 |

**根因**:

1. **全包零并发**:`grep -r "ThreadPool|concurrent.futures|asyncio" citeguard/` 结果为空。[`multi_source.py:37,53`](../citeguard/retrieval/scholarly_clients/multi_source.py) 的 search/lookup 都是 `for source in self.sources` 串行;`resolve` 还要 lookup + search 各跑一轮。
2. **库路径与 MCP 路径默认值劈叉**——[`factory.py:30`](../citeguard/retrieval/scholarly_clients/factory.py):`harvest_remote_evidence: bool = True` 是**库函数默认值**(每条搜索结果额外抓 2–3 个落地页;arXiv 每条抓 `html/` + `abs/`),而 MCP runtime 默认关闭。README 快速上手里的库示例代码,用户一跑就是 100 秒级——第一印象即劝退。

### 2.3 [P1] 工程健康观察

| # | 观察 | 证据 |
|---|---|---|
| a | 巨型模块:`support.py` **2273 行 / 74 个顶层符号**、`support_eval.py` **2857 行**、`cli.py` 1174、`runtime.py` 1055、`mcp/server.py` 970 | `wc -l` / `grep -c "^def\|^class"` |
| b | mypy typed-debt 白名单 **9 个模块**,恰含最核心的 cli / mcp.server / cache / extract / support_eval / support_backends | `pyproject.toml [[tool.mypy.overrides]]` |
| c | legacy 写作原型(orchestrator / planner / writer / benchmark,17 个文件)仍打进发布 wheel | `git ls-files citeguard/{orchestrator,planner,writer,benchmark}` |
| d | 硬编码语言规则内联:`_english_contradiction_pattern` / `_chinese_contradiction_pattern` / `_source_outage_safety_pattern` 等中英正则短语表散布在 support.py 内(意图正当——阻断"源故障证明伪造"类危险推理;形态是治理隐患:规则无独立清单、无反例配套、易随 eval 迭代无序增生) | `support.py:520-636` |
| e | MCP 工具面泄漏:`verify_citation_tool` 的参数含 `full_text` / `full_text_file` / `evidence_chunks`(支撑域参数混进存在性工具,徒增 agent 误用面) | 工具 schema 实测 |
| f | 会话文件未忽略:`.claude/`、`.mcp.json`、`.playwright-mcp/` 均为 untracked 噪音 | `git check-ignore` |

---

## 3. 改进方案

优先级定义:**P0 = 不修就谈不上"落地好用"**;P1 = 工程健康与可维护性;P2 = 增长与体验加分。工作量:S ≤ 半天,M ≈ 1–2 天,L ≥ 3 天。

### P0-1 标识符权威裁决(identifier authority)· M

- **问题**:§2.1 根因 1+2——调用方给了 DOI/arXiv id,却可能被静默丢弃,标题匹配结果冒充高置信裁决。
- **方案**:把"标识符优先"从涌现性质变成**强制不变量**:
  1. 候选带 arxiv_id → **直查 arXiv id_list**(带独立重试);带 DOI → 直查 Crossref works/DOI + 现有 DOI 注册表。此步与多源检索**分离**,结果单独标记 `identifier_lookup: hit | miss | failed`。
  2. `hit` → 该记录**必胜**(现有 1.0 分逻辑自然生效,因为记录保证在候选池)。
  3. `failed`(网络/超时)→ 裁决降级为 `outage_limited`,明说"权威标识符未能核验",**禁止**用标题匹配结果输出 `metadata_mismatch`。
  4. `miss`(id 真的查无)→ 才允许标题路径,且在 explanation 注明。
- **验收**:注入式测试(Fake 源模拟 arXiv 超时 + OpenAlex 污染记录):AIAYN 案例在任意单源故障下**永不**输出 mismatch——要么 verified,要么 outage_limited;线上真实 AIAYN 案例回归通过。

### P0-2 污染记录防御与跨源共识 · M

- **问题**:§2.1 根因 3——劫持/镜像记录赢得匹配并产出有害修正建议。
- **方案**:
  1. **年份共识降级**:多个强匹配候选(或跨源记录)对 year 分歧 > 1 → 裁决降为 `ambiguous`,列出候选,**不产出 suggested_citation**。
  2. **记录合理性启发**(计入排序,不做硬判):候选带 arxiv_id 时同名记录优先取带 arxiv_id 的;`cited_by_count` 极高但 year 极新(6583 引用的"2025 年论文")记 plausibility 惩罚;DOI 前缀维护一个小型灰名单(可配置,首批收录本例 `10.65215`)。
  3. `suggested_citation` 仅在"标识符命中 或 无任何跨源冲突"时产出。
- **验收**:污染记录 fixture 测试套(≥6 例:劫持镜像/再版/重索引);现有 545 测试零回归;"有害修正建议"在冲突场景下产出率为 0。

### P0-3 修复 `_rank` 归一化 bug · S

- **问题**:§2.1 附带发现,`0.20 * source_score` 用原始分(实测 15329)。
- **方案**:`source_score` 压缩到 0–1(如 `score/(score+k)` 或 min-max),或直接从 `_rank` 移除该项。
- **验收**:单测:构造 relevance_score=10000 的弱标题记录,不得排在强标题记录之前。

### P0-4 并发扇出 + 时间预算;统一证据抓取默认值 · M

- **问题**:§2.2 全部。
- **方案**:
  1. `MultiSourceMetadataSource` 的 search/lookup 用 `ThreadPoolExecutor` 跨源并发(**每源内部保持串行**,不破坏 polite pool 的 `min_interval`);总预算(默认 ~8s,可配 `CITEGUARD_SOURCE_BUDGET`)内先到先用,超时源按现有 failure 通道记录。
  2. `factory.py` 的 `harvest_remote_evidence` 默认改为 **False**,与 MCP runtime 对齐(证据抓取变成全链路显式 opt-in);CHANGELOG 记为行为变更。
  3. resolve 的 identifier 直查(P0-1)与标题检索也可并发。
- **验收**:冷缓存 verify P50 **≤ 5s**、P95 ≤ 10s;缓存命中 ≤ 0.5s;audit 30 条 ≤ 60s;polite 间隔仍受尊重(单源请求间隔不低于 min_interval)。

### P0-5 金标准 live-canary 回归 · S

- **问题**:本次误判由人工实测偶然发现;没有机制持续守住"旗舰案例不翻车"。
- **方案**:固化 10–15 条金标(AIAYN、OpenScholar、GB/T 7714 中文条目、已知伪造条目…),双形态:(a) fixture 离线版进 CI;(b) live 版每夜 GitHub Actions 跑真实源,漂移自动开 issue。
- **验收**:canary 工作流上线且首晚全绿;本次 AIAYN 案例进入金标。

### P1-6 巨型模块拆分 · M

- `support.py`(2273 行)拆为 `support/models.py`、`support/patterns.py`(语言规则)、`support/engine.py`(裁决)、`support/audit.py`;`support_eval.py`(2857 行)按 数据加载/指标/报告/门禁 拆分;`cli.py` 按子命令分模块。**纯移动,不改行为**,以 `git log --follow` 保历史。
- **验收**:单文件 ≤ ~800 行;545 测试零回归;公共 import 路径不变(转发导出)。

### P1-7 typed-debt 清零 · M

- mypy overrides 白名单 9 → 0,按 cache → extract → cli → mcp.server → support_eval → support_backends 顺序逐个摘除(与 P1-6 拆分同步做,事半功倍)。
- **验收**:`[[tool.mypy.overrides]] ignore_errors` 清单删空,CI mypy 全量通过。

### P1-8 语言规则治理(防 eval 过拟合)· M

- **问题**:§2.3-d。规则本身合理,但内联正则 + 无反例约束的形态,会随 eval 迭代无序增生,且无法审计"这条规则是为了通过哪个案例加的"。
- **方案**:规则外置为声明式表(YAML/JSON:pattern、语言、意图说明、来源案例 id、**必须附带的反例**);加载器统一执行;CI 增加规则-反例配对检查;support eval 建立 held-out 轮换制(新规则不得看 held-out 集)。
- **验收**:所有现存短语规则完成登记(含意图与反例);新增规则无反例即 CI 失败。

### P1-9 legacy 写作原型移出发布包 · S

- `orchestrator/ planner/ writer/ benchmark(写作部分)` 移至仓库根 `legacy/`(不进 wheel),或直接删除(git 历史仍在)。`scripts/run_agent.py`、`evaluate.py` 同步处理。
- **验收**:wheel 内只含核验域模块;包体积下降;`pip install citationguard && python -c "import citeguard"` 冒烟不变。

### P1-10 MCP 工具面卫生 + 杂项 · S

- `verify_citation_tool` 移除 `full_text` / `full_text_file` / `evidence_chunks` 参数(属支撑域);`.gitignore` 补 `.claude/`、`.mcp.json`、`.playwright-mcp/`;`docs/superpowers/` 历史设计文档统一加 archived 头(部分已加)。
- **验收**:工具 schema 与 `agent_output_contract.md` 一致;`git status` 干净。

### P1-11 批量审计并发 + 进度 · M

- `audit_citations` / support-audit 在 P0-4 的并发底座上按条目并发(跨条目复用同一 polite 限速器);CLI 加 `--jobs`;MCP 批量响应加 `progress`/分片说明(条目多时提示预计耗时)。
- **验收**:audit 100 条 ≤ 3 分钟;限速器审计日志显示未违反 min_interval。

### P2-12 可粘贴修正输出 · S

- `metadata_mismatch` 时在 `suggested_citation` 之外输出 `suggested_bibtex` 与 `suggested_gbt7714`(基于 canonical 记录格式化),agent/用户可直接替换原条目。

### P2-13 夜间 canary + 漂移告警 · S

- P0-5 的 live 版扩展:漂移时自动开 issue 并附 diff;README 挂 canary badge——把"诚实"变成可见的持续承诺。

### P2-14 分发增强 · M

- uvx/pipx 一键运行说明;Claude Code plugin(marketplace 形态,打包 skill + MCP 配置);Smithery / mcp.so 等目录收录;`server.json` 元数据随版本自动校验(已有 release gate,补充目录侧)。

### P2-15 文档与首体验 · S

- 基于 `error_codes.md` 写 troubleshooting 页(按"现象 → 原因 → 动作"组织);README 顶部 GIF(CLI 实录);"5 分钟接入 Claude Code"逐步截图页。

---

## 4. 里程碑

| 里程碑 | 内容 | 硬性验收指标 |
|---|---|---|
| **M1 · 信任与速度**(~1 周) | P0-1 … P0-5 | AIAYN 类金标 **0 误判**;单源故障注入下 0 错误 mismatch;冷 verify P50 ≤ 5s、缓存 ≤ 0.5s;audit 30 条 ≤ 60s;canary 上线 |
| **M2 · 工程健康**(~1–2 周) | P1-6 … P1-11 | mypy 白名单清零;单文件 ≤ 800 行;wheel 无 legacy;规则 100% 登记带反例;audit 100 条 ≤ 3 分钟 |
| **M3 · 增长**(机会性) | P2-12 … P2-15 | plugin 可一键装;canary badge 常绿;troubleshooting 上线 |

顺序说明:M1 必须最先——**速度和信任是 agent 场景的入场券**;M2 是 M1 改动能持续演进的保障;M3 依赖前两者的口碑基础。

## 5. 风险与明确不做

**风险**
- OpenAlex 污染记录形态多变,启发式无法穷举 → 兜底策略始终是**降级为 `ambiguous`**,绝不因规则失手而自信输出错误裁决(与项目"不冤枉"原则同构)。
- 并发可能冲击 polite pool → 设计为"跨源并发、源内串行 + min_interval 不变",并在验收中显式审计。
- 大重构(P1-6/7)可能引入回归 → 纯移动式拆分、转发导出保 import 兼容、545 测试 + eval 门禁全程护栏。

**明确不做**(维持既有红线)
- 不爬取知网/万方/维普等受限源;不绕过付费墙;远程全文继续默认关、OA-only。
- 不复活写作 agent 方向;不追求"断言伪造"——`not_found` 永远只是"无法核实"。
- 不为通过 eval 添加无反例约束的特判规则(P1-8 把这条变成 CI 强制)。

---

## 6. 附录:实测原始记录(2026-07-13)

```text
# MCP citeguard_status_tool (check_sources=true)
openalex  available  elapsed_ms=5756
crossref  available  elapsed_ms=3627
arxiv     available  elapsed_ms=4111
remote_evidence_enabled=false  http_retries=1  timeout=10s

# MCP verify_citation_tool(title=AIAYN, arxiv_id=1706.03762, year=2017)
verdict=metadata_mismatch conf=0.88
canonical=openalex:W2626778328 year=2025 doi=10.65215/2q58a426
sources_responded=[openalex]  outage_limited=false

# 本地复现(同代码路径)
[arxiv-only]                    verified          conf=0.82 elapsed=24.4s  year=2017 ✓
[multi openalex,crossref,arxiv] metadata_mismatch conf=0.70 elapsed=106.6s year=2025 ✗
```
