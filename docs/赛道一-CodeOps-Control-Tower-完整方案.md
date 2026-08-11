# 赛道一：CodeOps Control Tower

## 以 AgentTeams 为原生控制平面的软件研发 Agent Infra

版本：v1.0  
方案状态：目标架构完整，第一条本地纵向切片已闭环，真实 AgentTeams 原生链路已部分验证  
更新时间：2026-08-08

---

## 1. 一页结论

### 1.1 我们要解决的问题

现有 Coding Agent 通常擅长“读代码、写代码、运行命令”，但在真实研发环境中，最难的并不是生成一段代码，而是：

- 多来源问题如何归并，避免重复处理；
- 影响面和风险如何判断；
- 环境是否足以复现问题；
- 根因分析如何区别于猜测；
- 变更范围如何被限制；
- 谁批准了什么；
- Executor 是否越权；
- 测试通过结论是否来自独立证据；
- 中途故障能否恢复；
- 一次任务如何沉淀为下一次可复用的 Skill。

CodeOps Control Tower 将这些问题组织为一个由 AgentTeams 原生承载的、可审计、可恢复、可插拔的软件研发闭环。

### 1.2 核心定位

**CodeOps Control Tower 不是一个更大的 Coding Prompt，而是一个以 AgentTeams 为控制平面的研发基础设施。**

它由五层组成：

```text
AgentTeams Control Plane
  Identity / Team / Worker / Matrix / Shared Context / Runtime Lifecycle

CodeOps Agent Organization
  Intake / Triage / EnvBootstrap / RepoAnalyst
  Plan / Executor / Verifier / Postmortem

Skill Capability Layer
  12 个可版本化、可测试、可灰度和可回滚的 Skill

Middleware Plugin Fabric
  15 类 Port，连接本地、云端和混合 Provider

Evidence and Evaluation Layer
  State / Artifact / Trace / Approval / Evidence Pack / Conformance Kit
```

### 1.3 三个真正的差异化机制

1. **Trace-to-Skill 蒸馏闭环**  
   任务轨迹不是日志终点，而是下一代 Skill 的候选来源。Skill 只有通过保真、泛化、反例、安全和人工审核，才允许灰度发布。

2. **独立验证门**  
   Executor 只能提交 `PatchBundle`，不能自报“测试通过”。Verifier 使用独立工作区和独立 CIPort，读取 Patch、规范和独立运行结果，输出 `VerificationReport`。

3. **断点续跑韧性层**  
   通过 `state_version`、CAS、幂等键、checkpoint、lease、fencing、watchdog 和人工恢复阶梯，处理网络分区、工具挂死、重复副作用和运行时中断。

### 1.4 当前真实进度

| 范围 | 当前结果 |
|---|---|
| 本地 CodeOps 纵向切片 | 已闭环，`T1-codeops-demo = CLOSED` |
| 本地测试 | `31/31` 通过 |
| AgentTeams 安装 | `v1.2.0-beta.1` 已真实安装 |
| AgentTeams Worker | 9 个真实 Worker 已运行 |
| CodeOps Team | 已创建并绑定，Worker 就绪 |
| Native MCP | `codeops-state` 已健康，Worker `mcporter list` 已确认 |
| Native 真实任务 | 已创建、已产生 6 个 Artifact，当前 `LOCATED v4` |
| Native 严格验收 | 尚未完成 `RELEASE_READY`、Evidence Pack 导出和完成标记 |

严谨结论：**本地实现闭环已完成；真实 AgentTeams 主环境已打通；真实 AgentTeams 严格端到端验收仍差一条只读验证分支和一次新的完整回放。**

---

## 2. 参赛叙事

### 2.1 一句话叙事

**让 AgentTeams 不只是“能创建 Worker”，而是能把一次软件问题变成一个有证据、有边界、有审批、有独立验证和可复用经验的研发事件。**

### 2.2 评委应该看到的变化

普通 Agent 演示：

```text
输入问题 -> Agent 修改代码 -> 测试通过 -> 输出答案
```

CodeOps Control Tower 演示：

```text
输入问题
  -> Manager 创建任务
  -> Team Leader 通过 AgentTeams 调度 Worker
  -> Worker 以结构化 Artifact 协作
  -> Native MCP 以 CAS 写入状态
  -> 高风险动作触发 Matrix Human Approval
  -> Executor 只执行批准范围
  -> Verifier 在独立上下文验证
  -> 失败自动形成 Failure Signature
  -> 成功/失败/转人工进入 Postmortem
  -> SkillCandidate 经过评测后灰度发布
```

### 2.3 作品边界

本方案不承诺：

- 任意仓库都能自动修复；
- 任意测试通过结论都可信；
- 任意 Agent 都能自由执行命令；
- 云端 Provider 尚未实测却已经等价于本地 Provider；
- 论文设想已经全部工程化；
- AgentTeams 官方不存在的状态机 API 已经存在。

本方案承诺：

