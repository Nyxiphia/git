# -*- coding: utf-8 -*-
"""评测（实验7 2.5）：同一批样例、同一套判断规则，跑多个方案并汇总。

指标定义（都写在报告里，便于复算）：
  · JSON 合法率：`status == 'ok'` 的样例占比（模型确实返回了可解析 JSON）；
  · Schema 合规率：用 `schema.check_schema` 检查原始输出，0 处错误才算合规；
  · 字段级 P/R/F1：以“field_type + label”为匹配单位，与金标准逐样例比对；
    金标准为空且预测为空 → 记 1.0（正确弃权）；金标准为空但有输出 → 记 0.0；
  · 解读词出现率：整段输出里出现 BANNED 中任一措辞的样例占比；
  · 平均耗时、总 tokens、估算费用。

之所以把“正确弃权”单独定义，是因为本评测集里有 3 条（E12—E14）本来就**不该给字段**，
如果一律用 precision 会惩罚“正确地什么都不说”的系统。
"""
import json
import os
import time

from dreamjournal.prototype import baseline, schema
from dreamjournal.prototype.parser import ParsePrototype, load_cases, load_profile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'rag_data')

# 估算用单价（元 / 百万 token），仅用于数量级参考，实际以服务商账单为准
PRICE_IN = 1.0
PRICE_OUT = 2.0


def _label_set(fields):
    out = set()
    for f in fields or []:
        if not isinstance(f, dict):
            continue
        ft, lb = f.get('field_type'), f.get('label')
        if ft and lb:
            out.add((ft, str(lb).strip()))
    return out


def score_case(case, pred, raw_text):
    gold = _label_set(case.get('gold'))
    got = _label_set(pred.get('fields'))
    tp = len(gold & got)
    if gold and got:
        p, r = tp / len(got), tp / len(gold)
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    elif not gold and not got:
        p = r = f1 = 1.0            # 正确弃权
    else:
        p, r, f1 = 0.0, 0.0, 0.0
    clean, errs = schema.check_schema(pred.get('_obj')) if pred.get('_obj') is not None \
        else ({}, ['没有可检查的 JSON 对象'])
    banned = schema.scan_banned(raw_text) + schema.scan_banned(
        json.dumps(pred.get('_obj'), ensure_ascii=False) if pred.get('_obj') else '')
    return {'tp': tp, 'gold_n': len(gold), 'pred_n': len(got),
            'precision': round(p, 3), 'recall': round(r, 3), 'f1': round(f1, 3),
            'abstained': (not gold and not got),
            'schema_errors': errs, 'banned': sorted(set(banned))}


def _run_one(method, case):
    if method == 'baseline':
        pred = baseline.parse(case['raw_text'])
        pred['_obj'] = {'information_density': pred.get('information_density'),
                        'fields': pred.get('fields')}
    else:
        cfg = load_profile(method)
        pipe = ParsePrototype(cfg)
        if not pipe.available:
            raise SystemExit('【错误】未配置 API Key，无法运行 %s。'
                             '请设置 DREAM_LLM_API_KEY 后再跑。' % method)
        pred = pipe.parse(case['raw_text'])
        pred['_obj'] = None
        if pred['status'] == 'ok':
            obj, _ = schema.extract_json(pred.get('raw') or '')
            pred['_obj'] = obj
    return pred


