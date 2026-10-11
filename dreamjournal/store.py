# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 数据访问层（对应实验3 表 3-5 的 DreamRepository / SQLiteStore）。

选择 SQLite 的理由见实验3 ADR-02：单用户单机、无并发需求、标准库零部署，
且天然满足 NFR-S1“数据默认仅存本机”。

v0.1.0 可运行初版：只实现建表、新增、查询、列表、删除。
"""
import os
import sqlite3

from . import domain

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


class DreamRepository:
    def __init__(self, db_path):
        self.db_path = db_path
        d = os.path.dirname(os.path.abspath(db_path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def init_schema(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # ---------------- 记录 ----------------
    def add(self, rec):
        with self.connect() as conn:
            cur = conn.execute(
                'INSERT INTO dream_record (dream_date, created_at, source, raw_text,'
                ' transcript_confidence, information_density, audio_path, status)'
                ' VALUES (?,?,?,?,?,?,?,?)',
                (rec.dream_date, rec.created_at, rec.source, rec.raw_text,
                 rec.transcript_confidence, rec.information_density,
                 rec.audio_path, rec.status))
            rec.id = cur.lastrowid
            return rec.id

    def get(self, record_id):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM dream_record WHERE id = ?',
                               (record_id,)).fetchone()
        return self._to_record(row) if row else None

    def list_all(self, limit=200):
        with self.connect() as conn:
            rows = conn.execute(
                'SELECT * FROM dream_record ORDER BY dream_date DESC, id DESC'
                ' LIMIT ?', (limit,)).fetchall()
        return [self._to_record(r) for r in rows]

    def update_status(self, record_id, status):
        with self.connect() as conn:
            conn.execute('UPDATE dream_record SET status = ? WHERE id = ?',
                         (status, record_id))

    def delete(self, record_id):
        with self.connect() as conn:
            conn.execute('DELETE FROM parsed_field WHERE record_id = ?', (record_id,))
            conn.execute('DELETE FROM dream_record WHERE id = ?', (record_id,))

    def clear_all(self):
        with self.connect() as conn:
            conn.execute('DELETE FROM parsed_field')
            conn.execute('DELETE FROM dream_record')

    def count(self):
        with self.connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM dream_record').fetchone()[0]

    # ---------------- 字段 ----------------
    def add_field(self, f):
        with self.connect() as conn:
            cur = conn.execute(
                'INSERT INTO parsed_field (record_id, field_type, label, confidence,'
                ' needs_confirm, user_edited) VALUES (?,?,?,?,?,?)',
                (f.record_id, f.field_type, f.label, f.confidence,
                 int(f.needs_confirm), int(f.user_edited)))
            f.id = cur.lastrowid
            return f.id

    def fields_of(self, record_id):
        with self.connect() as conn:
            rows = conn.execute(
                'SELECT * FROM parsed_field WHERE record_id = ? ORDER BY id',
                (record_id,)).fetchall()
        return [self._to_field(r) for r in rows]

    def update_field_label(self, field_id, label):
        with self.connect() as conn:
            conn.execute('UPDATE parsed_field SET label = ?, user_edited = 1'
                         ' WHERE id = ?', (label, field_id))

    def delete_field(self, field_id):
        with self.connect() as conn:
            conn.execute('DELETE FROM parsed_field WHERE id = ?', (field_id,))

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