- 每个阶段有明确责任边界；
- 每个变更有批准范围；
- 每个状态有版本和事件；
- 每个 Artifact 有生产者和证据引用；
- 每个验证结论来自独立验证；
- 所有失败都能被结构化记录；
- 未满足条件时系统拒绝宣布成功。

---

## 3. AgentTeams 深度适配原则

### 3.1 AgentTeams 负责什么

AgentTeams 作为平台控制平面，负责：

- Manager、Team、Worker、Human 资源；
- Worker Identity 和生命周期；
- Team 拓扑和 Matrix 房间；
- Worker runtime 选择；
- 共享工作区和 Artifact 传输；
- Worker 之间的任务协作；
- 平台级 Trace、消息和运行状态；
- 人工成员和人工门禁的承载。

### 3.2 CodeOps 领域层负责什么

CodeOps 领域层负责：

- 研发任务状态语义；
- Artifact Schema；
- 状态迁移前置条件；
- 变更批准范围；
- 验证证据和 Failure Signature；
- Evidence Pack；
- 领域评测和 Conformance Kit。

### 3.3 为什么需要 Native MCP

AgentTeams 当前没有可直接复用的、足够严格的领域状态机原语；团队派单主要依赖 Manager/Leader 的语义编排，Worker 匹配也不是严格的结构化过滤。因此不能把“模型说已经派单”当作状态事实。

Native `codeops-state` MCP 作为领域状态权威，提供：

- Actor 身份绑定；
- `task_create`；
- `task_get`；
- 带 `expected_state_version` 的 `state_transition`；
- Artifact 写入；
- Matrix 证据绑定的 Approval；
- Evidence Pack 导出。

这不是另建隐藏编排器。正确边界是：

```text
AgentTeams = 平台控制平面与多 Agent 运行时
codeops-state MCP = CodeOps 领域状态与证据权威
Team Leader Skill = 领域编排策略
Python runtime = 本地一致性 Harness 和评测器
```

### 3.4 AgentTeams 机制映射

| AgentTeams 机制 | CodeOps 适配 |
|---|---|
| Manager CR | 创建和管理研发团队任务，负责平台级协调 |
| Team CR | 表达 `codeops-control-tower` 团队拓扑 |
| Worker CR | 注册 9 个 Worker 身份和运行时 |
| Worker `identity/soul/agents` | 绑定角色、边界、协作规则和职责 |
| Matrix Room | Worker 协作、任务回报和 Human Approval |
| shared Artifact / MinIO | 传输大文件、工作区和不可变证据 |
| `mcporter` | Worker 调用 CodeOps 状态 MCP |
| Higress | 模型和凭证隔离 |
| Hermes runtime | 受控代码执行 Worker |
| OpenClaw runtime | Leader、分析、计划和验证 Worker |
| TeamHarness | 作为实验性平台能力适配，不能假设其已稳定 |

### 3.5 共享对象存储和状态权威的边界

共享对象存储适合：

- 源码快照；
- Patch；
- 测试日志；
- 运行产物；
- 大型 Evidence；
- Worker 间共享上下文。

共享对象存储不适合单独承担：

- 严格 CAS；
- 单写者状态转换；
- 防止重复审批；
- 防止旧 Worker 覆盖新状态；
- Matrix 决策和状态版本的原子绑定。

因此 `shared/tasks/<task_id>/` 用于 Artifact 和工作上下文，Native MCP SQLite 用于事务状态、版本和审批事实。

---

## 4. 系统架构

### 4.1 总体架构

```text
                         Human Reviewer
                              |
                         Matrix / HITL
                              |
                    +---------v----------+
                    | AgentTeams Manager |
                    +---------+----------+
                              |
                    +---------v----------+
                    | CodeOps Team Leader|
                    | Leader Skill       |
                    +---------+----------+
                              |
       +----------------------+----------------------+
       |                      |                      |
   Intake/Triage         Repo/Plan              Executor/Verifier
       |                      |                      |
       +----------------------+----------------------+
                              |
                    +---------v----------+
                    | Native State MCP  |
                    | CAS / Artifact    |
                    | Approval / Trace  |
                    +---------+----------+
                              |
            +-----------------+-----------------+
            |                                   |
        SQLite Authority                    Shared Storage
        state_version                       MinIO / OSS
```

### 4.2 层次职责

#### L1：Platform Control Plane

AgentTeams 负责 Manager、Team、Worker、Human、Matrix、runtime 和平台生命周期。

#### L2：Agent Organization

8 个领域 Agent 根据状态、风险、证据和任务类型条件激活，不要求每个任务固定经过所有 Agent。

#### L3：Skill Capability

Skill 是版本化能力包，具备 Manifest、Schema、Policy、Eval、版本和回滚信息。

#### L4：Middleware Plugin Fabric

Port 屏蔽本地、云端和混合基础设施差异，Provider 负责具体实现。

#### L5：Evidence and Evaluation

把事件、Artifact、测试、审批、失败和恢复结果统一为可核对证据。

---

## 5. 8 个 Agent 设计

### 5.1 统一 Identity 合同

每个 Agent Identity 必须包含：

