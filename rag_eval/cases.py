# -*- coding: utf-8 -*-
"""实验5 2.5 的固定问题集与判断规则。

7 个问题覆盖三类情况：
  · 单片段可回答：Q1、Q3、Q5
  · 多片段综合：Q2、Q4
  · 资料无答案 / 含义不清：Q6（无答案）、Q7（有答案，用于区分“凭已有知识答”与“资料支持答”）

每个问题给出：
  must_have   回答中必须出现的事实要点（关键词，全部命中才算“要点完整”）
  must_not    回答中出现即视为“无依据/幻觉”的说法
  cite_hint   期望引用的来源文档（RAG 组用于检查引用可靠性）
  judge       人工判断用的标准描述
"""

import re

# 引号内出现的“禁用提法”不算违规：正确回答往往会**引用并否定**这些说法
_QUOTED = re.compile(r'[「“"『]([^」”"』]{0,60})[」”"』]')


def _in_quote(answer, kw):
    for m in _QUOTED.finditer(answer or ''):
        if kw in m.group(1):
            return True
    return False


CASES = [
    {
        'id': 'Q1', 'kind': '单片段',
        'question': '这个项目为什么不做解梦功能？',
        'must_have': ['象征', '标准', '预测'],
        'must_not': ['水代表', '梦见水意味着', '预示着你将会'],
        'cite_hint': '实验2',
        'judge': '应说明：删掉解梦知识库，因为象征含义没有客观标准、模型会输出“这预示着你……”式断言；'
                 '若回答给出具体梦境象征解释即为无依据。',
    },
    {
        'id': 'Q2', 'kind': '多片段综合',
        'question': '梦境数据存在哪里？会不会被上传？',
        'must_have': ['SQLite', '本机', '导出'],
        'must_not': ['云端数据库', '上传到服务器'],
        'cite_hint': '实验2、实验3',
        'judge': '应说明：本地 SQLite 单文件、默认仅本机、音频与原文不随仓库提交；'
                 '上传仅发生在解析时且只传纯文本。',
    },
    {
        'id': 'Q3', 'kind': '单片段',
        'question': '为什么选 SQLite 而不是 ORM？',
        'must_have': ['单', '标准库', '部署'],
        'must_not': ['SQLAlchemy 是必须的'],
        'cite_hint': '实验3',
        'judge': '应对应 ADR-02：单用户单机、无并发、标准库零部署、一个文件便于备份删除；'
                 '并说明拒绝 ORM 的理由。',
    },
    {
        'id': 'Q4', 'kind': '多片段综合',
        'question': '如果模型接口不可用，系统还能用吗？怎么降级？',
        'must_have': ['降级', '手动', '原文'],
        'must_not': ['无法使用', '系统崩溃'],
        'cite_hint': '实验2、实验3、实验5',
        'judge': '应说明：记录不受影响、原文保留、重试队列、降级为手动标签模式；'
                 '需综合实验2 的降级方案与实验3/4 的分层与异常处理。',
    },
    {
        'id': 'Q5', 'kind': '单片段（易幻觉）',
        'question': '这个项目实际用了哪个界面框架？',
        'must_have': ['tkinter'],
        'must_not': ['PySide6 实现', 'Vue'],
        'cite_hint': '实验4',
        'judge': '关键陷阱：实验3 的 ADR-01 选的是 PySide6，实验4 因环境无法安装改为 tkinter。'
                 '若回答仍说“使用 PySide6”即为过时/幻觉，因为最终实现是 tkinter。',
    },
    {
        'id': 'Q6', 'kind': '资料无答案',
        'question': '这个软件现在有多少注册用户？',
        'must_have': ['资料不足'],
        'must_not': ['万用户', '个用户', '注册量达'],
        'cite_hint': '',
        'judge': '知识库里没有用户数据。正确行为是明确回答“资料不足”，'
                 '任何具体数字都算编造。',
    },
    {
        'id': 'Q7', 'kind': '资料有答案（对照 Q6）',
        'question': '这个软件支持多设备同步吗？',
        'must_have': ['不支持', '排除'],
        'must_not': ['已支持同步', '可以同步'],
        'cite_hint': '实验2',
        'judge': '实验2 的 MVP 排除清单里明确写了“账号体系与多设备同步”不做。'
                 '正确行为是依据资料回答“不支持/未实现”，而不是凭常识泛泛解释同步方案。',
    },
]


def auto_judge(case, answer):
    """按关键词做一次可复现的自动判定，结果**仅供人工复核**，不能直接当结论。

    已知局限：关键词匹配不理解否定与语境。例如正确回答会引用并否定“这预示着你……”，
    若不排除引号内的内容，就会被误判为“无依据/错误”。因此这里做两件事：
      1) 引号内出现的禁用说法不计为违规；
      2) 在返回值里标注 auto_only=True，提示必须人工复核。

    返回 dict：points_hit / points_total / missing / violated / verdict / auto_only
    """
    a = answer or ''
    hit = [k for k in case['must_have'] if k in a]
    missing = [k for k in case['must_have'] if k not in a]
    violated = [k for k in case['must_not'] if k in a and not _in_quote(a, k)]
    quoted_only = [k for k in case['must_not'] if k in a and _in_quote(a, k)]
    if violated:
        verdict = '无依据/错误'
    elif not missing:
        verdict = '要点完整'
    elif hit:
        verdict = '部分命中'
    else:
        verdict = '未命中'
    return {'points_hit': len(hit), 'points_total': len(case['must_have']),
            'missing': missing, 'violated': violated,
            'violated_in_quote_ignored': quoted_only,
            'verdict': verdict, 'auto_only': True}
