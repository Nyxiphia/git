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

# 疑问词/指代词：只表达“在问什么”，不携带内容，参与匹配会把不相关片段顶上来。
# 只在**查询侧**过滤（文档侧照常索引，避免影响正常词频统计）。
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
    """BM25 关键词检索器。

    k1/b 为标准取值；df 统计用于 idf，长文档用 b 做长度归一。
    """

    def __init__(self, chunks, k1=1.5, b=0.75, min_score=5.0,
                 min_matched=2, min_coverage=0.30,
                 require_distinctive=True, distinctive_df_ratio=0.15):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.min_score = min_score
        self.min_matched = min_matched
        self.min_coverage = min_coverage
        self.require_distinctive = require_distinctive
        self.distinctive_df_ratio = distinctive_df_ratio
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

        相关性判断方法（2.4 要求说明）——四条同时满足才算“相关”：
          1) 分数门槛：BM25 总分 >= min_score（默认 2.0）；
          2) 命中词数：命中的查询词 >= min_matched（默认 2），避免单个高频词蒙中；
          3) 覆盖率：命中词数 / **可匹配查询词数** >= min_coverage（默认 0.30）。
             “可匹配查询词”指在语料中出现过的词（df>0）；把根本不存在的词算进分母，
             会让长问题被系统性惩罚——这个问题是在实机测试中发现的，见实验5 3.4；
          4) 区分度：至少要命中一个“有区分度的词”（df <= 15% × 片段总数）。
             否则像“项目”“功能”“为什么”这类泛词也能让不相关片段通过门槛。
        """
        raw_tokens = [t for t in dict.fromkeys(tokenize(query))]
        # 注意：曾尝试在查询侧过滤疑问词（为什/什么/如何…），实测会导致
        # “为什么选 SQLite 而不是 ORM” 之类问题区分度下降、并让无关问题误命中，
        # 因此回退，不做查询侧停用词过滤。
        q_tokens = raw_tokens
        if not q_tokens or self.N == 0:
            return [], {'query_tokens': q_tokens, 'candidates': 0, 'method': 'BM25'}

        # 只在语料中出现过的查询词才计入分母
        effective = [t for t in q_tokens if self.df.get(t, 0) > 0]
        denom = len(effective) or 1
        distinctive_df = max(1, int(self.distinctive_df_ratio * self.N))

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
                has_dist = any(self.df.get(t, 0) <= distinctive_df for t, _ in hits)
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
        info = {'query_tokens': q_tokens, 'effective_tokens': effective,
                'candidates': len(scored),
                'returned': len(out), 'min_score': self.min_score,
                'min_matched': self.min_matched, 'min_coverage': self.min_coverage,
                'distinctive_df_max': distinctive_df,
                'rejected': rejected,
                'top_score': round(scored[0][0], 3) if scored else 0.0,
                'top_coverage': round(scored[0][3], 2) if scored else 0.0,
                'method': 'BM25(k1=%.1f, b=%.2f) + 分数门槛 %.1f + 命中词≥%d + '
                          '覆盖率≥%.0f%%（分母=可匹配词）+ 含区分度词(df≤%d)'
                          % (self.k1, self.b, self.min_score, self.min_matched,
                             self.min_coverage * 100, distinctive_df)}
        return out, info