```text
agent_id
role
purpose
allowed_states
input_schema
output_schema
allowed_skills
allowed_tools
read_scope
write_scope
risk_level
budget
timeout
retry_policy
escalation_policy
trace_obligations
acceptance_metrics
```

每个 Agent 必须明确：

- 能做什么；
- 禁止做什么；
- 当前状态能否执行；
- 能调用哪些 Skill；
- 能读写哪些 Artifact；
- 是否可以推进状态；
- 失败后重试还是转人工；
- 如何留下证据。

### 5.2 Intake Agent

职责：

- 接收 Issue、告警、用户反馈、CI 失败和历史任务；
- 归并重复问题；
- 保留原始来源和时间；
- 标注信息缺口；
- 生成 `IssueCluster`。

不能：

- 判断最终根因；
- 生成 Patch；
- 修改仓库；
- 代替 Triage 做风险授权。

调用 Skill：

- `issue-fusion`
- `incident-memory`
- `policy-check`

验收指标：

- 聚类准确率；
- 重复任务减少率；
- 原始证据保留率；
- 输入缺口识别率。

### 5.3 Triage Agent

职责：

- 评估影响范围；
- 识别生产、灰度、测试环境；
- 判断风险等级；
- 决定是否需要人工审批；
- 生成 `RiskAssessment`。

不能：

- 越过 Policy 授权；
- 直接修改代码；
- 将高风险任务自动降级为低风险。

调用 Skill：

- `risk-guard`
- `policy-check`
- `runbook-rag`
- `incident-memory`

验收指标：

- 风险分级准确率；
- 高风险漏报率；
- 错误自动执行率；
- 升级路径完整率。

### 5.4 EnvBootstrap Agent

职责：

- 创建隔离工作区；
- 记录依赖、镜像、工具和服务版本；
- 执行最小基线命令；
- 判断问题是否能够稳定复现；
- 生成 `EnvironmentSnapshot`。

不能：

- 读取隐藏测试；
- 修改 Executor 工作区之外的内容；
- 在宿主机直接执行高副作用命令；
- 将“不具备复现条件”伪装为代码根因。

调用 Skill：

- `repo-map`
- `runbook-rag`
- `resume-guard`

验收指标：

- 环境准备成功率；
- 基线复现率；
- 依赖版本记录完整率；
- 环境问题识别率。

### 5.5 RepoAnalyst Agent

职责：

- 建立仓库地图；
- 定位相关模块和调用链；
- 生成多个可证伪根因假设；
- 同时记录支持证据和反对证据；
- 生成 `RootCauseHypotheses`。

不能：

- 在证据不足时输出确定性根因；
- 生成可直接执行的 Patch；
- 修改仓库；
- 把测试通过结果当作根因证明。

调用 Skill：

- `repo-map`
- `root-cause-probe`
- `runbook-rag`
- `incident-memory`

验收指标：

- 根因 Top-k 命中率；
- 证据引用完整率；
- 假设可证伪率；
- 错误确定性结论率。

### 5.6 Plan Agent

职责：

- 把根因假设转为最小变更计划；
- 指定变更文件范围；
- 指定公开、隐藏、历史和变异测试；
- 指定回滚路径；
- 指定资源预算和预计副作用；
- 生成 `ChangePlan`；
- 请求范围绑定的 Human Approval。

不能：

- 直接执行修改；
- 扩大批准文件范围；
- 将计划本身视为授权；
- 绕过高风险人工门禁。

调用 Skill：

- `root-cause-probe`
- `risk-guard`
- `policy-check`
- `runbook-rag`

验收指标：

- 一次批准率；
- 计划与实际 diff 的一致率；
- 回滚路径完整率；
- 测试覆盖率；
- 越权计划拦截率。

### 5.7 Executor Agent

职责：

- 读取批准状态；
- 在隔离工作区执行最小变更；
- 记录命令、退出码、diff digest 和副作用；
- 生成 `PatchBundle`；
- 将任务推进到 `PATCHED`。

不能：

- 扩大批准范围；
- 修改批准范围外文件；
- 修改验证标准；
- 输出“验证通过”结论；
- 用自报测试结果替代 Verifier。

调用 Skill：

- `safe-patch-exec`
- `resume-guard`
- `policy-check`
- `risk-guard`

运行时：

- 首选真实 Hermes runtime；
- 本地第一切片使用 `fixture-local`；
- opencode 作为可插拔 `CodeExecutionPort` Provider；
- `GOAI_OPENCODE_LIVE=1` 才允许进入 live CLI 路径。

验收指标：

- 批准范围内变更率；
- 越权拦截率；
- diff 可复现率；
- 副作用记录完整率；
- Executor 自报验证结论为零。

### 5.8 Verifier Agent

职责：

- 在独立验证上下文中读取 Patch、规范和运行证据；
- CAS 推进 `PATCHED -> VERIFYING`；
- 调用独立 `CIPort`；
- 运行公开、隐藏、历史和变异测试；
- 生成 `VerificationReport`；
- 仅在独立验证通过后推进 `RELEASE_READY`。

