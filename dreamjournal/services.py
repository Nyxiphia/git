# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 应用服务层（对应实验3 表 3-5 / 表 3-8）。

v0.1.0 可运行初版：仅打通“文字记录 → 落库 → 列表”这一条最小闭环，
其余服务保留实验3 表 3-8 约定的方法签名，暂未实现。
"""
from datetime import date, datetime

from . import domain
from .store import DreamRepository


class ValidationError(Exception):
    """参数校验失败。"""


def _today():
    return date.today().strftime('%Y-%m-%d')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class RecordService:
    """记录与落库（实验3 表 3-5）。"""

    def __init__(self, repo: DreamRepository):
        self.repo = repo

    def create(self, raw_text, dream_date=None, source=domain.SOURCE_TEXT):
        rec = domain.DreamRecord(
            dream_date=dream_date or _today(),
            raw_text=raw_text,
            source=source,
            status=domain.STATUS_DRAFT,
            created_at=_now())
        self.repo.add(rec)
        return rec

    def list_recent(self, limit=200):
        return self.repo.list_all(limit)

    def get(self, record_id):
        return self.repo.get(record_id)

    def delete(self, record_id):
        self.repo.delete(record_id)


class ReviewService:
    """人工确认与修正（实验3 表 3-5 / UC-03）。"""

    def __init__(self, repo: DreamRepository):
        self.repo = repo

    def list_fields(self, record_id):
        return self.repo.fields_of(record_id)

    def add_field(self, record_id, field_type, label,
                  confidence=1.0, needs_confirm=False):
        raise NotImplementedError('v0.1.0 未实现：手动标注字段')

    def update_field(self, field_id, label):
        raise NotImplementedError('v0.1.0 未实现：修正字段')

    def confirm_record(self, record_id):
        raise NotImplementedError('v0.1.0 未实现：确认记录')


class TrendService:
    """本地统计（实验3 表 3-5：不调用模型）。"""

    def __init__(self, repo: DreamRepository):
        self.repo = repo

    def top_symbols(self, days=30, limit=5):
        raise NotImplementedError('v0.1.0 未实现：趋势统计')


class ExportService:
    """Markdown 导出（实验3 表 3-5）。"""

    def __init__(self, repo: DreamRepository):
        self.repo = repo

    def export_markdown(self, target_path):
        raise NotImplementedError('v0.1.0 未实现：导出 Markdown')
