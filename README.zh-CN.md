# ExoFlow

**基于确定性状态机的多智能体软件工程编排框架。**

ExoFlow 通过类型化、CAS 门禁保护的状态机协调多个专业 AI Agent，完成问题录入、
根因定位、验证补丁执行和运维知识沉淀，全流程留下可审计的事件链。

## 为什么选择 ExoFlow？

- **确定性控制平面** — 单一状态机定义（`state_machine_def.py`）是唯一事实源，
  每次状态迁移都经过 CAS 校验并记录执行者。
- **纯 Python 标准库** — 零运行时依赖，Python ≥ 3.9，支持离线安装。
- **类型化产出物** — 每个 Agent 输出都经过 schema 校验，附带版本、摘要和来源信息。
- **可审计事件链** — 基于 SQLite 的事件存储记录每次状态迁移、门禁检查和产出物写入。
- **技能蒸馏** — 成功的 Agent 执行轨迹被蒸馏为可复用的技能包，附带评估回归守卫。

## 架构

```
                  ┌──────────────────────┐
                  │   Native MCP 服务     │  ← 12 工具、CAS、门禁
                  │   (native_mcp.py)     │
                  └──────────┬───────────┘
                             │ 类型化事件 + 产出物
                  ┌──────────▼───────────┐
                  │   状态机              │  ← 唯一事实源
                  │   (state_machine_def) │
                  └──────────┬───────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────▼─────┐  ┌─────▼──────┐  ┌──────▼──────┐
   │  Intake   │  │  Triage    │  │  Verifier   │  ...
   │  Worker   │  │  Worker    │  │  Worker     │
   └──────────┘  └────────────┘  └─────────────┘
```

## 快速开始

```bash
cd /path/to/exoflow

# 安装（无第三方依赖）
python3 -m pip install . --no-deps --no-build-isolation

# 运行双赛道演示
PYTHONPATH=src python3 run_demo.py

# 运行全部测试
PYTHONPATH=src python3 -m unittest discover -s tests -v

# CLI 入口
python3 -m goai_control_tower --track track1 --track1-input src/goai_control_tower/samples/track1/input.json
```

## 赛道说明

### 赛道一 — CodeOps 控制塔

端到端代码修复流水线：问题录入 → 分诊 → 环境初始化 → 仓库分析 → 方案规划 →
审批 → 补丁 → 验证 → 发布 → 复盘 → 技能蒸馏。

- 9 个专业 Worker Agent，每个附带类型化的 SKILL 清单
- 独立验证工作区执行隐藏测试
- `fixture-local` Provider 支持确定性回放

### 赛道二 — 因果增长归因

保险业务增长归因，内置因果门禁：
- **场景 A**：观测性数据（仅描述性分析，不做因果断言）
- **场景 B**：缺失实验元数据（拒绝闭合）
- **场景 C**：随机化实验（ITT 估计 + 95% 置信区间）
- 进程隔离的预言机基准测试保障可复现性

## 项目结构

```text
ExoFlow/
├── src/goai_control_tower/    ← 核心库（纯 Python 标准库）
│   ├── state_machine_def.py   ← 状态机定义
│   ├── native_mcp.py          ← MCP 状态权威服务
│   ├── skill_distill.py       ← 轨迹蒸馏
│   └── track1.py / track2.py  ← 赛道实现
├── packages/                  ← Worker SKILL 清单
│   ├── team-leader/           ← 编排 Agent
│   ├── skills/                ← 11 个专业技能 + 评估用例
│   └── ...
└── tests/                     ← 单元测试
```

## 运行要求

- Python ≥ 3.9
- 无运行时依赖（仅标准库）
- `opencode` CLI 为可选项（仅实时 CLI 执行路径需要）

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
