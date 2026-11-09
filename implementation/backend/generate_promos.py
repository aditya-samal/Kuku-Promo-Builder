"""Run the source-grounded LangGraph promo workflow without a web server."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys


def timestamp(seconds):
    minutes=int(seconds//60);remain=seconds-minutes*60
    return f'{minutes:02d}:{remain:05.2f}'


def generate(project_dir,output_dir,only=None,delay=5,retries=2,runner=None,retry_failed=False):
    from app import config
    from app.analysis import validate_analysis,configured
    from app.promos import VERSION,build_graph,rank_candidates,selected_blocks
    from app.llm_runtime import ModelRunner,save_json
    project_dir,output_dir=Path(project_dir).resolve(),Path(output_dir).resolve()
    if runner is None and not configured():raise ValueError('Configure LLM_MODEL and LLM_API_KEY')
    runner=runner or ModelRunner(output_dir/'responses',delay,retries)
    graph=build_graph(runner)
    save_json(output_dir/'graph.json',{'version':VERSION,'mermaid':graph.get_graph().draw_mermaid()})
    manifest=json.loads((project_dir/'project.json').read_text())
    available={e['number']:e for e in manifest['episodes']}
    numbers=sorted(only if only is not None else available)
    if not numbers or any(n not in available for n in numbers):raise ValueError('Requested episodes not in project manifest')
    reports=[];all_candidates=[];all_rejected=[]
    pending = numbers
    if retry_failed:
        previous = json.loads((output_dir/'generation.json').read_text())
        if Path(previous['project_dir']).resolve() != project_dir:
            raise ValueError('Existing run belongs to another project')
        numbers = previous['scope']
        pending = []
        previous_reports = {record['number']: record for record in previous['episodes']}
        for number in numbers:
            record = previous_reports.get(number, {'number': number, 'status': 'pending'})
            if record['status'] != 'completed':
                pending.append(number)
            else:
                saved = json.loads((output_dir/'episodes'/f'episode-{number:03d}.json').read_text())
                source = (project_dir/'sources'/f'episode-{number:03d}.txt').read_bytes()
                if saved['source_fingerprint'] != hashlib.sha256(source).hexdigest():
                    raise ValueError(f'Episode {number} source has changed since the previous run')
                all_candidates.extend(saved['accepted'])
                all_rejected.extend(saved['rejected'])
            reports.append(record)
    progress={'version':VERSION,'model':config.MODEL,'project_dir':str(project_dir),'status':'running','episodes':reports,'scope':numbers}
    save_json(output_dir/'generation.json',progress)
    for index,n in enumerate(pending,1):
        print(f'Promo episode {n} [{index}/{len(pending)}]',flush=True)
        record={'number':n,'status':'started'}
        if retry_failed:
            reports[numbers.index(n)] = record
        else:
            reports.append(record)
        try:
            if available[n]['status']!='analyzed':raise ValueError('Episode analysis is incomplete')
            parsed=json.loads((project_dir/'parsed'/f'episode-{n:03d}.json').read_text())
            episode=json.loads((project_dir/'episodes'/f'episode-{n:03d}.json').read_text())
            source=(project_dir/'sources'/f'episode-{n:03d}.txt').read_bytes()
            if hashlib.sha256(source).hexdigest()!=episode['source_fingerprint']:raise ValueError('Stale episode analysis')
            analysis=validate_analysis(episode['analysis'],parsed)
            state=graph.invoke({'parsed':parsed,'analysis':analysis},{'recursion_limit':20})
            # Persist the complete per-episode graph outcome before global ranking.
            payload={'number':n,'pipeline_version':VERSION,'source_fingerprint':episode['source_fingerprint'],
                     'accepted':state['accepted'],'rejected':state['rejected'],
                     'repair_count':state['repair_count'],'no_suitable_clip_reason':state.get('no_suitable_clip_reason','')}
            save_json(output_dir/'episodes'/f'episode-{n:03d}.json',payload)
            all_candidates.extend(state['accepted']);all_rejected.extend(state['rejected'])
            record.update(status='completed',accepted=len(state['accepted']),rejected=len(state['rejected']),repairs=state['repair_count'])
            print(f'  accepted {record["accepted"]}; rejected {record["rejected"]}',flush=True)
        except Exception as exc:
            record.update(status='failed',error_type=type(exc).__name__)
            if isinstance(exc,ValueError):record['error']=str(exc)
            print(f'  Failed: {record}',flush=True)
        save_json(output_dir/'generation.json',progress)
    ranked,duplicates=rank_candidates(all_candidates)
    for c in ranked:
        c['segments']=[{'episode_number':c['episode_number'],'start_timestamp':timestamp(c['start']),'end_timestamp':timestamp(c['end']),'start_seconds':c['start'],'end_seconds':c['end']}]
    save_json(output_dir/'suggestions.json',{'version':VERSION,'scope':numbers,'suggestions':ranked,'note':'Script-based editorial estimates, not measured ad performance. Human footage review required.'})
    save_json(output_dir/'rejected.json',{'rejected':all_rejected,'duplicates':duplicates})
    with (output_dir/'edit_sheet.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['rank','title','episode','start','end','duration','clip_tags','ending_tags','hook','cliffhanger','why_it_works','ranking_rationale'])
        for c in ranked:
            writer.writerow([c['rank'],c['title'],c['episode_number'],timestamp(c['start']),timestamp(c['end']),c['duration'],', '.join(c['clip_tags']),', '.join(c['ending_tags']),c['hook'],c['cliffhanger'],c['why_it_works'],c['ranking_rationale']])
    text=['# Promo edit sheet','',f'Analyzed {len(numbers)} episodes; {len(ranked)} deduplicated suggestions.','',
          'Scores are model editorial judgments. These are continuous source ranges; no video was edited.','']
    for c in ranked:
        text += [f'## {c["rank"]}. {c["title"]}', '',f'Episode {c["episode_number"]} · {timestamp(c["start"])}–{timestamp(c["end"])} · {c["duration"]:.2f}s',
                 '',f'Clip tags: {", ".join(c["clip_tags"])}',f'Ending tags: {", ".join(c["ending_tags"])}','',
                 'Hook: '+c['hook'],'','Cliffhanger: '+c['cliffhanger'],'','Open question: '+c['review']['open_question'],'',
                 'Ranking: '+c['ranking_rationale'],'','Concerns: '+('; '.join(c['review']['concerns']) or 'None reported by model'),'','### Selected dialogue/actions','']
        p=json.loads((project_dir/'parsed'/f'episode-{c["episode_number"]:03d}.json').read_text())
        for b in selected_blocks(p,c['start'],c['end']):
            if b['kind'] in ('dialogue','action'):
                text.append(f'- {timestamp(b["visible_start"])}–{timestamp(b["visible_end"])} [{b["id"]}] {b["speaker"] or "ACTION"}: {b["text"]}')
        text.append('')
    (output_dir/'edit_sheet.md').write_text('\n'.join(text),encoding='utf-8')
    progress.update(status='completed_with_errors' if any(r['status']=='failed' for r in reports) else 'completed',
                    total_suggestions=len(ranked),total_rejected=len(all_rejected),duplicates_removed=len(duplicates),
                    model_requests=runner.calls,cache_hits=runner.hits,covered_episodes=len([r for r in reports if r['status']=='completed']))
    save_json(output_dir/'generation.json',progress)
    print(f'{progress["status"]}: {len(ranked)} suggestions, {len(all_rejected)} rejected, {len(duplicates)} duplicates; {runner.calls} calls / {runner.hits} cached',flush=True)
    return progress


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--episodes',help='Comma-separated episode numbers; default all episodes')
    p.add_argument('--retry-failed', action='store_true', help='Retry unfinished episodes in the existing output and rebuild its exports')
    p.add_argument('--delay',type=float,default=5);p.add_argument('--retries',type=int,default=2)
    args=p.parse_args()
    if args.retry_failed and args.episodes:p.error('--retry-failed uses the existing run scope')
    if args.delay<0 or not 0<=args.retries<=8:p.error('Invalid delay/retries')
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent/'.env')
    only=[int(n) for n in args.episodes.split(',')] if args.episodes else None
    try:
        result=generate(args.project,args.output,only,args.delay,args.retries,retry_failed=args.retry_failed)
        if result['status']!='completed':sys.exit(1)
    except KeyboardInterrupt:
        print('\nCancelled. Cached stage responses are saved; rerun to resume.',file=sys.stderr);sys.exit(130)
    except (OSError,ValueError) as exc:
        print(f'Generation failed: {exc}',file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()
