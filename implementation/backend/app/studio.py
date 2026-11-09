"""ZIP intake and project-facing promo endpoints."""
import csv
import hashlib
import io
import json
import re
import shutil
from pathlib import PurePosixPath
from urllib.parse import quote
import uuid
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from .config import DATA_DIR, MAX_FILES, MAX_FILE_BYTES
from .db import connect, decode
from .parser import parse_episode
from .promos import rank_candidates, selected_blocks

router = APIRouter(prefix='/studio')
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


def parse_zip(file):
    batch = []
    seen = set()
    try:
        with zipfile.ZipFile(file) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES * 4:
                raise ValueError('The archive contains too many entries')
            scripts = []
            for entry in entries:
                path = PurePosixPath(entry.filename.replace('\\', '/'))
                if path.is_absolute() or '..' in path.parts:
                    raise ValueError('The ZIP contains an unsafe path')
                if not entry.is_dir() and path.suffix.lower() == '.txt' and not any(
                    part.startswith('.') or part == '__MACOSX' for part in path.parts
                ):
                    scripts.append(entry)
            if not 1 <= len(scripts) <= MAX_FILES:
                raise ValueError(f'Upload a ZIP containing 1–{MAX_FILES} timestamped .txt scripts')
            if sum(entry.file_size for entry in scripts) > MAX_ARCHIVE_BYTES:
                raise ValueError('The unpacked scripts must total at most 32 MiB')
            for entry in scripts:
                if entry.file_size > MAX_FILE_BYTES:
                    raise ValueError('Each script must be at most 2 MiB')
                with archive.open(entry) as script:
                    raw = script.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError('Each script must be at most 2 MiB')
                filename = PurePosixPath(entry.filename).name
                try:
                    source = raw.decode('utf-8-sig')
                    parsed = parse_episode(source)
                except ValueError as exc:
                    raise ValueError(f'{filename}: {exc}') from exc
                number = parsed['number']
                if number in seen:
                    raise ValueError(f'Duplicate episode {number}')
                seen.add(number)
                batch.append((number, filename, hashlib.sha256(raw).hexdigest(), source, json.dumps(parsed)))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError('Could not read the ZIP. Upload a valid, unencrypted archive.') from exc
    return batch


def project_data(db, project):
    pid = project['id']
    job = decode(db.execute(
        'SELECT * FROM jobs WHERE project_id=? AND mode=? ORDER BY rowid DESC LIMIT 1',
        (pid, 'promos'),
    ).fetchone())
    return dict(project, job=job, episode_count=db.execute(
        'SELECT COUNT(*) FROM episodes WHERE project_id=?', (pid,)
    ).fetchone()[0])


def require_project(db, pid):
    project = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
    if project is None:
        raise HTTPException(404, 'Project not found')
    return project


def queue_job(db, pid, count):
    job_id = str(uuid.uuid4())
    db.execute('INSERT INTO jobs(id,project_id,mode,total) VALUES(?,?,?,?)',
               (job_id, pid, 'promos', count))
    return job_id


@router.post('/projects', status_code=201)
def create_project(name: str = Form(...), archive: UploadFile = File(...)):
    name = name.strip()
    if not 1 <= len(name) <= 200:
        raise HTTPException(422, 'Enter a project name of 1–200 characters')
    if not archive.filename or not archive.filename.lower().endswith('.zip'):
        raise HTTPException(422, 'Choose a ZIP file')
    if archive.size is not None and archive.size > MAX_ARCHIVE_BYTES:
        raise HTTPException(413, 'The ZIP must be at most 32 MiB')
    try:
        batch = parse_zip(archive.file)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    pid = str(uuid.uuid4())
    with connect() as db:
        db.execute('INSERT INTO projects(id,name,zip_filename) VALUES(?,?,?)',
                   (pid, name, PurePosixPath(archive.filename.replace('\\', '/')).name))
        db.executemany('INSERT INTO episodes(project_id,number,filename,sha256,source,parsed) VALUES(?,?,?,?,?,?)',
                       [(pid, *episode) for episode in batch])
        queue_job(db, pid, len(batch))
        return project_data(db, require_project(db, pid))


@router.get('/projects')
def projects():
    with connect() as db:
        return [project_data(db, row) for row in db.execute('SELECT * FROM projects ORDER BY rowid DESC')]


