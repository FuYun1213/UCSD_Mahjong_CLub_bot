"""Preserve access audit metadata while redacting table entry credentials."""
import logging
import re

_ENCODED = re.compile(r"((?:%2[fF])(?:join-table|join|api%2[fF]table-join-tokens)%2[fF])[A-Za-z0-9_.-]+")
_ENTRY = re.compile(r"((?:[?#&]|%23|%26)(?:entry|entry_token)(?:=|%3d))[A-Za-z0-9_.-]+", re.IGNORECASE)
_PATTERN = re.compile(r"(/(?:join-table|join|api/table-join-tokens)/)[^/?\s]+")


def redact_table_token(value):
    return _ENTRY.sub(r"\1[redacted]", _ENCODED.sub(r"\1[redacted]", _PATTERN.sub(r"\1[redacted]", value))) if isinstance(value, str) else value


class TableTokenFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact_table_token(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_table_token(v) for v in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact_table_token(v) for k, v in record.args.items()}
        return True


def install_token_redaction():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, TableTokenFilter) for f in logger.filters):
        logger.addFilter(TableTokenFilter())
