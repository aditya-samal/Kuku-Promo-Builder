"""One durable worker per SQLite deployment. Restart resumes queued/running jobs."""
import argparse
import json
import time
from .db import init_db, connect, decode
from .analysis import configured, episode_prompt, call_model, parse_response, validate_analysis
from .config import MODEL, DATA_DIR
from .llm_runtime import ModelRunner
from .promos import build_graph



def run_studio_job(job):
    jid, pid = job['id'], job['project_id']
    if not configured():
        raise ValueError('Set LLM_API_KEY on the backend, restart the worker, then retry')
    with connect() as db:
        episodes = [decode(row) for row in db.execute(
            'SELECT * FROM episodes WHERE project_id=? ORDER BY number', (pid,)
        )]
        finished = {row['episode_number'] for row in db.execute(
            'SELECT episode_number FROM promo_runs WHERE project_id=?', (pid,)
        )}
    current_episode = None

    def update(stage, completed, attempt=None):
        with connect() as db:
            db.execute(
                """UPDATE jobs SET stage=?,completed=?,total=?,episode_number=?,attempt=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (stage, completed, len(episodes), current_episode, attempt, jid),
            )

    stage, completed = 'analysis', 0
    runner = ModelRunner(DATA_DIR / 'studio-runs' / pid, delay=7,
                         on_attempt=lambda attempt: update(stage, completed, attempt))
    update(stage, completed)
    for episode in episodes:
        current_episode = episode['number']
        if episode['analysis'] is None:
            parsed = episode['parsed']
            episode['analysis'] = runner.request(
                f'analysis-ep{current_episode:03d}', episode_prompt(parsed),
                lambda value: validate_analysis(value, parsed),
            )
            with connect() as db:
                db.execute('UPDATE episodes SET analysis=? WHERE project_id=? AND number=?',
                           (json.dumps(episode['analysis']), pid, current_episode))
        completed += 1
        update(stage, completed)

    stage, completed = 'promos', len(finished)
    current_episode = None
    update(stage, completed)
    graph = build_graph(runner)
    for episode in episodes:
        current_episode = episode['number']
        if current_episode in finished:
            continue
        state = graph.invoke({'parsed': episode['parsed'], 'analysis': episode['analysis']},
                             {'recursion_limit': 20})
        payload = {key: state[key] for key in ('accepted', 'rejected', 'repair_count')}
        with connect() as db:
            db.execute('INSERT INTO promo_runs(project_id,episode_number,payload) VALUES(?,?,?)',
                       (pid, current_episode, json.dumps(payload)))
        completed += 1
        update(stage, completed)
    with connect() as db:
        db.execute("""UPDATE jobs SET status='completed',error=NULL,episode_number=NULL,attempt=NULL,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""", (jid,))


def run_job(job):
    if job['mode'] == 'promos':
        return run_studio_job(job)
    jid, pid = job['id'], job['project_id']
    with connect() as db:
        episodes = [decode(r) for r in db.execute('SELECT * FROM episodes WHERE project_id=? ORDER BY number', (pid,))]
        db.execute("UPDATE jobs SET status='running', total=?, error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", (len(episodes), jid))
    done = 0
    for ep in episodes:
        if job['mode'] == 'analyze' and ep['analysis'] is None:
            if not configured():
                raise ValueError('Configure LLM_MODEL and LLM_API_KEY for AI analysis')
            prompt = episode_prompt(ep['parsed'])
            raw = None
            try:
                raw = call_model(prompt)
                value = validate_analysis(parse_response(raw), ep['parsed'])
                with connect() as db:
                    db.execute('UPDATE episodes SET analysis=? WHERE project_id=? AND number=?', (json.dumps(value), pid, ep['number']))
                    db.execute("INSERT INTO runs(job_id,episode_number,stage,model,prompt,raw_response,status) VALUES(?,?,?,?,?,?,'completed')", (jid,ep['number'],'episode_analysis',MODEL,prompt,raw))
            except Exception as exc:
                with connect() as db:
                    db.execute("INSERT INTO runs(job_id,episode_number,stage,model,prompt,raw_response,status,error) VALUES(?,?,?,?,?,?,'failed',?)", (jid,ep['number'],'episode_analysis',MODEL,prompt,raw,type(exc).__name__))
                raise ValueError(f'Episode {ep["number"]}: analysis failed ({type(exc).__name__}); inspect configuration and raw runs') from exc
        done += 1
        with connect() as db:
            db.execute('UPDATE jobs SET completed=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (done,jid))
    with connect() as db:
        result = {'processing_stage':'analyzed' if job['mode']=='analyze' else 'parsed',
                  'episodes':len(episodes),'promo_generation':'not_started'}
        db.execute("UPDATE jobs SET status='completed',result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps(result),jid))


def process_next():
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY created_at,id LIMIT 1").fetchone()
        if row is None:
            return False
        job = dict(row)
        db.execute("UPDATE jobs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",(job['id'],))
    try:
        run_job(job)
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE jobs SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(exc),job['id']))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    init_db()
    while True:
        worked = process_next()
        if args.once:
            return
        if not worked:
            time.sleep(1)

if __name__ == '__main__':
    main()
