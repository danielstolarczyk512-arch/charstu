import sqlite3
import threading
import time

from .config import DB_PATH

_lock = threading.RLock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, archetype TEXT, traits TEXT,
  outfit TEXT, style TEXT, adult_fictional INTEGER NOT NULL, created REAL);
CREATE TABLE IF NOT EXISTS canon_assets(
  id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL, role TEXT NOT NULL,
  tier TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT, approved INTEGER DEFAULT 0,
  note TEXT, created REAL);
CREATE TABLE IF NOT EXISTS shots(
  id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL, az REAL, el REAL,
  dist REAL, fov REAL, fmt TEXT, action TEXT, prompt TEXT, created REAL);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, shot_id INTEGER NOT NULL, kind TEXT NOT NULL,
  provider TEXT, model TEXT, params TEXT, status TEXT NOT NULL,
  workflow_id TEXT, idem_key TEXT, error TEXT, safe_filter INTEGER,
  created REAL, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS artifacts(
  id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, shot_id INTEGER NOT NULL,
  kind TEXT, path TEXT NOT NULL, sha256 TEXT, approved INTEGER DEFAULT 0,
  rating INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS outfits(
  id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, created REAL);
CREATE TABLE IF NOT EXISTS films(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, logline TEXT, synopsis TEXT, character_id INTEGER NOT NULL,
  fmt TEXT DEFAULT '16:9', music_prompt TEXT, music_artifact_id INTEGER, final_artifact_id INTEGER,
  status TEXT DEFAULT 'draft', budget_spark REAL DEFAULT 400, auto_pick INTEGER DEFAULT 1,
  image_model TEXT, edit_model TEXT, paused_until REAL, note TEXT, plan_state TEXT, usage_start REAL,
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS scenes(
  id INTEGER PRIMARY KEY, film_id INTEGER NOT NULL, idx INTEGER NOT NULL, title TEXT, summary TEXT,
  location TEXT, lighting TEXT, created REAL);
CREATE TABLE IF NOT EXISTS film_shots(
  id INTEGER PRIMARY KEY, film_id INTEGER NOT NULL, scene_id INTEGER NOT NULL, idx INTEGER NOT NULL, title TEXT,
  az REAL, el REAL, dist REAL, fov REAL, fmt TEXT, action TEXT, outfit TEXT, dialogue TEXT, duration INTEGER DEFAULT 5,
  link_next INTEGER DEFAULT 0, shot_row_id INTEGER, image_artifact_id INTEGER, clip_artifact_id INTEGER,
  speech_artifact_id INTEGER, failed INTEGER DEFAULT 0, note TEXT, created REAL);
CREATE TABLE IF NOT EXISTS interactions(
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT NOT NULL,
  image_path TEXT, builtin INTEGER DEFAULT 0, created REAL);
"""
with _lock:
    _conn.executescript(SCHEMA)
    for tbl, col, typ in (("artifacts", "face_score", "REAL"), ("artifacts", "face_min", "REAL"),
                          ("artifacts", "face_note", "TEXT"), ("shots", "outfit", "TEXT"),
                          ("characters", "voice", "TEXT"), ("artifacts", "label", "TEXT"),
                          ("jobs", "film_shot_id", "INTEGER"), ("jobs", "role", "TEXT"),
                          ("films", "assemble_state", "TEXT"), ("films", "srt_path", "TEXT"),
                          ("film_shots", "no_flf", "INTEGER DEFAULT 0"),
                          ("films", "allow_spark", "INTEGER DEFAULT 0"),
                          # --- Duet (dwie osoby w kadrze) ---
                          ("characters", "kind", "TEXT DEFAULT 'lead'"),
                          ("shots", "partner_id", "INTEGER"), ("shots", "interaction", "TEXT DEFAULT ''"),
                          ("shots", "outfit_b", "TEXT DEFAULT ''"),
                          ("films", "partner_id", "INTEGER"), ("films", "interaction", "TEXT DEFAULT ''"),
                          ("film_shots", "interaction", "TEXT DEFAULT ''"), ("film_shots", "outfit_b", "TEXT DEFAULT ''"),
                          ("artifacts", "face_score_b", "REAL"), ("artifacts", "face_min_b", "REAL"),
                          # --- Duet, etap E5: slot B referencji ('partner_face' | 'lead_body') i fraza anatomii pozycji ---
                          ("shots", "ref_slot_b", "TEXT DEFAULT 'partner_face'"),
                          ("interactions", "anatomy", "TEXT DEFAULT ''")):
        try:  # migracje: kolumny dodane po pierwszej wersji bazy
            _conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    _conn.commit()


def rows(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def run(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def now():
    return time.time()
