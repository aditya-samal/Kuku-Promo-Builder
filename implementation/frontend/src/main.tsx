import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Scores = { hook: number; clarity: number; cliffhanger: number; pacing: number };
type Job = {
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: 'analysis' | 'promos'; completed: number; total: number;
  episode_number: number | null; attempt: number | null; error: string | null;
};
type Project = { id: string; name: string; zip_filename: string | null; episode_count: number; job: Job | null };
type Promo = {
  id: string; rank: number; title: string; episode_number: number; start: number; end: number;
  duration: number; editorial_score: number; clip_tags: string[]; ending_tags: string[];
  hook: string; cliffhanger: string; why_it_works: string;
  review: { scores: Scores; open_question: string; concerns: string[] };
};
type DashboardData = Project & { promos: Promo[]; saved_ids: string[] };
type Block = { id: string; kind: string; speaker: string | null; text: string; visible_start: number };

const errorText = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong';
const active = (job: Job | null) => job?.status === 'queued' || job?.status === 'running';
const projectLink = (id: string) => '#/projects/' + id;
const criteria: (keyof Scores)[] = ['hook', 'clarity', 'cliffhanger', 'pacing'];
const limits: Scores = { hook: 25, clarity: 20, cliffhanger: 28, pacing: 7 };
const maximums: Scores = { hook: 30, clarity: 25, cliffhanger: 35, pacing: 10 };
const timecode = (seconds: number) => {
  const cs = Math.round(seconds * 100);
  return [Math.floor(cs / 6000), Math.floor(cs / 100) % 60].map(n => String(n).padStart(2, '0')).join(':')
    + '.' + String(cs % 100).padStart(2, '0');
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/studio' + path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Request failed (' + response.status + ')');
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

function useProjects<T extends Project | Project[]>(path: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState('');
  const [revision, refresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const value = await request<T>(path, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setData(value);
        setError('');
        if ((Array.isArray(value) ? value : [value]).some(p => active(p.job))) {
          timer = setTimeout(load, 2500);
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(errorText(err));
        timer = setTimeout(load, 5000);
      }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, revision]);
  return { data, error, refresh: () => refresh(n => n + 1) };
}

function Icon({ name }: { name: 'plus' | 'upload' | 'download' | 'arrow' | 'bookmark' | 'check' | 'film' }) {
  const paths = {
    plus: 'M12 5v14M5 12h14',
    upload: 'M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4',
    download: 'M12 4v12m-5-5 5 5 5-5M4 16v4h16v-4',
    arrow: 'm10 6-6 6 6 6M4 12h16',
    bookmark: 'M6 4h12v16l-6-4-6 4z',
    check: 'm5 12 4 4L19 6',
    film: 'M4 5h16v14H4zM8 5v14M16 5v14M4 10h4m8 0h4M4 14h4m8 0h4',
  };
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}

