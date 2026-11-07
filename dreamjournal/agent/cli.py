# -*- coding: utf-8 -*-
"""实验6 命令行入口。

用法：
    python -m dreamjournal.agent.cli tools                    查看工具 Schema
    python -m dreamjournal.agent.cli tool field_stats --args '{"field_type":"symbol"}'
                                                              直接测试一个工具（2.2 要求）
    python -m dreamjournal.agent.cli run                      运行 Agent（默认离线反射式）
    python -m dreamjournal.agent.cli run --live               运行 Agent（真实模型）
    python -m dreamjournal.agent.cli run --confirm no         模拟用户拒写操作
    python -m dreamjournal.agent.cli suite                    跑 6 类测试
"""
import argparse
import json
import os
import sys

from dreamjournal.agent import tools
from dreamjournal.agent.harness import Harness
from dreamjournal.agent.planner import LLMPlanner, ReflexPlanner, ScriptedPlanner
from dreamjournal.agent.tools import ToolContext

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB = os.path.join(ROOT, 'data', 'dream.db')


def make_confirm(mode):
    """返回确认函数：yes 一律同意，no 一律拒绝，ask 交互询问。"""
    def confirm(name, summary, spec):
        if mode == 'yes':
            print('  [确认] 自动同意：%s' % summary)
            return True
        if mode == 'no':
            print('  [确认] 自动拒绝：%s' % summary)
            return False
        print('\n  ── 需要确认的操作 ──')
        print('  工具：%s' % name)
        print('  内容：%s' % summary)
        print('  影响：%s' % ('会写入文件' if spec.side_effect else '无'))
        ans = input('  是否执行？[y/N] ').strip().lower()
        return ans in ('y', 'yes', '是')
    return confirm


def build_planner(args):
    if args.live:
        from dreamjournal.ai.client import LLMClient
        key = os.environ.get('DREAM_LLM_API_KEY', '')
        if not key:
            print('[错误] --live 需要环境变量 DREAM_LLM_API_KEY', file=sys.stderr)
            raise SystemExit(2)
        client = LLMClient(api_key=key,
                           base_url=os.environ.get('DREAM_LLM_BASE_URL',
                                                   'https://api.deepseek.com/v1'),
                           model=os.environ.get('DREAM_LLM_MODEL', 'deepseek-chat'),
                           timeout=60, max_retries=1)
        print('模型：%s  接口：%s' % (client.model, client.base_url))
        return LLMPlanner(client, tools.tool_schemas())
    print('【离线反射式】未使用模型，只验证 Harness 控制流与工具回路。')
    return ReflexPlanner(field_type=args.field, top_n=args.top)


def cmd_tools(args):
    for s in tools.tool_schemas():
        fn = s['function']
        print('· %s' % fn['name'])
        print('  说明：%s' % fn['description'])
        props = fn['parameters'].get('properties', {})
        req = set(fn['parameters'].get('required', []))
        for k, v in props.items():
            extra = []
            if 'enum' in v:
                extra.append('取值 %s' % '/'.join(v['enum']))
            if 'minimum' in v:
                extra.append('%s~%s' % (v.get('minimum'), v.get('maximum', '∞')))
            if k in req:
                extra.append('必填')
            print('    - %-14s %-8s %s' % (k, v.get('type'), '，'.join(extra)))
        spec = tools.TOOLS[fn['name']]
        print('  副作用：%s ｜ 需确认：%s ｜ 超时：%.0fs ｜ %s'
              % ('有' if spec.side_effect else '无',
                 '是' if spec.requires_confirm else '否', spec.timeout,
                 spec.idempotent))
        print()
    return 0


def cmd_tool(args):
    """直接测试单个工具（不经 Agent），用于 2.2 要求的前置测试。"""
    ctx = ToolContext(DEFAULT_DB, allow_write=args.allow_write)
    try:
        payload = json.loads(args.args or '{}')
    except json.JSONDecodeError as e:
        print('[错误] --args 不是合法 JSON：%s' % e, file=sys.stderr)
        return 2
    print('调用 %s 参数=%s' % (args.name, json.dumps(payload, ensure_ascii=False)))
    out = tools.dispatch(args.name, payload, ctx,
                         confirm_fn=make_confirm(args.confirm) if args.confirm != 'no'
                         else (lambda *a: False))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get('ok') else 1


def cmd_run(args):
    task = {'name': '梦境意象统计', 'field_type': args.field,
            'top_n': args.top, 'db_path': args.db}
    planner = build_planner(args)
    ctx = ToolContext(args.db, allow_write=args.allow_write)
    h = Harness(planner, ctx, task, max_steps=args.steps,
                wall_clock=args.wall, confirm_fn=make_confirm(args.confirm),
                verbose=True)
    res = h.run()
    print('\n' + '=' * 74)
    print('任务编号 %s ｜ 状态 %s ｜ 步数 %d/%d ｜ 工具调用 %d ｜ tokens %d ｜ 耗时 %.0f ms'
          % (res['run_id'], res['status'], res['steps_used'], res['max_steps'],
             res['tool_calls_total'], res['tokens_total'], res['elapsed_ms']))
    if res['stop_reason']:
        print('停止原因：%s' % res['stop_reason'])
    print('-' * 74)
    print('最终回答：\n%s' % (res['final_answer'] or '(无)'))
    if res['verdict']:
        print('-' * 74)
        print('成功标准核对：%s' % ('通过' if res['verdict']['passed'] else '未通过'))
        for c in res['verdict']['criteria']:
            print('  [%s] %-4s %s —— %s' % ('✓' if c['passed'] else '✗',
                                            c['id'], c['desc'], c['detail']))
    print('日志：%s' % res['log_path'])
    return 0 if res['status'] == 'ok' else 1


def cmd_suite(args):
    from agent_eval.runner import run_suite
    return run_suite(live=args.live)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='dreamjournal.agent.cli', description='实验6 Agent')
    ap.add_argument('--db', default=DEFAULT_DB)
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('tools').set_defaults(func=cmd_tools)

    p = sub.add_parser('tool')
    p.add_argument('name')
    p.add_argument('--args', default='{}')
    p.add_argument('--confirm', default='yes', choices=['yes', 'no', 'ask'])
    p.add_argument('--allow-write', action='store_true')
    p.set_defaults(func=cmd_tool)

    p = sub.add_parser('run')
    p.add_argument('--live', action='store_true', help='使用真实模型')
    p.add_argument('--field', default='symbol',
                   choices=['emotion', 'character', 'scene', 'symbol'])
    p.add_argument('--top', type=int, default=5)
    p.add_argument('--steps', type=int, default=6)
    p.add_argument('--wall', type=float, default=120.0)
    p.add_argument('--confirm', default='yes', choices=['yes', 'no', 'ask'])
    p.add_argument('--allow-write', action='store_true')
    p.set_defaults(func=cmd_run)

    p = sub.add_parser('suite')
    p.add_argument('--live', action='store_true')
    p.set_defaults(func=cmd_suite)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
