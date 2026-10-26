# -*- coding: utf-8 -*-
"""AI 适配层 —— 知识库加载与切分（对应实验5 2.3）。

知识库来源刻意选择**本项目自己的实验文档**（实验2 需求、实验3 设计、实验4 实现、
仓库 README），理由：
  · 来源明确：每条片段都能回指到仓库里的具体文件与标题；
  · 权限清晰：本项目自有文档，无第三方版权问题；
  · 无隐私风险：不含个人梦境原文，满足实验2/3 “敏感数据不出本机”的约束；
  · 与前面实验强相关：知识库本身就是实验2/3/4 的产出。

切分策略：先按 Markdown 标题分节（保留标题路径作为定位信息），
节内按段落聚合到目标长度；超长节按字符切分并保留重叠，避免关键句被切断。
"""
import hashlib
import json
import os
import re

# ---------------- 知识库来源清单 ----------------
WS = r'C:\Users\35004\Desktop\1'

SOURCES = [
    {'doc_id': 'exp2', 'title': '实验2 个人软件选题与需求分析',
     'path': os.path.join(WS, '实验2-个人软件选题与需求分析.md'),
     'repo_path': 'docs/实验2-个人软件选题与需求分析.md',
     'usage': '本项目自有文档，可自由引用', 'sensitivity': '不含个人信息与梦境原文'},
    {'doc_id': 'exp3', 'title': '实验3 软件架构与界面设计',
     'path': os.path.join(WS, '实验3-软件架构与界面设计.md'),
     'repo_path': 'docs/实验3-软件架构与界面设计.md',
     'usage': '本项目自有文档，可自由引用', 'sensitivity': '不含个人信息与梦境原文'},
    {'doc_id': 'exp4', 'title': '实验4 软件基础功能开发',
     'path': os.path.join(WS, '实验4-软件基础功能开发.md'),
     'repo_path': 'docs/实验4-软件基础功能开发.md',
     'usage': '本项目自有文档，可自由引用', 'sensitivity': '不含个人信息与梦境原文'},
]

# 切分参数
TARGET_CHARS = 480       # 目标片段长度
MAX_CHARS = 800          # 单片上限
OVERLAP_CHARS = 80       # 超长节切分时的重叠长度

_HEADING = re.compile(r'^(#{1,4})\s+(.*)$')
_DECOR = re.compile(r'^[\s|:\-—=_*`>]+$')

# 无关内容过滤：这几节是**实验模板给出的写作要求**（“使用已经学习的类图…”），
# 不属于项目知识，保留会污染检索，因此整体剔除。
# 注意：第 3 节（操作记录）与第 4 节（实验小结）是本项目自己写的，保留。
EXCLUDE_PREFIXES = ('学习通提交说明', '1. 实验目的', '2. 实验内容')


def _is_irrelevant(heading):
    parts = [p.strip() for p in heading.split(' > ')]
    for part in parts:
        for pref in EXCLUDE_PREFIXES:
            if part.startswith(pref):
                return True
    return False


def read_document(src):
    with open(src['path'], encoding='utf-8') as f:
        return f.read()


