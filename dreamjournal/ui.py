# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 界面层（实验3 图 3-5 页面结构与导航、图 3-6/3-7/3-8 原型）。

v0.2.0 修订版：补齐“记录 → 列表 → 详情与人工标注 → 确认 → 趋势 → 检索 → 导出 →
删除”闭环，并把界面层与控制层之间的异常处理补全（实验4 审查项 R2）：
界面只捕获 ValidationError / StorageError 并弹出提示，绝不让异常打断主循环。

技术栈说明：实验3 ADR-01 选择 PySide6，但本次开发环境无法安装（无网络）。
依据实验3 ADR-03 的分层设计，界面层是唯一依赖 GUI 框架的层，
业务层与数据层完全不 import tkinter，因此替换为 tkinter 未影响其余各层。
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import domain
from .logging_setup import get_logger
from .store import StorageError
from .services import ValidationError

FONT = ('Microsoft YaHei', 10)
FONT_B = ('Microsoft YaHei', 11, 'bold')
FONT_T = ('Microsoft YaHei', 14, 'bold')
FONT_S = ('Microsoft YaHei', 9)
LOG = get_logger()


class DreamApp:
    def __init__(self, root, services, db_path=''):
        self.root = root
        self.svc = services
        self.db_path = db_path
        self.current_id = None
        root.title('AI 梦境记录与解析 v0.2.0')
        root.geometry('1080x680')
        root.configure(bg='#f4f6fa')
        self._build()
        self.refresh()
        LOG.info('界面启动，数据库=%s', db_path)

    # ================= 界面构建 =================
    def _build(self):
        head = tk.Frame(self.root, bg='#e6e6e6')
        head.pack(fill='x')
        tk.Label(head, text='我的梦境', font=FONT_T, bg='#e6e6e6').pack(
            side='left', padx=14, pady=8)
        tk.Label(head, text='v0.2.0 测试修订版 · 数据仅保存在本机', font=FONT_S,
                 bg='#e6e6e6', fg='#666').pack(side='right', padx=14)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill='both', expand=True, padx=8, pady=8)

        self.tab_dream = tk.Frame(self.nb, bg='#f4f6fa')
        self.tab_trend = tk.Frame(self.nb, bg='#f4f6fa')
        self.tab_set = tk.Frame(self.nb, bg='#f4f6fa')
        self.nb.add(self.tab_dream, text='  梦境  ')
        self.nb.add(self.tab_trend, text='  趋势  ')
        self.nb.add(self.tab_set, text='  设置  ')
        self._build_dream(self.tab_dream)
        self._build_trend(self.tab_trend)
        self._build_setting(self.tab_set)

        self.status = tk.Label(self.root, text='就绪', font=FONT_S, anchor='w',
                               bg='#e6e6e6', fg='#333', relief='sunken')
        self.status.pack(fill='x', side='bottom')

    # ---------------- 梦境页 ----------------
    def _build_dream(self, p):
        body = tk.Frame(p, bg='#f4f6fa')
        body.pack(fill='both', expand=True, padx=8, pady=8)

        left = tk.LabelFrame(body, text='记录一个梦（核心任务页）', font=FONT, bg='#f4f6fa')
        left.pack(side='left', fill='both', expand=True, padx=(0, 8))
        tk.Label(left, text='日期（YYYY-MM-DD，留空取今天）', font=FONT_S,
                 bg='#f4f6fa').pack(anchor='w', padx=10, pady=(8, 2))
        self.date_var = tk.StringVar()
        tk.Entry(left, textvariable=self.date_var, font=FONT, width=20).pack(
            anchor='w', padx=10)
        tk.Label(left, text='梦境内容（非空，≤2000 字）', font=FONT_S,
                 bg='#f4f6fa').pack(anchor='w', padx=10, pady=(8, 2))
        self.text = tk.Text(left, height=9, font=FONT, wrap='word',
                            relief='solid', borderwidth=1)
        self.text.pack(fill='both', expand=True, padx=10)
        tk.Button(left, text='保存记录', font=FONT_B, bg='#ffe3c2',
                  command=self.on_save).pack(anchor='w', padx=10, pady=8)

        right = tk.LabelFrame(body, text='梦境列表（首页）', font=FONT, bg='#f4f6fa')
        right.pack(side='left', fill='both', expand=True)

        bar = tk.Frame(right, bg='#f4f6fa')
        bar.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(bar, text='关键词', font=FONT_S, bg='#f4f6fa').pack(side='left')
        self.kw_var = tk.StringVar()
        ent = tk.Entry(bar, textvariable=self.kw_var, font=FONT, width=16)
        ent.pack(side='left', padx=6)
        ent.bind('<Return>', lambda e: self.on_search())
        tk.Button(bar, text='检索', font=FONT_S, command=self.on_search).pack(side='left')
        tk.Button(bar, text='全部', font=FONT_S, command=self.refresh).pack(side='left', padx=4)
        tk.Button(bar, text='导出', font=FONT_S, command=self.on_export).pack(side='right')

        cols = ('id', 'date', 'text', 'fields', 'status')
        self.tree = ttk.Treeview(right, columns=cols, show='headings', height=12)
        for c, t, w in (('id', 'ID', 46), ('date', '日期', 92), ('text', '摘要', 230),
                        ('fields', '标签', 150), ('status', '状态', 78)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w')
        self.tree.pack(fill='both', expand=True, padx=10)
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_select())

        rbar = tk.Frame(right, bg='#f4f6fa')
        rbar.pack(fill='x', padx=10, pady=6)
        tk.Button(rbar, text='删除选中记录', font=FONT_S,
                  command=self.on_delete).pack(side='left')
        self.count = tk.Label(rbar, text='共 0 条', font=FONT_S, bg='#f4f6fa', fg='#555')
        self.count.pack(side='right')

        # 详情与人工标注
        det = tk.LabelFrame(right, text='详情与人工标注（结果页）', font=FONT, bg='#f4f6fa')
        det.pack(fill='both', expand=True, padx=10, pady=(0, 8))
        self.detail = tk.Text(det, height=6, font=FONT_S, wrap='word',
                              relief='solid', borderwidth=1, bg='#ffffff')
        self.detail.pack(fill='both', expand=True, padx=8, pady=6)
        self.detail.config(state='disabled')

        add = tk.Frame(det, bg='#f4f6fa')
        add.pack(fill='x', padx=8, pady=(0, 8))
        tk.Label(add, text='类型', font=FONT_S, bg='#f4f6fa').pack(side='left')
        self.ft_var = tk.StringVar(value=domain.FIELD_TYPE_CN[domain.FIELD_EMOTION])
        ttk.Combobox(add, textvariable=self.ft_var, width=6, state='readonly',
                     values=[domain.FIELD_TYPE_CN[k] for k in domain.FIELD_TYPES]
                     ).pack(side='left', padx=4)
        tk.Label(add, text='标签', font=FONT_S, bg='#f4f6fa').pack(side='left')
        self.label_var = tk.StringVar()
        tk.Entry(add, textvariable=self.label_var, font=FONT_S, width=14).pack(
            side='left', padx=4)
        self.pending_var = tk.BooleanVar(value=False)
        tk.Checkbutton(add, text='待确认', variable=self.pending_var, font=FONT_S,
                       bg='#f4f6fa').pack(side='left', padx=4)
        tk.Button(add, text='添加字段', font=FONT_S, command=self.on_add_field).pack(
            side='left', padx=4)
        tk.Button(add, text='确认记录', font=FONT_S, command=self.on_confirm).pack(
            side='left', padx=4)

    # ---------------- 趋势页 ----------------
    def _build_trend(self, p):
        box = tk.LabelFrame(p, text='本地趋势统计（近 30 天 · 不使用模型）',
                            font=FONT, bg='#f4f6fa')
        box.pack(fill='both', expand=True, padx=12, pady=12)
        self.trend_text = tk.Text(box, font=('Consolas', 11), wrap='word',
                                  relief='solid', borderwidth=1, bg='#fbfdff')
        self.trend_text.pack(fill='both', expand=True, padx=10, pady=10)
        bar = tk.Frame(box, bg='#f4f6fa')
        bar.pack(fill='x', padx=10, pady=(0, 10))
        tk.Button(bar, text='刷新统计', font=FONT, command=self.on_trend).pack(side='left')

    # ---------------- 设置页 ----------------
    def _build_setting(self, p):
        box = tk.LabelFrame(p, text='设置与数据（仅本地）', font=FONT, bg='#f4f6fa')
        box.pack(fill='both', expand=True, padx=12, pady=12)
        self.set_text = tk.Text(box, height=14, font=FONT, wrap='word',
                                relief='solid', borderwidth=1, bg='#fbfdff')
        self.set_text.pack(fill='both', expand=True, padx=10, pady=10)
        bar = tk.Frame(box, bg='#f4f6fa')
        bar.pack(fill='x', padx=10, pady=(0, 10))
        tk.Button(bar, text='一键清空全部数据', font=FONT,
                  command=self.on_clear).pack(side='left')
        tk.Button(bar, text='导出 Markdown', font=FONT,
                  command=self.on_export).pack(side='left', padx=6)
        self._fill_setting()

    def _fill_setting(self):
        txt = ('数据文件：%s\n'
               '日志文件：%s\n\n'
               '隐私说明\n'
               '· 梦境原文与标签仅保存在本机 SQLite 文件中，本版本不上传任何数据；\n'
               '· 导出的 Markdown 含私人内容，请勿上传到第三方服务；\n'
               '· “一键清空”不可恢复，操作前请先导出备份。\n\n'
               '样例数据\n'
               '· 初始化：python main.py --seed\n'
               '· 清空：    python main.py --reset\n'
               % (self.db_path, os.path.join(
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'logs', 'app.log')))
        self.set_text.delete('1.0', 'end')
        self.set_text.insert('1.0', txt)

    # ================= 行为 =================
    def _msg(self, text, level='info'):
        self.status.config(text=text)
        LOG.info('%s', text)
        if level == 'error':
            messagebox.showerror('操作失败', text)
        elif level == 'warn':
            messagebox.showwarning('请注意', text)

    def on_save(self):
        raw = self.text.get('1.0', 'end-1c')
        try:
            rec = self.svc['record'].create(raw, self.date_var.get() or None)
        except ValidationError as e:
            self._msg(str(e), 'error')
            return None
        except StorageError as e:
            self._msg(str(e), 'error')
            return None
        self.text.delete('1.0', 'end')
        self.date_var.set('')
        self._msg('已保存记录 #%d（状态 draft）' % rec.id)
        self.refresh()
        return rec

    def refresh(self):
        try:
            rows = self.svc['record'].list_recent()
        except StorageError as e:
            self._msg(str(e), 'error')
            return []
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in rows:
            labels = '、'.join(f.label for f in self.svc['review'].list_fields(r.id)[:3])
            self.tree.insert('', 'end', iid=str(r.id),
                             values=(r.id, r.dream_date, r.summary(), labels, r.status))
        self.count.config(text='共 %d 条' % len(rows))
        self.on_trend()
        return rows

    def on_search(self):
        kw = self.kw_var.get()
        try:
            rows = self.svc['record'].search(kw)
        except ValidationError as e:
            self._msg(str(e), 'error')
            return []
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in rows:
            labels = '、'.join(f.label for f in self.svc['review'].list_fields(r.id)[:3])
            self.tree.insert('', 'end', iid=str(r.id),
                             values=(r.id, r.dream_date, r.summary(), labels, r.status))
        self.count.config(text='检索“%s”命中 %d 条' % (kw, len(rows)))
        self._msg('检索“%s”命中 %d 条' % (kw, len(rows)))
        return rows

    def on_select(self):
        sel = self.tree.selection()
        if not sel:
            return
        rid = int(sel[0])
        self.current_id = rid
        try:
            rec = self.svc['record'].require(rid)
        except ValidationError as e:
            self._msg(str(e), 'error')
            return
        fields = self.svc['review'].list_fields(rid)
        lines = ['#%d  %s  状态：%s' % (rec.id, rec.dream_date, rec.status),
                 '原文：%s' % rec.raw_text, '']
        if fields:
            for f in fields:
                lines.append('  [%s] %s  置信度 %.2f%s%s'
                             % (domain.FIELD_TYPE_CN[f.field_type], f.label, f.confidence,
                                '  待确认' if f.needs_confirm else '',
                                '  已人工修改' if f.user_edited else ''))
        else:
            lines.append('  （暂无解析字段，可手动添加；此记录的“信息量”视为低）')
        pending = sum(1 for f in fields if f.needs_confirm)
        if pending:
            lines.append('')
            lines.append('  ⚠ 仍有 %d 个待确认字段，确认前不计入趋势统计' % pending)
        self.detail.config(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', '\n'.join(lines))
        self.detail.config(state='disabled')

    def on_add_field(self):
        if self.current_id is None:
            self._msg('请先在列表中选中一条记录', 'warn')
            return
        m = {v: k for k, v in domain.FIELD_TYPE_CN.items()}
        try:
            self.svc['review'].add_field(self.current_id, m[self.ft_var.get()],
                                         self.label_var.get(),
                                         needs_confirm=self.pending_var.get())
        except ValidationError as e:
            self._msg(str(e), 'error')
            return
        self.label_var.set('')
        self.pending_var.set(False)
        self._msg('已添加字段')
        self.on_select()
        self.refresh()

    def on_confirm(self):
        if self.current_id is None:
            self._msg('请先在列表中选中一条记录', 'warn')
            return
        try:
            pending = self.svc['review'].confirm_record(self.current_id)
        except ValidationError as e:
            self._msg(str(e), 'error')
            return
        self._msg('记录 #%d 已确认，仍有 %d 个待确认字段' % (self.current_id, pending))
        self.on_select()
        self.refresh()

    def on_delete(self):
        if self.current_id is None:
            self._msg('请先在列表中选中一条记录', 'warn')
            return
        if not messagebox.askyesno('二次确认', '删除后不可恢复，确定删除记录 #%d 吗？'
                                                % self.current_id):
            return
        try:
            self.svc['record'].delete(self.current_id)
        except ValidationError as e:
            self._msg(str(e), 'error')
            return
        self._msg('已删除记录 #%d' % self.current_id)
        self.current_id = None
        self.detail.config(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.config(state='disabled')
        self.refresh()

    def on_trend(self):
        res = self.svc['trend'].top_symbols()
        lines = ['近 30 天趋势统计（本地聚合，不调用模型）', '=' * 46, '']
        if res['insufficient']:
            lines.append('样本过少，暂不出统计：当前 %d 条，需要满 %d 条。'
                         % (res['records'], res['need']))
            lines.append('（这条提示本身就是设计要求的空数据状态）')
        else:
            lines.append('有效记录：%d 条' % res['records'])
            lines.append('')
            lines.append('意象 Top5')
            for i, it in enumerate(res['symbols'], 1):
                lines.append('  %d. %-10s %s  (%d 次)'
                             % (i, it['label'], '█' * it['count'], it['count']))
            lines.append('')
            lines.append('情绪频次')
            for it in res['emotions']:
                lines.append('  %-10s %s  (%d 次)'
                             % (it['label'], '█' * it['count'], it['count']))
            lines.append('')
            lines.append('说明：待确认字段不计入统计。')
        self.trend_text.delete('1.0', 'end')
        self.trend_text.insert('1.0', '\n'.join(lines))
        return res

    def on_export(self):
        path = filedialog.asksaveasfilename(
            title='导出梦境档案', defaultextension='.md',
            initialfile='dreams.md', filetypes=[('Markdown', '*.md'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            n = self.svc['export'].export_markdown(path)
        except ValidationError as e:
            self._msg(str(e), 'error')
            return
        self._msg('已导出 %d 条记录到 %s' % (n, path))
        messagebox.showinfo('导出成功', '已导出 %d 条记录到\n%s\n\n'
                                        '提示：该文件含私人内容，请勿上传到第三方服务。'
                            % (n, path))

    def on_clear(self):
        if not messagebox.askyesno('二次确认', '将清空全部梦境数据且不可恢复，确定继续吗？'):
            return
        try:
            self.svc['record'].repo.clear_all()
        except StorageError as e:
            self._msg(str(e), 'error')
            return
        self.current_id = None
        self.refresh()
        self._msg('已清空全部数据')
