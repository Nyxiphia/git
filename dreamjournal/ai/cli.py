# -*- coding: utf-8 -*-
"""AI 适配层 —— 命令行入口（实验5 2.6 要求提供可运行入口）。

子命令：
  ingest                      构建/重建知识库索引并输出统计
  chunks [--show N]           列出片段，或抽查 N 个片段（显示内容与元数据）
  search "问题" [--k 4]       只做检索，输出 Top-k 与排序依据
  ask "问题" [--k 4] [--v2]   完整 RAG 链路：检索→上下文→调用→带出处回答
  direct "问题"               对照组：不提供资料，直接问模型
  demo-fail                   演示 4 类调用失败的处理（未配置/拒绝/超时/返回异常）
  eval [--limit N]            两组对比测试，输出 Markdown 表格

凭据从环境变量读取：
  DREAM_LLM_API_KEY   必填（否则只能跑离线演示）
  DREAM_LLM_BASE_URL  默认 https://api.deepseek.com/v1
  DREAM_LLM_MODEL     默认 deepseek-chat
"""
import argparse
import json
import os
import socket
import sys
import threading
import time

from . import prompts
from .client import (LLMClient, LLMAuthError, LLMError, LLMResponseError,
                     LLMTimeout, LLMUnavailable, OfflineProvider)
from .kb import build_index, load_index
from .pipeline import INDEX_PATH, RagPipeline, make_offline_pipeline, assemble_context
from .retriever import BM25Retriever, tokenize

DEFAULT_BASE = os.environ.get('DREAM_LLM_BASE_URL', 'https://api.deepseek.com/v1')
DEFAULT_MODEL = os.environ.get('DREAM_LLM_MODEL', 'deepseek-chat')


def build_client(timeout=30, max_retries=2):
    return LLMClient(api_key=os.environ.get('DREAM_LLM_API_KEY', ''),
                     base_url=DEFAULT_BASE, model=DEFAULT_MODEL,
                     timeout=timeout, max_retries=max_retries)


def build_pipeline(args, offline=False):
    if offline:
        return make_offline_pipeline(index_path=INDEX_PATH, k=args.k,
                                     prompt_version=args.version), None
    cli = build_client(timeout=args.timeout, max_retries=args.retries)
    return RagPipeline(cli, INDEX_PATH, k=args.k,
                       prompt_version=args.version), cli


# ---------------- 子命令 ----------------
def cmd_ingest(args):
    chunks, stats = build_index(INDEX_PATH, verbose=False)
    print('知识库构建完成')
    print('  参数：目标 %d 字 / 上限 %d 字 / 重叠 %d 字'
          % (stats['params']['target_chars'], stats['params']['max_chars'],
             stats['params']['overlap_chars']))
    for d in stats['documents']:
        print('  · %-28s %-42s %3d 片段 %6d 字'
              % (d['title'], d['repo_path'], d['chunks'], d['chars']))
    print('  合计：原始 %d → 去重删除 %d → 最终 %d 片段，共 %d 字，平均 %.1f 字/片段'
          % (stats['chunks_raw'], stats['chunks_dropped_duplicate'], stats['chunks'],
             stats['chars_total'], stats['avg_chars']))
    print('  清理无关内容：剔除 %d 个小节 / %d 字（实验模板的写作要求，非项目知识）'
          % (stats['sections_skipped_irrelevant'], stats['chars_skipped_irrelevant']))
    print('  索引文件：%s' % INDEX_PATH)
    return 0


