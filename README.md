# git

个人 Git 仓库 / 工作区。

## 克隆

```bash
git clone https://github.com/Nyxiphia/git.git
```

## 说明

- 默认分支：`main`
- 提交前请确认 `.gitignore` 已覆盖需要忽略的构建产物与本地配置。

## 实验6：工具调用、Agent 与 Harness

单 Agent + 运行时 Harness，跑在本机真实数据库上，工具为只读统计与需确认的导出。

```
python -m dreamjournal.agent.cli tools         # 查看工具 Schema
python -m dreamjournal.agent.cli run           # 运行 Agent（离线反射式）
python -m dreamjournal.agent.cli run --live --allow-write   # 真实模型
python -m dreamjournal.agent.cli suite         # 7 类测试
```

代码：`dreamjournal/agent/`（tools / planner / harness / verify / cli）
测试：`agent_eval/`　日志：`runs/`　导出：`out/`

## 实验7：核心 AI 能力原型（梦境文本 → 结构化字段）

```
python -m dreamjournal.prototype.cli config --profile v2    # 查看配置（密钥不显示）
python -m dreamjournal.prototype.cli cases                  # 15 条评测样例
python -m dreamjournal.prototype.cli run --profile v2 --case E01
python -m dreamjournal.prototype.cli run --profile v2 --case E01 --save-db data/prototype.db
python -m dreamjournal.prototype.cli eval --methods baseline,v1,v2
```

代码：`dreamjournal/prototype/`　配置：`config/exp7_v1.json`、`config/exp7_v2.json`
评测集：`eval/exp7_cases.json`　两个版本：Tag `v0.5.0`（初版）、`v0.6.0`（修订版）
