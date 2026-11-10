# -*- coding: utf-8 -*-
"""原型主链路（实验7 2.4）：用户输入 → 预处理 → 模型处理 → 结果检查 → 展示/保存。

设计要点：
  · 模型名、Prompt、温度、超时、重试、阈值**全部来自 config/exp7_*.json**，
    代码里不写死任何一版 Prompt，也不出现密钥；
  · 每一步的中间结果（原始返回、错误、耗时、usage、修复次数）都保留在返回值里，
    一次失败能直接看出问题出在预处理、调用、解析还是校验；
  · 失败一律以 status + error 返回，不抛异常，方便批量评测。

修订版（v0.6.0）相对初版新增四处，**全部由配置开关控制**，因此同一份代码
把 `validate/repair_attempts/min_confidence/dedupe` 关掉即可复现初版行为：
  ① Schema 校验（`schema.check_schema`）；
  ② 把校验错误回传模型做一次修复重试；
  ③ 置信度阈值过滤；
  ④ 去重 + 待确认标记（与实验4 的 `needs_confirm` 语义一致）。
"""
import json
import os
import time

from dreamjournal import domain
from dreamjournal.ai.client import LLMClient, LLMError
from dreamjournal.prototype import schema

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(ROOT, 'config')
CASES_PATH = os.path.join(ROOT, 'eval', 'exp7_cases.json')

# 低于该置信度的字段标记为“待确认”，不直接计入统计（沿用实验3 表 3-5 的约定）
CONFIRM_THRESHOLD = 0.6