function Empty({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <section className="empty"><span className="tile-icon"><Icon name="film"/></span>
    <h2>{title}</h2><p>{children}</p>{action}</section>;
}
function NewButton() { return <a className="button primary" href="#/new"><Icon name="plus"/>New project</a>; }
function Back() { return <a className="back" href="#/"><Icon name="arrow"/> Back to projects</a>; }
function Status({ job }: { job: Job | null }) {
  const label = job?.status === 'completed' ? 'Complete' : job?.status === 'failed' ? 'Needs retry'
    : job?.status === 'queued' ? 'Queued' : job?.status === 'running'
    ? (job.stage === 'promos' ? 'Generating promos' : 'Analyzing scenes') : 'Ready';
  return <span className={'status ' + (job?.status ?? '')}><i/>{label}</span>;
}

function Projects() {
  const { data, error, refresh } = useProjects<Project[]>('/projects');
  const [deleting, setDeleting] = useState<string>();
  const [deleteError, setDeleteError] = useState('');

  async function remove(project: Project) {
    if (!window.confirm(`Delete “${project.name}” and all its results and saved promos?`)) return;
    setDeleting(project.id);
    setDeleteError('');
    try {
      await request('/projects/' + project.id, { method: 'DELETE' });
      refresh();
    } catch (err) {
      setDeleteError(errorText(err));
    } finally {
      setDeleting(undefined);
    }
  }

  return <>
    <div className="page-title"><p className="eyebrow">WORKSPACE</p><h1>Projects</h1>
      <p>Turn episode scripts into a ranked shortlist of promo cuts.</p></div>
    {error && <p className="notice" role="alert">{error} <button onClick={refresh}>Retry</button></p>}
    {deleteError && <p className="notice" role="alert">{deleteError}</p>}
    {!data && !error && <p role="status" className="muted">Loading projects…</p>}
    {data?.length === 0 && <Empty title="Create your first project" action={<NewButton/>}>
      Upload a ZIP of timestamped episode scripts to start generating promos.
    </Empty>}
    {!!data?.length && <section className="project-grid" aria-label="Projects">
      {data.map(project => <article className="project-card" key={project.id}>
        <span className="tile-icon"><Icon name="film"/></span>
        <Status job={project.job}/>
        <h2>{project.name}</h2>
        <p>{project.episode_count} {project.episode_count === 1 ? 'episode' : 'episodes'}
          {active(project.job) && ' · ' + project.job!.completed + ' of ' + project.job!.total + ' processed'}</p>
        <div className="project-actions">
          <a className="button secondary" href={projectLink(project.id)}>Open project <span aria-hidden="true">↗</span></a>
          <button className="button secondary delete-project" disabled={!!deleting || active(project.job)}
            title={active(project.job) ? 'Available after processing finishes' : undefined}
            onClick={() => void remove(project)}>{deleting === project.id ? 'Deleting…' : 'Delete project'}</button>
        </div>
      </article>)}
    </section>}
  </>;
}

function NewProject() {
  const [name, setName] = useState('');
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  function choose(candidate?: File) {
    if (!candidate || busy) return;
    setError('');
    if (!/\.zip$/i.test(candidate.name) || candidate.size > 32 * 1024 * 1024) {
      setError('Choose a ZIP file up to 32 MiB.'); return;
    }
    setFile(candidate);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !file || busy) return;
    setBusy(true); setError('');
    const form = new FormData();
    form.set('name', name.trim()); form.set('archive', file);
    try {
      const created = await request<Project>('/projects', { method: 'POST', body: form });
      window.location.hash = projectLink(created.id);
    } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  return <div className="narrow"><Back/>
    <div className="page-title"><p className="eyebrow">NEW WORKSPACE</p><h1>New project</h1>
      <p>Give your project a name and add its episode scripts.</p></div>
    <form className="form" onSubmit={submit}>
      <label htmlFor="name">Project name</label>
      <input id="name" placeholder="e.g. Broken Soldier, Season 1" required maxLength={200}
        value={name} onChange={event => setName(event.target.value)} disabled={busy}/>
      <label htmlFor="archive">Episode scripts ZIP</label>
      <input id="archive" ref={picker} type="file" accept=".zip,application/zip" className="visually-hidden"
        tabIndex={-1} onChange={event => { choose(event.target.files?.[0]); event.target.value = ''; }} disabled={busy}/>
      {file ? <div className="file-row"><span className="file-icon">ZIP</span><div><strong>{file.name}</strong>
        <small>{(file.size / 1024).toFixed(1)} KB</small></div>
        <button type="button" className="button secondary" disabled={busy} onClick={() => picker.current?.click()}>Replace</button>
      </div> : <div className={'drop-zone ' + (dragging ? 'dragging' : '')}
        onDragOver={event => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={event => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files[0]); }}>
        <span className="tile-icon"><Icon name="upload"/></span>
        <strong>Drop your ZIP here</strong><small>Timestamped .txt scripts · up to 32 MiB</small>
        <button className="button secondary" type="button" onClick={() => picker.current?.click()}>Choose ZIP</button>
      </div>}
      {busy && <div className="working" role="status"><span className="spinner"/> Validating ZIP and reading scripts…</div>}
      {error && <p className="notice" role="alert">{error}</p>}
      <div className="form-actions"><a className="button secondary" href="#/">Cancel</a>
        <button className="button primary" disabled={busy || !name.trim() || !file}>{busy ? 'Creating project…' : 'Create project'}</button></div>
    </form>
  </div>;
}

