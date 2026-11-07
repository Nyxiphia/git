# -*- coding: utf-8 -*-
"""结果校验（实验6 2.3）：模型说“完成”不算完成，必须由程序核对。

两条独立校验：
  · **真值重算**：用一段与工具实现**互不复用**的 SQL 重新统计，得到 ground truth；
    工具结果与它一致，才说明工具本身没算错。
  · **回答核对**：从最终回答里抽出“标签 + 次数”，与真值逐个比对；
    模型改写、漏写、编造数字都会在这里被抓出来。
"""
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# “标签”后跟一个数字，允许中间有 “：”“|”“ ”“次” 等字符
_NUM_AFTER = re.compile(r'[：:\|\s\-—]{0,3}(\d{1,3})\s*(?:次|条)?')


def ground_truth(db_path, field_type, top_n=5, days=0, exclude_pending=True):
    """独立重算（刻意不复用 tools.py 里的实现，避免同一个 bug 两边一致）。"""
    conn = sqlite3.connect(db_path)
    try:
        sql = ('SELECT f.label, COUNT(*) n FROM parsed_field f '
               'INNER JOIN dream_record r ON r.id = f.record_id '
               'WHERE f.field_type = ?')
        params = [field_type]
        if exclude_pending:
            sql += ' AND f.needs_confirm = 0'
        if days and days > 0:
            sql += " AND r.dream_date >= date('now', ?)"
            params.append('-%d day' % days)
        sql += ' GROUP BY f.label ORDER BY n DESC, f.label'
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [{'label': r[0], 'count': r[1]} for r in rows[:top_n]], rows


def extract_claims(answer, labels):
    """从回答里抽取“标签 → 声称的次数”。

    做法：对每个候选标签，在回答里找到它，取**其后最近的一个数字**作为模型声称的次数。
    找不到数字就不计为 claim（不是错误，只是没给数字）。
    """
    claims = {}
    text = answer or ''
    for lb in labels:
        pos = text.find(lb)
        if pos < 0:
            continue
        seg = text[pos + len(lb): pos + len(lb) + 12]
        m = _NUM_AFTER.search(seg)
        if m:
            claims[lb] = int(m.group(1))
    return claims


def check_success(final_answer, trace, task):
    """按 2.1 的成功标准逐条判定。

    task 形如：
      {'field_type':'symbol','top_n':5,'db_path':..., 'export_path':None|'out/xxx.md'}
    返回 {'passed':bool, 'criteria':[{'id','desc','passed','detail'}]}
    """
    field_type = task['field_type']
    top_n = task.get('top_n', 5)
    truth, all_rows = ground_truth(task['db_path'], field_type, top_n, 0, True)
    truth_map = {r['label']: r['count'] for r in truth}

    criteria = []

    # S1：至少一次成功的 field_stats 调用，且结果与真值一致
    s1, s1_detail = False, '没有任何成功的 field_stats 调用'
    for step in trace:
        for call in step.get('tool_calls', []):
            if call.get('tool') != 'field_stats' or not call.get('ok'):
                continue
            got = (call.get('result') or {}).get('top') or []
            got_map = {r['label']: r['n'] for r in got}
            if got_map == truth_map:
                s1, s1_detail = True, ('工具结果与独立重算完全一致（%d 个标签）'
                                       % len(got_map))
            else:
                diff = [k for k in set(got_map) | set(truth_map)
                        if got_map.get(k) != truth_map.get(k)]
                s1, s1_detail = False, '工具结果与真值不一致：%s' % diff
            break
        if s1:
            break
    criteria.append({'id': 'S1', 'desc': '统计工具返回的结果与独立重算一致',
                     'passed': s1, 'detail': s1_detail})

    # S2：最终回答中至少 3 个标签的次数与真值一致
    claims = extract_claims(final_answer, list(truth_map))
    hit = {k: v for k, v in claims.items() if truth_map.get(k) == v}
    wrong = {k: (v, truth_map.get(k)) for k, v in claims.items()
             if truth_map.get(k) != v}
    s2 = len(hit) >= 3 and not wrong
    criteria.append({'id': 'S2', 'desc': '回答中至少 3 个标签的次数与真值一致',
                     'passed': s2,
                     'detail': '一致 %d 个（%s）%s'
                               % (len(hit), '、'.join(hit) or '无',
                                  '；不一致：%s' % wrong if wrong else '')})

    # S3：若导出过文件，文件必须存在且包含同样的标签
    export_calls = [c for step in trace for c in step.get('tool_calls', [])
                    if c.get('tool') == 'export_markdown' and c.get('ok')]
    if export_calls:
        rel = (export_calls[-1].get('result') or {}).get('path')
        fp = os.path.join(ROOT, rel.replace('/', os.sep)) if rel else ''
        exists = bool(fp) and os.path.isfile(fp)
        content = ''
        if exists:
            with open(fp, encoding='utf-8') as f:
                content = f.read()
        in_file = [k for k in hit if k in content]
        s3 = exists and len(in_file) >= 3
        detail = ('导出文件 %s 存在，包含 %d 个已核对的标签' % (rel, len(in_file))
                  if s3 else '导出文件缺失或不含可核对标签（%s）' % rel)
    else:
        s3, detail = True, '本次未调用导出工具，该条不适用（按通过计）'
    criteria.append({'id': 'S3', 'desc': '导出文件的标签与统计一致（未导出则不适用）',
                     'passed': s3, 'detail': detail})

    return {'passed': all(c['passed'] for c in criteria), 'criteria': criteria,
            'truth': truth, 'claims': claims, 'labels_total': len(all_rows)}
