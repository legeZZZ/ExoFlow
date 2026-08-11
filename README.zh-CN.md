# ExoFlow

[English](README.md)

**基于确定性、类型化、可审计状态机的多智能体软件工程编排框架。**

ExoFlow 通过 CAS 门禁保护的状态机协调 9 个专业 AI Agent，完成事故分诊、根因定位、
验证补丁执行和运维知识蒸馏，全程维护可密码学验证的事件链。

## 目录

- [为什么选择 ExoFlow？](#为什么选择-exoflow)
- [架构](#架构)
- [核心组件](#核心组件)
  - [状态机](#状态机)
  - [Native MCP 服务](#native-mcp-服务)
  - [技能蒸馏](#技能蒸馏)
  - [Agent 身份与授权](#agent-身份与授权)
  - [端口抽象层](#端口抽象层)
- [赛道说明](#赛道说明)
  - [赛道一 — CodeOps 控制塔](#赛道一--codeops-控制塔)
  - [赛道二 — 因果增长归因](#赛道二--因果增长归因)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [运行要求](#运行要求)
- [许可证](#许可证)

## 为什么选择 ExoFlow？

大多数多 Agent 框架让 LLM 通过非结构化提示驱动控制流。ExoFlow 反转了这一范式：
**状态机是唯一事实源**，Agent 必须在类型化、可验证的边界内运行。

| 能力 | ExoFlow 的实现方式 |
|---|---|
| **状态完整性** | CAS 门禁迁移；任何 Agent 都不能跳过或伪造状态 |
| **授权控制** | 按角色划分状态所有权 — 验证者不能批准自己的补丁 |
| **可审计性** | SQLite WAL 事件存储记录每次迁移、产出物和审批 |
| **故障隔离** | 相同失败签名重复 3 次后熔断，强制升级人工处理 |
| **知识留存** | 从已关闭任务轨迹中执行 3 阶段技能蒸馏流水线 |
| **因果安全** | 数据为观测性或不足时，因果门禁阻止断言输出 |
| **零依赖** | 纯 Python 标准库；支持离线安装，无需网络 |
| **供应商中立** | 15 个抽象端口，本地/云端 Provider 可替换 |

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Native MCP 服务                          │
│  12 工具 · CAS 迁移 · 产出物门禁 · 人工审批                  │
│  副作用账本 · 证据包校验                                     │
└─────────────────────┬───────────────────────────────────────┘
                      │  类型化事件 + 产出物
┌─────────────────────▼───────────────────────────────────────┐
│                    状态机                                     │
│  赛道一：21 状态、25 迁移规则                                 │
│  赛道二：19 状态、21 迁移规则                                 │
│  产出物生命周期 × 9 种 · 角色所有权 × 10 个                   │
│  失败熔断 × 阈值 3 · 迁移前置条件                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────┼───────────────────────────────────────┐
│                     │                   │                   │
│  ┌──────────┐  ┌────▼─────┐  ┌──────────▼──────┐          │
│  │  Intake   │  │  Triage   │  │  Repo Analyst   │  ...     │
│  │  Worker   │  │  Worker   │  │  Worker         │          │
│  └──────────┘  └───────────┘  └─────────────────┘          │
│                                                              │
│  9 个专业 Agent · 类型化 SKILL 清单 · 评估门禁               │
└──────────────────────────────────────────────────────────────┘
```

## 核心组件

### 状态机

状态机（`state_machine_def.py`）是唯一事实源。所有消费者——本地控制平面、Native
SQLite 权威服务、Worker 包预言机——都从此文件派生。一致性测试将三者钉在一起。

**赛道一标准路径（19 步代码修复流水线）：**

```
RECEIVED → FUSED → TRIAGED → BOOTSTRAPPED → LOCATED → PLANNED
→ AWAITING_APPROVAL → PATCHED → VERIFYING → RELEASE_READY
→ POSTMORTEM → SKILL_DISTILLING → CLOSED
```

**只读分析分支（不产生代码变更）：**

```
LOCATED → READONLY_VERIFYING → READONLY_VERIFIED → EVIDENCE_PACKED → CLOSED
```

关键门禁：
- **迁移前置条件** — 如 `PATCHED → VERIFYING` 要求存在 `PatchBundle`；
  `VERIFYING → RELEASE_READY` 要求当前版本下 `VerificationReport` 带
  `verdict=PASS`。
- **产出物状态门禁** — `VerificationReport` 只能在 `VERIFYING` 或
  `READONLY_VERIFYING` 状态发布，其他状态下写入会被拒绝。
- **失败签名熔断器** — 同一 `failure_signature` 出现 3 次后禁止重新进入验证态，
  强制升级 `NEEDS_HUMAN`。
- **崩溃恢复** — 通过 `RECOVERING` 状态恢复，保持版本号不变，Agent 从断点精确续跑。

### Native MCP 服务

基于 SQLite WAL 模式的事务型单写状态权威服务（`native_mcp.py`），通过 streamable
HTTP（端口 8780）暴露 **12 个 MCP 工具**。

| 工具 | 说明 |
|---|---|
| `task_create` | 幂等任务创建（仅 Leader） |
| `task_get` | 读取权威任务状态 |
| `state_transition` | CAS 门禁迁移，校验 Actor 授权 |
| `state_describe` | Agent 工作站契约——可用输入、可执行迁移、退出条件、熔断状态 |
| `artifact_put` | 在精确状态版本发布类型化产出物 |
| `approval_request` | 创建范围绑定的人工审批 |
| `approval_decide` | 记录 Matrix 背书的审批决策 |
| `approval_status` | 读取审批状态 |
| `evidence_pack` | 导出完整事件链，可选校验回放 |
| `side_effect_intent` | 执行前查询账本——记录外部副作用意图 |
| `side_effect_result` | 记录 EXECUTED/FAILED/ROLLED_BACK 结果 |
| `side_effect_list` | 恢复重读——查询副作用账本避免重复执行 |

每次工具调用均通过 Bearer Token 进行 **Actor 身份门禁**。权威服务独立校验：
- Actor 是否有权进入目标状态
- 状态版本是否匹配（CAS — 拒绝脏写）
- 必需产出物是否存在并通过裁决检查
- 审批范围是否绑定且未过期
- 失败签名熔断器是否触发

`evidence_pack(validate=true)` 完整回放事件链并重新计算所有摘要——不信任导出包中的任何字段。

### 技能蒸馏

基于 Trace2Skill 模式（arXiv:2603.25158）。已关闭的成功任务进入 3 阶段流水线
（`skill_distill.py`）：

```
阶段 A：轨迹池
  └─ 证据包入库，按领域/裁决/失败签名打标签

阶段 B：双视角分析
  ├─ 成功模式分析师提出补丁（哪些做对了）
  └─ 失败防护分析师提出补丁（哪些出错了 + 防御措施）

阶段 C：合并、门禁与发布
  ├─ 程序化冲突检测 + 格式校验
  ├─ 敏感信息与许可证扫描
  ├─ 忠实度 / 泛化性 / 反例检查
  ├─ 人工审查闸口
  └─ 版本化发布 + 回滚支持
```

当前实现保持阶段 B 为确定性模式（启发式、可回放）；LLM 驱动的分析师后续通过同一
`propose_patches` 接口接入，无需修改流水线。

### Agent 身份与授权

每个 Agent 具有类型化身份，明确定义其能力边界：

| Agent | 拥有状态 | 产出物 |
|---|---|---|
| `codeops-intake` | `FUSED` | `IssueCluster` |
| `codeops-triage` | `TRIAGED` | `RiskAssessment` |
| `codeops-env-bootstrap` | `BOOTSTRAPPED` | `EnvironmentSnapshot` |
| `codeops-repo-analyst` | `LOCATED` | `RootCauseHypotheses` |
| `codeops-plan` | `PLANNED`, `AWAITING_APPROVAL` | `ChangePlan` |
| `codeops-executor` | `PATCHED`, `RECOVERING` | `PatchBundle` |
| `codeops-verifier` | `VERIFYING`, `RELEASE_READY`, `READONLY_VERIFYING`, `READONLY_VERIFIED`, `NEEDS_HUMAN` | `VerificationReport` |
| `codeops-postmortem` | `POSTMORTEM`, `SKILL_DISTILLING`, `CLOSED` | `Postmortem`, `SkillCandidate` |
| `codeops-lead` | `RECOVERING`, `NEEDS_HUMAN`, `EVIDENCE_PACKED`, `CLOSED` | —（仅协调） |

核心原则：**验证者不能批准自己的补丁**。执行者发布 `PatchBundle`，但验证在独立
工作区运行（含隐藏测试），只有验证者能发出 `VerificationReport`。

### 端口抽象层

15 个抽象端口，分布于 4 个平面，每个端口支持本地/云端 Provider 替换：

| 平面 | 端口 |
|---|---|
| **运行时** | `CodeExecutionPort`, `WorkspacePort`, `StateCheckpointPort`, `LeaseRecoveryPort`, `EventBusPort` |
| **工具与证据** | `ArtifactEvidencePort`, `KnowledgeMemoryPort`, `SCMPort`, `CIPort` |
| **治理** | `PolicyGuardPort`, `ApprovalHITLPort`, `SecretPort`, `ConfigRegistryPort` |
| **模型与可观测性** | `ModelGatewayPort`, `ObservabilityPort` |

`CIPort` 有特殊语义：验证运行始终独立于代码执行器，补丁 Agent 无法通过自报"通过"
使自己的变更获得权威性。

## 赛道说明

### 赛道一 — CodeOps 控制塔

端到端事故修复流水线，21 个状态，强制人工审批：

1. **录入** — 多源聚合去重，产出 `IssueCluster`
2. **分诊** — 风险定级，只读/修复分支决策
3. **环境快照** — 只读采集（不修改任何文件）
4. **根因定位** — 假设须锚定到具体代码位置
5. **方案规划** — 产出 `ChangePlan`，发起正式审批
6. **审批闸口** — 范围绑定的人工审批，Matrix 背书
7. **补丁执行** — 仅限审批范围内的文件修改
8. **独立验证** — 独立工作区，公开+隐藏测试套件
9. **发布确认** — 验证 PASS 确认
10. **复盘归档** — 产出 `SkillCandidate`
11. **技能蒸馏** — 须存在已批准候选或显式 `NO_DISTILL_CONFIRMED`

演示用例（`run_demo.py`）针对一个真实 Bug：`retry_guard.py` 的超时预算缺陷。
第一轮补丁修复了超时但未通过隐藏验证（`REGRESSION_TIMEOUT_GUARD`）；第二轮补丁
添加了幂等重试并通过。

### 赛道二 — 因果增长归因

保险业务分析，3 种因果就绪场景：

| 场景 | 数据类型 | 结果 | 行为 |
|---|---|---|---|
| **A** | 观测性数据 | `DESCRIPTIVE_ONLY` | 展示共变关系与分解，禁止因果动词 |
| **B** | 缺失实验元数据 | `DATA_INSUFFICIENT` | 拒绝闭合，列举缺失字段与补数路径 |
| **C** | 随机化实验 | `CAUSAL_READY` | ITT 估计 + 95% CI + 护栏 + 监控方案 |

进程隔离的预言机基准测试衡量因果门禁准确率、错误因果断言率、拒绝召回率、效应
误差和 95% CI 覆盖率——种子、潜在结果和预言机不暴露给被测 Agent。

**注意**：这是因果模拟器的安全性与可复现性基准测试，并非真实保险业务提升的证据。
UCI Bank Marketing 数据集适配器（`track2_real_data.py`）锁定 SHA-256
`94a5cb4b7d461dab12f7f6123723054911fbdd28d84a2c4ec92378af019be686`，因数据无
随机化处理分配，对因果声明执行拒绝闭合。

## 快速开始

```bash
cd /path/to/exoflow

# 安装（Python 标准库外无依赖）
python3 -m pip install . --no-deps --no-build-isolation

# 运行双赛道演示
PYTHONPATH=src python3 run_demo.py

# 运行全部测试
PYTHONPATH=src python3 -m unittest discover -s tests -v

# CLI 入口
python3 -m goai_control_tower --track track1 \
  --track1-input src/goai_control_tower/samples/track1/input.json

python3 -m goai_control_tower --track track2 --track2-benchmark --track2-benchmark-seeds 3

# 启动 Native MCP 状态权威服务（streamable HTTP，端口 8780）
CODEOPS_STATE_DATABASE=runtime_data/state.sqlite3 \
  python3 -m goai_control_tower.native_mcp --identity-file path/to/identities.json
```

## 项目结构

```text
ExoFlow/
├── src/goai_control_tower/
│   ├── state_machine_def.py     ← 30+ 状态、9 种产出物、角色所有权
│   ├── native_mcp.py            ← 12 工具 MCP 服务、SQLite WAL 权威
│   ├── skill_distill.py         ← 3 阶段轨迹蒸馏流水线
│   ├── foundation.py            ← 控制平面、15 端口清单、CI Provider
│   ├── track1.py                ← 赛道一执行：夹具 + 回放 Provider
│   ├── track2.py                ← 赛道二执行：3 种因果场景
│   ├── track2_analysis.py       ← 固定序对数链分解
│   ├── track2_benchmark.py      ← 进程隔离预言机基准
│   ├── track2_datasets.py       ← 来源感知数据集目录
│   ├── track2_real_data.py      ← UCI Bank Marketing 适配器（SHA-256 锁定）
│   ├── track2_worker.py         ← Worker 侧因果计算
│   ├── configuration.py         ← JSON 配置加载
│   ├── cli.py                   ← CLI 入口
│   └── samples/                 ← 输入输出契约夹具
├── packages/                    ← 9 个 Worker SKILL.md 清单 + team-leader 编排
│   ├── team-leader/             ← Worker 状态机预言机（一致性测试钉死）
│   └── skills/                  ← 11 个专业技能，每个含评估门禁
│       ├── incident-memory/     ← 跨任务记忆搜索
│       ├── issue-fusion/        ← 多源问题去重
│       ├── judge-calibrator/    ← 评估一致性基准
│       ├── policy-check/        ← 策略合规检查
│       ├── repo-map/            ← 代码库结构分析
│       ├── resume-guard/        ← 恢复/续跑安全
│       ├── risk-guard/          ← 风险评估与打分
│       ├── root-cause-probe/    ← 根因定位
│       ├── runbook-rag/         ← Runbook 检索增强生成
│       ├── safe-patch-exec/     ← 审批范围内补丁执行
│       ├── skill-distiller/     ← 轨迹到技能蒸馏
│       └── verify-and-replay/   ← 验证与确定性回放
├── tests/                       ← 单元测试套件
├── run_demo.py                  ← 双赛道夹具演示
├── pyproject.toml
└── LICENSE
```

## 运行要求

- **Python** ≥ 3.9
- **无运行时依赖** — 仅标准库
- `opencode` CLI 为可选项，仅实时执行路径需要（夹具/确定性模式不依赖）

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
