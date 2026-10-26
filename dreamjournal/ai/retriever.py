# -*- coding: utf-8 -*-
"""AI 适配层 —— 关键词检索（BM25，对应实验5 2.4）。

为什么选关键词检索而不是向量检索：
  · 知识库是本项目自己写的技术文档，提问多为术语（SQLite、needs_confirm、tag、BM25…），
    关键词检索对这类“精确术语 + 中文短语”的匹配更稳定，且**完全可解释**——
    可以逐条说明“命中了哪几个词、各自贡献多少分”，便于报告中论证排序依据；
  · 向量检索需要嵌入模型（云端调用或本地模型），本次环境不具备，且会引入额外的费用与不可解释性；
  · 知识库规模小（数十个片段），BM25 足够，无需近似最近邻。

中文无分词库可用，采用“汉字二元组 + ASCII 单词”的切词方式，属于常见且可接受的近似。
"""
import math
import re


_TOKEN_ASCII = re.compile(r'[a-zA-Z][a-zA-Z0-9_\-\.]*')
_TOKEN_CJK = re.compile(r'[\u4e00-\u9fff]')

STOP_BIGRAMS = {
    '的是', '了_', '我们', '这个', '那个', '可以', '如果', '以及', '并且', '因此',
    '一个', '没有', '不是', '就是', '这些', '那些', '进行', '通过', '对于', '其中',
}


def tokenize(text):
    """切词：ASCII 单词（小写）+ 连续汉字串的二元组。"""
    text = text or ''
    tokens = [m.group(0).lower() for m in _TOKEN_ASCII.finditer(text)]
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        if len(run) == 1:
            tokens.append(run)
            continue
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in STOP_BIGRAMS:
                tokens.append(bg)
    return tokens


class BM25Retriever:
    """BM25 关键词检索器。

    k1/b 为标准取值；df 统计用于 idf，长文档用 b 做长度归一。
    """

    def __init__(self, chunks, k1=1.5, b=0.75, min_score=2.0,
                 min_matched=2, min_coverage=0.30):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.min_score = min_score
        self.min_matched = min_matched
        self.min_coverage = min_coverage
        self.docs_tokens = [tokenize(c['text'] + ' ' + c.get('heading', ''))
                            for c in chunks]
        self.doc_len = [len(t) for t in self.docs_tokens]
        self.avgdl = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.tf = []
        self.df = {}
        for toks in self.docs_tokens:
            d = {}
            for t in toks:
                d[t] = d.get(t, 0) + 1
            self.tf.append(d)
            for t in d:
                self.df[t] = self.df.get(t, 0) + 1
        self.N = len(chunks)

    def _idf(self, term):
        df = self.df.get(term, 0)
        return math.log(1 + (self.N - df + 0.5) / (df + 0.5))

    def search(self, query, k=4):
        """返回 Top-k 片段（按分数降序），并附排序依据。

        相关性判断方法（2.4 要求说明）——三条同时满足才算“相关”：
          1) 分数门槛：BM25 总分 >= min_score（默认 2.0）；
          2) 命中词数：命中的查询词 >= min_matched（默认 2），避免单个高频词蒙中；
          3) 覆盖率：命中词数 / 查询词数 >= min_coverage（默认 0.30）。
        三条中任一不满足即丢弃该片段；全部片段被丢弃时判定“无相关片段”，
        上层返回“资料不足”，不把无关片段塞进上下文。
        """
        q_tokens = [t for t in dict.fromkeys(tokenize(query))]
        if not q_tokens or self.N == 0:
            return [], {'query_tokens': q_tokens, 'candidates': 0, 'method': 'BM25'}

        scored = []
        for i, tf in enumerate(self.tf):
            score = 0.0
            hits = []
            norm = self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1))
            for t in q_tokens:
                f = tf.get(t)
                if not f:
                    continue
                s = self._idf(t) * (f * (self.k1 + 1)) / (f + norm)
                score += s
                hits.append((t, round(s, 3)))
            if hits:
                cov = len(hits) / len(q_tokens)
                scored.append((score, i, hits, cov))
        scored.sort(key=lambda x: -x[0])

        out = []
        rejected = {'low_score': 0, 'too_few_matched': 0, 'low_coverage': 0}
        for score, i, hits, cov in scored[:k * 3]:
            if score < self.min_score:
                rejected['low_score'] += 1
                continue
            if len(hits) < self.min_matched:
                rejected['too_few_matched'] += 1
                continue
            if cov < self.min_coverage:
                rejected['low_coverage'] += 1
                continue
            c = dict(self.chunks[i])
            c['score'] = round(score, 3)
            c['coverage'] = round(cov, 2)
            c['matched'] = sorted(hits, key=lambda x: -x[1])[:6]
            out.append(c)
            if len(out) >= k:
                break
        for r, c in enumerate(out):
            c['rank'] = r + 1
        info = {'query_tokens': q_tokens, 'candidates': len(scored),
                'returned': len(out), 'min_score': self.min_score,
                'min_matched': self.min_matched, 'min_coverage': self.min_coverage,
                'rejected': rejected,
                'top_score': round(scored[0][0], 3) if scored else 0.0,
                'top_coverage': round(scored[0][3], 2) if scored else 0.0,
                'method': 'BM25(k1=%.1f, b=%.2f) + 分数门槛 %.1f + 命中词≥%d + 覆盖率≥%.0f%%'
                          % (self.k1, self.b, self.min_score, self.min_matched,
                             self.min_coverage * 100)}
        return out, info