def _split_sections(text):
    """按 Markdown 标题分节，返回 [(标题路径, 起始行号, 正文)]。

    注意：必须跳过围栏代码块内的行——实验4 的“代码清单 4-2”里含有以 ## 开头的
    Markdown 片段，若不过滤，会被误当成标题，切分出错误的定位路径。
    """
    sections = []
    stack = []          # [(level, text)]
    buf = []
    start_line = 1
    in_fence = False
    for lineno, line in enumerate(text.split('\n'), 1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if m:
            if ''.join(buf).strip():
                sections.append((' > '.join(t for _, t in stack) or '（正文）',
                                 start_line, '\n'.join(buf)))
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            buf = []
            start_line = lineno + 1
        else:
            buf.append(line)
    if ''.join(buf).strip():
        sections.append((' > '.join(t for _, t in stack) or '（正文）', start_line,
                         '\n'.join(buf)))
    return sections


def _is_decor(s):
    """纯装饰行（分割线、空表格边框等），且**不含竖线**。

    注意：Markdown 表格的表头分隔行形如 `| --- | --- |`，只由 - 和 | 组成，
    若把它当装饰行删掉，表格结构会被破坏（表头与数据行失去对应关系）。
    因此对含 `|` 的行一律保留。
    """
    return bool(_DECOR.match(s)) and '|' not in s


def _clean(text):
    """清理：去掉纯装饰行、压缩空行、去首尾空白。"""
    lines = []
    for ln in text.split('\n'):
        s = ln.rstrip()
        if _is_decor(s):
            continue
        lines.append(s)
    out = '\n'.join(lines)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()


def _merge_short(pieces, min_chars=60, max_chars=MAX_CHARS):
    """把过短片段并入下一段。

    典型场景：表格的标题（如“**表 3-23　仓库、文件路径与 Commit**”）会与表格本体
    被切成两个片段，标题单独成段价值很低。这里把短片段与下一段合并，
    使“标题 + 表格”留在同一片段里。
    """
    out = []
    i = 0
    while i < len(pieces):
        p = pieces[i]
        if (len(p) < min_chars and i + 1 < len(pieces)
                and len(p) + len(pieces[i + 1]) + 2 <= max_chars):
            out.append(p + '\n\n' + pieces[i + 1])
            i += 2
            continue
        out.append(p)
        i += 1
    return out


def _is_table_block(b):
    """判断一个块是不是 Markdown 表格（所有非空行都以 | 开头）。"""
    lines = [ln for ln in b.split('\n') if ln.strip()]
    return bool(lines) and all(ln.lstrip().startswith('|') for ln in lines)


def _split_long(text, target=TARGET_CHARS, max_chars=MAX_CHARS, overlap=OVERLAP_CHARS):
    """按“段落块”打包切分。

    先以空行把文本切成块（表格、列表通常是一个整块），再贪心打包到目标长度。
    这样表格行、列表项不会被从中间切断；只有单块本身超过上限时，才在句号/分号处
    硬切，并保留 overlap 字的重叠，避免关键句被割裂。

    因此：**常规片段之间不重叠，只有硬切产生的片段相邻重叠**。
    """
    blocks = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]
    out, buf = [], []
    buf_len = 0
    for b in blocks:
        # 表格：原子块，单独成片段，永不切分（切开会让表头与数据行失去对应关系）
        if _is_table_block(b):
            if buf:
                out.append('\n\n'.join(buf))
                buf, buf_len = [], 0
            out.append(b)
            continue
        if len(b) > max_chars:
            if buf:
                out.append('\n\n'.join(buf))
                buf, buf_len = [], 0
            # 预计算“连续表格行”的偏移区间，硬切时避开
            spans, pos = [], 0
            for ln in b.split('\n'):
                spans.append((pos, pos + len(ln)))
                pos += len(ln) + 1
            runs, cur = [], None
            for s, e in spans:
                if b[s:e].lstrip().startswith('|'):
                    cur = (s, e) if cur is None else (cur[0], e)
                elif cur:
                    runs.append(cur)
                    cur = None
            if cur:
                runs.append(cur)

            def adjust(cut, base):
                """切点若落在表格行内部，移到表格之前（够长）或之后。"""
                for s, e in runs:
                    if s < cut < e:
                        return s if (s - base) >= target * 0.4 else e + 1
                return cut

            def inside_run(p):
                for s, e in runs:
                    if s < p < e:
                        return True
                return False

            i = 0
            while i < len(b):
                end = min(i + target, len(b))
                if end < len(b):
                    cut = max(b.rfind('。', i, end), b.rfind('；', i, end),
                              b.rfind('\n', i, end))
                    if cut > i + target * 0.5:
                        end = cut + 1
                    end = adjust(end, i)
                out.append(b[i:end].strip())
                if end >= len(b):
                    break
                nxt = max(end - overlap, i + 1)
                # 关键：若重叠回退会落到表格行内部，则不回退，避免下一段从表格中间开始
                if inside_run(nxt):
                    nxt = end
                i = nxt
            continue
        if buf_len + len(b) + 2 > target and buf:
            out.append('\n\n'.join(buf))
            buf, buf_len = [], 0
        buf.append(b)
        buf_len += len(b) + 2
    if buf:
        out.append('\n\n'.join(buf))
    return [p for p in out if p.strip()]


