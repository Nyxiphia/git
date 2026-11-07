# -*- coding: utf-8 -*-
"""运行时 Harness（实验6 2.3 / 2.4）：组织模型与工具运行的外围程序。

控制流程（全部由程序执行，不依赖提示词）：

    接收目标 → [停止检查] → 模型提出调用请求 → 参数/权限检查 → （需确认则问用户）
             → 执行工具 → 结果写回上下文 → 回到停止检查
             → 模型给出最终回答 → **程序核对成功标准** → 结束

一步如何计数：**一次模型回复算一步**，同一条回复里包含的多个工具调用仍算这一步。
停止检查有两个位置：每轮模型调用之前，以及每个工具执行之前（总时限）。

关键限制都是硬编码在代码里的：工具白名单、参数 Schema、写路径白名单、
最大步数、单次工具超时、总运行时限、连续错误上限。提示词里没有任何一条“限制”是唯一防线。
"""
import json
import os
import random
import re
import time
import traceback

from dreamjournal.agent import tools, verify
from dreamjournal.ai.client import LLMError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(ROOT, 'runs')

_KEY_LIKE = re.compile(r'(sk-|Bearer\s+)[A-Za-z0-9_\-]{6,}')

SYSTEM_PROMPT = (
    '你是一个单 Agent，任务是用工具查清本机梦境数据的统计结果并回答。\n'
    '规则：\n'
    '1. 只能通过提供的工具获取数据，不要编造数字；\n'
    '2. 需要数据就调用工具，拿到结果后再决定下一步；\n'
    '3. 工具返回错误时，按错误信息修正参数后重试，不要原样重复同一个错误调用；\n'
    '4. 导出文件是写操作，会请求用户确认；用户拒绝就不要重试；\n'
    '5. 得到足够数据后，用「标签 + 次数」的形式给出最终回答，至少列出 3 个标签。'
)

USER_TEMPLATE = (
    '任务：统计本机梦境记录中「{field_type}」类型的标签出现次数，给出前 {top_n} 名，'
    '并把统计结果导出为 out/dream_stats.md。\n'
    '统计口径：排除待确认字段（needs_confirm=1）。\n'
    '输出要求：最终回答里用「标签 次数」逐条列出，例如“焦虑 7 次”。'
)


def _redact(text):
    """日志脱敏：密钥绝不落盘。"""
    return _KEY_LIKE.sub(lambda m: m.group(1) + '***', str(text))


def new_run_id():
    return '%s-%04d' % (time.strftime('%Y%m%d-%H%M%S'), random.randint(0, 9999))