不能：

- 依赖 Executor 的“测试通过”字段；
- 修改代码；
- 修改测试标准；
- 读取不应暴露的隐藏真值；
- 将缺少证据解释为成功。

调用 Skill：

- `verify-and-replay`
- `judge-calibrator`
- `policy-check`
- `resume-guard`

验收指标：

- 独立验证覆盖率；
- 隐藏回归检出率；
- 误放行率；
- Failure Signature 结构化率；
- 同一失败签名的恢复成功率。

### 5.9 Postmortem Agent

职责：

- 处理成功、失败和转人工任务；
- 归纳触发条件、执行步骤和边界；
- 生成 `Postmortem`；
- 生成 `SkillCandidate`；
- 触发 Skill 评测和人工审核。

不能：

- 直接发布新 Skill；
- 跳过敏感信息扫描；
- 跳过许可证检查；
- 只保留成功轨迹而忽略失败轨迹；
- 把一次偶然成功写成通用规则。

调用 Skill：

- `incident-memory`
- `skill-distiller`
- `judge-calibrator`

验收指标：

- 复盘完整率；
- 成功/失败/转人工覆盖率；
- SkillCandidate 保真率；
- 相似任务泛化率；
- 反例拒绝率；
- 人工回滚可用率。

---

## 6. 12 个 Skill 设计

### 6.1 Skill 统一包结构

```text
skill.yaml
input.schema.json
output.schema.json
SKILL.md
executor/
policy/
evals/
examples/
CHANGELOG.md
README.md
```

Manifest 至少包含：

```text
skill_id
version
category
compatible_agents
input_schema
output_schema
preconditions
required_tools
required_ports
permissions
budget
timeout
retry_policy
idempotency_policy
fallback
promotion_threshold
rollback_condition
```

### 6.2 诊断类 Skill

#### `issue-fusion`

将多个问题源按症状、时间、服务、错误签名和证据相似度归并为 `IssueCluster`。必须保留原始来源，不允许为了聚类而删除冲突证据。

#### `repo-map`

建立仓库目录、入口、依赖、测试、构建和运行边界。输出结构化仓库地图，而不是一段无法复用的自然语言总结。

#### `root-cause-probe`

根据仓库地图、运行日志和规范生成多个根因假设；每个假设必须有支持证据、反对证据、验证方式和置信度。

### 6.3 知识类 Skill

#### `runbook-rag`

检索历史 Runbook、故障手册和发布规范。所有检索结果必须带版本、来源、有效期和许可证信息。

#### `incident-memory`

按错误签名、服务、依赖、时间窗口和解决结果查询历史事件。历史记忆只能作为候选证据，不能直接替代当前任务验证。

#### `skill-distiller`

从 Evidence Pack 生成 `SkillCandidate`，保留触发条件、操作步骤、输入输出、边界、反例和轨迹引用。

### 6.4 治理类 Skill

#### `risk-guard`

对生产影响、数据敏感性、命令副作用、变更范围和失败成本进行确定性风险评级。

#### `policy-check`

检查命令、路径、工具、依赖、网络和审批是否符合策略。策略检查失败必须失败关闭。

#### `judge-calibrator`

校准 Agent 评估和 Verifier 报告，检测过度自信、证据不足、结论漂移和评分偏差。

### 6.5 执行类 Skill

#### `safe-patch-exec`

读取批准范围，执行最小 diff，记录变更文件、命令 digest、退出码、工作区和副作用。

#### `verify-and-replay`

在独立上下文执行验证，支持公开、隐藏、历史、变异和回放测试，并形成结构化 Failure Signature。

#### `resume-guard`

保护断点续跑：读取 checkpoint、校验 `state_version`、检查悬空 tool call、执行 query-before-create，并避免重复副作用。

### 6.6 Skill 晋升

任何 SkillCandidate 进入生产前必须通过：

1. 原任务保真；
2. 相似任务泛化；
3. 不应触发的反例；
4. 许可证和敏感信息扫描；
5. JudgeCalibrator；
6. Human Reviewer；
7. 灰度发布；
8. 回滚演示。

---

## 7. Middleware Plugin Fabric

### 7.1 15 类 Port

| Plane | Port | 能力 |
|---|---|---|
| Runtime | `CodeExecutionPort` | `execute / inspect / cancel` |
| Runtime | `WorkspacePort` | `create / snapshot / restore / destroy` |
| Runtime | `StateCheckpointPort` | `save / load / compare-and-swap` |
| Runtime | `LeaseRecoveryPort` | `acquire / renew / fence / release` |
| Runtime | `EventBusPort` | `publish / subscribe / ack` |
| Tool/Evidence | `ArtifactEvidencePort` | `put / get / list / digest` |
| Tool/Evidence | `KnowledgeMemoryPort` | `search / upsert / delete` |
| Tool/Evidence | `SCMPort` | `diff / branch / commit / revert` |
| Tool/Evidence | `CIPort` | `run / status / logs / cancel` |
| Governance | `PolicyGuardPort` | `check / explain / audit` |
| Governance | `ApprovalHITLPort` | `request / approve / reject / resume` |
| Governance | `SecretPort` | `resolve / rotate / audit` |
| Governance | `ConfigRegistryPort` | `get / watch / version` |
| Model | `ModelGatewayPort` | `complete / embed / health` |
| Observability | `ObservabilityPort` | `trace / metric / log / export` |