function Progress({ project, retry }: { project: DashboardData; retry: () => Promise<void> }) {
  const job = project.job;
  const [busy, setBusy] = useState(false);
  if (!job || job.status === 'completed') return null;
  const stage = job.stage === 'analysis' ? 'Analyze scenes' : 'Generate and review promos';
  return <section className="progress-panel" aria-label="Processing progress">
    <div className="progress-top"><div><h2>{job.status === 'failed' ? 'Processing paused' : stage}</h2>
      <p>{job.status === 'failed' ? job.error : 'You can return to Projects while this runs.'}</p></div>
      {job.status === 'failed'
        ? <button className="button secondary" disabled={busy} onClick={async () => { setBusy(true); try { await retry(); } finally { setBusy(false); } }}>Retry</button>
        : <span className="count">{job.completed} of {job.total} episodes</span>}
    </div>
    <progress aria-label={stage} max={job.total || 1} value={job.completed}/>
    {job.status === 'running' && job.episode_number != null && <p role="status" className="muted">
      Episode {job.episode_number}{job.attempt && job.attempt > 1 ? ' · retry attempt ' + job.attempt : ''}
    </p>}
    <ul className="stages">
      <li><span className="step done"><Icon name="check"/></span><strong>Read episode scripts</strong><span>{project.episode_count} read</span></li>
      {(['analysis', 'promos'] as const).map((key, i) => {
        const done = key === 'analysis' && job.stage === 'promos';
        const current = key === job.stage;
        return <li key={key}><span className={'step ' + (done ? 'done' : current ? 'current' : '')}>
          {done ? <Icon name="check"/> : i + 2}</span><strong>{i === 0 ? 'Analyze scenes' : 'Generate and review promos'}</strong>
          <span>{done ? 'Complete' : current ? (job.status === 'failed' ? 'Paused' : job.status === 'queued' ? 'Queued' : job.completed + ' of ' + job.total) : 'Pending'}</span></li>;
      })}
    </ul>
  </section>;
}

function PromoDetail({ pid, promo }: { pid: string; promo: Promo }) {
  const [blocks, setBlocks] = useState<Block[]>();
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    request<Block[]>('/projects/' + pid + '/promos/' + promo.id, { signal: controller.signal })
      .then(setBlocks).catch(err => { if (!controller.signal.aborted) setError(errorText(err)); });
    return () => controller.abort();
  }, [pid, promo.id]);
  return <div className="promo-detail">
    <div className="story-grid">
      {[['Hook', promo.hook], ['Cliffhanger', promo.cliffhanger], ['Unanswered question', promo.review.open_question]].map(([label, value]) =>
        <div key={label}><h4>{label}</h4><p>{value}</p></div>)}
    </div>
    <p className="why">{promo.why_it_works}</p>
    <h4>Script excerpts</h4>
    {error ? <p className="notice">{error}</p> : !blocks ? <p className="muted">Loading excerpts…</p> :
      <div className="excerpts">{blocks.length === 0 ? <p>No dialogue or action blocks in this cut.</p> :
        blocks.map(block => <div key={block.id}><time>{timecode(block.visible_start)}</time>
          <p><strong>{block.speaker ?? 'Action'}</strong> {block.text}</p></div>)}</div>}
    <div className="score-grid">{criteria.map(criterion => <div key={criterion}>
      <span>{criterion}</span><strong>{Number((promo.review.scores[criterion] * maximums[criterion] / 100).toFixed(2))}<small>/{maximums[criterion]}</small></strong>
      <progress aria-label={criterion} max={maximums[criterion]} value={promo.review.scores[criterion] * maximums[criterion] / 100}/>
      <small>Minimum {limits[criterion]}</small>
    </div>)}</div>
  </div>;
}

