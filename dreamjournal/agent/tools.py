# -*- coding: utf-8 -*-
"""工具层（实验6 2.2）：Schema 定义、参数校验、权限边界、超时与错误反馈。

三条关键原则：
  1. **模型只能选工具和填参数，不能执行任意函数名或命令**——所有可调用工具都在
     `TOOLS` 白名单里，名字不在表中的一律拒绝，不做任何反射式调用。
  2. **权限边界由程序执行，不写在提示词里**：写文件的工具只能写到 `out/` 目录，
     文件名不允许带路径分隔符；数据库工具根本不返回 `raw_text`（隐私数据），
     即使模型要求也拿不到。
  3. **参数先校验再执行**：类型、范围、枚举、必填项、多余字段全部检查，
     校验失败返回结构化错误，供模型下一轮修正。
"""
import os
import re
import sqlite3
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'out')

FIELD_TYPES = ('emotion', 'character', 'scene', 'symbol')
STATUSES = ('draft', 'parsed', 'confirmed')
SAFE_NAME = re.compile(r'^[A-Za-z0-9_\u4e00-\u9fff\-]{1,40}\.md$')


class ToolError(Exception):
    """工具层错误的基类，带稳定的错误码供上层与日志使用。"""
    code = 'tool_error'


class SchemaError(ToolError):
    code = 'invalid_arguments'


class PermissionDenied(ToolError):
    code = 'permission_denied'


class ToolTimeout(ToolError):
    code = 'timeout'


class ToolFailure(ToolError):
    code = 'tool_failure'


class ToolContext:
    """一次运行共享的上下文：数据库路径、超时覆盖、是否允许写文件。"""

    def __init__(self, db_path, allow_write=True, timeout_override=None):
        self.db_path = db_path
        self.allow_write = allow_write
        self.timeout_override = timeout_override

    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn


# ---------------- 工具实现 ----------------
def _list_dreams(ctx, days, status, limit):
    """只读：按日期范围列出记录摘要。**故意不返回 raw_text**（隐私）。"""
    with ctx.connect() as c:
        sql = ('SELECT id, dream_date, status, source, information_density '
               'FROM dream_record WHERE 1=1')
        args = []
        if days and days > 0:
            sql += ' AND dream_date >= date("now", ?)'
            args.append('-%d day' % days)
        if status:
            sql += ' AND status = ?'
            args.append(status)
        sql += ' ORDER BY dream_date DESC, id DESC LIMIT ?'
        args.append(limit)
        rows = [dict(r) for r in c.execute(sql, args)]
        total = c.execute('SELECT COUNT(*) FROM dream_record').fetchone()[0]
    return {'returned': len(rows), 'records_total': total, 'items': rows,
            'note': '按隐私约束，raw_text 不提供查询'}


def _field_stats(ctx, field_type, top_n, days, exclude_pending):
    """只读：按字段类型做频次统计，默认排除“待确认”字段（与实验4 的规则一致）。"""
    sql = ('SELECT f.label AS label, COUNT(*) AS n FROM parsed_field f '
           'JOIN dream_record r ON r.id = f.record_id WHERE f.field_type = ?')
    args = [field_type]
    if exclude_pending:
        sql += ' AND f.needs_confirm = 0'
    if days and days > 0:
        sql += ' AND r.dream_date >= date("now", ?)'
        args.append('-%d day' % days)
    sql += ' GROUP BY f.label ORDER BY n DESC, f.label ASC'
    with ctx.connect() as c:
        rows = [dict(r) for r in c.execute(sql, args)]
        pending = c.execute(
            'SELECT COUNT(*) FROM parsed_field WHERE field_type = ? AND needs_confirm = 1',
            (field_type,)).fetchone()[0]
    return {'field_type': field_type, 'top': rows[:top_n], 'distinct_labels': len(rows),
            'fields_total': sum(r['n'] for r in rows),
            'excluded_pending': pending if exclude_pending else 0}


