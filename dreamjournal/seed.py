# -*- coding: utf-8 -*-
"""样例数据（实验4 2.2：提供一组可重复使用的样例数据，并说明如何初始化、清空或恢复）。

命令行：
    python main.py --seed     写入 12 条样例梦境与若干解析字段
    python main.py --reset    清空全部数据（恢复为空库）
"""
from . import domain

DEMO = [
    ('2026-09-01', '我梦见在考试，卷子上的字一个都不认识，旁边的人都在写，我很着急。',
     [(domain.FIELD_EMOTION, '焦虑', 0.86, False), (domain.FIELD_SCENE, '考场', 0.93, False),
      (domain.FIELD_SYMBOL, '考试', 0.90, False), (domain.FIELD_SYMBOL, '陌生的字', 0.71, False)]),
    ('2026-09-03', '梦见一片水，怎么也游不到岸，脚下很冷。',
     [(domain.FIELD_EMOTION, '无助', 0.74, False), (domain.FIELD_SCENE, '水边', 0.88, False),
      (domain.FIELD_SYMBOL, '水', 0.91, False)]),
    ('2026-09-05', '有人一直在后面追我，我在楼梯上跑，腿抬不起来。',
     [(domain.FIELD_EMOTION, '恐惧', 0.82, False), (domain.FIELD_SYMBOL, '被追赶', 0.89, False),
      (domain.FIELD_SYMBOL, '楼梯', 0.66, False)]),
    ('2026-09-07', '又梦见考试，这次是找不到考场，在楼里绕。',
     [(domain.FIELD_EMOTION, '焦虑', 0.80, False), (domain.FIELD_SCENE, '教学楼', 0.77, False),
      (domain.FIELD_SYMBOL, '考试', 0.88, False), (domain.FIELD_SYMBOL, '迟到', 0.69, False)]),
    ('2026-09-09', '梦见和前同事吵架，说了很多平时不敢说的话。',
     [(domain.FIELD_EMOTION, '愤怒', 0.72, False), (domain.FIELD_CHARACTER, '前同事', 0.42, True),
      (domain.FIELD_SYMBOL, '争吵', 0.75, False)]),
    ('2026-09-11', '梦见海水涨上来，我在楼顶看。',
     [(domain.FIELD_EMOTION, '紧张', 0.68, False), (domain.FIELD_SYMBOL, '水', 0.84, False),
      (domain.FIELD_SCENE, '楼顶', 0.80, False)]),
    ('2026-09-13', '梦见在楼梯上一直往上走，永远走不到头。',
     [(domain.FIELD_EMOTION, '疲惫', 0.63, False), (domain.FIELD_SYMBOL, '楼梯', 0.79, False)]),
    ('2026-09-15', '梦见考试，这次考的是我完全不会的科目。',
     [(domain.FIELD_EMOTION, '焦虑', 0.83, False), (domain.FIELD_SYMBOL, '考试', 0.87, False)]),
    ('2026-09-17', '梦见被追，跑进一条很长的走廊。',
     [(domain.FIELD_EMOTION, '恐惧', 0.78, False), (domain.FIELD_SYMBOL, '被追赶', 0.85, False),
      (domain.FIELD_SCENE, '走廊', 0.74, False)]),
    ('2026-09-19', '梦到一片很平静的湖水，坐在岸边。',
     [(domain.FIELD_EMOTION, '平静', 0.81, False), (domain.FIELD_SYMBOL, '水', 0.86, False)]),
    ('2026-09-21', '梦见赶不上火车，行李也丢了。',
     [(domain.FIELD_EMOTION, '焦虑', 0.76, False), (domain.FIELD_SYMBOL, '迟到', 0.72, False)]),
    ('2026-09-23', '记不清了，好像在一个很大的房子里。', []),
]


def seed(repo, review, reset=False):
    """写入样例数据；reset=True 时先清空，保证可重复执行。"""
    if reset:
        repo.clear_all()
    made = []
    for d, text, fields in DEMO:
        rec = _new(d, text)
        repo.add(rec)                      # add() 会回填 rec.id
        for ft, label, conf, pending in fields:
            review.add_field(rec.id, ft, label, confidence=conf, needs_confirm=pending)
        if not fields:
            # 无字段的记录标记为“信息量低”，用于演示低信息量状态
            repo.update_status(rec.id, domain.STATUS_DRAFT)
        review.confirm_record(rec.id)
        made.append(rec.id)
    return len(made)


def _new(d, text):
    from datetime import datetime
    return domain.DreamRecord(dream_date=d, raw_text=text,
                              created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


def reset(repo):
    n = repo.count()
    repo.clear_all()
    return n