def cmd_chunks(args):
    chunks, stats = load_index(INDEX_PATH)
    if not args.show:
        for c in chunks:
            print('%s %-42s %4d 字  %s' % (c['chunk_id'], c['locator'], c['chars'],
                                           c['doc_title']))
        print('共 %d 个片段' % len(chunks))
        return 0
    step = max(1, len(chunks) // args.show)
    picked = [chunks[i] for i in range(0, len(chunks), step)][:args.show]
    for c in picked:
        print('=' * 78)
        print('片段 %s  来源 %s  定位 %s  行 %s  %d 字'
              % (c['chunk_id'], c['source'], c['locator'], c['line'], c['chars']))
        print('权限：%s ｜ 隐私：%s' % (c['usage'], c['sensitivity']))
        print('-' * 78)
        print(c['text'][:600] + ('…' if c['chars'] > 600 else ''))
    return 0


def cmd_search(args):
    chunks, _ = load_index(INDEX_PATH)
    r = BM25Retriever(chunks)
    got, info = r.search(args.question, args.k)
    print('查询：%s' % args.question)
    print('查询词（二元组）：%s' % ' '.join(info['query_tokens'][:20]))
    print('方法：%s ｜ 命中候选 %d ｜ 返回 %d ｜ Top1 分数 %.3f'
          % (info['method'], info['candidates'], info['returned'], info['top_score']))
    print()
    if not got:
        print('结果：无相关片段 → 上层应返回“资料不足”')
        return 0
    for c in got:
        print('#%d  %-10s 分数 %6.3f  %s' % (c['rank'], c['chunk_id'], c['score'],
                                             c['locator']))
        print('    来源：%s' % c['source'])
        print('    命中词及贡献：%s' % '，'.join('%s=%.2f' % (t, s) for t, s in c['matched']))
        print('    内容：%s' % c['text'][:160].replace('\n', ' '))
        print()
    return 0


def _print_result(res, show_input=False):
    print('=' * 78)
    print('问题：%s' % res['question'])
    print('分组：%s ｜ Prompt：%s ｜ 状态：%s ｜ 模型：%s%s'
          % (res['group'], res['prompt_version'], res['status'], res['model'] or '(未调用)',
             '（离线）' if res['offline'] else ''))
    if res['retrieval_info']:
        print('检索：%s ｜ 命中 %d ｜ 上下文 %d 片段 / %d 字（精简前 %d 字）'
              % (res['retrieval_info'].get('method'),
                 res['retrieval_info'].get('returned', 0),
                 res['context_info'].get('chunks_out', 0),
                 res['context_info'].get('chars_after', 0),
                 res['context_info'].get('chars_before', 0)))
    print('输入：%d 条消息 / %d 字 / 约 %d tokens ｜ 输出：%s tokens ｜ 耗时 %.0f ms'
          % (res['meta'].get('messages', 0), res['meta'].get('chars', 0),
             res['meta'].get('est_tokens', 0),
             res['usage'].get('total_tokens', '-'), res['latency_ms']))
    print('-' * 78)
    if show_input and res['messages']:
        print('【实际发送的完整输入】')
        print(prompts.render_full_input(res['messages']))
        print('-' * 78)
    print('【回答】')
    print(res['answer'] or '(无)')
    if res['error']:
        print('【错误】%s' % res['error'])
    if res['citations']:
        print('【引用】')
        for c in res['citations']:
            if c['valid']:
                print('  [%d] 《%s》 %s  ←  %s' % (c['n'], c['doc_title'],
                                                  c['locator'], c['source']))
            else:
                print('  [%d] 无效：%s' % (c['n'], c['reason']))
    return 0


def cmd_ask(args):
    pipe, cli = build_pipeline(args)
    if cli is not None and not cli.configured:
        print('未检测到 DREAM_LLM_API_KEY，改用离线演示模式（不产生模型输出）。\n')
        pipe = make_offline_pipeline(index_path=INDEX_PATH, k=args.k,
                                     prompt_version=args.version)
    res = pipe.ask(args.question, group='rag', k=args.k)
    return _print_result(res, show_input=args.show_input)


def cmd_direct(args):
    pipe, cli = build_pipeline(args)
    if cli is not None and not cli.configured:
        pipe = make_offline_pipeline(index_path=INDEX_PATH, k=args.k)
    res = pipe.ask(args.question, group='direct', k=args.k)
    return _print_result(res, show_input=args.show_input)


# ---------------- 失败处理演示 ----------------
class _SilentServer(threading.Thread):
    """只接受连接、不返回任何数据 —— 用于制造真实的读超时。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
                time.sleep(30)
                conn.close()
            except OSError:
                return


class _BadJSONServer(threading.Thread):
    """返回 200 但内容不是 JSON —— 用于制造“返回体异常”。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
                conn.recv(65536)
                body = b'this is not json'
                conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                             b'Content-Length: ' + str(len(body)).encode() +
                             b'\r\nConnection: close\r\n\r\n' + body)
                conn.close()
            except OSError:
                return


