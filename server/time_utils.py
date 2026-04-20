"""
统一时区工具：所有时间显示为上海时间 (Asia/Shanghai, UTC+8)

使用固定偏移 timezone(timedelta(hours=8))，避免 Windows 上缺失 tzdata 依赖的问题。
"""
from datetime import datetime, timezone, timedelta
import logging

# 上海时区（UTC+8，固定偏移，无夏令时）
SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_shanghai() -> datetime:
    """返回带时区信息的上海当前时间（aware datetime）。"""
    return datetime.now(SHANGHAI_TZ)


def _shanghai_time_converter(*_args):
    """供 logging.Formatter.converter 使用：返回上海本地 struct_time。

    logging 内部用 time.strftime 格式化 struct_time，不会处理时区。
    我们返回上海当前时间对应的本地字段值，让日志显示上海时间。
    """
    return datetime.now(SHANGHAI_TZ).timetuple()


def setup_shanghai_logging() -> None:
    """将全局 logging 的时间字段改为上海时区。

    通过修改 logging.Formatter.converter 这一类级别属性，
    所有已创建和之后创建的 Formatter（包括 uvicorn 默认 Formatter）
    都会使用上海时间渲染 %(asctime)s。应在程序入口尽早调用。
    """
    logging.Formatter.converter = _shanghai_time_converter
