# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 程序入口。

用法：
    python main.py                       启动图形界面
    python main.py --db data/demo.db     指定数据库文件
"""
import argparse
import os
import sys

from dreamjournal.store import DreamRepository
from dreamjournal.services import (RecordService, ReviewService,
                                   TrendService, ExportService)

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'data', 'dream.db')


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
    args = ap.parse_args(argv)

    repo, services = build_services(args.db)

    import tkinter as tk
    from dreamjournal.ui import DreamApp
    root = tk.Tk()
    DreamApp(root, services)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