### 7.2 Provider 设计

每个 Port 支持：

- local Provider；
- cloud Provider；
- hybrid Provider；
- fallback Provider；
- conformance test；
- healthcheck；
- timeout；
- retry；
- idempotency；
- compensation；
- audit。

目标 Provider 映射：

| Port | 本地 Provider | 阿里云/云端方向 | 当前状态 |
|---|---|---|---|
| CodeExecution | `fixture-local`、opencode | 云沙箱/容器 | 本地已实测 |
| Workspace | filesystem | 云端工作区/快照 | 本地已实现 |
| StateCheckpoint | SQLite | Redis/PolarDB | SQLite 已实测 |
| LeaseRecovery | file-lock | Redis/数据库 fencing | 接口已定义 |
| EventBus | in-memory | RocketMQ | 接口已定义 |
| ArtifactEvidence | filesystem | OSS/MinIO | 本地已实测 |
| KnowledgeMemory | JSON index | 云端知识库 | 接口已定义 |
| SCM | Git | Codeup/GitHub/GitLab | 本地契约已实测 |
| CI | subprocess | 云效/CI 服务 | 独立 CIPort 已实测 |
| PolicyGuard | deterministic rules | 云端安全策略 | 本地已实测 |
| ApprovalHITL | console/Matrix | Matrix/钉钉 | Matrix 证据已部分实测 |
| Secret | environment | KMS/Secrets Manager | 适配待核验 |
| ConfigRegistry | YAML | Nacos | 设计已完成 |
| ModelGateway | direct SDK | Higress/云模型网关 | AgentTeams 模型链路已运行 |
| Observability | JSONL | Tracing/日志平台 | 本地证据已保留 |

### 7.3 插件 Manifest

```yaml
plugin_id: artifact-evidence-local
version: 0.1.0
plugin_type: ArtifactEvidencePort
capabilities:
  - put
  - get
  - list
  - digest
config_schema: config/artifact-evidence.json
secret_refs: []
permissions:
  - task_scoped_write
healthcheck: local_fs_writable
timeout_seconds: 30
retry_policy: bounded
idempotency_policy: content_digest
fallback_plugin: null
audit_policy: append_only
```

统一生命周期：

```text
initialize
  -> healthcheck
  -> invoke
  -> checkpoint
  -> compensate
  -> close
```

---

## 8. 状态、Artifact 和证据模型

### 8.1 标准状态

```text
RECEIVED
 -> FUSED
 -> TRIAGED
 -> BOOTSTRAPPED
 -> LOCATED
 -> PLANNED
 -> AWAITING_APPROVAL
 -> PATCHED
 -> VERIFYING
 -> RELEASE_READY
 -> POSTMORTEM
 -> SKILL_DISTILLING
 -> CLOSED
```

异常状态：

```text
RETRYABLE_FAILURE
NEEDS_HUMAN
BLOCKED_BY_POLICY
RECOVERING
```

### 8.2 只读验证分支

只读仓库分析不产生 PatchBundle，因此不能硬套修改任务状态机。建议增加显式分支：

```text
RECEIVED
 -> FUSED
 -> TRIAGED
 -> BOOTSTRAPPED
 -> LOCATED
 -> READONLY_VERIFYING
 -> READONLY_VERIFIED
 -> EVIDENCE_PACKED
 -> CLOSED
```

其中：

- `READONLY_VERIFYING` 只能由 `codeops-verifier` 进入；
- Verifier 必须提供独立上下文、仓库快照 digest、命令 digest 和结果日志；
- `READONLY_VERIFIED` 必须引用 `VerificationReport`；
- `EVIDENCE_PACKED` 必须引用完整 Worker、Matrix、MCP、SQLite 和 Artifact 证据；
- 完成标记只能由 Leader 在 Evidence Pack 校验通过后输出。

### 8.3 Artifact

标准 Artifact：

| Artifact | Producer |
|---|---|
| `IssueCluster` | Intake |
| `RiskAssessment` | Triage |
| `EnvironmentSnapshot` | EnvBootstrap |
| `RootCauseHypotheses` | RepoAnalyst |
| `ChangePlan` | Plan |
| `PatchBundle` | Executor |
| `VerificationReport` | Verifier |
| `Postmortem` | Postmortem |
| `SkillCandidate` | Postmortem |

统一消息字段：

```text
task_id
trace_id
artifact_type
schema_version
producer
consumer
state_version
evidence_refs
confidence
risk_level
next_action
```

### 8.4 Evidence Minimum

每个任务至少需要：

