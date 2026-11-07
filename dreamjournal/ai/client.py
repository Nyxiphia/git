# -*- coding: utf-8 -*-
"""AI 适配层 —— 模型客户端（对应实验3 表 3-5 的 LLMAdapter 位置）。

设计要点（与实验2/3 的约束一致）：
  · 只负责“把请求发出去、把结果拿回来”，不做任何业务判断；
  · 异常必须分类后抛出，由上层决定如何降级（实验2 表 3-14 的“非 AI 降级方案”）；
  · 记录耗时与用量，供实验5 2.5 的费用/性能统计；
  · 兼容任何 OpenAI Chat Completions 风格的接口，只需换 base_url 和 model。

不依赖第三方库：用标准库 urllib。
"""
import json
import time
import urllib.error
import urllib.request


# ---------------- 异常分类 ----------------
class LLMError(Exception):
    """模型调用失败的基类。上层据此决定降级还是提示用户。"""


class LLMUnavailable(LLMError):
    """连接失败、DNS/网络不可达、代理问题等。"""


class LLMTimeout(LLMError):
    """请求超时。"""


class LLMAuthError(LLMError):
    """鉴权失败（key 无效、余额不足等 401/403）。"""


class LLMRateLimit(LLMError):
    """限流（429）。"""


class LLMResponseError(LLMError):
    """返回体不符合预期（非 JSON、缺 choices、内容为空）。"""


class LLMResult:
    """一次调用的结果与计量。"""

    def __init__(self, text, model, usage, latency_ms, raw=None, offline=False,
                 tool_calls=None):
        self.text = text
        self.model = model
        self.usage = usage or {}          # {'prompt_tokens':..,'completion_tokens':..,'total_tokens':..}
        self.latency_ms = latency_ms
        self.raw = raw
        self.offline = offline
        # 实验6：工具调用。每项形如 {'id','name','arguments'}，arguments 是原始 JSON 字符串
        self.tool_calls = tool_calls or []

    def __repr__(self):
        return ('LLMResult(model=%r, chars=%d, total_tokens=%s, latency=%.0fms, offline=%s)'
                % (self.model, len(self.text or ''),
                   self.usage.get('total_tokens'), self.latency_ms, self.offline))


