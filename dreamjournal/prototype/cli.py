# -*- coding: utf-8 -*-
"""实验7 命令行入口。

    python -m dreamjournal.prototype.cli config --profile v2     查看配置（密钥已隐藏）
    python -m dreamjournal.prototype.cli cases                   列出评测样例
    python -m dreamjournal.prototype.cli run --profile v2 --case E01
    python -m dreamjournal.prototype.cli run --profile v2 --text "梦见..."
    python -m dreamjournal.prototype.cli eval                    跑 baseline/v1/v2 三方案
    python -m dreamjournal.prototype.cli eval --methods baseline,v1
"""
import argparse
import json
import os
import sys

from dreamjournal.prototype import baseline, schema
from dreamjournal.prototype.evaluate import run_all
from dreamjournal.prototype.parser import ParsePrototype, load_cases, load_profile


def cmd_config(args):
    cfg = load_profile(args.profile)
    env_name = cfg['model'].get('api_key_env', 'DREAM_LLM_API_KEY')
    print('配置档：%s（%s）' % (cfg.get('profile'), cfg.get('display_name')))
    print('文件：%s' % cfg.get('_path'))
    print('说明：%s' % cfg.get('note'))
    print('\n[模型]')
    for k, v in cfg['model'].items():
        if 'key' in k:
            v = '（从环境变量 %s 读取，配置里不出现）' % v
        print('  %-12s %s' % (k, v))
    print('  环境变量是否已设置：%s'
          % ('是' if os.environ.get(env_name) else '否'))
    print('\n[流水线]')
    for k, v in cfg['pipeline'].items():
        print('  %-16s %s' % (k, v))
    print('\n[Prompt] system（%d 字）' % len(cfg['prompt']['system']))
    print(cfg['prompt']['system'][:400] + ('…' if len(cfg['prompt']['system']) > 400 else ''))
    return 0


def cmd_cases(args):
    data = load_cases()
    print('%s（%d 条）' % (data.get('name'), len(data['cases'])))
    for c in data['cases']:
        print('\n%s [%s] %s' % (c['id'], c['group'], c['raw_text'][:60]))
        print('   金标准：%s' % ('、'.join('%s/%s' % (g['field_type'], g['label'])
                                        for g in c['gold']) or '（无，应弃权）'))
        print('   期望：%s' % c['expect'])
    return 0


def _print_result(res):
    print('状态：%s ｜ 阶段：%s ｜ 信息量：%s ｜ 耗时 %.0f ms ｜ 修复 %d 次'
          % (res['status'], res.get('stage'), res.get('information_density'),
             res['latency_ms'], res.get('repairs', 0)))
    if res.get('error'):
        print('错误：%s' % res['error'])
    for f in res.get('fields') or []:
        if isinstance(f, dict):
            print('   %-9s %-10s %.2f  %s'
                  % (f.get('field_type'), f.get('label'),
                     float(f.get('confidence') or 0),
                     '待确认' if float(f.get('confidence') or 0) < 0.6 else ''))
    if res.get('repairs'):
        print('（修复重试 %d 次后通过）' % res['repairs'])
    if res.get('raw'):
        print('原始返回：%s' % res['raw'][:200].replace('\n', ' '))


def cmd_run(args):
    cfg = load_profile(args.profile)
    if args.text:
        text, tag = args.text, '（命令行文本）'
    elif args.case:
        case = [c for c in load_cases()['cases'] if c['id'] == args.case]
        if not case:
            print('没有编号为 %s 的样例' % args.case, file=sys.stderr)
            return 2
        text, tag = case[0]['raw_text'], '（样例 %s）' % args.case
        print('金标准：%s' % ('、'.join('%s/%s' % (g['field_type'], g['label'])
                                     for g in case[0]['gold']) or '（无）'))
        print('期望：%s' % case[0]['expect'])
    else:
        print('需要 --case 或 --text', file=sys.stderr)
        return 2

    print('\n配置：%s（%s）' % (cfg.get('display_name'), cfg.get('_path')))
    print('输入%s：%s' % (tag, text))
    print('-' * 70)
    res = ParsePrototype(cfg).parse(text)
    _print_result(res)
    if res['status'] == 'ok':
        obj = {'information_density': res['information_density'],
               'fields': res['fields']}
        _, errs = schema.check_schema(obj)
        print('-' * 70)
        print('Schema 检查：%s' % ('通过' if not errs else '%d 处问题' % len(errs)))
        for e in errs:
            print('   · %s' % e)
        banned = schema.scan_banned(res.get('raw') or '')
        print('解读词检查：%s' % ('未出现' if not banned else '出现 %s' % banned))
    return 0 if res['status'] == 'ok' else 1


def cmd_baseline(args):
    res = baseline.parse(args.text or '')
    print('无 AI 基线（关键词匹配，非模型）')
    _print_result(res)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='dreamjournal.prototype.cli',
                                 description='实验7 核心AI能力原型')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('config')
    p.add_argument('--profile', default='v2', choices=['v1', 'v2'])
    p.set_defaults(func=cmd_config)

    sub.add_parser('cases').set_defaults(func=cmd_cases)

    p = sub.add_parser('run')
    p.add_argument('--profile', default='v2', choices=['v1', 'v2'])
    p.add_argument('--case')
    p.add_argument('--text')
    p.set_defaults(func=cmd_run)

    p = sub.add_parser('baseline')
    p.add_argument('--text', required=True)
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser('eval')
    p.add_argument('--methods', default='baseline,v1,v2')
    p.set_defaults(func=lambda a: (run_all(tuple(a.methods.split(','))), 0)[1])

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
