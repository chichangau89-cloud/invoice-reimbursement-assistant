from collections.abc import Iterator
from contextlib import contextmanager

import pymysql
from pymysql.connections import Connection

from app.core.config import get_settings


@contextmanager
def mysql_connection(autocommit: bool = False) -> Iterator[Connection]:
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=autocommit,
        connect_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()