1. 状态转换事件、Actor、原因和版本；
2. Typed Artifact、Schema Version 和 Evidence Reference；
3. 内容 digest；
4. Approval scope、Reviewer、Matrix room 和 event；
5. 执行命令、退出码、工作区和副作用；
6. 独立 Verifier 结果；
7. 最终状态；
8. 失败、拒绝或转人工原因；
9. 可复现输入、版本和 seed。

---

## 9. 关键运行机制

### 9.1 M1：Trace-to-Skill

任务结束后，Postmortem 收集：

- 状态序列；
- Agent/Skill 调用；
- 输入输出 Artifact；
- 工具调用和退出码；
- Failure Signature；
- 人工审批；
- 最终结果。

蒸馏流程：

```text
Evidence Pack
  -> sensitive/license scan
  -> trace normalization
  -> SkillCandidate
  -> fidelity eval
  -> generalization eval
  -> counterexample eval
  -> human review
  -> gray release
  -> rollback if needed
```

### 9.2 M2：Independent Verification

验证上下文不得直接复用 Executor 的工作目录和自报测试字段。

Verifier 输入：

- 任务契约；
- 批准范围；
- PatchBundle；
- 仓库和环境快照；
- 测试规范；
- 独立工作区。

Verifier 输出：

```text
VerificationReport
  public_tests
  hidden_tests
  historical_tests
  mutation_tests
  commands
  exit_codes
  logs
  failure_signature
  verdict
  verifier_context
```

失败处理：

- 相同 Failure Signature 最多自动恢复三次；
- 第三次失败输出已尝试的验证路径；
- 不再妥协 SQL、测试标准或安全策略；
- 转 `NEEDS_HUMAN`；
- 失败轨迹进入 Postmortem。

### 9.3 M3：Resilient Execution

保护对象：

- 重复创建任务；
- 重复执行命令；
- 旧 Worker 覆盖新状态；
- 工具调用悬空；
- Matrix 消息已发但状态未写入；
- 状态已写入但 Artifact 未落盘；
- 网络分区后错误恢复；
- 人工审批过期。

机制：

- CAS `expected_state_version`；
- 幂等键；
- `query-before-create`；
- lease；
- fencing token；
- checkpoint；
- watchdog；
- session/fork/recap；
- 人工恢复阶梯；
- append-only audit。

---

## 10. 安全和治理

### 10.1 权限模型

权限按 Agent、Skill、Port、状态和工作区五维限制：

```text
who      = Agent Identity
what     = Skill / Tool
where    = Workspace / Path
when     = Current State / Version
why      = Task Contract / Approval
```

### 10.2 Executor 安全边界

- 文件修改必须落在批准的 `files` 列表；
- PatchBundle 必须引用有效 Approval；
- Approval 必须绑定 Matrix room、event 和 scope digest；
- Executor 不得提交 VerificationReport；
- 隐藏测试不进入 Executor 工作区；
- 命令、密钥、网络和副作用必须经过 PolicyGuard；
- 工具失败必须有退出码和 Failure Signature。

### 10.3 证据安全

- Evidence Pack 不存放明文 Token；
- 大型证据放共享对象存储，只在 SQLite 记录 digest 和路径；
- 任务和 Artifact 使用 task scope；
- 未经授权不得把个人、密钥和隐藏真值放进 Prompt；
- 许可证和来源写入数据/Skill Manifest；
- 证据文件采用 append-only 语义。

---

## 11. 评测体系

### 11.1 主指标

| 维度 | 指标 |
|---|---|
| 问题理解 | Issue 聚类准确率、信息缺口识别率 |
| 风险控制 | 高风险漏报率、错误自动执行率、越权拦截率 |
| 环境 | 基线复现率、环境准备成功率 |
| 根因 | Top-k 命中率、支持/反对证据完整率 |
| 计划 | 批准范围合规率、回滚完整率 |
| 执行 | diff 合规率、重复副作用率 |
| 验证 | 独立验证覆盖率、误放行率、隐藏回归检出率 |
| 恢复 | 断点续跑成功率、重复任务抑制率、故障转人工率 |
| 蒸馏 | Skill 保真率、泛化率、反例拒绝率 |
| 体验 | 首次可理解时间、人工决策时间、证据查找时间 |

### 11.2 红队和消融

必须测试：

- Executor 自报“测试通过”；
- 隐藏测试进入 Executor 工作区；
- 越界文件修改；
- 旧版本 Worker 写入新状态；
- Matrix 审批 scope 被篡改；
- MCP Token 错配；
- AgentTeams Manager 代替 Leader 宣布完成；
- 失败后重复执行副作用；
- Skill 仅记住成功样例；
- 相似问题但根因不同；
- 命令挂死；
- 网络分区；
- 恶意仓库指令注入。

消融维度：

- 无独立 Verifier；
- 无 CAS；
- 无 PolicyGuard；
- 无 Evidence Pack；
- 无 Skill 蒸馏；
- 无 Team Leader；
- 无 Human Approval。

每项消融必须展示质量下降或风险上升，而不是只展示全量成功案例。

### 11.3 验收条件

真正宣称“闭环完成”必须同时满足：