def cmd_demo_fail(args):
    print('演示 4 类调用失败的处理（全部为真实发生的异常）\n')
    cases = []

    # A. 未配置 Key
    cli_a = LLMClient(api_key='', base_url=DEFAULT_BASE, model=DEFAULT_MODEL)
    cases.append(('A 未配置 API Key', cli_a, '未配置'))

    # B. 连接被拒绝（本机 9 端口，通常无监听）
    cli_b = LLMClient(api_key='sk-test', base_url='http://127.0.0.1:9/v1',
                      model='x', timeout=3, max_retries=0)
    cases.append(('B 连接被拒绝', cli_b, '拒绝'))

    # C. 读超时（服务端只接受不响应）
    srv = _SilentServer()
    srv.start()
    cli_c = LLMClient(api_key='sk-test', base_url='http://127.0.0.1:%d/v1' % srv.port,
                      model='x', timeout=2, max_retries=0)
    cases.append(('C 读超时', cli_c, '超时'))

    # D. 返回体不是 JSON
    srv2 = _BadJSONServer()
    srv2.start()
    cli_d = LLMClient(api_key='sk-test', base_url='http://127.0.0.1:%d/v1' % srv2.port,
                      model='x', timeout=3, max_retries=0)
    cases.append(('D 返回体异常', cli_d, '返回异常'))

    for name, client, _tag in cases:
        t0 = time.time()
        try:
            client.chat([{'role': 'user', 'content': 'ping'}])
            print('%-16s 竟然成功（不符合预期）' % name)
        except LLMError as e:
            print('%-16s 捕获 %-18s 耗时 %5.0f ms' % (name, type(e).__name__,
                                                      (time.time() - t0) * 1000))
            print('%-16s 消息：%s' % ('', str(e)[:150]))
        print()
    srv.stop = srv2.stop = True
    print('结论：四类失败都被分类成不同的异常类型，上层可据此选择提示、重试或降级。')
    return 0


# ---------------- 对比测试 ----------------
def cmd_eval(args):
    from rag_eval.runner import run_two_groups
    return run_two_groups(limit=args.limit, k=args.k)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='dreamjournal.ai.cli', description='RAG 命令行')
    ap.add_argument('--timeout', type=float, default=30)
    ap.add_argument('--retries', type=int, default=2)
    ap.add_argument('--version', default=prompts.DEFAULT_VERSION,
                    choices=list(prompts.PROMPT_VERSIONS))
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('ingest').set_defaults(func=cmd_ingest)

    p = sub.add_parser('chunks')
    p.add_argument('--show', type=int, default=0)
    p.set_defaults(func=cmd_chunks)

    p = sub.add_parser('search')
    p.add_argument('question')
    p.add_argument('--k', type=int, default=4)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser('ask')
    p.add_argument('question')
    p.add_argument('--k', type=int, default=4)
    p.add_argument('--show-input', action='store_true')
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser('direct')
    p.add_argument('question')
    p.add_argument('--k', type=int, default=4)
    p.add_argument('--show-input', action='store_true')
    p.set_defaults(func=cmd_direct)

    sub.add_parser('demo-fail').set_defaults(func=cmd_demo_fail)

    p = sub.add_parser('eval')
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--k', type=int, default=4)
    p.set_defaults(func=cmd_eval)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
