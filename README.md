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
