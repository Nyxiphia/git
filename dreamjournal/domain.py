# -*- coding: utf-8 -*-
"""AI 梦境记录与解析 —— 领域模型。

对应实验3 图 3-3 核心数据模型（类图）：
    DreamRecord 1 : 0..* ParsedField
    DreamRecord 1 : 0..1 AudioAsset
字段约束与敏感标记见实验3 表 3-7。
"""
from dataclasses import dataclass, field
from typing import List, Optional

# ---- 枚举取值（对应实验3 图 3-3 中的 enum）----
SOURCE_TEXT = 'text'
SOURCE_VOICE = 'voice'
SOURCES = (SOURCE_TEXT, SOURCE_VOICE)

STATUS_DRAFT = 'draft'
STATUS_PARSED = 'parsed'
STATUS_CONFIRMED = 'confirmed'
STATUSES = (STATUS_DRAFT, STATUS_PARSED, STATUS_CONFIRMED)

DENSITY_HIGH = 'high'
DENSITY_MEDIUM = 'medium'
DENSITY_LOW = 'low'
DENSITIES = (DENSITY_HIGH, DENSITY_MEDIUM, DENSITY_LOW)

FIELD_EMOTION = 'emotion'
FIELD_CHARACTER = 'character'
FIELD_SCENE = 'scene'
FIELD_SYMBOL = 'symbol'
FIELD_TYPES = (FIELD_EMOTION, FIELD_CHARACTER, FIELD_SCENE, FIELD_SYMBOL)
FIELD_TYPE_CN = {FIELD_EMOTION: '情绪', FIELD_CHARACTER: '人物',
                 FIELD_SCENE: '场景', FIELD_SYMBOL: '意象'}

# 约束（实验3 表 3-7）
RAW_TEXT_MAX = 2000
AUDIO_MAX_SEC = 180
TREND_MIN_RECORDS = 10


@dataclass
class DreamRecord:
    """一条梦境记录。raw_text 与 audio_path 属于敏感数据（仅本机保存）。"""
    dream_date: str                      # YYYY-MM-DD
    raw_text: str                        # 非空且 <= RAW_TEXT_MAX
    source: str = SOURCE_TEXT
    status: str = STATUS_DRAFT
    information_density: Optional[str] = None
    transcript_confidence: Optional[float] = None
    audio_path: Optional[str] = None
    created_at: str = ''
    id: Optional[int] = None
    fields: List['ParsedField'] = field(default_factory=list)

    def summary(self, n: int = 24) -> str:
        t = self.raw_text.replace('\n', ' ')
        return t if len(t) <= n else t[:n] + '……'


@dataclass
class ParsedField:
    """解析字段。needs_confirm=True 的字段不计入趋势统计（实验3 图 3-3 约束）。"""
    record_id: int
    field_type: str                      # FIELD_TYPES 之一
    label: str
    confidence: float = 1.0              # 0..1
    needs_confirm: bool = False
    user_edited: bool = False
    id: Optional[int] = None
