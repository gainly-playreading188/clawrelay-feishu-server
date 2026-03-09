"""
简洁日志配置

只显示关键业务日志，屏蔽技术细节。
"""

import logging


class BusinessLogFilter(logging.Filter):
    MUST_SHOW = [
        '[Dispatcher:',
        '[FeishuWs:',
        '[FeishuAPI]',
        '[ClaudeRelay]',
        '[ChatLogger]',
        '[TaskRegistry]',
        'ERROR',
        'WARNING',
    ]

    MUST_HIDE = [
        '数据库连接',
        '[后台LLM任务]',
    ]

    def filter(self, record):
        msg = record.getMessage()
        for keyword in self.MUST_HIDE:
            if keyword in msg:
                return False
        for keyword in self.MUST_SHOW:
            if keyword in msg:
                return True
        if record.levelno >= logging.ERROR:
            return True
        return False


def setup_business_logging():
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(BusinessLogFilter())
    print("[日志配置] 已启用简洁业务日志模式")
