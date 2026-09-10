"""Read display names only for explicitly configured local chat IDs."""
import sqlite3
from contextlib import closing
from pathlib import Path


def read_rollout(home, identity):
    """Codex may move a resumed chat to a suffixed rollout file."""
    databases = sorted(home.glob("state_*.sqlite"), key=lambda p: int(p.stem.split("_")[-1]) if p.stem.split("_")[-1].isdigit() else -1, reverse=True)
    for database in databases:
        try:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=.2)) as db:
                row = db.execute("SELECT rollout_path FROM threads WHERE id = ?", (identity,)).fetchone()
                if row and row[0]:
                    path = Path(row[0])
                    if path.is_file():
                        return path
        except (sqlite3.Error, OSError):
            continue
    return None


def read_titles(home, identities):
    if not identities:
        return {}
    databases = sorted(home.glob("state_*.sqlite"), key=lambda p: int(p.stem.split("_")[-1]) if p.stem.split("_")[-1].isdigit() else -1, reverse=True)
    for path in databases:
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.2)) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(threads)")}
                expression = "COALESCE(NULLIF(name, ''), title)" if "name" in columns else "title"
                result = {}
                for identity in identities:
                    row = db.execute(f"SELECT {expression} FROM threads WHERE id = ?", (identity,)).fetchone()
                    if row and isinstance(row[0], str) and row[0].strip():
                        result[identity] = row[0].strip()
                return result
        except (sqlite3.Error, OSError):
            continue
    return {}