def _export_markdown(ctx, field_type, top_n, filename):
    """写文件：把统计结果写成 Markdown。**内容由程序生成**，模型只能选参数。

    幂等性：先写临时文件再原子替换，重复调用得到同样内容，不会产生重复文件或重复追加。
    """
    if not ctx.allow_write:
        raise PermissionDenied('本次运行未开启写权限')
    if not SAFE_NAME.match(filename or ''):
        raise PermissionDenied('文件名不合法：只能写 out/ 下的 .md 文件，且不能带路径')
    target = os.path.join(OUT_DIR, filename)
    real = os.path.realpath(target)
    if os.path.dirname(real) != os.path.realpath(OUT_DIR):
        raise PermissionDenied('目标路径越界：只允许写入 out/ 目录')

    stats = _field_stats(ctx, field_type, top_n, 0, True)
    lines = ['# 梦境统计报告（自动生成）', '',
             '> 本文件由 Agent 的 export_markdown 工具生成，内容由程序计算，'
             '不含梦境原文。', '',
             '| 标签 | 次数 |', '| --- | --- |']
    for r in stats['top']:
        lines.append('| %s | %d |' % (r['label'], r['n']))
    lines += ['', '统计口径：字段类型 %s，已排除待确认字段 %d 个。'
              % (field_type, stats['excluded_pending'])]
    text = '\n'.join(lines) + '\n'

    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = real + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, real)
    return {'path': os.path.relpath(real, ROOT).replace('\\', '/'),
            'bytes': len(text.encode('utf-8')), 'rows': len(stats['top'])}


def _read_export(ctx, filename):
    """只读：核对 out/ 下已导出的文件内容。

    存在的意义：写操作超时或状态不明时，模型必须先用它核对结果，
    再决定是否重试，避免“其实写成功了又重写一遍”。
    """
    if not SAFE_NAME.match(filename or ''):
        raise PermissionDenied('文件名不合法：只能读 out/ 下的 .md 文件')
    target = os.path.join(OUT_DIR, filename)
    real = os.path.realpath(target)
    if os.path.dirname(real) != os.path.realpath(OUT_DIR):
        raise PermissionDenied('目标路径越界：只允许读取 out/ 目录')
    if not os.path.isfile(real):
        return {'exists': False, 'filename': filename, 'note': '文件不存在'}
    with open(real, encoding='utf-8') as f:
        text = f.read()
    return {'exists': True, 'filename': filename, 'bytes': len(text.encode('utf-8')),
            'lines': len(text.split('\n')),
            'head': '\n'.join(text.split('\n')[:12])}


# ---------------- 工具注册表 ----------------
class ToolSpec:
    def __init__(self, name, description, schema, handler, side_effect=False,
                 requires_confirm=False, timeout=10.0, idempotent='不适用（只读）'):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.side_effect = side_effect
        self.requires_confirm = requires_confirm
        self.timeout = timeout
        self.idempotent = idempotent

    def as_openai(self):
        return {'type': 'function',
                'function': {'name': self.name, 'description': self.description,
                             'parameters': self.schema}}