- 9 个 AgentTeams Worker 全部 Running；
- Team 与 Worker 绑定关系正确；
- Leader 真实派单；
- Intake、RepoAnalyst、Verifier 真实工作；
- 每个 Worker 通过 Native MCP 写状态或 Artifact；
- 状态序列使用 CAS 且无冲突覆盖；
- Verifier 独立上下文运行；
- Evidence Pack 存在并可独立校验；
- Matrix 房间、事件和审批可追溯；
- SQLite 状态与 Artifact 版本一致；
- 最终响应包含真实证据；
- 只有全部满足时才输出：

```text
CODEOPS_VALIDATION_COMPLETE
```

---

## 12. 可执行代码包

### 12.1 包内容

```text
goai_control_tower/
  README.md
  EXECUTABLE_CONTRACT.md
  pyproject.toml
  run_demo.py
  run_server.py
  src/goai_control_tower/
  tests/
  samples/track1/
  fixtures/track1/
  packages/
  deploy/agentteams/
  runtime_data/
```

### 12.2 本地运行

```bash
cd /path/to/exoflow

python3 -m pip install . --no-deps --no-build-isolation

goai-demo

PYTHONPATH=src python3 -m goai_control_tower \
  --track track1 \
  --track1-input samples/track1/input.json
```

### 12.3 本地控制台

```bash
PYTHONPATH=src python3 run_server.py 8765
```

浏览器地址：

```text
http://127.0.0.1:8765
```

### 12.4 AgentTeams 部署

部署入口：

```text
deploy/agentteams/apply_codeops.sh
```

执行顺序：

1. 检查 Docker 和 AgentTeams Controller；
2. 读取 Manager 当前模型；
3. 构建 9 个 Worker ZIP；
4. 渲染 `codeops-setup.yaml`；
5. 应用 Manager 和 Worker；
6. 上传 Worker 包；
7. 应用 Team 和 Human；
8. 等待 Identity map；
9. 导出 Manager、Team、Worker 和 Human 状态。

Native MCP 启动：

```text
deploy/agentteams/run_native_mcp.sh
```

Worker 容器内必须通过：

```text
http://host.docker.internal:8780/mcp
```

确认：

```text
mcporter list
```

结果必须显示 `codeops-state` healthy。

---

## 13. 当前实现地图

| 能力 | 代码位置 | 当前状态 |
|---|---|---|
| 本地控制平面 | `src/goai_control_tower/foundation.py` | 已实测 |
| 本地状态机 | `packages/team-leader/scripts/state_machine.py` | 已实现，Native 仅作离线 Conformance Oracle |
| Native MCP | `src/goai_control_tower/native_mcp.py` | 已实测 |
| Worker 包 | `packages/`、`deploy/agentteams/build_packages.py` | 已实测生成 |
| AgentTeams 资源 | `deploy/agentteams/codeops-setup.yaml` | 已真实应用 |
| Team 资源 | `deploy/agentteams/codeops-team.yaml` | 已真实应用和绑定 |
| Matrix 回放 | `deploy/agentteams/matrix_replay.py` | 已运行，严格完成标记未收到 |
| 独立 CIPort | `foundation.py` | 本地已实测 |
| fixture-local Provider | `foundation.py` / `track1.py` | 本地已闭环 |
| opencode Provider | `foundation.py` / `track1.py` | dry-run 已验证，live 待独立核验 |
| 15 Port Manifest | `foundation.py` | 本地契约已定义 |
| 云端 Provider | `PORT_MANIFESTS` alternate/cloud 字段 | 待逐项 Conformance |
| 只读 Native 状态分支 | `native_mcp.py` / `foundation.py` | 当前缺口 |
| Native evidence_pack 导出文件 | `native_mcp.py` 有工具，回放尚未完成导出 | 当前缺口 |

---

## 14. 现场 Demo 设计

### 14.1 Demo 主线

输入一个可复现的研发问题，例如：

```text
重试逻辑在请求超时后可能产生重复副作用。
请只修改批准文件，保留测试证据，并由独立验证器确认。
```

演示顺序：

1. Manager 收到任务；
2. Team Leader 展示任务拆解；
3. Intake 输出 IssueCluster；
4. Triage 输出风险和审批路径；
5. EnvBootstrap 输出隔离环境和基线；
6. RepoAnalyst 输出根因假设；
7. Plan 输出最小变更和批准范围；
8. Human 在 Matrix 房间批准；
9. Executor 生成 PatchBundle；
10. Verifier 运行第一次隐藏测试并输出 `REGRESSION_TIMEOUT_GUARD`；
11. Leader 触发第二次受控修复；
12. Verifier 在独立工作区通过；
13. Postmortem 生成 SkillCandidate；
14. 控制台展示 Trace、Artifact、Evidence Pack 和最终状态。

### 14.2 必须展示的反例

至少展示一个失败场景：

- Executor 尝试修改批准范围外文件，被 Native MCP 拒绝；
- Verifier 不接受 Executor 的自报测试；
- 隐藏测试失败后生成 Failure Signature；
- 连续失败达到阈值后转人工；
- Matrix 审批缺失时不能进入 Patch；
- 状态版本过期时 CAS 拒绝写入。

