# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 应用服务层（对应实验3 表 3-5 / 表 3-8）。

v0.2.0 修订版：补全非AI关键业务闭环（记录 → 校验 → 落库 → 标注 → 确认 →
本地统计 → 检索 → 导出 → 删除），并处理实验4 代码审查发现的问题：

  R1 参数校验缺失      -> 新增 validate_text / validate_date，统一抛 ValidationError
  R2 异常未处理        -> 统一捕获 StorageError 并转换为 ValidationError / 业务异常
  R4 检索接口不存在    -> 补 RecordService.search
  R5 敏感数据无声明    -> 导出时写入隐私声明；提供“仅本地”提示
"""
import os
from datetime import date, datetime, timedelta

from . import domain
from .store import DreamRepository, StorageError


class ValidationError(Exception):
    """参数校验失败或业务前置条件不满足（界面层据此给出提示，不崩溃）。"""


def _today():
    return date.today().strftime('%Y-%m-%d')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ---------------- 校验（R1） ----------------
def validate_text(raw_text):
    if raw_text is None or not str(raw_text).strip():
        raise ValidationError('梦境内容不能为空，请输入至少 1 个字符。')
    text = str(raw_text).strip()
    if len(text) > domain.RAW_TEXT_MAX:
        raise ValidationError('梦境内容超过 %d 字（当前 %d 字），请精简后再保存。'
                              % (domain.RAW_TEXT_MAX, len(text)))
    return text


def validate_date(s, allow_empty=True):
    """校验并规范化日期为 YYYY-MM-DD。

    必须规范化而不是原样入库：dream_record.dream_date 是字符串列，
    list_all 依赖字符串排序，recent_records 依赖字符串比较，
    若允许 '2026-9-7' 这类非规范写法入库，排序与趋势的日期筛选都会出错。
    """
    if s is None or not str(s).strip():
        if allow_empty:
            return _today()
        raise ValidationError('日期不能为空，格式应为 YYYY-MM-DD。')
    s = str(s).strip()
    try:
        d = datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        raise ValidationError('日期格式不正确：%r，应为 YYYY-MM-DD（如 2026-09-27）。' % s)
    if d > date.today() + timedelta(days=1):
        raise ValidationError('记录日期 %s 晚于今天，请确认日期是否填错。' % s)
    return d.strftime('%Y-%m-%d')


def validate_field_type(ft):
    if ft not in domain.FIELD_TYPES:
        raise ValidationError('字段类型 %r 非法，只能是：%s'
                              % (ft, '、'.join(domain.FIELD_TYPES)))
    return ft


class _Base:
    def __init__(self, repo: DreamRepository):
        self.repo = repo


class RecordService(_Base):
    """记录与落库（实验3 表 3-8 IRecordService）。"""

    def create(self, raw_text, dream_date=None, source=domain.SOURCE_TEXT):
        text = validate_text(raw_text)
        d = validate_date(dream_date)
        if source not in domain.SOURCES:
            raise ValidationError('来源 %r 非法' % source)
        rec = domain.DreamRecord(dream_date=d, raw_text=text, source=source,
                                 status=domain.STATUS_DRAFT, created_at=_now())
        try:
            self.repo.add(rec)
        except StorageError as e:
            raise ValidationError('保存失败（数据文件不可写）：%s' % e)
        return rec

    def list_recent(self, limit=200):
        return self.repo.list_all(limit)

    def get(self, record_id):
        return self.repo.get(record_id)

    def require(self, record_id):
        """取记录，不存在则抛 ValidationError（避免界面拿到 None 后崩溃）。"""
        rec = self.repo.get(record_id)
        if rec is None:
            raise ValidationError('记录 #%s 不存在，可能已被删除。' % record_id)
        return rec

    def search(self, keyword, limit=200):
        """关键词检索（UC-05，R4 补上的接口）。"""
        if not keyword or not str(keyword).strip():
            raise ValidationError('请输入检索关键词。')
        try:
            return self.repo.search(str(keyword).strip(), limit)
        except StorageError as e:
            raise ValidationError('检索失败：%s' % e)

    def update_text(self, record_id, raw_text):
        self.require(record_id)
        text = validate_text(raw_text)
        self.repo.update_text(record_id, text)
        return self.repo.get(record_id)

    def delete(self, record_id):
        self.require(record_id)
        self.repo.delete(record_id)
        return True


class ReviewService(_Base):
    """人工确认与修正（实验3 表 3-8 IReviewService，UC-03）。"""

    def list_fields(self, record_id):
        return self.repo.fields_of(record_id)

    def add_field(self, record_id, field_type, label,
                  confidence=1.0, needs_confirm=False):
        if self.repo.get(record_id) is None:
            raise ValidationError('记录 #%s 不存在，无法新增字段。' % record_id)
        validate_field_type(field_type)
        if not label or not str(label).strip():
            raise ValidationError('字段内容不能为空。')
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValidationError('置信度必须在 0~1 之间。')
        f = domain.ParsedField(record_id=record_id, field_type=field_type,
                               label=str(label).strip(), confidence=float(confidence),
                               needs_confirm=bool(needs_confirm))
        self.repo.add_field(f)
        return f

    def update_field(self, field_id, label):
        if self.repo.get_field(field_id) is None:
            raise ValidationError('字段 #%s 不存在。' % field_id)
        if not label or not str(label).strip():
            raise ValidationError('字段内容不能为空。')
        self.repo.update_field_label(field_id, str(label).strip())
        return self.repo.get_field(field_id)

    def delete_field(self, field_id):
        if self.repo.get_field(field_id) is None:
            raise ValidationError('字段 #%s 不存在。' % field_id)
        self.repo.delete_field(field_id)

    def confirm_record(self, record_id):
        """确认记录；返回仍未处理的待确认字段数量。

        设计依据：实验3 图 3-3 约束“未确认字段不计入趋势统计”，
        因此待确认字段仍然允许存在，只是不参与统计。
        """
        if self.repo.get(record_id) is None:
            raise ValidationError('记录 #%s 不存在，无法确认。' % record_id)
        self.repo.update_status(record_id, domain.STATUS_CONFIRMED)
        return self.repo.count_pending(record_id)


class TrendService(_Base):
    """本地统计（实验3 表 3-5：不调用模型，只做聚合）。"""

    def top_symbols(self, days=30, limit=5):
        since = (date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
        total = len(self.repo.recent_records(since))
        if total < domain.TREND_MIN_RECORDS:
            return {'insufficient': True, 'records': total,
                    'need': domain.TREND_MIN_RECORDS, 'symbols': [], 'emotions': []}
        return {
            'insufficient': False,
            'records': total,
            'symbols': [{'label': l, 'count': n} for l, n in
                        self.repo.stats_by_field_type(domain.FIELD_SYMBOL, limit=limit)],
            'emotions': [{'label': l, 'count': n} for l, n in
                         self.repo.stats_by_field_type(domain.FIELD_EMOTION, limit=limit)],
        }


class ExportService(_Base):
    """Markdown 导出（实验3 表 3-8 IExportService）。"""

    HEADER = ('# 梦境档案导出\n\n> 本文件包含敏感的私人内容，仅保存在本机，请勿上传到任何第三方服务。\n\n')

    def export_markdown(self, target_path):
        target_path = os.path.abspath(target_path)
        parent = os.path.dirname(target_path)
        try:
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
        except OSError as e:
            raise ValidationError('导出目录不可创建：%s' % e)

        records = self.repo.list_all(limit=100000)
        lines = [self.HEADER]
        for r in records:
            lines.append('## #%d  %s\n' % (r.id, r.dream_date))
            lines.append('%s\n\n' % r.raw_text)
            fs = self.repo.fields_of(r.id)
            if fs:
                lines.append('| 类型 | 内容 | 置信度 | 待确认 |\n|---|---|---|---|\n')
                for f in fs:
                    lines.append('| %s | %s | %.2f | %s |\n'
                                 % (domain.FIELD_TYPE_CN[f.field_type], f.label,
                                    f.confidence, '是' if f.needs_confirm else '否'))
                lines.append('\n')
        try:
            with open(target_path, 'w', encoding='utf-8') as fh:
                fh.write(''.join(lines))
        except OSError as e:
            raise ValidationError('导出失败（目标路径不可写）：%s' % e)
        return len(records)
