# -*- coding: utf-8 -*-
"""日志配置（实验4 2.5：记录能帮助定位问题的必要日志）。

日志位置：<项目根>/logs/app.log
主要内容：启动参数、数据文件路径、每次业务操作的结果、被拒绝的输入、异常堆栈。
控制台只输出 WARNING 及以上，避免影响界面演示。
"""
import logging
import os

_LOGGER_NAME = 'dreamjournal'
_configured = False


def setup(log_dir=None, level=logging.INFO):
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = log_dir or os.path.join(root, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    logger.setLevel(level)
    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    fh = logging.FileHandler(os.path.join(log_dir, 'app.log'), encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    _configured = True
    logger.info('日志系统启动，日志文件：%s', os.path.join(log_dir, 'app.log'))
    return logger


def get_logger():
    return logging.getLogger(_LOGGER_NAME)