TOOLS = {
    'list_dreams': ToolSpec(
        name='list_dreams',
        description='列出本机梦境记录的摘要（不含梦境原文）。只读，可重复调用。',
        schema={
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'minimum': 1, 'maximum': 365,
                         'description': '只取最近多少天的记录，默认 30'},
                'status': {'type': 'string', 'enum': list(STATUSES),
                           'description': '可选，按状态过滤'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50,
                          'description': '最多返回多少条，默认 20'},
            },
            'required': [],
            'additionalProperties': False,
        },
        handler=_list_dreams,
    ),
    'field_stats': ToolSpec(
        name='field_stats',
        description='按字段类型统计标签出现次数并返回 Top-N。只读，可重复调用。'
                    '默认排除“待确认”字段，与项目既有统计口径一致。',
        schema={
            'type': 'object',
            'properties': {
                'field_type': {'type': 'string', 'enum': list(FIELD_TYPES),
                               'description': '字段类型：emotion/character/scene/symbol'},
                'top_n': {'type': 'integer', 'minimum': 1, 'maximum': 10,
                          'description': '取前几名，默认 5'},
                'days': {'type': 'integer', 'minimum': 0, 'maximum': 365,
                         'description': '只统计最近多少天，0 表示不限，默认 0'},
                'exclude_pending': {'type': 'boolean',
                                    'description': '是否排除待确认字段，默认 true'},
            },
            'required': ['field_type'],
            'additionalProperties': False,
        },
        handler=_field_stats,
    ),
    'export_markdown': ToolSpec(
        name='export_markdown',
        description='把统计结果导出为 Markdown 文件到 out/ 目录。**会写文件，需要用户确认**。',
        schema={
            'type': 'object',
            'properties': {
                'field_type': {'type': 'string', 'enum': list(FIELD_TYPES)},
                'top_n': {'type': 'integer', 'minimum': 1, 'maximum': 10},
                'filename': {'type': 'string',
                             'description': '文件名，如 dream_stats.md，只能写到 out/ 目录'},
            },
            'required': ['field_type', 'filename'],
            'additionalProperties': False,
        },
        handler=_export_markdown,
        side_effect=True,
        requires_confirm=True,
        idempotent='幂等：临时文件 + 原子替换，重复调用内容相同',
    ),
    'read_export': ToolSpec(
        name='read_export',
        description='读取 out/ 下已导出文件的内容，用于核对写操作是否真的成功。只读。',
        schema={
            'type': 'object',
            'properties': {
                'filename': {'type': 'string',
                             'description': '要核对的文件名，如 dream_stats.md'},
            },
            'required': ['filename'],
            'additionalProperties': False,
        },
        handler=_read_export,
    ),
}


def tool_schemas():
    return [spec.as_openai() for spec in TOOLS.values()]


# ---------------- 参数校验 ----------------
def validate_arguments(spec, args):
    """按 JSON Schema 的子集校验参数，返回 (clean_args, errors)。

    只支持本实验用到的关键字：type/required/enum/minimum/maximum/
    additionalProperties/properties。不支持嵌套对象与数组——工具参数刻意保持扁平。
    """
    errors = []
    if not isinstance(args, dict):
        return {}, ['参数必须是 JSON 对象，实际收到 %s' % type(args).__name__]

    props = spec.schema.get('properties', {})
    allowed = set(props)
    for k in args:
        if k not in allowed:
            errors.append('未知参数 “%s”，允许的参数是：%s'
                          % (k, ', '.join(sorted(allowed))))

    for k in spec.schema.get('required', []):
        if k not in args or args[k] in (None, ''):
            errors.append('缺少必填参数 “%s”' % k)

    clean = {}
    for k, v in args.items():
        if k not in props or v is None:
            continue
        rule = props[k]
        t = rule.get('type')
        if t == 'integer':
            if isinstance(v, bool) or not isinstance(v, int):
                if isinstance(v, str) and v.strip().lstrip('-').isdigit():
                    v = int(v)                      # 容忍 "5" 这种字符串
                else:
                    errors.append('参数 “%s” 必须是整数，实际是 %r' % (k, v))
                    continue
        elif t == 'boolean':
            if not isinstance(v, bool):
                if str(v).lower() in ('true', 'false'):
                    v = str(v).lower() == 'true'
                else:
                    errors.append('参数 “%s” 必须是布尔值，实际是 %r' % (k, v))
                    continue
        elif t == 'string':
            if not isinstance(v, str):
                errors.append('参数 “%s” 必须是字符串，实际是 %r' % (k, v))
                continue
            if 'enum' in rule and v not in rule['enum']:
                errors.append('参数 “%s” 的取值 “%s” 不在允许范围内：%s'
                              % (k, v, ', '.join(rule['enum'])))
                continue
        if t == 'integer':
            if 'minimum' in rule and v < rule['minimum']:
                errors.append('参数 “%s” 不能小于 %d（收到 %d）'
                              % (k, rule['minimum'], v))
                continue
            if 'maximum' in rule and v > rule['maximum']:
                errors.append('参数 “%s” 不能大于 %d（收到 %d）'
                              % (k, rule['maximum'], v))
                continue
        clean[k] = v
    return clean, errors


