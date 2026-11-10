# -*- coding: utf-8 -*-
"""原型主链路（实验7 2.4）：用户输入 → 预处理 → 模型处理 → 结果检查 → 输出。

设计要点：
  · 模型名、Prompt、温度、超时、重试等**全部来自 config/exp7_*.json**，
    代码里不写死任何一版 Prompt，也不出现密钥；
  · 每一步的中间结果（原始返回、错误、耗时、usage）都保留在返回值里，
    一次失败能直接看出问题出在预处理、调用还是解析；
  · 失败一律以 status + error 返回，不抛异常，方便批量评测。

本文件是 **v0.5.0 初版**：只做“调用 + 取 JSON + 截断字段数量”，
没有 Schema 校验、没有修复重试、没有置信度阈值——这些是第 2 周要补的。
"""
import json
import os
import time

from dreamjournal.ai.client import LLMClient, LLMError
from dreamjournal.prototype import schema

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(ROOT, 'config')
CASES_PATH = os.path.join(ROOT, 'eval', 'exp7_cases.json')


def load_profile(name):
    """读取一个配置档（v1 / v2）。密钥不在配置里，只记录环境变量名。"""
    path = os.path.join(CONFIG_DIR, 'exp7_%s.json' % name)
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    cfg['_path'] = os.path.relpath(path, ROOT).replace('\\', '/')
    return cfg


def load_cases():
    with open(CASES_PATH, encoding='utf-8') as f:
        return json.load(f)


class ParsePrototype:
    def __init__(self, cfg, client=None):
        self.cfg = cfg
        self.mc = cfg['model']
        self.pc = cfg['pipeline']
        self.client = client if client is not None else self._make_client()

    def _make_client(self):
        env_name = self.mc.get('api_key_env', 'DREAM_LLM_API_KEY')
        key = os.environ.get(env_name, '')
        if not key:
            return None
        return LLMClient(api_key=key,
                         base_url=self.mc['base_url'],
                         model=self.mc['name'],
                         timeout=self.mc.get('timeout', 60),
                         max_retries=self.mc.get('max_retries', 0),
                         temperature=self.mc.get('temperature', 0.7),
                         max_tokens=self.mc.get('max_tokens', 800))

    @property
    def available(self):
        return self.client is not None

    def describe(self):
        return {'profile': self.cfg.get('profile'),
                'display_name': self.cfg.get('display_name'),
                'model': self.mc.get('name'),
                'temperature': self.mc.get('temperature'),
                'max_tokens': self.mc.get('max_tokens'),
                'config': self.cfg.get('_path'),
                'available': self.available}

    # ---------------- 各阶段 ----------------
    def _fail(self, status, message, started, stage, **extra):
        out = {'status': status, 'error': message, 'stage': stage,
               'fields': [], 'information_density': None, 'errors': [],
               'raw': '', 'usage': {}, 'repairs': 0,
               'latency_ms': (time.time() - started) * 1000,
               'profile': self.cfg.get('profile'), 'chars': extra.pop('chars', 0)}
        out.update(extra)
        return out

    def parse(self, text):
        started = time.time()
        t = (text or '').strip()
        if not t:
            return self._fail('empty_input', '输入为空', started, 'preprocess')
        if len(t) < self.pc.get('min_text_chars', 1):
            return self._fail('too_short',
                              '输入只有 %d 字，少于最小长度 %d，已在预处理阶段拒绝，'
                              '未调用模型' % (len(t), self.pc.get('min_text_chars', 1)),
                              started, 'preprocess', chars=len(t))
        if not self.available:
            return self._fail('no_model',
                              '未配置 API Key（环境变量 %s），无法调用模型'
                              % self.mc.get('api_key_env'), started, 'setup',
                              chars=len(t))

        messages = [{'role': 'system', 'content': self.cfg['prompt']['system']},
                    {'role': 'user',
                     'content': self.cfg['prompt']['user_template'].format(text=t)}]
        try:
            res = self.client.chat(messages)
        except LLMError as e:
            return self._fail('call_failed', '%s: %s' % (type(e).__name__, e),
                              started, 'call', chars=len(t))

        obj, err = schema.extract_json(res.text)
        if obj is None:
            return self._fail('bad_json', err, started, 'parse', chars=len(t),
                              raw=res.text, usage=res.usage or {})

        fields = obj.get('fields') or []
        if not isinstance(fields, list):
            fields = []
        cap = self.pc.get('max_fields', 20)
        return {
            'status': 'ok',
            'error': '',
            'stage': 'done',
            'information_density': obj.get('information_density'),
            'fields': fields[:cap],
            'errors': [],
            'raw': res.text,
            'usage': res.usage or {},
            'repairs': 0,
            'latency_ms': (time.time() - started) * 1000,
            'profile': self.cfg.get('profile'),
            'chars': len(t),
            'truncated': max(0, len(fields) - cap),
        }