@router.delete('/projects/{pid}', status_code=204)
def delete_project(pid: str):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        require_project(db, pid)
        if db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)).fetchone():
            raise HTTPException(409, 'Wait for project processing to finish before deleting it')
        db.execute('DELETE FROM runs WHERE job_id IN (SELECT id FROM jobs WHERE project_id=?)', (pid,))
        for table in ('saved_promos', 'promo_runs', 'episodes', 'jobs'):
            db.execute(f'DELETE FROM {table} WHERE project_id=?', (pid,))
        db.execute('DELETE FROM projects WHERE id=?', (pid,))
        cache = DATA_DIR / 'studio-runs' / pid
        if cache.exists():
            shutil.rmtree(cache)
    return Response(status_code=204)


def results(db, pid):
    candidates = []
    for row in db.execute('SELECT payload FROM promo_runs WHERE project_id=?', (pid,)):
        candidates.extend(json.loads(row['payload'])['accepted'])
    ranked, _ = rank_candidates(candidates)
    return ranked


@router.get('/projects/{pid}')
def dashboard(pid: str):
    with connect() as db:
        project = project_data(db, require_project(db, pid))
        return dict(project, promos=results(db, pid), saved_ids=[
            row['promo_id'] for row in db.execute('SELECT promo_id FROM saved_promos WHERE project_id=?', (pid,))
        ])


@router.get('/projects/{pid}/promos/{promo_id}')
def promo_detail(pid: str, promo_id: str):
    with connect() as db:
        require_project(db, pid)
        promo = next((cut for cut in results(db, pid) if cut['id'] == promo_id), None)
        if promo is None:
            raise HTTPException(404, 'Promo not found')
        row = db.execute('SELECT parsed FROM episodes WHERE project_id=? AND number=?',
                         (pid, promo['episode_number'])).fetchone()
        blocks = selected_blocks(json.loads(row['parsed']), promo['start'], promo['end'])
        return [block for block in blocks if block['kind'] in ('dialogue', 'action')]


@router.put('/projects/{pid}/saved/{promo_id}', status_code=204)
def save_promo(pid: str, promo_id: str):
    with connect() as db:
        require_project(db, pid)
        if not any(cut['id'] == promo_id for cut in results(db, pid)):
            raise HTTPException(404, 'Promo not found')
        db.execute('INSERT OR IGNORE INTO saved_promos(project_id,promo_id) VALUES(?,?)', (pid, promo_id))
    return Response(status_code=204)


@router.delete('/projects/{pid}/saved/{promo_id}', status_code=204)
def remove_promo(pid: str, promo_id: str):
    with connect() as db:
        require_project(db, pid)
        db.execute('DELETE FROM saved_promos WHERE project_id=? AND promo_id=?', (pid, promo_id))
    return Response(status_code=204)


@router.post('/projects/{pid}/retry', status_code=202)
def retry(pid: str):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        project = project_data(db, require_project(db, pid))
        if not project['job'] or project['job']['status'] != 'failed':
            raise HTTPException(409, 'Only failed runs can be retried')
        if db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)).fetchone():
            raise HTTPException(409, 'Project is already processing')
        queue_job(db, pid, project['episode_count'])
        return project_data(db, require_project(db, pid))


@router.get('/projects/{pid}/export')
def export_csv(pid: str, saved: bool = False):
    with connect() as db:
        name = require_project(db, pid)['name']
        ranked = results(db, pid)
        if saved:
            saved_ids = {r['promo_id'] for r in db.execute('SELECT promo_id FROM saved_promos WHERE project_id=?', (pid,))}
            ranked = [cut for cut in ranked if cut['id'] in saved_ids]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['rank', 'title', 'episode', 'start_seconds', 'end_seconds', 'duration_seconds',
                     'score', 'hook', 'cliffhanger'])
    def cell(value):
        # Keep text cells literal when opened in a spreadsheet.
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        return value
    for cut in ranked:
        writer.writerow([cell(value) for value in [cut['rank'], cut['title'], cut['episode_number'],
                        cut['start'], cut['end'], cut['duration'], cut['editorial_score'],
                        cut['hook'], cut['cliffhanger']]])
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', name).strip(' .') or 'project'
    filename = safe_name + '_promos.csv'
    fallback = filename.encode('ascii', 'replace').decode('ascii').replace('?', '_')
    disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
    return Response(output.getvalue(), media_type='text/csv',
                    headers={'Content-Disposition': disposition})
