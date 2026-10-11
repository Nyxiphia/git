# -*- coding: utf-8 -*-
"""实验4 测试用例（对照实验2 验收条件与实验3 表 3-8 的失败情况设计）。

运行：
    python tests/run_tests.py

每个用例独立使用临时数据库，互不影响；输出 通过/失败 与失败原因，
可直接用于实验4 2.5 的“初版结果 / 修订版复测结果”记录。
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dreamjournal import domain                                    # noqa: E402
from dreamjournal.services import (ValidationError, RecordService,  # noqa: E402
                                   ReviewService, TrendService, ExportService)
from dreamjournal.store import DreamRepository                      # noqa: E402

# 测试产物统一放在工程目录内，便于清理与复现
TMP_ROOT = os.path.join(ROOT, 'data', '_test_tmp')
_seq = [0]


class Case:
    def __init__(self, cid, title, expect, fn):
        self.cid, self.title, self.expect, self.fn = cid, title, expect, fn


def fresh(**kw):
    """每个用例一个独立数据库（位于工程目录内，便于清理）。"""
    _seq[0] += 1
    d = os.path.join(TMP_ROOT, 'case%02d' % _seq[0])
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    repo = DreamRepository(os.path.join(d, 'test.db'))
    repo.init_schema()
    svc = {'record': RecordService(repo), 'review': ReviewService(repo),
           'trend': TrendService(repo), 'export': ExportService(repo)}
    return repo, svc


# ---------------- 用例实现 ----------------
def tc01_normal_record():
    """TC-01 正常记录：合法文本应落库并处于 draft。"""
    repo, svc = fresh()
    rec = svc['record'].create('我梦见在考试，卷子上的字一个都不认识。')
    assert rec.id, '未返回记录 id'
    got = svc['record'].get(rec.id)
    assert got is not None and got.status == domain.STATUS_DRAFT, '状态不是 draft'
    assert repo.count() == 1, '记录数应为 1'
    return '记录 #%d 已落库，status=draft' % rec.id


def tc02_empty_input():
    """TC-02 空输入：空白文本应被拒绝并给出明确错误（对应 NFR 与 2.5）。"""
    repo, svc = fresh()
    for bad in ('', '   ', '\n\t '):
        try:
            svc['record'].create(bad)
        except ValidationError as e:
            continue
        raise AssertionError('空白输入 %r 未被拒绝（应抛 ValidationError）' % bad)
    assert repo.count() == 0, '被拒绝的输入不应落库'
    return '空白输入全部被拒绝，未产生脏数据'


def tc03_text_too_long():
    """TC-03 超长文本：超过 2000 字应被拒绝（实验3 表 3-7 约束）。"""
    repo, svc = fresh()
    over = '梦' * (domain.RAW_TEXT_MAX + 1)
    try:
        svc['record'].create(over)
    except ValidationError:
        assert repo.count() == 0
        return '2001 字被拒绝'
    raise AssertionError('超长文本未被拒绝')


def tc04_empty_dataset():
    """TC-04 空数据：无记录时列表返回空，趋势服务给出提示而不是崩溃。"""
    repo, svc = fresh()
    rows = svc['record'].list_recent()
    assert rows == [], '空库应返回空列表'
    r = svc['trend'].top_symbols()
    assert isinstance(r, dict) and r.get('insufficient') is True, \
        '记录不足时应返回 insufficient 提示'
    return '空库列表为空；趋势返回“样本过少”提示'


def tc05_missing_record():
    """TC-05 数据不存在：查询不存在的 id 应返回 None，不抛异常。"""
    repo, svc = fresh()
    got = svc['record'].get(9999)
    assert got is None, '不存在的记录应返回 None'
    try:
        svc['review'].confirm_record(9999)
    except ValidationError:
        return '查询返回 None；确认不存在的记录被拒绝'
    raise AssertionError('确认不存在的记录应抛 ValidationError')


def tc06_invalid_date():
    """TC-06 格式错误：非法日期被拒绝；非规范但可解析的日期被规范化。

    用例修正说明：本用例初稿只断言“2026-9-7 应被拒绝”，实测发现
    Python strptime 接受非零填充写法。经分析，拒绝它是过度严格且损害易用性，
    真正的风险是它会让字符串排序与日期筛选失效，因此改为断言“规范化”。
    """
    repo, svc = fresh()
    # 空字符串不在其中：create() 的约定是“日期可省略，省略或留空取今天”
    for bad in ('2026-13-45', '2026/09/27', 'abc', '2026-02-30'):
        try:
            svc['record'].create('测试梦境内容', dream_date=bad)
        except ValidationError:
            continue
        raise AssertionError('非法日期 %r 未被拒绝' % bad)

    rec = svc['record'].create('非规范日期的梦。', dream_date='2026-9-7')
    got = svc['record'].get(rec.id)
    assert got.dream_date == '2026-09-07', \
        '非规范日期未规范化，实际入库为 %r' % got.dream_date

    svc['record'].create('较早的梦。', dream_date='2026-09-10')
    svc['record'].create('较晚的梦。', dream_date='2026-09-20')
    order = [r.dream_date for r in svc['record'].list_recent()]
    assert order == sorted(order, reverse=True), '字符串排序不正确：%s' % order
    return '4 种非法日期被拒绝；2026-9-7 规范化为 2026-09-07，排序正确'


def tc07_manual_label_and_confirm():
    """TC-07 人工标注与确认：字段可增改，确认后状态为 confirmed。"""
    repo, svc = fresh()
    rec = svc['record'].create('我梦见在考场里，旁边的人都在写。')
    f1 = svc['review'].add_field(rec.id, domain.FIELD_SCENE, '考场')
    f2 = svc['review'].add_field(rec.id, domain.FIELD_CHARACTER, '前同事',
                                 confidence=0.42, needs_confirm=True)
    svc['review'].update_field(f1.id, '阶梯教室')
    got = {f.field_type: f for f in svc['review'].list_fields(rec.id)}
    assert got[domain.FIELD_SCENE].label == '阶梯教室', '字段修正未生效'
    assert got[domain.FIELD_SCENE].user_edited is True, 'user_edited 未置位'
    out = svc['review'].confirm_record(rec.id)
    assert svc['record'].get(rec.id).status == domain.STATUS_CONFIRMED, '状态未变 confirmed'
    assert out == 1, '仍存在待确认字段时 confirm_record 应返回待确认数量'
    return '字段可增可改；确认返回 1 个待确认项'


def tc08_pending_excluded_from_trend():
    """TC-08 设计约束：needs_confirm 的字段不计入趋势统计（实验3 图 3-3）。"""
    repo, svc = fresh()
    for i in range(domain.TREND_MIN_RECORDS):
        r = svc['record'].create('第 %d 个梦：又梦见考试。' % i)
        svc['review'].add_field(r.id, domain.FIELD_SYMBOL, '考试')
        svc['review'].confirm_record(r.id)
    r = svc['record'].create('第 11 个梦：梦到一片水。')
    svc['review'].add_field(r.id, domain.FIELD_SYMBOL, '水', needs_confirm=True)
    svc['review'].confirm_record(r.id)
    res = svc['trend'].top_symbols()
    labels = [x['label'] for x in res.get('symbols', [])]
    assert '考试' in labels, '已确认字段应计入统计'
    assert '水' not in labels, '待确认字段不应计入统计'
    return '已确认字段计入统计；待确认字段被排除'


def tc09_search():
    """TC-09 关键词检索（UC-05），含 SQL 注入字符的安全测试。"""
    repo, svc = fresh()
    svc['record'].create('梦见在考试，卷子一片空白。')
    svc['record'].create('梦见一片水，怎么也游不到岸。')
    assert len(svc['record'].search('考试')) == 1, '关键词检索结果不正确'
    evil = "x'; DROP TABLE dream_record; --"
    svc['record'].search(evil)          # 不应抛异常、不应破坏数据
    assert repo.count() == 2, '注入型输入破坏了数据表'
    return '关键词命中正确；注入型输入未破坏数据'


def tc10_delete_and_export():
    """TC-10 删除与导出：删除后检索不到；导出对不可写路径给出错误。"""
    repo, svc = fresh()
    r1 = svc['record'].create('要删除的梦。')
    r2 = svc['record'].create('要保留的梦。')
    svc['record'].delete(r1.id)
    assert svc['record'].get(r1.id) is None, '删除后仍能查到'
    assert repo.count() == 1, '记录数不正确'

    out = os.path.join(TMP_ROOT, 'case%02d' % _seq[0], 'export', 'dreams.md')
    n = svc['export'].export_markdown(out)
    assert n == 1 and os.path.isfile(out), '导出失败'
    with open(out, encoding='utf-8') as f:
        content = f.read()
    assert '要保留的梦' in content and '要删除的梦' not in content, '导出内容不正确'

    try:
        svc['export'].export_markdown(os.path.join(out, 'sub', 'x.md'))
    except ValidationError:
        return '删除生效；导出成功且对不可写路径报错'
    raise AssertionError('不可写路径应抛 ValidationError')


CASES = [
    Case('TC-01', '正常记录并落库', '落库成功，status=draft', tc01_normal_record),
    Case('TC-02', '空输入被拒绝', '抛 ValidationError，不落库', tc02_empty_input),
    Case('TC-03', '超长文本被拒绝', '超过 2000 字被拒绝', tc03_text_too_long),
    Case('TC-04', '空数据不崩溃', '空列表 + 趋势提示样本过少', tc04_empty_dataset),
    Case('TC-05', '记录不存在', '返回 None，确认时报错', tc05_missing_record),
    Case('TC-06', '非法日期格式', '4 种非法格式被拒绝', tc06_invalid_date),
    Case('TC-07', '人工标注与确认', '字段可增改，确认生效', tc07_manual_label_and_confirm),
    Case('TC-08', '待确认字段不计入趋势', '确认的计入、待确认的排除', tc08_pending_excluded_from_trend),
    Case('TC-09', '关键词检索与注入安全', '命中正确且数据未被破坏', tc09_search),
    Case('TC-10', '删除与导出', '删除生效，导出可用且路径错误有反馈', tc10_delete_and_export),
]


def main():
    passed, failed = 0, 0
    lines = []
    for c in CASES:
        try:
            detail = c.fn()
            passed += 1
            lines.append('PASS  %s  %s  |  %s' % (c.cid, c.title, detail))
        except NotImplementedError as e:
            failed += 1
            lines.append('FAIL  %s  %s  |  未实现：%s' % (c.cid, c.title, e))
        except AssertionError as e:
            failed += 1
            lines.append('FAIL  %s  %s  |  断言失败：%s' % (c.cid, c.title, e))
        except Exception as e:      # noqa: BLE001
            failed += 1
            lines.append('ERROR %s  %s  |  %s: %s'
                         % (c.cid, c.title, type(e).__name__, e))
    for ln in lines:
        print(ln)
    print('\n合计 %d 个用例：通过 %d，失败 %d' % (len(CASES), passed, failed))
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
