# -*- coding: utf-8 -*-
"""AI 适配层：LLM 调用、Prompt 模板、知识库、检索与 RAG 流水线。

分层位置见实验3 图 3-2：本包属于「AI 适配层」，只被应用服务层调用，
自身不依赖任何 GUI，也不直接读写业务数据表——因此可以单独测试、整体替换或关闭
（实验2 表 3-14 的“非 AI 降级方案”）。
"""
from .client import (LLMClient, LLMError, LLMAuthError, LLMUnavailable,
                     LLMTimeout, LLMRateLimit, LLMResponseError, LLMResult,
                     OfflineProvider)
from .kb import build_index, load_index, SOURCES
from .retriever import BM25Retriever, tokenize
from .prompts import build_messages, render_full_input, PROMPT_VERSIONS
from .pipeline import RagPipeline, assemble_context, extract_citations

__all__ = [
    'LLMClient', 'LLMError', 'LLMAuthError', 'LLMUnavailable', 'LLMTimeout',
    'LLMRateLimit', 'LLMResponseError', 'LLMResult', 'OfflineProvider',
    'build_index', 'load_index', 'SOURCES', 'BM25Retriever', 'tokenize',
    'build_messages', 'render_full_input', 'PROMPT_VERSIONS',
    'RagPipeline', 'assemble_context', 'extract_citations',
]
