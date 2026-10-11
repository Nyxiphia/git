# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 界面层（实验3 图 3-5 / 图 3-6 / 图 3-7 / 图 3-8）。

v0.1.0 可运行初版：只实现首页（记录列表）+ 记录页（文字输入），
满足实验4 2.1 “程序能够正常启动，并至少完成一次核心数据的读取或保存
以及一个页面、接口或操作入口”。
"""
import tkinter as tk
from tkinter import messagebox, ttk

from . import domain

FONT = ('Microsoft YaHei', 10)
FONT_B = ('Microsoft YaHei', 11, 'bold')
FONT_T = ('Microsoft YaHei', 14, 'bold')


class DreamApp:
    def __init__(self, root, services):
        self.root = root
        self.svc = services
        self.root.title('梦境记录 v0.1.0')
        self.root.geometry('900x560')
        self.root.configure(bg='#f4f6fa')
        self._build()
        self.refresh()

    # ---------------- 界面 ----------------
    def _build(self):
        head = tk.Frame(self.root, bg='#e6e6e6')
        head.pack(fill='x')
        tk.Label(head, text='我的梦境', font=FONT_T, bg='#e6e6e6').pack(
            side='left', padx=14, pady=8)
        tk.Label(head, text='v0.1.0 可运行初版', font=FONT, bg='#e6e6e6',
                 fg='#666').pack(side='right', padx=14)

        body = tk.Frame(self.root, bg='#f4f6fa')
        body.pack(fill='both', expand=True, padx=10, pady=10)

        left = tk.LabelFrame(body, text='记录一个梦', font=FONT, bg='#f4f6fa')
        left.pack(side='left', fill='both', expand=True, padx=(0, 8))

        tk.Label(left, text='日期（YYYY-MM-DD）', font=FONT, bg='#f4f6fa').pack(
            anchor='w', padx=10, pady=(10, 2))
        self.date_var = tk.StringVar(value='')
        tk.Entry(left, textvariable=self.date_var, font=FONT, width=18).pack(
            anchor='w', padx=10)

        tk.Label(left, text='梦境内容', font=FONT, bg='#f4f6fa').pack(
            anchor='w', padx=10, pady=(10, 2))
        self.text = tk.Text(left, height=12, font=FONT, wrap='word',
                            relief='solid', borderwidth=1)
        self.text.pack(fill='both', expand=True, padx=10)

        tk.Button(left, text='保存记录', font=FONT_B, bg='#dce9ff',
                  command=self.on_save).pack(anchor='w', padx=10, pady=10)
        self.status = tk.Label(left, text='就绪', font=FONT, bg='#f4f6fa', fg='#555')
        self.status.pack(anchor='w', padx=10, pady=(0, 8))

        right = tk.LabelFrame(body, text='梦境列表', font=FONT, bg='#f4f6fa')
        right.pack(side='left', fill='both', expand=True)

        cols = ('id', 'date', 'text', 'status')
        self.tree = ttk.Treeview(right, columns=cols, show='headings', height=16)
        for c, t, w in (('id', 'ID', 50), ('date', '日期', 100),
                        ('text', '摘要', 240), ('status', '状态', 80)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w')
        self.tree.pack(fill='both', expand=True, padx=10, pady=10)

        bar = tk.Frame(right, bg='#f4f6fa')
        bar.pack(fill='x', padx=10, pady=(0, 10))
        tk.Button(bar, text='刷新', font=FONT, command=self.refresh).pack(side='left')
        self.count = tk.Label(bar, text='共 0 条', font=FONT, bg='#f4f6fa', fg='#555')
        self.count.pack(side='right')

    # ---------------- 行为 ----------------
    def on_save(self):
        raw = self.text.get('1.0', 'end-1c')
        rec = self.svc['record'].create(raw, self.date_var.get() or None)
        self.text.delete('1.0', 'end')
        self.status.config(text='已保存记录 #%s' % rec.id)
        self.refresh()
        return rec

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        rows = self.svc['record'].list_recent()
        for r in rows:
            self.tree.insert('', 'end', values=(r.id, r.dream_date,
                                                r.summary(), r.status))
        self.count.config(text='共 %d 条' % len(rows))
        return rows
