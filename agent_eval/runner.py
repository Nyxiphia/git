# -*- coding: utf-8 -*-
"""跑实验6 的 7 类测试，输出可直接粘进报告的表格。"""
import json
import os
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WS not in sys.path:
    sys.path.insert(0, WS)

from agent_eval.cases import all_cases        # noqa: E402

OUTDIR = os.path.join(WS, 'rag_data')


def run_suite(live=False):
    rows = []
    records = []
    for cid, kind, inp, expect, fn in all_cases(live):
        print('\n' + '=' * 76)
        print('%s [%s] 输入：%s' % (cid, kind, inp))
        print('预期：%s' % expect)
        t0 = time.time()
        try:
            res, checks = fn()
            ok = all(c[1] for c in checks)
            status = res['status']
            run_id = res['run_id']
            steps = res['steps_used']
            calls = res['tool_calls_total']
            log = res['log_path']
            detail = res['stop_reason'] or ''
        except Exception as e:                       # noqa: BLE001
            import traceback
            traceback.print_exc()
            ok, status, run_id, steps, calls, log = False, 'EXCEPTION', '-', 0, 0, ''
            detail = '%s: %s' % (type(e).__name__, e)
            checks = [('用例本身抛异常', False, detail)]
        ms = (time.time() - t0) * 1000
        print('实际：状态 %s ｜ 步数 %s ｜ 工具调用 %s ｜ 耗时 %.0f ms ｜ 判定 %s'
              % (status, steps, calls, ms, '通过' if ok else '未通过'))
        for desc, good, extra in checks:
            print('   %s %s%s' % ('✓' if good else '✗', desc,
                                  ('（%s）' % extra) if extra else ''))
        rows.append((cid, kind, inp, expect, status, steps, calls, ok, detail))
        records.append({'id': cid, 'kind': kind, 'input': inp, 'expect': expect,
                        'status': status, 'steps': steps, 'tool_calls': calls,
                        'passed': ok, 'stop_reason': detail, 'run_id': run_id,
                        'log': log, 'elapsed_ms': round(ms, 1),
                        'checks': [{'desc': d, 'passed': bool(g), 'detail': x}
                                   for d, g, x in checks]})

    # ---------------- 汇总表 ----------------
    md = ['| 编号 | 类型 | 输入 | 预期行为 | 实际状态 | 步数 | 工具调用 | 结论 | 判断依据 |',
          '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for cid, kind, inp, expect, status, steps, calls, ok, detail in rows:
        md.append('| %s | %s | %s | %s | `%s` | %s | %s | %s | %s |'
                  % (cid, kind, inp, expect, status, steps, calls,
                     '通过' if ok else '**未通过**', (detail or '—')[:60]))
    table = '\n'.join(md)
    print('\n' + table)
    passed = sum(1 for r in rows if r[7])
    print('\n合计 %d 个用例：通过 %d，未通过 %d'
          % (len(rows), passed, len(rows) - passed))

    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, 'agent_suite.json'), 'w', encoding='utf-8') as f:
        json.dump({'live': live, 'passed': passed, 'total': len(rows),
                   'cases': records}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUTDIR, 'agent_suite.md'), 'w', encoding='utf-8') as f:
        f.write('# 实验6 测试结果%s\n\n' % ('（真实模型）' if live else '（离线反射式）'))
        f.write(table + '\n')
    print('已保存：rag_data/agent_suite.json、rag_data/agent_suite.md')
    return 0 if passed == len(rows) else 1


if __name__ == '__main__':
    sys.exit(run_suite(live='--live' in sys.argv))