# ---------------- 真实客户端 ----------------
class LLMClient:
    """OpenAI Chat Completions 兼容客户端。

    参数：
        api_key   密钥；留空则视为未配置
        base_url  例如 https://api.deepseek.com/v1 或 https://api.openai.com/v1
        model     模型名
        timeout   单次请求超时（秒）
        max_retries 可重试错误（超时、连接、429、5xx）的重试次数
    """

    def __init__(self, api_key='', base_url='https://api.deepseek.com/v1',
                 model='deepseek-chat', timeout=30, max_retries=2,
                 temperature=0.2, max_tokens=800):
        self.api_key = (api_key or '').strip()
        self.base_url = (base_url or '').rstrip('/')
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def configured(self):
        return bool(self.api_key and self.base_url and self.model)

    def describe(self):
        return {'base_url': self.base_url, 'model': self.model,
                'timeout': self.timeout, 'max_retries': self.max_retries,
                'temperature': self.temperature, 'max_tokens': self.max_tokens,
                'configured': self.configured}

    def chat(self, messages, **overrides):
        """发送一次对话请求，返回 LLMResult。失败抛分类后的 LLMError。"""
        if not self.configured:
            raise LLMUnavailable('未配置 API Key / base_url / model，无法调用云端模型'
                                 '（请设置环境变量 DREAM_LLM_API_KEY）')
        payload = {
            'model': overrides.get('model', self.model),
            'messages': messages,
            'temperature': overrides.get('temperature', self.temperature),
            'max_tokens': overrides.get('max_tokens', self.max_tokens),
            'stream': False,
        }
        # 实验6：把工具 Schema 一起发给模型，由模型决定是否调用
        if overrides.get('tools'):
            payload['tools'] = overrides['tools']
            payload['tool_choice'] = overrides.get('tool_choice', 'auto')
        url = self.base_url + '/chat/completions'
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        last = None
        for attempt in range(self.max_retries + 1):
            started = time.time()
            try:
                req = urllib.request.Request(
                    url, data=body, method='POST',
                    headers={'Content-Type': 'application/json',
                             'Authorization': 'Bearer ' + self.api_key})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode('utf-8', 'replace')
                latency = (time.time() - started) * 1000
                return self._parse(raw, payload['model'], latency)
            except urllib.error.HTTPError as e:
                latency = (time.time() - started) * 1000
                detail = ''
                try:
                    detail = e.read().decode('utf-8', 'replace')[:300]
                except Exception:      # noqa: BLE001
                    pass
                if e.code in (401, 403):
                    raise LLMAuthError('鉴权失败 HTTP %d：%s' % (e.code, detail))
                if e.code == 429:
                    last = LLMRateLimit('触发限流 HTTP 429：%s' % detail)
                elif e.code >= 500:
                    last = LLMUnavailable('服务端错误 HTTP %d：%s' % (e.code, detail))
                else:
                    raise LLMResponseError('请求被拒绝 HTTP %d：%s' % (e.code, detail))
            except urllib.error.URLError as e:
                reason = getattr(e, 'reason', e)
                if 'timed out' in str(reason).lower():
                    last = LLMTimeout('请求超时（%.0fs）：%s' % (self.timeout, reason))
                else:
                    last = LLMUnavailable('连接失败：%s' % reason)
            except TimeoutError:
                last = LLMTimeout('请求超时（%.0fs）' % self.timeout)
            except LLMError:
                # 已经是分类过的错误（如 _parse 抛出的 LLMResponseError），原样抛出，
                # 不能被下面的兜底分支吞成 LLMUnavailable
                raise
            except Exception as e:                       # noqa: BLE001
                raise LLMUnavailable('调用异常：%s: %s' % (type(e).__name__, e))

            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 4) * 0.5)
        raise last

    def _parse(self, raw, model, latency):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise LLMResponseError('返回体不是合法 JSON：%s' % raw[:200])
        choices = data.get('choices') or []
        if not choices:
            raise LLMResponseError('返回体缺少 choices：%s' % raw[:200])
        msg = choices[0].get('message') or {}
        text = (msg.get('content') or '').strip()
        calls = []
        for c in (msg.get('tool_calls') or []):
            fn = c.get('function') or {}
            calls.append({'id': c.get('id') or '',
                          'name': fn.get('name') or '',
                          'arguments': fn.get('arguments') or '{}'})
        if not text and not calls:
            raise LLMResponseError('模型返回空内容（既无文本也无工具调用）')
        return LLMResult(text=text, model=data.get('model') or model,
                         usage=data.get('usage') or {}, latency_ms=latency, raw=data,
                         tool_calls=calls)


# ---------------- 离线提供者 ----------------
class OfflineProvider:
    """离线演示用提供者：**不是模型**，只用于在无网络环境下验证流水线可跑通。

    返回内容一律带【离线】前缀，避免被误当成模型输出；
    当 group='direct'（不提供资料）时明确返回“无法生成”，不做任何捏造。
    """

    name = 'offline-extractive'
    configured = True

    def __init__(self, chunks_provider=None):
        self._chunks = chunks_provider or (lambda q, k: [])

    def describe(self):
        return {'base_url': '(offline)', 'model': self.name, 'timeout': 0,
                'max_retries': 0, 'temperature': 0, 'max_tokens': 0,
                'configured': True, 'offline': True}

    def chat(self, messages, **overrides):
        started = time.time()
        group = overrides.get('group', 'rag')
        question = overrides.get('question', '')
        if group == 'direct':
            text = ('【离线模式】当前环境无法访问云端模型，本组（直接模型组）没有模型可调用，'
                    '因此不生成任何回答，以免产生不可核验的内容。')
        else:
            chunks = self._chunks(question, 2)
            if not chunks:
                text = '【离线模式】检索未命中，按设计要求返回“资料不足”，不编造答案。'
            else:
                lines = ['【离线抽取式，非模型生成】按命中片段摘录作答：']
                for c in chunks[:2]:
                    lines.append('[%d] 《%s》%s：%s' % (c['rank'], c['doc_title'],
                                                      c['locator'], c['text'][:180]))
                text = '\n'.join(lines)
        latency = (time.time() - started) * 1000
        return LLMResult(text=text, model=self.name, usage={}, latency_ms=latency,
                         offline=True)