def chunk_document(src, target=TARGET_CHARS, max_chars=MAX_CHARS,
                   overlap=OVERLAP_CHARS):
    """切分一份文档，返回 (片段列表, 统计)。"""
    text = read_document(src)
    chunks = []
    skipped_sections = 0
    skipped_chars = 0
    for heading, line_no, body in _split_sections(text):
        if _is_irrelevant(heading):
            skipped_sections += 1
            skipped_chars += len(_clean(body))
            continue
        body = _clean(body)
        if not body or len(body) < 20:
            continue
        pieces = _split_long(body, target, max_chars, overlap)
        pieces = _merge_short(pieces, max_chars=max_chars)
        for k, piece in enumerate(pieces):
            piece = piece.strip()
            if len(piece) < 20:
                continue
            locator = '§%s%s' % (heading, '' if k == 0 else '（续%d）' % (k + 1))
            chunks.append({
                'doc_id': src['doc_id'],
                'doc_title': src['title'],
                'heading': heading,
                'locator': locator,
                'line': line_no,
                'source': src['repo_path'],
                'usage': src['usage'],
                'sensitivity': src['sensitivity'],
                'text': piece,
                'chars': len(piece),
                'chunk_id': None,          # 由 build_index 统一编号
            })
    return chunks, {'skipped_sections': skipped_sections,
                    'skipped_chars': skipped_chars}


def dedupe(chunks):
    """去掉内容完全重复的片段（保留首次出现），返回 (保留, 被删数量)。"""
    seen, kept, dropped = set(), [], 0
    for c in chunks:
        key = hashlib.md5(re.sub(r'\s+', '', c['text']).encode('utf-8')).hexdigest()
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append(c)
    return kept, dropped


def build_index(out_path=None, verbose=True):
    """构建知识库索引，返回 (chunks, stats)。"""
    all_chunks, stats_docs = [], []
    skip_sections = skip_chars = 0
    for src in SOURCES:
        if not os.path.isfile(src['path']):
            if verbose:
                print('  [跳过] 找不到 %s' % src['path'])
            continue
        got, sinfo = chunk_document(src)
        skip_sections += sinfo['skipped_sections']
        skip_chars += sinfo['skipped_chars']
        stats_docs.append({'doc_id': src['doc_id'], 'title': src['title'],
                           'repo_path': src['repo_path'], 'chunks': len(got),
                           'chars': sum(c['chars'] for c in got),
                           'skipped_sections': sinfo['skipped_sections'],
                           'skipped_chars': sinfo['skipped_chars']})
        all_chunks.extend(got)

    before = len(all_chunks)
    all_chunks, dropped = dedupe(all_chunks)
    for i, c in enumerate(all_chunks):
        c['chunk_id'] = 'C%03d' % (i + 1)

    stats = {
        'documents': stats_docs,
        'chunks_raw': before,
        'chunks_dropped_duplicate': dropped,
        'sections_skipped_irrelevant': skip_sections,
        'chars_skipped_irrelevant': skip_chars,
        'chunks': len(all_chunks),
        'chars_total': sum(c['chars'] for c in all_chunks),
        'avg_chars': round(sum(c['chars'] for c in all_chunks) / max(1, len(all_chunks)), 1),
        'params': {'target_chars': TARGET_CHARS, 'max_chars': MAX_CHARS,
                   'overlap_chars': OVERLAP_CHARS},
    }
    if out_path:
        d = os.path.dirname(os.path.abspath(out_path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump({'stats': stats, 'chunks': all_chunks}, f, ensure_ascii=False, indent=1)
    if verbose:
        print('  文档 %d 份，原始片段 %d 个，去重删除 %d 个，最终 %d 个，共 %d 字'
              % (len(stats_docs), before, dropped, len(all_chunks), stats['chars_total']))
    return all_chunks, stats


def load_index(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return data['chunks'], data['stats']
