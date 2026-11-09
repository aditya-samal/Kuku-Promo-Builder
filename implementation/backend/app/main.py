import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .db import init_db, connect, decode
from .parser import parse_episode
from .config import MAX_FILES, MAX_FILE_BYTES
from .analysis import configured

@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(title='Kuku Promo API', version='0.1.0', lifespan=lifespan)
origins = [x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:5173').split(',') if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET','POST','PUT','DELETE'], allow_headers=['Content-Type','X-API-Key'])

def authorize(x_api_key: str | None = Header(default=None)):
    import secrets
    expected = os.getenv('APP_API_KEY','')
    if expected and (not x_api_key or not secrets.compare_digest(x_api_key,expected)):
        raise HTTPException(401, 'Invalid API key')

def project_exists(db, pid):
    if not db.execute('SELECT id FROM projects WHERE id=?',(pid,)).fetchone():
        raise HTTPException(404,'Project not found')

class ProjectInput(BaseModel):
    name: str = Field(min_length=1,max_length=200)

class ProcessInput(BaseModel):
    mode: Literal['parse','analyze'] = 'parse'

@app.get('/health')
def health():
    with connect() as db:
        db.execute('SELECT 1')
    return {'status':'ok','ai_configured':configured(),'promo_duration_seconds':{'min':20,'max':60}}

@app.post('/projects',status_code=201,dependencies=[Depends(authorize)])
def create_project(body: ProjectInput):
    name = body.name.strip()
    if not name:
        raise HTTPException(422,'Project name cannot be blank')
    pid = str(uuid.uuid4())
    with connect() as db:
        db.execute('INSERT INTO projects(id,name) VALUES(?,?)',(pid,name))
    return {'id':pid,'name':name}

@app.get('/projects',dependencies=[Depends(authorize)])
def list_projects():
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT p.*,COUNT(e.number) AS episode_count FROM projects p LEFT JOIN episodes e ON p.id=e.project_id GROUP BY p.id ORDER BY p.created_at DESC')]

@app.get('/projects/{pid}',dependencies=[Depends(authorize)])
def project_detail(pid: str):
    with connect() as db:
        project_exists(db,pid)
        p = dict(db.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone())
        counts = db.execute('SELECT COUNT(*) AS total, COUNT(analysis) AS analyzed FROM episodes WHERE project_id=?',(pid,)).fetchone()
        p.update(dict(counts))
        p['latest_job'] = decode(db.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(pid,)).fetchone())
        return p

@app.post('/projects/{pid}/episodes',dependencies=[Depends(authorize)])
async def upload_episodes(pid: str, files: list[UploadFile] = File(...)):
    if not 1 <= len(files) <= MAX_FILES:
        raise HTTPException(422,f'Upload 1–{MAX_FILES} files')
    with connect() as db:
        project_exists(db,pid)
    batch = []
    seen = set()
    for f in files:
        if not f.filename or Path(f.filename).suffix.lower() != '.txt':
            raise HTTPException(422,'Only .txt screenplay files are accepted')
        raw = await f.read(MAX_FILE_BYTES+1)
        if len(raw)>MAX_FILE_BYTES:
            raise HTTPException(413,'Each file must be at most 2 MiB')
        try:
            text = raw.decode('utf-8-sig')
            parsed = parse_episode(text)
        except (UnicodeError,ValueError) as exc:
            raise HTTPException(422,f'{Path(f.filename).name}: {exc}') from exc
        if parsed['number'] in seen:
            raise HTTPException(409,'Duplicate episode number within upload')
        seen.add(parsed['number'])
        batch.append((parsed,Path(f.filename).name,hashlib.sha256(raw).hexdigest(),text))
    # Validate the whole upload before committing; identical uploads are idempotent.
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",(pid,)).fetchone():
            raise HTTPException(409,'Wait for active processing before changing episodes')
        changed = False
        for parsed,filename,digest,text in batch:
            old = db.execute('SELECT sha256 FROM episodes WHERE project_id=? AND number=?',(pid,parsed['number'])).fetchone()
            if old and old['sha256'] != digest:
                raise HTTPException(409,f'Episode {parsed["number"]} already exists with different content; replacement is not supported yet')
            if not old:
                changed = True
                db.execute('INSERT INTO episodes(project_id,number,filename,sha256,source,parsed) VALUES(?,?,?,?,?,?)',(pid,parsed['number'],filename,digest,text,json.dumps(parsed)))
    return {'uploaded':len(batch),'episodes':[{'number':p['number'],'duration':p['duration'],'blocks':len(p['blocks']),'warnings':p['warnings']} for p,_,_,_ in batch]}

@app.get('/projects/{pid}/episodes',dependencies=[Depends(authorize)])
def episodes(pid: str):
    with connect() as db:
        project_exists(db,pid)
        result=[]
        for row in db.execute('SELECT number,filename,parsed,analysis FROM episodes WHERE project_id=? ORDER BY number',(pid,)):
            ep=decode(row)
            p=ep.pop('parsed')
            ep.update(logline=p['logline'],continuity_notes=p['continuity_notes'],duration=p['duration'],scene_count=len(p['scenes']),block_count=len(p['blocks']),warnings=p['warnings'])
            result.append(ep)
        return result

@app.get('/projects/{pid}/episodes/{number}',dependencies=[Depends(authorize)])
def episode(pid: str,number: int):
    with connect() as db:
        row=db.execute('SELECT * FROM episodes WHERE project_id=? AND number=?',(pid,number)).fetchone()
        if not row:
            raise HTTPException(404,'Episode not found')
        return decode(row)

@app.post('/projects/{pid}/process',status_code=202,dependencies=[Depends(authorize)])
def process(pid: str, body: ProcessInput):
    if body.mode=='analyze' and not configured():
        raise HTTPException(503,'Set LLM_MODEL and LLM_API_KEY before requesting analysis')
    jid=str(uuid.uuid4())
    try:
        with connect() as db:
            project_exists(db,pid)
            count=db.execute('SELECT COUNT(*) FROM episodes WHERE project_id=?',(pid,)).fetchone()[0]
            if not count:
                raise HTTPException(422,'Upload episodes first')
            db.execute('INSERT INTO jobs(id,project_id,mode,total) VALUES(?,?,?,?)',(jid,pid,body.mode,count))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409,'Project already has an active job') from exc
    return {'job_id':jid,'status':'queued','status_url':f'/jobs/{jid}'}

@app.get('/jobs/{jid}',dependencies=[Depends(authorize)])
def job_status(jid: str):
    with connect() as db:
        row=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row:
            raise HTTPException(404,'Job not found')
        return decode(row)

@app.get('/projects/{pid}/runs',dependencies=[Depends(authorize)])
def raw_runs(pid: str,limit: int=50,offset: int=0):
    with connect() as db:
        project_exists(db,pid)
        if not 1<=limit<=200 or offset<0:
            raise HTTPException(422,'Invalid pagination')
        return [dict(r) for r in db.execute('SELECT r.* FROM runs r JOIN jobs j ON r.job_id=j.id WHERE j.project_id=? ORDER BY r.id LIMIT ? OFFSET ?',(pid,limit,offset))]


from .studio import router as studio_router

app.include_router(studio_router, dependencies=[Depends(authorize)])

from fastapi.staticfiles import StaticFiles

frontend = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if (frontend / 'index.html').is_file():
    app.mount('/', StaticFiles(directory=frontend, html=True), name='studio-ui')
