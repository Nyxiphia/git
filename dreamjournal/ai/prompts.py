# -*- coding: utf-8 -*-
"""AI 适配层 —— Prompt 模板（对应实验3 表 3-5 的 PromptTemplate）。

v1 → v2 的修改依据见实验5 2.2；两个版本都保留，便于复现“改 Prompt 前后”的差异。

模板设计原则（与实验2 的结论一致）：
  · 只回答“资料里写了什么”，禁止推断产品未实现的能力，不做解梦式解读；
  · 资料不足时必须明确说“资料不足”，不得编造；
  · 每条结论都要能落到 [n] 来源编号上，便于界面回链到原片段。
"""

PROMPT_VERSIONS = ('v1', 'v2')
DEFAULT_VERSION = 'v2'

SYSTEM_V1 = '你是一个项目文档助手，请根据资料回答问题。'

SYSTEM_V2 = (
    '你是一名严谨的项目文档助手，服务对象是本项目的开发者。\n'
    '规则：\n'
    '1. 只能依据【资料】中的内容回答，不得使用资料之外的知识，不得推测产品尚未实现的功能；\n'
    '2. 每条结论都要在后面标注来源编号，形如 [1]、[2]；\n'
    '3. 如果资料不足以回答，只输出一行“资料不足：<缺少什么>”，不要编造；\n'
    '4. 不要做梦境象征解读、吉凶预测或医学诊断，这类问题一律按第 3 条处理；\n'
    '5. 回答使用简体中文，先给结论，再列依据。'
)

FORMAT_V2 = (
    '输出格式：\n'
    '【结论】一到三句话直接回答问题。\n'
    '【依据】逐条列出，每条以 [编号] 开头，后接简短说明。\n'
    '资料不足时只输出：【结论】资料不足：<缺少什么>'
)


def _format_context(chunks):
    """把检索片段渲染成带编号的【资料】块。"""
    if not chunks:
        return '（无检索资料）'
    lines = []
    for c in chunks:
        lines.append('[%d] 文档：《%s》 位置：%s 来源：%s\n%s'
                     % (c['rank'], c['doc_title'], c['locator'], c['source'], c['text']))
    return '\n\n'.join(lines)


def build_messages(question, chunks, version=DEFAULT_VERSION, history=None):
    """组装一次完整输入。

    返回 (messages, meta)：messages 是 OpenAI 兼容的对话数组，
    meta 记录本次输入的组装信息（版本、字符数、片段数、是否含历史），供 2.2 统计。
    """
    if version not in PROMPT_VERSIONS:
        raise ValueError('未知 Prompt 版本：%r' % version)

    if version == 'v1':
        # v1：一句话系统提示 + 资料 + 问题，没有引用要求、没有不足判定、没有格式约束
        user = '资料：\n%s\n\n问题：%s' % (_format_context(chunks), question)
        messages = [{'role': 'system', 'content': SYSTEM_V1},
                    {'role': 'user', 'content': user}]
    else:
        user = ('【资料】\n%s\n\n【用户问题】\n%s\n\n%s'
                % (_format_context(chunks), question, FORMAT_V2))
        messages = [{'role': 'system', 'content': SYSTEM_V2}]
        for h in (history or [])[-4:]:          # 多轮：仅保留最近 4 条，避免上下文膨胀
            messages.append({'role': h['role'], 'content': h['content']})
        messages.append({'role': 'user', 'content': user})

    chars = sum(len(m['content']) for m in messages)
    meta = {
        'version': version,
        'messages': len(messages),
        'chars': chars,
        'est_tokens': int(chars / 1.6),          # 粗估：中文约 1.6 字符/token
        'chunks': len(chunks),
        'has_history': bool(history),
        'has_citation_rule': '来源编号' in SYSTEM_V2 and version == 'v2',
        'has_refusal_rule': '资料不足' in SYSTEM_V2 and version == 'v2',
        'has_format_rule': version == 'v2',
    }
    return messages, meta


def render_full_input(messages):
    """把 messages 渲染成可直接贴进报告的“实际发送的完整输入”。"""
    out = []
    for m in messages:
        out.append('=== role: %s ===\n%s' % (m['role'], m['content']))
    return '\n\n'.join(out)
