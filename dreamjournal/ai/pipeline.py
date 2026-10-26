# -*- coding: utf-8 -*-
"""AI 适配层 —— RAG 最小链路（对应实验5 2.4 / 2.6）。

流程：问题输入 → 检索 → 上下文组织（去重/裁剪/编号）→ 模型调用 → 回答返回（带出处）。
本模块是可被 CLI、界面或其它代码直接调用的模块（实验5 2.6 的要求）。
"""
import difflib
import re
import time

from . import prompts
from .client import LLMError
from .kb import build_index, load_index
from .retriever import BM25Retriever

INDEX_PATH = r'C:\Users\35004\Desktop\1\rag_data\kb_index.json'

_CITE = re.compile(r'\[(\d+)\]')


# ---------------- 上下文工程 ----------------
def _similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def assemble_context(chunks, max_chars=2400, sim_threshold=0.92, dedupe_near=True):
    """把检索片段整理成上下文：去近似重复 → 按分数保留 → 超长裁剪。

    2.2 要求“检查输入中是否存在无关或重复信息，按需精简并记录检查结果”，
    本函数返回精简前后的长度，供报告对比。
    """
    before_chars = sum(len(c['text']) for c in chunks)
    dropped = []
    kept = []
    for c in chunks:
        dup = None
        if dedupe_near:
            for k in kept:
                if _similar(c['text'], k['text']) >= sim_threshold or \
                        c['text'][:120] in k['text']:
                    dup = k
                    break
        if dup:
            dropped.append({'chunk_id': c['chunk_id'], 'reason': '近似重复',
                            'same_as': dup['chunk_id']})
            # 保留更长的一条
            if len(c['text']) > len(dup['text']):
                dup['text'] = c['text']
            continue
        kept.append(c)

    trimmed = []
    used = 0
    for c in kept:
        if used + len(c['text']) > max_chars and trimmed:
            dropped.append({'chunk_id': c['chunk_id'], 'reason': '超出上下文上限'})
            continue
        trimmed.append(c)
        used += len(c['text'])

    for r, c in enumerate(trimmed, 1):
        c['rank'] = r
    return trimmed, {
        'chunks_in': len(chunks),
        'chunks_out': len(trimmed),
        'chars_before': before_chars,
        'chars_after': used,
        'dropped': dropped,
        'max_chars': max_chars,
        'dedupe_near': dedupe_near,
    }


def extract_citations(answer, chunks):
    """从回答中抽取 [n] 引用，映射回片段，并判断引用是否落在已知片段范围内。"""
    nums = []
    for m in _CITE.finditer(answer or ''):
        n = int(m.group(1))
        if n not in nums:
            nums.append(n)
    by_rank = {c['rank']: c for c in chunks}
    cites = []
    for n in nums:
        c = by_rank.get(n)
        if c is None:
            cites.append({'n': n, 'valid': False, 'reason': '引用的编号不存在'})
        else:
            cites.append({'n': n, 'valid': True, 'chunk_id': c['chunk_id'],
                          'doc_title': c['doc_title'], 'locator': c['locator'],
                          'source': c['source'], 'snippet': c['text'][:120]})
    return cites


class RagPipeline:
    """可调用的 RAG 模块。

    构造：
        provider       LLMClient 或 OfflineProvider
        index_path     知识库索引 JSON（不存在则自动构建）
        k              Top-k
        prompt_version 'v1' / 'v2'
    输入：ask(question)
    输出：dict（见 ask 的返回字段）
    失败：不抛异常，返回 status='insufficient' 或 status='error' 的结构，便于界面直接渲染。
    """

    def __init__(self, provider, index_path=INDEX_PATH, k=4,
                 prompt_version=prompts.DEFAULT_VERSION, max_context_chars=2400):
        self.provider = provider
        self.k = k
        self.prompt_version = prompt_version
        self.max_context_chars = max_context_chars
        if not index_path or not __import__('os').path.isfile(index_path):
            self.chunks, self.index_stats = build_index(index_path, verbose=False)
        else:
            self.chunks, self.index_stats = load_index(index_path)
        self.retriever = BM25Retriever(self.chunks)

    # ---------------- 检索 ----------------
    def retrieve(self, question, k=None):
        return self.retriever.search(question, k or self.k)

    # ---------------- 主流程 ----------------
    def ask(self, question, history=None, group='rag', k=None, prompt_version=None):
        """执行一次完整链路。

        group='direct' 表示“直接模型组”：不检索、不提供资料（实验5 2.5 的对照组）。
        """
        t0 = time.time()
        version = prompt_version or self.prompt_version
        res = {
            'question': question, 'group': group, 'prompt_version': version,
            'status': 'ok', 'answer': '', 'citations': [],
            'retrieved': [], 'retrieval_info': {}, 'context_info': {},
            'messages': [], 'meta': {}, 'usage': {}, 'latency_ms': 0.0,
            'model': '', 'offline': False, 'error': '', 'k': k or self.k,
        }

        # 1) 检索
        if group == 'direct':
            chunks, info = [], {'method': '不检索（对照组）', 'returned': 0}
        else:
            chunks, info = self.retrieve(question, k)
        res['retrieved'] = chunks
        res['retrieval_info'] = info

        # 2) 资料不足前置判定（不浪费一次模型调用）
        if group == 'rag' and not chunks:
            res['status'] = 'insufficient'
            res['answer'] = ('资料不足：知识库中没有与本题相关的片段。'
                             '（检索方法：%s；命中候选 %d 个，均未达阈值）'
                             % (info.get('method'), info.get('candidates', 0)))
            res['latency_ms'] = round((time.time() - t0) * 1000, 1)
            return res

        # 3) 上下文组织
        chunks_ctx, ctx_info = assemble_context(chunks, self.max_context_chars)
        res['context_info'] = ctx_info

        # 4) 组装完整输入
        messages, meta = prompts.build_messages(question, chunks_ctx, version, history)
        res['messages'] = messages
        res['meta'] = meta

        # 5) 调用模型
        try:
            out = self.provider.chat(messages, group=group, question=question)
        except LLMError as e:
            res['status'] = 'error'
            res['error'] = '%s: %s' % (type(e).__name__, e)
            res['latency_ms'] = round((time.time() - t0) * 1000, 1)
            return res

        res['answer'] = out.text
        res['usage'] = out.usage
        res['model'] = out.model
        res['offline'] = out.offline
        res['latency_ms'] = round((time.time() - t0) * 1000, 1)

        # 6) 引用与不足判定
        res['citations'] = extract_citations(out.text, chunks_ctx)
        if group == 'rag' and ('资料不足' in out.text or not res['citations']):
            res['status'] = 'insufficient'
        return res


def make_offline_pipeline(chunks_provider=None, index_path=INDEX_PATH,
                          k=4, prompt_version=prompts.DEFAULT_VERSION):
    """构造离线演示用流水线（**不是模型**，仅用于验证链路可跑通）。"""
    from .client import OfflineProvider
    p = RagPipeline(OfflineProvider(chunks_provider), index_path, k, prompt_version)

    def _cb(q, kk):
        got, _ = p.retrieve(q, kk)
        return got
    p.provider._chunks = _cb
    return p