function Dashboard({ id, savedTab }: { id: string; savedTab: boolean }) {
  const { data, error, refresh } = useProjects<DashboardData>('/projects/' + id);
  const [open, setOpen] = useState<string>();
  const [mutationError, setMutationError] = useState('');
  const [busy, setBusy] = useState<string>();
  async function bookmark(promo: Promo, saved: boolean) {
    setBusy(promo.id); setMutationError('');
    try { await request('/projects/' + id + '/saved/' + promo.id, { method: saved ? 'DELETE' : 'PUT' }); refresh(); }
    catch (err) { setMutationError(errorText(err)); }
    finally { setBusy(undefined); }
  }
  async function retry() {
    setMutationError('');
    try { await request('/projects/' + id + '/retry', { method: 'POST' }); refresh(); }
    catch (err) { setMutationError(errorText(err)); }
  }
  const saved = new Set(data?.saved_ids ?? []);
  const cuts = data?.promos.filter(promo => !savedTab || saved.has(promo.id)) ?? [];
  return <><Back/>
    {error && <p className="notice" role="alert">{error}</p>}
    {!data && !error && <p className="muted" role="status">Loading project…</p>}
    {data && <>
      <div className="dashboard-title"><div><p className="eyebrow">PROJECT</p><h1>{data.name}</h1>
        <p className="muted">{data.episode_count} episodes {data.zip_filename && '· ' + data.zip_filename}</p></div>
        <Status job={data.job}/>
        <a className="button secondary export" href={'/studio/projects/' + id + '/export?saved=' + savedTab}><Icon name="download"/>Export CSV</a>
      </div>
      <nav className="tabs" aria-label="Project sections">
        <a href={projectLink(id)} aria-current={!savedTab ? 'page' : undefined}>Results</a>
        <a href={projectLink(id) + '/saved'} aria-current={savedTab ? 'page' : undefined}>Saved promos <span>{saved.size}</span></a>
      </nav>
      {mutationError && <p className="notice" role="alert">{mutationError}</p>}
      {!savedTab && <Progress project={data} retry={retry}/>}
      <div className="section-title"><div><h2>{savedTab ? 'Saved promos' : 'Ranked promos'}</h2>
        <p>{cuts.length} {savedTab ? 'saved' : 'accepted'} {cuts.length === 1 ? 'cut' : 'cuts'}
          {!savedTab && active(data.job) && ' · Ranking updates as cuts pass review'}</p></div>
        {!savedTab && !!cuts.length && <small>Scores out of 100</small>}
      </div>
      {!cuts.length && (savedTab
        ? <Empty title="No saved promos yet" action={<a href={projectLink(id)} className="button secondary">Go to Results</a>}>
          Save cuts from Results to collect them here.</Empty>
        : <Empty title={data.job?.status === 'completed' ? 'No qualifying cuts' : 'No cuts to show yet'}>
          {data.job?.status === 'completed' ? 'This run finished without any cuts meeting the score thresholds.'
            : 'Qualifying cuts will appear here as episodes finish review.'}</Empty>)}
      {!!cuts.length && <section className="promo-list" aria-label={savedTab ? 'Saved promos' : 'Ranked promos'}>
        {cuts.map(promo => <article className={'promo ' + (open === promo.id ? 'expanded' : '')} key={promo.id}>
          <div className="promo-head">
            <button className="expand" type="button" aria-expanded={open === promo.id}
              onClick={() => setOpen(open === promo.id ? undefined : promo.id)}>
              <span className="rank">{String(promo.rank).padStart(2, '0')}</span>
              <span className="promo-title"><strong>{promo.title}</strong>
                <small>Episode {promo.episode_number} · {timecode(promo.start)}–{timecode(promo.end)} · {promo.duration}s</small></span>
              <span className="score">{promo.editorial_score}<small>/100</small></span>
              <span aria-hidden="true" className="chevron">{open === promo.id ? '⌃' : '⌄'}</span>
            </button>
            <button className="button secondary save" disabled={busy === promo.id}
              aria-pressed={saved.has(promo.id)} onClick={() => bookmark(promo, saved.has(promo.id))}>
              <Icon name={saved.has(promo.id) ? 'check' : 'bookmark'}/>
              {savedTab ? 'Remove' : saved.has(promo.id) ? 'Saved' : 'Save promo'}
            </button>
          </div>
          <div className="tags">{[...new Set([...promo.clip_tags, ...promo.ending_tags])].map(tag => <span key={tag}>{tag}</span>)}</div>
          {open === promo.id && <PromoDetail pid={id} promo={promo}/>}
        </article>)}
      </section>}
    </>}
  </>;
}

function App() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const change = () => { setHash(window.location.hash); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  const project = /^#\/projects\/([a-f0-9-]+)(\/saved)?$/.exec(hash);
  return <><header className="header"><div className="header-inner">
    <a href="#/" className="brand"><span><Icon name="film"/></span>KUKU <em>Promo Studio</em></a>
    {hash !== '#/new' && <NewButton/>}
  </div></header><main>
    {hash === '#/new' ? <NewProject/> : project
      ? <Dashboard key={project[1]} id={project[1]} savedTab={!!project[2]}/> : <Projects/>}
  </main></>;
}
createRoot(document.getElementById('root')!).render(<App/>);
