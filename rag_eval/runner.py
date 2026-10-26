# -*- coding: utf-8 -*-
"""实验5 2.5 的两组对比测试运行器。

两组使用**相同的问题、相同的模型、相同的主要参数和相同的输出格式**：
  · direct 组：不提供检索资料（group='direct'）
  · rag    组：提供检索资料 + 依据资料回答 + 引用来源（group='rag'）

每次调用都新建独立上下文（不使用 history），避免前一次结果影响后一次。
输出 Markdown 表格，可直接粘进报告。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dreamjournal.ai.cli import build_client                     # noqa: E402
from dreamjournal.ai.pipeline import INDEX_PATH, RagPipeline, make_offline_pipeline  # noqa: E402
from rag_eval.cases import CASES, auto_judge                      # noqa: E402

OUTDIR = os.path.join(ROOT, 'rag_data')


def _one(pipe, case, group, k):
    res = pipe.ask(case['question'], group=group, k=k)
    return {
        'id': case['id'], 'kind': case['kind'], 'group': group,
        'answer': res['answer'], 'status': res['status'],
        'citations': res['citations'], 'usage': res['usage'],
        'latency_ms': res['latency_ms'], 'retrieval': res['retrieval_info'],
        'context': res['context_info'], 'meta': res['meta'],
        'offline': res['offline'], 'error': res['error'],
        'judgement': auto_judge(case, res['answer']),
    }


def run_two_groups(limit=0, k=4):
    cases = CASES[:limit] if limit else CASES
    client = build_client(timeout=30, max_retries=2)
    offline = not client.configured
    if offline:
        pipe = make_offline_pipeline(index_path=INDEX_PATH, k=k)
        print('【注意】未检测到 DREAM_LLM_API_KEY：本次以离线抽取式运行，'
              '只用于验证流程可跑通，回答质量结论无效。\n')
    else:
        pipe = RagPipeline(client, INDEX_PATH, k=k)
        print('模型：%s  接口：%s\n' % (client.model, client.base_url))

    rows = []
    record = {'offline': offline, 'k': k, 'model': (pipe.provider.describe().get('model')),
              'cases': []}
    for c in cases:
        d = _one(pipe, c, 'direct', k)
        r = _one(pipe, c, 'rag', k)
        record['cases'].append({'id': c['id'], 'direct': d, 'rag': r, 'case': c})
        rows.append((c, d, r))
        print('%s [%s] 完成：direct=%s / rag=%s' % (c['id'], c['kind'],
                                                    d['status'], r['status']))

    md = []
    md.append('| 编号 | 类型 | 问题 | 组别 | 状态 | 要点命中 | 自动判定 | 引用数 | 总tokens | 耗时(ms) |')
    md.append('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for c, d, r in rows:
        for tag, x in (('直接模型', d), ('RAG', r)):
            md.append('| %s | %s | %s | %s | %s | %d/%d | %s | %d | %s | %.0f |'
                      % (c['id'], c['kind'], c['question'], tag, x['status'],
                         x['judgement']['points_hit'], x['judgement']['points_total'],
                         x['judgement']['verdict'], len(x['citations']),
                         x['usage'].get('total_tokens', '-'), x['latency_ms']))

    table = '\n'.join(md)
    print('\n' + table)

    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, 'eval_result.json'), 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUTDIR, 'eval_table.md'), 'w', encoding='utf-8') as f:
        f.write('# 实验5 两组对比测试结果%s\n\n' % ('（离线抽取式，结论无效）' if offline else ''))
        f.write(table + '\n')
    print('\n已保存：rag_data/eval_result.json、rag_data/eval_table.md')
    return 0


if __name__ == '__main__':
    sys.exit(run_two_groups(limit=int(sys.argv[1]) if len(sys.argv) > 1 else 0))