REPAIR_TEMPLATE = (
    '上面的 JSON 有 {n} 处不符合约定：\n{errors}\n'
    '请只输出修正后的 JSON 对象，不要任何解释文字。\n'
    '格式：{{"information_density": "high|medium|low", '
    '"fields": [{{"field_type": "emotion|character|scene|symbol", '
    '"label": "简短名词", "confidence": 0.0~1.0}}]}}'
)


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
        self.last_messages = []

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

    # ---------------- 失败构造 ----------------
    def _fail(self, status, message, started, stage, chars=0, raw='', usage=None,
              repairs=0):
        return {'status': status, 'error': message, 'stage': stage,
                'information_density': None, 'fields': [], 'errors': [],
                'raw': raw, 'usage': usage or {}, 'repairs': repairs,
                'latency_ms': (time.time() - started) * 1000,
                'profile': self.cfg.get('profile'), 'chars': chars,
                'dropped': 0}

    # ---------------- 主流程 ----------------
    def parse(self, text):
        started = time.time()
        t = (text or '').strip()
        if not t:
            return self._fail('empty_input', '输入为空', started, 'preprocess')
        min_chars = self.pc.get('min_text_chars', 1)
        if len(t) < min_chars:
            return self._fail('too_short',
                              '输入只有 %d 字，少于最小长度 %d，已在预处理阶段拒绝，'
                              '未调用模型' % (len(t), min_chars),
                              started, 'preprocess', chars=len(t))
        if not self.available:
            return self._fail('no_model',
                              '未配置 API Key（环境变量 %s），无法调用模型'
                              % self.mc.get('api_key_env'), started, 'setup',
                              chars=len(t))

        do_validate = bool(self.pc.get('validate'))
        max_repair = int(self.pc.get('repair_attempts', 0) or 0)
        max_fields = int(self.pc.get('max_fields', 20))

        messages = [{'role': 'system', 'content': self.cfg['prompt']['system']},
                    {'role': 'user',
                     # 用 replace 而不是 str.format：Prompt 里含大量 JSON 花括号，
                     # format 会把它们当成占位符报 KeyError
                     'content': self.cfg['prompt']['user_template'].replace('{text}', t)}]
        repairs = 0
        usage_total = {}
        res = None
        obj, errs = None, []

        while True:
            try:
                res = self.client.chat(messages)
            except LLMError as e:
                return self._fail('call_failed', '%s: %s' % (type(e).__name__, e),
                                  started, 'call', chars=len(t), repairs=repairs)
            for k, v in (res.usage or {}).items():
                if isinstance(v, (int, float)):
                    usage_total[k] = usage_total.get(k, 0) + v

            obj, jerr = schema.extract_json(res.text)
            if obj is None:
                errs = [jerr]
            elif do_validate:
                obj, errs = schema.check_schema(obj)
            else:
                errs = []
                obj = {'information_density': (obj or {}).get('information_density'),
                       'fields': ((obj or {}).get('fields') or [])[:max_fields]}

            if not errs:
                break
            if repairs >= max_repair:
                status = 'bad_json' if obj is None else 'schema_invalid'
                return self._fail(status,
                                  '；'.join(errs[:3]) + ('…' if len(errs) > 3 else ''),
                                  started, 'parse' if obj is None else 'validate',
                                  chars=len(t), raw=res.text,
                                  usage=usage_total, repairs=repairs)
            repairs += 1
            messages.append({'role': 'assistant', 'content': res.text})
            messages.append({'role': 'user',
                             'content': REPAIR_TEMPLATE.format(
                                 n=len(errs), errors='\n'.join('- ' + e for e in errs[:6]))})
        self.last_messages = messages

        # ---------------- 后处理 ----------------
        min_conf = float(self.pc.get('min_confidence', 0.0) or 0.0)
        fields = [f for f in (obj.get('fields') or [])
                  if isinstance(f, dict) and float(f.get('confidence') or 0) >= min_conf]
        dropped = len(obj.get('fields') or []) - len(fields)

        if self.pc.get('dedupe'):
            best = {}
            for f in fields:
                key = (f['field_type'], f['label'])
                if key not in best or f['confidence'] > best[key]['confidence']:
                    best[key] = f
            deduped = len(fields) - len(best)
            fields = list(best.values())
            dropped += deduped

        fields.sort(key=lambda f: -float(f.get('confidence') or 0))
        fields = fields[:max_fields]
        for f in fields:
            f['needs_confirm'] = float(f.get('confidence') or 0) < CONFIRM_THRESHOLD

        density = obj.get('information_density')
        if density not in schema.DENSITY_VALUES:
            density = ('high' if len(fields) >= 4
                       else ('medium' if fields else 'low'))

        return {
            'status': 'ok',
            'error': '',
            'stage': 'done',
            'information_density': density,
            'fields': fields,
            'errors': [],
            'raw': res.text,
            'usage': usage_total,
            'repairs': repairs,
            'latency_ms': (time.time() - started) * 1000,
            'profile': self.cfg.get('profile'),
            'chars': len(t),
            'dropped': dropped,
        }

    # ---------------- 与基础软件的连接点 ----------------
    def to_db_rows(self, result):
        """把原型输出映射成 `parsed_field` 表的列，便于直接入库。"""
        rows = []
        for f in result.get('fields') or []:
            rows.append({'field_type': f['field_type'], 'label': f['label'],
                         'confidence': round(float(f.get('confidence') or 0), 3),
                         'needs_confirm': bool(f.get('needs_confirm'))})
        return rows

    def save_to_db(self, db_path, raw_text, result, dream_date=None):
        """把一次解析结果写进指定 SQLite 文件（**不碰用户现有数据库**）。

        这一步只是把“连接点”打通，证明原型输出能直接被实验4 的数据层接收；
        完整集成（解析完自动入库、界面回显）不在本次范围内。
        """
        from dreamjournal.services import RecordService, ReviewService
        from dreamjournal.store import DreamRepository

        repo = DreamRepository(db_path)
        repo.init_schema()
        rec = RecordService(repo).create(raw_text, dream_date=dream_date)
        review = ReviewService(repo)
        ids = []
        for row in self.to_db_rows(result):
            f = review.add_field(rec.id, row['field_type'], row['label'],
                                 confidence=row['confidence'],
                                 needs_confirm=row['needs_confirm'])
            ids.append(f.id)
        if result.get('information_density') in domain.DENSITIES:
            repo.update_status(rec.id, domain.STATUS_PARSED)
        return {'record_id': rec.id, 'field_ids': ids,
                'db': os.path.relpath(db_path, ROOT).replace('\\', '/')}
