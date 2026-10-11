# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 程序入口。

用法：
    python main.py                          启动图形界面
    python main.py --db data/demo.db        指定数据库文件
    python main.py --seed                   写入样例数据后启动
    python main.py --seed --no-gui          只写样例数据（便于脚本化验证）
    python main.py --reset                  清空全部数据
    python main.py --export out/dreams.md   导出 Markdown
"""
import argparse
import os
import sys

from dreamjournal import logging_setup
from dreamjournal.seed import seed, reset
from dreamjournal.services import (RecordService, ReviewService,
                                   TrendService, ExportService, ValidationError)
from dreamjournal.store import DreamRepository, StorageError

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(ROOT, 'data', 'dream.db')


def build_services(db_path):
    repo = DreamRepository(db_path)
    repo.init_schema()
    return repo, {
        'record': RecordService(repo),
        'review': ReviewService(repo),
        'trend': TrendService(repo),
        'export': ExportService(repo),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='AI 梦境记录与解析')
    ap.add_argument('--db', default=DEFAULT_DB, help='SQLite 数据库文件路径')
    ap.add_argument('--seed', action='store_true', help='写入样例数据')
    ap.add_argument('--reset', action='store_true', help='清空全部数据')
    ap.add_argument('--export', metavar='PATH', help='导出 Markdown 后退出')
    ap.add_argument('--no-gui', action='store_true', help='不启动界面（配合 --seed/--reset）')
    args = ap.parse_args(argv)

    log = logging_setup.setup()
    log.info('启动：db=%s seed=%s reset=%s export=%s',
             args.db, args.seed, args.reset, args.export)

    try:
        repo, services = build_services(args.db)
    except StorageError as e:
        log.error('数据库初始化失败：%s', e)
        print('[错误] %s' % e, file=sys.stderr)
        return 2

    if args.reset:
        n = reset(repo)
        log.info('已清空 %d 条记录', n)
        print('已清空 %d 条记录' % n)

    if args.seed:
        n = seed(repo, services['review'], reset=False)
        log.info('已写入 %d 条样例数据', n)
        print('已写入 %d 条样例数据' % n)

    if args.export:
        try:
            n = services['export'].export_markdown(args.export)
            print('已导出 %d 条记录到 %s' % (n, args.export))
        except ValidationError as e:
            print('[错误] %s' % e, file=sys.stderr)
            return 3

    if args.no_gui or args.reset or args.export:
        return 0

    import tkinter as tk
    from dreamjournal.ui import DreamApp
    root = tk.Tk()
    DreamApp(root, services, db_path=args.db)
    root.mainloop()
    log.info('界面退出')
    return 0


if __name__ == '__main__':
    sys.exit(main())
