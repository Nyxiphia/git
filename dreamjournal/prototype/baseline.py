# -*- coding: utf-8 -*-
"""无 AI 基线（实验7 2.5 的对照方案之一）。

做法：一张关键词 → 标签的对照表，命中即输出该标签，置信度固定 0.5。
它不代表任何智能，只用来回答一个问题：**“不调用模型，靠规则能做到什么程度？”**
如果模型方案打不过这张表，那这次 AI 原型就没有存在价值。
"""
import re

# 关键词表刻意只用“常见词 + 同义写法”，不针对评测样例逐条调优
EMOTION_KW = {
    '焦虑': ['着急', '紧张', '担心', '赶不上', '找不到', '来不及', '慌'],
    '恐惧': ['怕', '恐惧', '吓', '追赶', '追我', '被追'],
    '愤怒': ['生气', '愤怒', '吵架', '吵', '火'],
    '无助': ['无助', '游不到', '动不了', '抬不起', '没办法'],
    '疲惫': ['累', '疲惫', '走不到头', '一直走'],
    '紧张': ['紧张', '涨上来', '心慌'],
    '平静': ['平静', '安宁', '舒服', '安静'],
}
SCENE_KW = {
    '考场': ['考试', '考场', '卷子'],
    '教学楼': ['教学楼', '教室', '教学楼里'],
    '楼顶': ['楼顶', '天台', '屋顶'],
    '走廊': ['走廊', '过道'],
    '水边': ['水边', '岸边', '湖', '海', '水'],
    '房间': ['房间', '房子', '屋'],
}
SYMBOL_KW = {
    '考试': ['考试', '卷子', '考'],
    '水': ['水', '湖', '海', '河', '雨'],
    '楼梯': ['楼梯', '台阶'],
    '被追赶': ['追', '逃', '跑'],
    '迟到': ['迟到', '赶不上', '来不及', '火车'],
    '争吵': ['吵架', '争吵', '吵'],
    '陌生的字': ['不认识', '陌生'],
}
CHARACTER_KW = {
    '同事': ['同事'],
    '朋友': ['朋友'],
    '家人': ['家人', '爸妈', '父母'],
    '陌生人': ['陌生人', '有人'],
}

FIXED_CONF = 0.5


def _match(text, table):
    out = []
    for label, kws in table.items():
        if any(k in text for k in kws):
            out.append(label)
    return out


def parse(text):
    """返回与原型同构的结果，便于同一套评测脚本度量。"""
    t = (text or '').strip()
    fields = []
    for ftype, table in (('emotion', EMOTION_KW), ('character', CHARACTER_KW),
                         ('scene', SCENE_KW), ('symbol', SYMBOL_KW)):
        for label in _match(t, table):
            fields.append({'field_type': ftype, 'label': label,
                           'confidence': FIXED_CONF})
    density = 'high' if len(fields) >= 4 else ('medium' if fields else 'low')
    return {
        'status': 'ok',
        'information_density': density,
        'fields': fields,
        'errors': [],
        'raw': '',
        'usage': {},
        'latency_ms': 0.0,
        'repairs': 0,
        'profile': 'baseline',
        'chars': len(t),
        'hits': len(fields),
        '_note': '关键词匹配，非模型',
    }
