# -*- coding: utf-8 -*-
"""输出 Schema 与结果检查（实验7 2.2 / 2.4）。

这里只放**判定规则**，不放流程：
  · 枚举与上限：一次输出里允许出现的字段类型、密度值、标签长度、字段数量；
  · `check_schema`：把模型返回的对象逐项检查，返回 (clean, errors)；
  · `extract_json`：从模型自由文本里取出 JSON（容忍 ```json 围栏）；
  · `BANNED`：实验中反复强调的“只描述不解读”，命中即判为不合格。

注意：`check_schema` **同时被评测脚本和 v2 的运行时使用**。
评测脚本用它来度量 v1（不校验）的合规率，运行时用它来拦截不合格输出——
两处用同一份规则，保证“度量的标准”和“拦截的标准”一致。
"""
import json
import re

FIELD_TYPES = ('emotion', 'character', 'scene', 'symbol')
FIELD_TYPE_CN = {'emotion': '情绪', 'character': '人物',
                 'scene': '场景', 'symbol': '意象'}
DENSITY_VALUES = ('high', 'medium', 'low')

LABEL_MAX_CHARS = 12
FIELDS_MAX = 12

# 出现即视为“解读/预测/诊断”，与实验2 的 CH-01（删除解梦知识库）一致
BANNED = ('预示', '意味着', '象征', '吉凶', '运势', '征兆', '预示着什么',
          '诊断', '治疗', '建议你', '说明你', '代表你', '命中注定')

_PUNCT = re.compile(r'[，。！？、；：“”‘’（）()\[\]{}<>《》…—\-·,.!?;:]')


def extract_json(text):
    """从模型输出里取出 JSON 对象。

    模型常常在 JSON 外面套 ```json 围栏，或者在前后加一句“好的，结果如下”。
    这里先去掉围栏，再取第一个 `{` 到最后一个 `}`。
    """
    if not text:
        return None, '模型返回空内容'
    s = text.strip()
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```$', s, re.S)
    if fence:
        s = fence.group(1).strip()
    if not s.startswith('{'):
        i, j = s.find('{'), s.rfind('}')
        if i >= 0 and j > i:
            s = s[i:j + 1]
    try:
        return json.loads(s), None
    except json.JSONDecodeError as e:
        return None, '不是合法 JSON：%s（原文前 120 字：%s）' % (e, s[:120])


def check_schema(obj):
    """检查模型输出是否符合约定，返回 (clean, errors)。"""
    errors = []
    if not isinstance(obj, dict):
        return {}, ['顶层必须是 JSON 对象，实际是 %s' % type(obj).__name__]

    density = obj.get('information_density')
    if density is not None and density not in DENSITY_VALUES:
        errors.append('information_density 取值 “%s” 不在 %s 之内'
                      % (density, '/'.join(DENSITY_VALUES)))

    raw_fields = obj.get('fields')
    if raw_fields is None:
        errors.append('缺少 fields 字段')
        raw_fields = []
    if not isinstance(raw_fields, list):
        errors.append('fields 必须是数组，实际是 %s' % type(raw_fields).__name__)
        raw_fields = []
    if len(raw_fields) > FIELDS_MAX:
        errors.append('fields 数量 %d 超过上限 %d' % (len(raw_fields), FIELDS_MAX))

    clean_fields = []
    for idx, f in enumerate(raw_fields):
        tag = '第 %d 个字段' % (idx + 1)
        if not isinstance(f, dict):
            errors.append('%s 不是对象' % tag)
            continue
        ft = f.get('field_type')
        label = (f.get('label') or '').strip() if isinstance(f.get('label'), str) else ''
        conf = f.get('confidence')
        if ft not in FIELD_TYPES:
            errors.append('%s 的 field_type “%s” 不在 %s 之内'
                          % (tag, ft, '/'.join(FIELD_TYPES)))
            continue
        if not label:
            errors.append('%s 的 label 为空' % tag)
            continue
        if len(label) > LABEL_MAX_CHARS:
            errors.append('%s 的 label “%s” 超过 %d 字'
                          % (tag, label, LABEL_MAX_CHARS))
            continue
        if _PUNCT.search(label):
            errors.append('%s 的 label “%s” 含标点，应为简短名词' % (tag, label))
            continue
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            errors.append('%s 的 confidence 不是数字：%r' % (tag, conf))
            continue
        if not 0.0 <= conf <= 1.0:
            errors.append('%s 的 confidence %r 不在 [0,1]' % (tag, conf))
            continue
        hit = [w for w in BANNED if w in label]
        if hit:
            errors.append('%s 的 label 含解读性措辞 %s' % (tag, hit))
            continue
        clean_fields.append({'field_type': ft, 'label': label,
                             'confidence': round(conf, 3)})

    return {'information_density': density if density in DENSITY_VALUES else None,
            'fields': clean_fields}, errors


def scan_banned(text):
    """检查整段文本（不只是 label）里是否出现解读性措辞。"""
    return [w for w in BANNED if w and w in (text or '')]
