import pytest

from jarvis.db import init_db


@pytest.fixture
def db(tmp_path):
    """In-memory (well, temp-file) DB with full schema applied."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from jarvis.db import _connect

    conn = _connect(db_path)
    yield conn
    conn.close()
