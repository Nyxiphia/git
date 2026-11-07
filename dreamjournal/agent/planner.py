# -*- coding: utf-8 -*-
"""规划器（实验6 2.3）：决定“下一步做什么”的那一方。

两种实现，接口相同（`chat(messages) -> LLMResult`）：
  · **LLMPlanner**：真实模型，走 OpenAI 兼容的 function calling；
    工具 Schema 随请求发出，模型返回 tool_calls 或最终回答。
  · **ScriptedPlanner**：**不是模型**，按预先写好的脚本回放固定动作，
    只用于在无网络环境下验证 Harness 的控制流（步数、超时、确认、错误反馈）。
    它的输出一律带 `scripted=True` 标记，绝不能当成模型能力。
"""
import json

from dreamjournal.ai.client import LLMResult


class LLMPlanner:
    name = 'llm'

    def __init__(self, client, tool_schemas, max_tokens=800):
        self.client = client
        self.tool_schemas = tool_schemas
        self.max_tokens = max_tokens
        self.scripted = False

    def describe(self):
        d = self.client.describe()
        d['planner'] = 'llm'
        return d

    def chat(self, messages):
        return self.client.chat(messages, tools=self.tool_schemas,
                                max_tokens=self.max_tokens)


def format_stats_answer(result, prefix='【反射式，非模型】'):
    """把 field_stats 的结果格式化成“标签 N 次”形式的最终回答。"""
    lines = ['%s依据 field_stats 的返回结果整理：' % prefix]
    for r in (result or {}).get('top', []):
        lines.append('%s %d 次' % (r['label'], r['n']))
    lines.append('（口径：%s，已排除待确认字段 %d 个）'
                 % ((result or {}).get('field_type'),
                    (result or {}).get('excluded_pending', 0)))
    return '\n'.join(lines)


def last_tool_result(messages, tool_name=None):
    """从上下文里取最近一条成功的工具结果。"""
    for m in reversed(messages):
        if m.get('role') != 'tool':
            continue
        if tool_name and m.get('name') != tool_name:
            continue
        try:
            payload = json.loads(m.get('content') or '{}')
        except json.JSONDecodeError:
            continue
        if payload.get('ok'):
            res = payload.get('result')
            if tool_name or (isinstance(res, dict) and 'top' in res):
                return res
    return None


class ReflexPlanner:
    """确定性“反射式”规划器：**不是模型**，但真实走完 Agent 循环。

    行为：第一轮提出一次 `field_stats` 调用；拿到工具结果后，把结果格式化成最终回答。
    用途：在无网络环境下验证“工具结果确实被写回上下文并被后续决策使用”——
    如果工具算错了，这里的回答也会跟着错，因此它检验的是**回路**而不是模型能力。
    """

    name = 'reflex'
    scripted = True

    def __init__(self, field_type='symbol', top_n=5,
                 model_name='reflex-not-a-model'):
        self.field_type = field_type
        self.top_n = top_n
        self.model_name = model_name
        self.called = False

    def describe(self):
        return {'planner': 'reflex', 'model': self.model_name, 'offline': True,
                'scripted': True}

    def chat(self, messages):
        # 从上下文里找最近一条成功的 field_stats 结果
        last = None
        for m in reversed(messages):
            if m.get('role') == 'tool' and m.get('name') == 'field_stats':
                try:
                    payload = json.loads(m.get('content') or '{}')
                except json.JSONDecodeError:
                    continue
                if payload.get('ok'):
                    last = payload.get('result')
                    break

        if last is None and not self.called:
            self.called = True
            calls = [{'id': 'reflex_1', 'name': 'field_stats',
                      'arguments': json.dumps({'field_type': self.field_type,
                                               'top_n': self.top_n},
                                              ensure_ascii=False)}]
            return LLMResult(text='', model=self.model_name, usage={},
                             latency_ms=0.0, offline=True, tool_calls=calls)

        if last is None:
            return LLMResult(text='【反射式，非模型】工具没有返回可用结果，无法给出统计。',
                             model=self.model_name, usage={}, latency_ms=0.0,
                             offline=True)

        lines = ['【反射式，非模型】依据 field_stats 的返回结果整理：']
        for r in last.get('top', []):
            lines.append('%s %d 次' % (r['label'], r['n']))
        lines.append('（口径：%s，已排除待确认字段 %d 个）'
                     % (last.get('field_type'), last.get('excluded_pending', 0)))
        return LLMResult(text='\n'.join(lines), model=self.model_name, usage={},
                         latency_ms=0.0, offline=True)


class ScriptedPlanner:
    """按脚本回放动作，用于离线验证 Harness。

    script 是一个列表，每项要么是
        {'tool': 'field_stats', 'args': {...}}          → 模拟模型提出一次工具调用
        {'text': '最终回答……'}                          → 模拟模型给出最终回答
    每被调用一次消费一项；用完后重复最后一项（便于构造“达到步数上限”）。
    """
    name = 'scripted'

    def __init__(self, script, model_name='scripted-not-a-model'):
        self.script = list(script) or [{'text': '【脚本回放】脚本为空'}]
        self.i = 0
        self.scripted = True
        self.model_name = model_name

    def describe(self):
        return {'planner': 'scripted', 'model': self.model_name, 'offline': True,
                'scripted': True, 'steps_scripted': len(self.script)}

    def chat(self, messages):
        item = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        if 'tool' in item:
            calls = [{'id': 'call_%d' % self.i, 'name': item['tool'],
                      'arguments': json.dumps(item.get('args') or {},
                                              ensure_ascii=False)}]
            return LLMResult(text='', model=self.model_name, usage={},
                             latency_ms=0.0, offline=True, tool_calls=calls)
        if item.get('text_from_last_tool'):
            # 脚本只规定“该收尾了”，回答内容由真实工具结果生成——
            # 这样如果工具算错，回答也会错，成功校验才有意义。
            res = last_tool_result(messages)
            text = (format_stats_answer(res, '【脚本回放，非模型】')
                    if res else '【脚本回放，非模型】没有可用的工具结果。')
            return LLMResult(text=text, model=self.model_name, usage={},
                             latency_ms=0.0, offline=True)
        return LLMResult(text=item.get('text', ''), model=self.model_name,
                         usage={}, latency_ms=0.0, offline=True)
