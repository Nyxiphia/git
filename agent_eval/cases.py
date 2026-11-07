# -*- coding: utf-8 -*-
"""实验6 2.6 的测试集：7 类情况。

| 编号 | 类型 | 用法 |
| T1 | 正常完成 | 离线用 ReflexPlanner；`--live` 时用真实模型（2.6 要求正常流程必须实际调用模型） |
| T2 | 参数错误 | 先传 top_n=999，看错误是否回传并被修正 |
| T3 | 工具异常 | 数据库路径不存在，看是否返回明确错误码与原因 |
| T4 | 达到步数上限 | 脚本让它一直调工具，看是否在步数上限处停止 |
| T5 | 人工确认-同意 | 导出文件，confirm=yes |
| T6 | 人工确认-拒绝 | 导出文件，confirm=no，必须不产生文件 |
| T7 | 工具超时 | 把超时设为 0，看是否返回 timeout 且提示写操作状态未知需核对 |
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WS not in sys.path:
    sys.path.insert(0, WS)

from dreamjournal.agent.harness import Harness                       # noqa: E402
from dreamjournal.agent.planner import (LLMPlanner, ReflexPlanner,   # noqa: E402
                                        ScriptedPlanner)
from dreamjournal.agent.tools import ToolContext, tool_schemas       # noqa: E402

DB = os.path.join(WS, 'data', 'dream.db')
OUT = os.path.join(WS, 'out')
FIELD, TOPN = 'symbol', 5


def _task(db=DB):
    return {'name': '梦境意象统计', 'field_type': FIELD, 'top_n': TOPN, 'db_path': db}


def _codes(result):
    return [c.get('error', {}).get('code')
            for s in result.get('_trace_codes', []) for c in [s]]


def _trace_errors(res):
    """从消息流里提取所有工具错误码。"""
    codes = []
    for m in res['messages']:
        if m.get('role') == 'tool':
            try:
                p = json.loads(m.get('content') or '{}')
            except json.JSONDecodeError:
                continue
            if not p.get('ok'):
                codes.append((p.get('error') or {}).get('code'))
    return codes


# ---------------- 各用例 ----------------
def case_normal(live=False):
    """T1 正常完成。"""
    if live:
        from dreamjournal.ai.client import LLMClient
        key = os.environ.get('DREAM_LLM_API_KEY', '')
        if not key:
            raise SystemExit('--live 需要 DREAM_LLM_API_KEY')
        client = LLMClient(api_key=key,
                           base_url=os.environ.get('DREAM_LLM_BASE_URL',
                                                   'https://api.deepseek.com/v1'),
                           model=os.environ.get('DREAM_LLM_MODEL', 'deepseek-chat'),
                           timeout=60, max_retries=1)
        planner = LLMPlanner(client, tool_schemas())
    else:
        planner = ReflexPlanner(FIELD, TOPN)
    ctx = ToolContext(DB, allow_write=False)
    h = Harness(planner, ctx, _task(), max_steps=6, wall_clock=120,
                confirm_fn=lambda *a: True)
    res = h.run()
    checks = [
        ('状态为 ok', res['status'] == 'ok', res['status']),
        ('调用了 field_stats', any(c['tool'] == 'field_stats'
                                for s in h.trace for c in s['tool_calls']), ''),
        ('通过成功标准 S1/S2', bool(res['verdict'] and res['verdict']['passed']),
         '; '.join('%s=%s' % (c['id'], c['passed'])
                   for c in (res['verdict'] or {}).get('criteria', []))),
    ]
    return res, checks


def case_bad_args():
    """T2 参数错误：先错后对，验证错误被回传并修正。"""
    planner = ScriptedPlanner([
        {'tool': 'field_stats', 'args': {'field_type': 'symbol', 'top_n': 999}},
        {'tool': 'field_stats', 'args': {'field_type': 'symbol', 'top_n': TOPN}},
        {'text_from_last_tool': True},
    ])
    ctx = ToolContext(DB, allow_write=False)
    h = Harness(planner, ctx, _task(), max_steps=6)
    res = h.run()
    errs = _trace_errors(res)
    ok_calls = [m for m in res['messages']
                if m.get('role') == 'tool'
                and (json.loads(m.get('content') or '{}')).get('ok')]
    checks = [
        ('第一次调用报 invalid_arguments', 'invalid_arguments' in errs, str(errs)),
        ('第二次调用成功', len(ok_calls) >= 1, '成功调用 %d 次' % len(ok_calls)),
        ('错误信息含允许范围', any('不能大于' in (m.get('content') or '')
                             for m in res['messages'] if m.get('role') == 'tool'), ''),
        ('修正后通过成功标准', res['status'] == 'ok', res['status']),
    ]
    return res, checks


def case_tool_error():
    """T3 工具异常：数据库打不开。"""
    bad = os.path.join(WS, 'data', '_no_such_dir', 'x.db')
    planner = ScriptedPlanner([
        {'tool': 'list_dreams', 'args': {'days': 7}},
        {'tool': 'field_stats', 'args': {'field_type': 'symbol'}},
    ])
    ctx = ToolContext(bad, allow_write=False)
    h = Harness(planner, ctx, _task(db=bad), max_steps=4,
                max_consecutive_errors=2)
    res = h.run()
    errs = _trace_errors(res)
    checks = [
        ('返回 db_error', 'db_error' in errs, str(errs)),
        ('错误信息含原因', any('数据库错误' in (m.get('content') or '')
                         for m in res['messages'] if m.get('role') == 'tool'), ''),
        ('因连续错误而停下', res['status'] in ('too_many_errors', 'step_limit'),
         res['status'] + ' / ' + res['stop_reason']),
    ]
    return res, checks


def case_step_limit():
    """T4 达到步数上限：一直要工具，不给回答。"""
    planner = ScriptedPlanner([{'tool': 'list_dreams', 'args': {'days': 30}}])
    ctx = ToolContext(DB, allow_write=False)
    h = Harness(planner, ctx, _task(), max_steps=3)
    res = h.run()
    checks = [
        ('状态为 step_limit', res['status'] == 'step_limit', res['status']),
        ('步数恰为 3', res['steps_used'] == 3, str(res['steps_used'])),
        ('停止原因说明了上限', '最大步数' in (res['stop_reason'] or ''),
         res['stop_reason']),
    ]
    return res, checks


def case_confirm_yes():
    """T5 人工确认-同意：导出文件。"""
    fn = 'agent_t5_export.md'
    path = os.path.join(OUT, fn)
    if os.path.exists(path):
        os.remove(path)
    planner = ScriptedPlanner([
        {'tool': 'field_stats', 'args': {'field_type': 'symbol', 'top_n': TOPN}},
        {'tool': 'export_markdown', 'args': {'field_type': 'symbol',
                                             'top_n': TOPN, 'filename': fn}},
        {'text_from_last_tool': True},
    ])
    ctx = ToolContext(DB, allow_write=True)
    asked = []
    h = Harness(planner, ctx, _task(), max_steps=5,
                confirm_fn=lambda n, s, sp: (asked.append(s), True)[1])
    res = h.run()
    checks = [
        ('触发了确认', len(asked) == 1, str(asked)),
        ('文件已生成', os.path.exists(path), path),
        ('文件含标签行', os.path.exists(path) and '|' in open(path, encoding='utf-8').read(),
         ''),
        ('导出调用成功', _trace_errors(res) == [], str(_trace_errors(res))),
        ('S3 通过', bool(res['verdict']) and all(c['passed'] for c in res['verdict']['criteria']),
         res['status']),
    ]
    return res, checks


def case_confirm_no():
    """T6 人工确认-拒绝：必须什么都不写。"""
    fn = 'agent_t6_should_not_exist.md'
    path = os.path.join(OUT, fn)
    if os.path.exists(path):
        os.remove(path)
    planner = ScriptedPlanner([
        {'tool': 'field_stats', 'args': {'field_type': 'symbol', 'top_n': TOPN}},
        {'tool': 'export_markdown', 'args': {'field_type': 'symbol',
                                             'top_n': TOPN, 'filename': fn}},
        {'text_from_last_tool': True},
    ])
    ctx = ToolContext(DB, allow_write=True)
    asked = []
    h = Harness(planner, ctx, _task(), max_steps=5,
                confirm_fn=lambda n, s, sp: (asked.append(s), False)[1])
    res = h.run()
    checks = [
        ('触发了确认', len(asked) == 1, str(asked)),
        ('返回 permission_denied',
         'permission_denied' in _trace_errors(res), str(_trace_errors(res))),
        ('文件未生成', not os.path.exists(path), '存在' if os.path.exists(path) else '不存在'),
        ('错误说明是用户拒绝', any('拒绝' in (m.get('content') or '')
                             for m in res['messages'] if m.get('role') == 'tool'), ''),
    ]
    return res, checks


def case_timeout():
    """T7 工具超时：超时设为 0，且写操作要提示状态未知需核对。"""
    fn = 'agent_t7_timeout.md'
    planner = ScriptedPlanner([
        {'tool': 'field_stats', 'args': {'field_type': 'symbol', 'top_n': TOPN}},
        {'tool': 'export_markdown', 'args': {'field_type': 'symbol',
                                             'top_n': TOPN, 'filename': fn}},
        {'text_from_last_tool': True},
    ])
    ctx = ToolContext(DB, allow_write=True, timeout_override={'export_markdown': 0.0})
    h = Harness(planner, ctx, _task(), max_steps=5, confirm_fn=lambda *a: True)
    res = h.run()
    errs = _trace_errors(res)
    tool_msgs = [m.get('content') or '' for m in res['messages']
                 if m.get('role') == 'tool']
    checks = [
        ('返回 timeout', 'timeout' in errs, str(errs)),
        ('提示没有强制取消能力', any('强制' in t or '停止等待' in t for t in tool_msgs), ''),
        ('写操作提示先核对', any('read_export' in t for t in tool_msgs), ''),
    ]
    return res, checks


def all_cases(live=False):
    return [
        ('T1', '正常完成', '统计意象 Top5 并回答', '状态 ok 且通过成功标准',
         lambda: case_normal(live)),
        ('T2', '参数错误', 'field_stats(top_n=999)', '报参数错误→修正后成功',
         case_bad_args),
        ('T3', '工具异常', '数据库路径不存在', '返回 db_error 并停下说明原因',
         case_tool_error),
        ('T4', '达到步数上限', 'max_steps=3 且一直要工具', '状态 step_limit，步数=3',
         case_step_limit),
        ('T5', '人工确认-同意', '导出 out/agent_t5_export.md', '确认后文件生成',
         case_confirm_yes),
        ('T6', '人工确认-拒绝', '确认时选否', '不写文件，返回 permission_denied',
         case_confirm_no),
        ('T7', '工具超时', '超时设为 0 秒', '返回 timeout，且提示先核对再重试',
         case_timeout),
    ]