反例比单纯展示成功更能证明方案不是提示词工程。

---

## 15. 风险和决策

### 15.1 AgentTeams 平台风险

AgentTeams 部分机制仍处于 beta：

- TeamHarness 不能假设为稳定 API；
- Manager 派单具有语义匹配特征；
- 官方没有完整显式状态机原语；
- 资源 CR、CLI 和 runtime 在不同版本间可能变化；
- `v1.2.0-beta.1` 使用 `hiclaw` CLI，不应混用后续 `agt` 命令。

应对：

- 固定版本和镜像 digest；
- 每次真实运行记录 Controller、Manager、Worker、Team generation；
- 用 Conformance Kit 检查平台能力；
- 不在方案中编造官方函数名；
- AgentTeams 负责平台生命周期，CodeOps MCP 负责领域状态事实；
- 云端 Provider 未实测时明确标为 pending。

### 15.2 Manager 与 Leader 边界风险

Manager 可以接收管理员任务，但 CodeOps 任务必须交给 `codeops-lead`。Manager 不得代替 Leader 生成根因、修改状态或宣布完成。

验收必须检查：

- 任务是否到达 Leader Room；
- Leader 是否真实派单；
- Worker 是否收到含 task id、repo、state version 和 Artifact 目标的指令；
- 最终结论是否由 Leader 聚合；
- Manager 是否仅转发平台级结果。

### 15.3 状态机风险

共享对象存储可以保证文件可见，不等于保证并发一致性。所有状态变更必须经过 Native MCP CAS；禁止直接编辑状态 JSON 或 SQLite。

### 15.4 失败包装风险

第三次修正失败时不能输出模糊的“系统已完成尝试”，必须输出：

```text
已尝试 X / Y / Z 三种验证方式，仍无法获得可信证据。
当前状态：NEEDS_HUMAN。
建议：人工提供查询模板或补充独立验证条件。
```

失败是合法能力状态，不是需要被隐藏的异常。

---

## 16. 研发路线图

### P0：严格 Native 闭环

- 只读验证状态分支；
- Leader 原生派单；
- Verifier 独立验证；
- Evidence Pack 导出和校验；
- 完成标记门禁；
- 新的 Matrix 回放；
- 真实日志和截图。

### P1：AgentTeams 深度能力

- Team/Project Room 规范化；
- MinIO Artifact 生命周期；
- Matrix Human Approval；
- Higress 凭证隔离；
- Nacos Skill Registry；
- Worker runtime Provider 切换；
- Hermes 与 OpenClaw 对照运行。

### P2：可复用平台

- 15 Port Conformance Kit；
- 本地/云端/混合 Provider；
- Lease/Fencing 混沌演练；
- Skill 灰度和回滚；
- 评测集、消融和红队；
- 干净环境一键复现；
- 开源交付包和录屏材料。

---

## 17. 最终验收清单

### 架构

- [ ] AgentTeams 是平台控制平面；
- [ ] 8 个 Agent 有独立 Identity、状态、权限和指标；
- [ ] 12 个 Skill 有 Manifest、Schema、Eval 和版本；
- [ ] 15 个 Port 有统一契约和 Provider；
- [ ] 没有隐藏的第二套主编排器。

### 运行

- [x] AgentTeams `v1.2.0-beta.1` 已安装；
- [x] 9 个 Worker 已运行；
- [x] `codeops-control-tower` Team 已绑定；
- [x] Native MCP 已健康；
- [x] 本地纵向切片已闭环；
- [ ] Native 只读任务完成最终闭环；
- [ ] 云端 Provider Conformance 完成。

### 证据

- [x] 本地 Trace；
- [x] Typed Artifact；
- [x] 独立本地 Verifier；
- [x] 本地 Evidence Pack；
- [x] Native SQLite 状态；
- [x] Native Artifact；
- [ ] Native 最终 Evidence Pack；
- [ ] Matrix 完成事件；
- [ ] `CODEOPS_VALIDATION_COMPLETE`。

### 现场表现

- [ ] 成功路径录屏；
- [ ] 越权拒绝录屏；
- [ ] 隐藏测试失败和恢复录屏；
- [ ] Matrix 审批录屏；
- [ ] Evidence Pack 和 SQLite 对照展示；
- [ ] 评委可在干净环境复现。

---

## 18. 方案基线文件

- [赛道一方案与进展页面](../web/static/track1-plan.html)
- [赛道一完善建议](../赛道一-CodeOps-Control-Tower-具体完善建议.md)
- [两案改造建议 2.0](../../建议2.0/GOAI方案改造建议2.0.md)
- [本地执行契约](../EXECUTABLE_CONTRACT.md)
- [AgentTeams 部署说明](../deploy/agentteams/README.md)

本文件是赛道一后续研发、验收、演示和初赛材料的主方案基线。任何“已完成”表述，必须回到对应代码、测试、日志、SQLite 或 Evidence Pack 核对。
