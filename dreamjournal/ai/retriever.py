# -*- coding: utf-8 -*-
"""AI 适配层 —— 关键词检索（BM25，对应实验5 2.4）。

为什么选关键词检索而不是向量检索：
  · 知识库是本项目自己写的技术文档，提问多为术语（SQLite、needs_confirm、tag、BM25…），
    关键词检索对这类“精确术语 + 中文短语”的匹配更稳定，且**完全可解释**——
    可以逐条说明“命中了哪几个词、各自贡献多少分”，便于报告中论证排序依据；
  · 向量检索需要嵌入模型（云端调用或本地模型），本次环境不具备，且会引入额外的费用与不可解释性；
  · 知识库规模小（一百多个片段），BM25 足够，无需近似最近邻。

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

# 疑问词/指代词：只表达“在问什么”，不携带内容。
# 曾经尝试在查询侧直接过滤它们，实测会让“为什么选 SQLite 而不是 ORM”这类问题
# 失去区分度、并让无关问题误命中，因此**不直接删除**，而是靠下面的 idf 区分度判据
# 让它们自然失去权重（这些词在本语料中 idf 普遍在 2.0~2.7 之间）。
QUESTION_STOP = {
    '为什', '什么', '么不', '怎么', '么样', '如何', '何用', '哪些', '是否', '能否',
    '这个', '个项', '那个', '请问', '一下', '多少', '几个', '吗',
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
    """BM25 关键词检索器（k1/b 取标准值，长文档用 b 做长度归一）。"""

    def __init__(self, chunks, k1=1.5, b=0.75, min_score=5.0,
                 min_matched=2, min_coverage=0.30,
                 require_distinctive=True, min_distinctive_idf=1.2):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.min_score = min_score
        self.min_matched = min_matched
        self.min_coverage = min_coverage
        self.require_distinctive = require_distinctive
        self.min_distinctive_idf = min_distinctive_idf

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

    def _is_distinctive(self, term):
        """是否为“内容词”：不在疑问词表中，且 idf 不低于下限。

        不能用单纯的 idf 阈值区分——本语料中“解梦”(2.78) 与“为什么”(2.69) 几乎贴在一起，
        任何一个单一阈值都会同时误伤其中一个。因此把疑问词表作为**区分度判据的一部分**
        （匹配时仍然保留这些词，让它们正常参与打分，只是不能单独撑起“相关”的结论）。
        """
        return term not in QUESTION_STOP and self._idf(term) >= self.min_distinctive_idf

    def search(self, query, k=4):
        """返回 Top-k 片段（按分数降序），并附排序依据。

        相关性判断方法（2.4 要求说明）——四条同时满足才算“相关”：
          1) 分数门槛：BM25 总分 >= min_score（默认 5.0，由本知识库样例校准）；
          2) 命中词数：命中的查询词 >= min_matched（默认 2），避免单个词蒙中；
          3) 覆盖率：命中词数 / **可匹配查询词数** >= min_coverage（默认 0.30）。
             “可匹配查询词”指在语料中出现过的词（df>0）。把根本不存在的词算进分母，
             会系统性惩罚长问题——这个问题是实机测试暴露的，见实验5 3.4；
          4) 区分度：至少要命中一个“内容词”（idf >= min_distinctive_idf，默认 3.0）。
             否则“为什么”“什么”“项目”“功能”这类高频词也能让不相关片段通过。
        """
        q_tokens = [t for t in dict.fromkeys(tokenize(query))]
        if not q_tokens or self.N == 0:
            return [], {'query_tokens': q_tokens, 'candidates': 0, 'method': 'BM25'}

        effective = [t for t in q_tokens if self.df.get(t, 0) > 0]
        denom = len(effective) or 1

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
                cov = len(hits) / denom
                has_dist = any(self._is_distinctive(t) for t, _ in hits)
                scored.append((score, i, hits, cov, has_dist))
        scored.sort(key=lambda x: -x[0])

        out = []
        rejected = {'low_score': 0, 'too_few_matched': 0, 'low_coverage': 0,
                    'no_distinctive': 0}
        for score, i, hits, cov, has_dist in scored[:k * 4]:
            if score < self.min_score:
                rejected['low_score'] += 1
                continue
            if len(hits) < self.min_matched:
                rejected['too_few_matched'] += 1
                continue
            if cov < self.min_coverage:
                rejected['low_coverage'] += 1
                continue
            if self.require_distinctive and not has_dist:
                rejected['no_distinctive'] += 1
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
        info = {
            'query_tokens': q_tokens,
            'effective_tokens': effective,
            'candidates': len(scored),
            'returned': len(out),
            'min_score': self.min_score,
            'min_matched': self.min_matched,
            'min_coverage': self.min_coverage,
            'min_distinctive_idf': self.min_distinctive_idf,
            'rejected': rejected,
            'top_score': round(scored[0][0], 3) if scored else 0.0,
            'top_coverage': round(scored[0][3], 2) if scored else 0.0,
            'method': 'BM25(k1=%.1f, b=%.2f) + 分数门槛 %.1f + 命中词>=%d + '
                      '覆盖率>=%.0f%%(分母=可匹配词) + 含内容词(idf>=%.1f)'
                      % (self.k1, self.b, self.min_score, self.min_matched,
                         self.min_coverage * 100, self.min_distinctive_idf),
        }
        return out, info