def run_method(method, cases, verbose=True):
    rows = []
    for c in cases:
        t0 = time.time()
        pred = _run_one(method, c)
        raw = pred.get('raw') or ''
        sc = score_case(c, pred, raw)
        row = {
            'id': c['id'], 'group': c['group'], 'status': pred['status'],
            'error': (pred.get('error') or '')[:160], 'stage': pred.get('stage'),
            'density': pred.get('information_density'),
            'pred': [{'field_type': f.get('field_type'), 'label': f.get('label'),
                      'confidence': f.get('confidence')}
                     for f in (pred.get('fields') or []) if isinstance(f, dict)],
            'gold': c.get('gold') or [],
            'latency_ms': round((time.time() - t0) * 1000, 1),
            'usage': pred.get('usage') or {},
            'repairs': pred.get('repairs', 0),
            'json_ok': pred['status'] == 'ok',
            'schema_ok': pred['status'] == 'ok' and not sc['schema_errors'],
            'p': sc['precision'], 'r': sc['recall'], 'f1': sc['f1'],
            'tp': sc['tp'], 'gold_n': sc['gold_n'], 'pred_n': sc['pred_n'],
            'abstained': sc['abstained'], 'banned': sc['banned'],
            'schema_errors': sc['schema_errors'][:3],
        }
        rows.append(row)
        if verbose:
            print('  %-4s %-6s %-14s P=%.2f R=%.2f F1=%.2f %5.0fms %s'
                  % (row['id'], row['group'], row['status'], row['p'], row['r'],
                     row['f1'], row['latency_ms'],
                     ('解读词=%s' % row['banned']) if row['banned'] else ''))
    return rows


def summarize(method, rows):
    n = len(rows) or 1
    tokens = sum((r['usage'] or {}).get('total_tokens') or 0 for r in rows)
    return {
        'method': method,
        'cases': len(rows),
        'json_ok_rate': round(sum(1 for r in rows if r['json_ok']) / n, 3),
        'schema_ok_rate': round(sum(1 for r in rows if r['schema_ok']) / n, 3),
        'precision': round(sum(r['p'] for r in rows) / n, 3),
        'recall': round(sum(r['r'] for r in rows) / n, 3),
        'f1': round(sum(r['f1'] for r in rows) / n, 3),
        'banned_rate': round(sum(1 for r in rows if r['banned']) / n, 3),
        'abstain_ok': sum(1 for r in rows if r['abstained']),
        'avg_latency_ms': round(sum(r['latency_ms'] for r in rows) / n, 1),
        'tokens': tokens,
        'est_cost_cny': round(tokens / 1_000_000 * ((PRICE_IN + PRICE_OUT) / 2), 5),
        'failures': [r['id'] + ':' + r['status'] for r in rows if not r['json_ok']],
    }


def run_all(methods=('baseline', 'v1', 'v2')):
    data = load_cases()
    cases = data['cases']
    print('评测集：%s（%d 条）' % (data.get('name'), len(cases)))
    results = {}
    for m in methods:
        print('\n=== 方案 %s ===' % m)
        rows = run_method(m, cases)
        results[m] = {'rows': rows, 'summary': summarize(m, rows)}
        s = results[m]['summary']
        print('  汇总：JSON 合法 %.0f%% ｜ Schema 合规 %.0f%% ｜ P=%.2f R=%.2f F1=%.2f'
              ' ｜ 解读词 %.0f%% ｜ 平均 %.0fms ｜ tokens %d'
              % (s['json_ok_rate'] * 100, s['schema_ok_rate'] * 100,
                 s['precision'], s['recall'], s['f1'], s['banned_rate'] * 100,
                 s['avg_latency_ms'], s['tokens']))

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {'when': time.strftime('%Y-%m-%d %H:%M:%S'), 'cases': len(cases),
               'methods': {m: results[m] for m in results}}
    with open(os.path.join(OUT_DIR, 'exp7_eval.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    md = ['| 方案 | 样例 | JSON合法率 | Schema合规率 | 字段P | 字段R | 字段F1 | 解读词出现率 '
          '| 平均耗时(ms) | tokens |',
          '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for m in results:
        s = results[m]['summary']
        md.append('| %s | %d | %.0f%% | %.0f%% | %.2f | %.2f | %.2f | %.0f%% | %.0f | %d |'
                  % (m, s['cases'], s['json_ok_rate'] * 100, s['schema_ok_rate'] * 100,
                     s['precision'], s['recall'], s['f1'], s['banned_rate'] * 100,
                     s['avg_latency_ms'], s['tokens']))
    table = '\n'.join(md)
    with open(os.path.join(OUT_DIR, 'exp7_eval.md'), 'w', encoding='utf-8') as f:
        f.write('# 实验7 评测结果\n\n' + table + '\n')
    print('\n' + table)
    print('\n已保存：rag_data/exp7_eval.json、rag_data/exp7_eval.md')
    return results
