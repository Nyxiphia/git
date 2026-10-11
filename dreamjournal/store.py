# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 数据访问层（对应实验3 表 3-5 的 DreamRepository / SQLiteStore）。

v0.2.0 修订（针对实验4 代码审查发现的问题）：
  · R2 数据访问异常统一转换为 StorageError，不再把裸 sqlite3.Error 抛给界面
  · R4 补上 search()（实验3 表 3-8 遗漏的检索接口签名），使用参数化 LIKE
       并转义 % 与 _，杜绝注入与通配符滥用
  · 新增 stats()/recent_days() 供本地趋势统计使用（不调用模型）
"""
import os
import sqlite3

from . import domain


class StorageError(Exception):
    """数据访问层统一异常，界面层只需捕获这一种。"""


SCHEMA = """
CREATE TABLE IF NOT EXISTS dream_record (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    dream_date            TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    source                TEXT    NOT NULL DEFAULT 'text',
    raw_text              TEXT    NOT NULL,
    transcript_confidence REAL,
    information_density   TEXT,
    audio_path            TEXT,
    status                TEXT    NOT NULL DEFAULT 'draft'
);
CREATE TABLE IF NOT EXISTS parsed_field (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     INTEGER NOT NULL,
    field_type    TEXT    NOT NULL,
    label         TEXT    NOT NULL,
    confidence    REAL    NOT NULL DEFAULT 1.0,
    needs_confirm INTEGER NOT NULL DEFAULT 0,
    user_edited   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (record_id) REFERENCES dream_record(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_record_date ON dream_record(dream_date);
CREATE INDEX IF NOT EXISTS idx_field_record ON parsed_field(record_id);
"""


def _escape_like(s):
    """转义 LIKE 的通配符，避免用户输入的 % 和 _ 变成通配符。"""
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class DreamRepository:
    def __init__(self, db_path):
        self.db_path = db_path
        d = os.path.dirname(os.path.abspath(db_path))
        if d and not os.path.isdir(d):
            try:
                os.makedirs(d, exist_ok=True)
            except OSError as e:
                raise StorageError('无法创建数据目录 %s：%s' % (d, e))

    # ---------------- 连接 ----------------
    def connect(self):
        try:
            conn = sqlite3.connect(self.db_path)
        except sqlite3.Error as e:
            raise StorageError('无法打开数据库 %s：%s' % (self.db_path, e))
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def _exec(self, sql, params=(), fetch=None):
        try:
            with self.connect() as conn:
                cur = conn.execute(sql, params)
                if fetch == 'one':
                    return cur.fetchone()
                if fetch == 'all':
                    return cur.fetchall()
                return cur.lastrowid
        except sqlite3.Error as e:
            raise StorageError('数据库操作失败：%s' % e)

    def init_schema(self):
        try:
            with self.connect() as conn:
                conn.executescript(SCHEMA)
        except sqlite3.Error as e:
            raise StorageError('初始化数据库结构失败：%s' % e)

    # ---------------- 记录 ----------------
    def add(self, rec):
        rec.id = self._exec(
            'INSERT INTO dream_record (dream_date, created_at, source, raw_text,'
            ' transcript_confidence, information_density, audio_path, status)'
            ' VALUES (?,?,?,?,?,?,?,?)',
            (rec.dream_date, rec.created_at, rec.source, rec.raw_text,
             rec.transcript_confidence, rec.information_density,
             rec.audio_path, rec.status))
        return rec.id

    def get(self, record_id):
        row = self._exec('SELECT * FROM dream_record WHERE id = ?',
                         (record_id,), fetch='one')
        return self._to_record(row) if row else None

    def list_all(self, limit=200):
        rows = self._exec(
            'SELECT * FROM dream_record ORDER BY dream_date DESC, id DESC LIMIT ?',
            (limit,), fetch='all')
        return [self._to_record(r) for r in rows]

    def search(self, keyword, limit=200):
        """全文检索（UC-05）。参数化查询 + 转义通配符，防止注入。"""
        pat = '%' + _escape_like(keyword.strip()) + '%'
        rows = self._exec(
            "SELECT * FROM dream_record WHERE raw_text LIKE ? ESCAPE '\\'"
            ' ORDER BY dream_date DESC, id DESC LIMIT ?',
            (pat, limit), fetch='all')
        return [self._to_record(r) for r in rows]

    def update_status(self, record_id, status):
        self._exec('UPDATE dream_record SET status = ? WHERE id = ?',
                   (status, record_id))

    def update_text(self, record_id, raw_text):
        self._exec('UPDATE dream_record SET raw_text = ? WHERE id = ?',
                   (raw_text, record_id))

    def delete(self, record_id):
        # parsed_field 由 ON DELETE CASCADE 自动清理；显式删除是为了不依赖 pragma
        self._exec('DELETE FROM parsed_field WHERE record_id = ?', (record_id,))
        self._exec('DELETE FROM dream_record WHERE id = ?', (record_id,))

    def clear_all(self):
        self._exec('DELETE FROM parsed_field')
        self._exec('DELETE FROM dream_record')

    def count(self):
        return self._exec('SELECT COUNT(*) AS n FROM dream_record',
                          fetch='one')['n']

    # ---------------- 字段 ----------------
    def add_field(self, f):
        f.id = self._exec(
            'INSERT INTO parsed_field (record_id, field_type, label, confidence,'
            ' needs_confirm, user_edited) VALUES (?,?,?,?,?,?)',
            (f.record_id, f.field_type, f.label, f.confidence,
             int(f.needs_confirm), int(f.user_edited)))
        return f.id

    def get_field(self, field_id):
        row = self._exec('SELECT * FROM parsed_field WHERE id = ?',
                         (field_id,), fetch='one')
        return self._to_field(row) if row else None

    def fields_of(self, record_id):
        rows = self._exec('SELECT * FROM parsed_field WHERE record_id = ?'
                          ' ORDER BY id', (record_id,), fetch='all')
        return [self._to_field(r) for r in rows]

    def update_field_label(self, field_id, label):
        self._exec('UPDATE parsed_field SET label = ?, user_edited = 1'
                   ' WHERE id = ?', (label, field_id))

    def delete_field(self, field_id):
        self._exec('DELETE FROM parsed_field WHERE id = ?', (field_id,))

    def count_pending(self, record_id):
        return self._exec(
            'SELECT COUNT(*) AS n FROM parsed_field'
            ' WHERE record_id = ? AND needs_confirm = 1',
            (record_id,), fetch='one')['n']

    # ---------------- 本地统计（不调用模型） ----------------
    def stats_by_field_type(self, field_type, exclude_pending=True, limit=5):
        sql = ('SELECT label, COUNT(*) AS n FROM parsed_field'
               ' WHERE field_type = ?')
        if exclude_pending:
            sql += ' AND needs_confirm = 0'
        sql += ' GROUP BY label ORDER BY n DESC, label ASC LIMIT ?'
        return [(r['label'], r['n']) for r in
                self._exec(sql, (field_type, limit), fetch='all')]

    def recent_records(self, since_date):
        rows = self._exec('SELECT * FROM dream_record WHERE dream_date >= ?'
                          ' ORDER BY dream_date DESC', (since_date,), fetch='all')
        return [self._to_record(r) for r in rows]

    # ---------------- 工具 ----------------
    @staticmethod
    def _to_record(row):
        return domain.DreamRecord(
            dream_date=row['dream_date'], raw_text=row['raw_text'],
            source=row['source'], status=row['status'],
            information_density=row['information_density'],
            transcript_confidence=row['transcript_confidence'],
            audio_path=row['audio_path'], created_at=row['created_at'],
            id=row['id'])

    @staticmethod
    def _to_field(row):
        return domain.ParsedField(
            record_id=row['record_id'], field_type=row['field_type'],
            label=row['label'], confidence=row['confidence'],
            needs_confirm=bool(row['needs_confirm']),
            user_edited=bool(row['user_edited']), id=row['id'])