class Harness:
    def __init__(self, planner, ctx, task, max_steps=6, wall_clock=120.0,
                 max_retries=1, max_consecutive_errors=3, confirm_fn=None,
                 log_dir=LOG_DIR, verbose=False):
        self.planner = planner
        self.ctx = ctx
        self.task = task
        self.max_steps = max_steps
        self.wall_clock = wall_clock
        self.max_retries = max_retries
        self.max_consecutive_errors = max_consecutive_errors
        self.confirm_fn = confirm_fn
        self.log_dir = log_dir
        self.verbose = verbose

        self.run_id = new_run_id()
        self.steps = []            # 每一步的日志记录
        self.trace = []            # 供结果校验使用的结构化轨迹
        self.messages = []
        self.step = 0
        self.tool_calls_total = 0
        self.tokens_total = 0
        self.status = 'running'
        self.stop_reason = ''
        self.final_answer = ''
        self._log_path = None

    # ---------------- 日志 ----------------
    def _log(self, event, **fields):
        rec = {'run_id': self.run_id, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'event': event}
        rec.update({k: _redact(v) if isinstance(v, str) else v
                    for k, v in fields.items()})
        self.steps.append(rec)
        if self._log_path is None:
            os.makedirs(self.log_dir, exist_ok=True)
            self._log_path = os.path.join(self.log_dir, 'run-%s.jsonl' % self.run_id)
        with open(self._log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        if self.verbose:
            print('  [%s] %s' % (event, json.dumps(
                {k: v for k, v in fields.items() if k != 'messages'},
                ensure_ascii=False)[:200]))

    # ---------------- 主循环 ----------------
    def run(self):
        started = time.time()
        self.messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': USER_TEMPLATE.format(
                field_type=self.task['field_type'],
                top_n=self.task.get('top_n', 5))},
        ]
        self._log('run_start', task=self.task.get('name', ''),
                  planner=self.planner.name,
                  max_steps=self.max_steps, wall_clock_s=self.wall_clock,
                  model=self.planner.describe().get('model'))

        consecutive_errors = 0
        while True:
            # ---- 停止检查一：步数 ----
            if self.step >= self.max_steps:
                self.status, self.stop_reason = 'step_limit', (
                    '达到最大步数 %d，未得到最终回答' % self.max_steps)
                break
            # ---- 停止检查二：总时限 ----
            if time.time() - started > self.wall_clock:
                self.status, self.stop_reason = 'time_limit', (
                    '超过总运行时限 %.0fs' % self.wall_clock)
                break

            self.step += 1
            res = self._call_model()
            if res is None:                       # 模型调用彻底失败
                break

            calls = getattr(res, 'tool_calls', []) or []
            if not calls:
                self.final_answer = (res.text or '').strip()
                self._log('final_answer', step=self.step, chars=len(self.final_answer),
                          preview=self.final_answer[:120])
                self.status = 'answered'
                break

            # 把助手的工具调用写回上下文（2.3 要求：调用请求也要进上下文）
            self.messages.append({
                'role': 'assistant', 'content': res.text or '',
                'tool_calls': [{'id': c['id'], 'type': 'function',
                                'function': {'name': c['name'],
                                             'arguments': c['arguments']}}
                               for c in calls]})
            self._log('model_turn', step=self.step, tool_calls=len(calls),
                      names=[c['name'] for c in calls])

            turn_errors = 0
            for c in calls:
                if time.time() - started > self.wall_clock:
                    self.status, self.stop_reason = 'time_limit', (
                        '执行工具前已超过总运行时限 %.0fs' % self.wall_clock)
                    break
                out = self._run_tool(c['name'], c['arguments'], c['id'])
                self.messages.append({'role': 'tool', 'tool_call_id': c['id'],
                                      'name': c['name'],
                                      'content': json.dumps(out, ensure_ascii=False)})
                if not out.get('ok'):
                    turn_errors += 1
            if self.status in ('time_limit',):
                break

            consecutive_errors = consecutive_errors + turn_errors if turn_errors else 0
            if consecutive_errors >= self.max_consecutive_errors:
                self.status, self.stop_reason = 'too_many_errors', (
                    '连续 %d 次工具调用失败，停止以免空转' % consecutive_errors)
                break

        elapsed = (time.time() - started) * 1000
        return self._finish(elapsed)

    def _call_model(self):
        """调用模型，失败按 retries 重试；彻底失败则结束运行。"""
        last = None
        for attempt in range(self.max_retries + 1):
            try:
                res = self.planner.chat(self.messages)
                usage = res.usage or {}
                self.tokens_total += usage.get('total_tokens') or 0
                return res
            except LLMError as e:
                last = e
                self._log('llm_error', step=self.step, attempt=attempt,
                          error_type=type(e).__name__, message=str(e))
                if attempt < self.max_retries:
                    time.sleep(0.5)
        self.status = 'llm_error'
        self.stop_reason = '模型调用失败：%s: %s' % (type(last).__name__, last)
        return None

    def _run_tool(self, name, raw_arguments, call_id):
        """解析参数 → 分发执行 → 记录日志。所有异常都不外泄，转成 ok=False。"""
        t0 = time.time()
        try:
            args = json.loads(raw_arguments or '{}')
        except json.JSONDecodeError as e:
            out = {'ok': False, 'tool': name, 'duration_ms': 0.0,
                   'error': {'code': 'bad_json',
                             'message': '参数不是合法 JSON：%s' % e}}
            self._log('tool_call', step=self.step, tool=name, ok=False,
                      error_code='bad_json', duration_ms=0.0)
            self.trace.append({'step': self.step, 'tool_calls': [
                {'tool': name, 'args': {}, 'ok': False, 'result': None}]})
            return out

        summary = tools.summarize_call(name, args)
        self.tool_calls_total += 1
        try:
            out = tools.dispatch(name, args, self.ctx, self.confirm_fn)
        except Exception as e:                     # noqa: BLE001
            out = {'ok': False, 'tool': name, 'duration_ms': (time.time() - t0) * 1000,
                   'error': {'code': 'harness_error',
                             'message': '%s: %s' % (type(e).__name__, e)}}
            self._log('harness_error', step=self.step, tool=name,
                      traceback=traceback.format_exc()[:400])

        spec = tools.TOOLS.get(name)
        # 写操作失败且状态不明（超时/异常）时，明确要求先核对，不许直接重试
        if (spec is not None and spec.side_effect and not out.get('ok')
                and out['error']['code'] in ('timeout', 'tool_failure',
                                             'unexpected', 'harness_error')):
            out['error']['message'] += (
                '（写入状态未知：请先调用 read_export 核对文件是否已生成，'
                '确认没写入再决定是否重试；不要直接重试）')

        self._log('tool_call', step=self.step, tool=name, args_summary=summary,
                  ok=out.get('ok'), error_code=(out.get('error') or {}).get('code'),
                  duration_ms=round(out.get('duration_ms', 0), 1))
        self.trace.append({'step': self.step, 'tool_calls': [
            {'tool': name, 'args': args, 'ok': out.get('ok'),
             'result': out.get('result')}]})
        return out

    # ---------------- 收尾 ----------------
    def _finish(self, elapsed_ms):
        # 结果检查：模型说完成不算完成
        verdict = None
        if self.status == 'answered':
            try:
                verdict = verify.check_success(self.final_answer, self.trace, self.task)
            except Exception as e:                 # noqa: BLE001
                verdict = {'passed': False, 'criteria': [
                    {'id': 'S0', 'desc': '校验过程本身出错', 'passed': False,
                     'detail': '%s: %s' % (type(e).__name__, e)}], 'truth': []}
            self.status = 'ok' if verdict['passed'] else 'criteria_failed'
            if not verdict['passed']:
                failed = [c['id'] for c in verdict['criteria'] if not c['passed']]
                self.stop_reason = '未通过成功标准：%s' % ','.join(failed)

        result = {
            'run_id': self.run_id,
            'task': self.task.get('name', ''),
            'planner': self.planner.name,
            'model': self.planner.describe().get('model'),
            'scripted': getattr(self.planner, 'scripted', False),
            'status': self.status,
            'stop_reason': self.stop_reason,
            'steps_used': self.step,
            'max_steps': self.max_steps,
            'tool_calls_total': self.tool_calls_total,
            'tokens_total': self.tokens_total,
            'elapsed_ms': elapsed_ms,
            'final_answer': self.final_answer,
            'verdict': verdict,
            'log_path': os.path.relpath(self._log_path, ROOT).replace('\\', '/')
            if self._log_path else '',
            'messages': self.messages,
        }
        self._log('run_end', status=self.status, stop_reason=self.stop_reason,
                  steps=self.step, tool_calls=self.tool_calls_total,
                  tokens=self.tokens_total, elapsed_ms=round(elapsed_ms, 1))
        return result

    # ---------------- 供测试使用的工具 ----------------
    def snapshot(self):
        return {'run_id': self.run_id, 'steps': self.step,
                'tool_calls': self.tool_calls_total, 'status': self.status,
                'log_path': self._log_path}
