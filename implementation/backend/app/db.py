import json
import sqlite3
from contextlib import contextmanager
from .config import DATA_DIR, DB_PATH


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS episodes (
          project_id TEXT NOT NULL REFERENCES projects(id), number INTEGER NOT NULL,
          filename TEXT NOT NULL, sha256 TEXT NOT NULL, source TEXT NOT NULL,
          parsed TEXT NOT NULL, analysis TEXT, PRIMARY KEY(project_id, number));
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          mode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
          completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
          error TEXT, result TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(project_id)
          WHERE status IN ('queued','running');
        CREATE TABLE IF NOT EXISTS runs (
          id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, episode_number INTEGER,
          stage TEXT NOT NULL, model TEXT, prompt TEXT, raw_response TEXT,
          status TEXT NOT NULL, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS promo_runs (
          project_id TEXT NOT NULL, episode_number INTEGER NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(project_id, episode_number),
          FOREIGN KEY(project_id, episode_number) REFERENCES episodes(project_id, number));
        CREATE TABLE IF NOT EXISTS saved_promos (
          project_id TEXT NOT NULL REFERENCES projects(id), promo_id TEXT NOT NULL,
          saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(project_id, promo_id));
        ''')
        for table, column, declaration in (
            ('projects', 'zip_filename', 'TEXT'),
            ('jobs', 'stage', "TEXT NOT NULL DEFAULT 'analysis'"),
            ('jobs', 'episode_number', 'INTEGER'),
            ('jobs', 'attempt', 'INTEGER'),
        ):
            if column not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def decode(row):
    if row is None:
        return None
    result = dict(row)
    for key in ('parsed', 'analysis', 'result'):
        if result.get(key):
            result[key] = json.loads(result[key])
    return result