def defaults_for(spec, clean):
    """补上未传参数的默认值，保证工具实现拿到完整参数。"""
    out = dict(clean)
    if spec.name == 'list_dreams':
        out.setdefault('days', 30)
        out.setdefault('status', None)
        out.setdefault('limit', 20)
    elif spec.name == 'field_stats':
        out.setdefault('top_n', 5)
        out.setdefault('days', 0)
        out.setdefault('exclude_pending', True)
    elif spec.name == 'export_markdown':
        out.setdefault('top_n', 5)
    return out


# ---------------- 分发与执行 ----------------
def summarize_call(name, args):
    """生成给用户看的一句话摘要（用于确认提示与日志，不含敏感内容）。"""
    if name == 'export_markdown':
        return ('将写文件 out/%s，内容为 %s 的 Top%s 统计'
                % (args.get('filename', '?'), args.get('field_type', '?'),
                   args.get('top_n', 5)))
    if name == 'field_stats':
        return ('读取统计：字段类型 %s，Top%s，最近 %s 天'
                % (args.get('field_type', '?'), args.get('top_n', 5),
                   args.get('days', 0) or '不限'))
    if name == 'list_dreams':
        return ('读取记录列表：最近 %s 天，最多 %s 条'
                % (args.get('days', 30), args.get('limit', 20)))
    if name == 'read_export':
        return '读取并核对文件 out/%s' % args.get('filename', '?')
    return '%s(%s)' % (name, args)


def dispatch(name, raw_args, ctx, confirm_fn=None):
    """执行一次工具调用，返回结构化结果。

    返回：{'ok': bool, 'tool': name, 'duration_ms': float,
           'result': ... | 'error': {'code','message'}}
    不会抛出异常——所有失败都转成 ok=False，便于把错误回传给模型继续修正。
    """
    started = time.time()

    def fail(code, msg):
        return {'ok': False, 'tool': name, 'duration_ms': (time.time() - started) * 1000,
                'error': {'code': code, 'message': msg}}

    spec = TOOLS.get(name)
    if spec is None:
        return fail('unknown_tool',
                    '没有名为 “%s” 的工具。可用工具：%s'
                    % (name, ', '.join(sorted(TOOLS))))

    clean, errors = validate_arguments(spec, raw_args)
    if errors:
        return fail(SchemaError.code, '；'.join(errors))
    args = defaults_for(spec, clean)

    if spec.requires_confirm:
        if confirm_fn is None:
            return fail(PermissionDenied.code,
                        '该操作会修改数据，需要用户确认，但当前没有确认通道')
        approved = confirm_fn(name, summarize_call(name, args), spec)
        if not approved:
            return fail(PermissionDenied.code,
                        '用户拒绝执行该操作（%s），未做任何修改' % summarize_call(name, args))

    timeout = spec.timeout
    if ctx.timeout_override is not None:
        if isinstance(ctx.timeout_override, dict):
            timeout = ctx.timeout_override.get(name, spec.timeout)
        else:
            timeout = ctx.timeout_override
    box = {}

    def run():
        try:
            box['value'] = spec.handler(ctx, **args)
        except ToolError as e:
            box['error'] = (e.code, str(e))
        except sqlite3.Error as e:
            box['error'] = ('db_error', '数据库错误：%s' % e)
        except Exception as e:                      # noqa: BLE001
            box['error'] = ('unexpected', '%s: %s' % (type(e).__name__, e))

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        # 诚实说明：Python 线程无法被强制杀死，这里只是“停止等待”
        return fail(ToolTimeout.code,
                    '工具执行超过 %.2fs，已停止等待（注意：后台线程可能仍在运行，'
                    '本实现没有强制取消能力）' % timeout)
    if 'error' in box:
        code, msg = box['error']
        return fail(code, msg)
    return {'ok': True, 'tool': name, 'duration_ms': (time.time() - started) * 1000,
            'result': box.get('value')}
