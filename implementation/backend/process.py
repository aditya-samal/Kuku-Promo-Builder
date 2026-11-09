"""Standalone processing entry point. No API, database, or worker required."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import uuid

VERSION = 'scene-analysis-v1'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def process_folder(input_dir, output_dir, analyze=False, limit=None, delay=5, retries=3, model_call=None):
    from app.parser import parse_episode
    from app import analysis, config
    input_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    if not input_dir.is_dir():
        raise ValueError(f'Input folder does not exist: {input_dir}')
    files = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == '.txt')
    if not files:
        raise ValueError('No .txt episodes found')
    # Parse and validate the whole pack before making any model calls.
    episodes, numbers = [], set()
    for path in files:
        raw = path.read_bytes()
        parsed = parse_episode(raw.decode('utf-8-sig'))
        if parsed['number'] in numbers:
            raise ValueError(f'Duplicate episode number: {parsed["number"]}')
        numbers.add(parsed['number'])
        episodes.append((path,raw,parsed))
    episodes.sort(key=lambda e:e[2]['number'])
    if limit:
        episodes=episodes[:limit]
    if analyze and model_call is None and not analysis.configured():
        raise ValueError('AI analysis requires LLM_MODEL and LLM_API_KEY in the environment or .env')
    call=model_call or analysis.call_model
    # Do not mix a different series into an existing output directory.
    identity=hashlib.sha256(str(input_dir).encode()).hexdigest()
    manifest_path=output_dir/'project.json'
    if manifest_path.exists():
        previous=json.loads(manifest_path.read_text())
        if previous.get('input_identity') != identity:
            raise ValueError('Output belongs to a different input folder; choose a new --output')
    run_id=uuid.uuid4().hex
    manifest={'input_identity':identity,'input_folder':str(input_dir),'mode':'analyze' if analyze else 'parse',
              'run_id':run_id,'status':'running','episodes':[], 'pipeline_version':VERSION}
    write_json(manifest_path,manifest)
    last_request=None
    for path,raw,parsed in episodes:
        n=parsed['number']; key=f'episode-{n:03d}'
        print(f'[{len(manifest["episodes"])+1}/{len(episodes)}] Episode {n}: {len(parsed["blocks"])} blocks',flush=True)
        write_json(output_dir/'parsed'/f'{key}.json',parsed)
        # Retain exact uploaded bytes, including BOM/newlines, under a safe filename.
        source_dir=output_dir/'sources';source_dir.mkdir(parents=True,exist_ok=True)
        (source_dir/f'{key}.txt').write_bytes(raw)
        record={'number':n,'source_filename':path.name,'duration':parsed['duration'],'warnings':parsed['warnings'],
                'source_logline':parsed['logline'],'status':'parsed'}
        if analyze:
            prompt=analysis.episode_prompt(parsed)
            fingerprint=hashlib.sha256((VERSION+config.MODEL+config.BASE_URL+prompt).encode()).hexdigest()
            cached_path=output_dir/'analysis'/f'{key}.json'
            value=None
            if cached_path.exists():
                try:
                    cached=json.loads(cached_path.read_text())
                    if cached['fingerprint']==fingerprint:
                        value=analysis.validate_analysis(cached['analysis'],parsed)
                        record['cached']=True
                except (ValueError,KeyError,TypeError):
                    pass
            if value is None:
                request_prompt=prompt
                for attempt in range(retries+1):
                    if last_request is not None:
                        time.sleep(max(0,delay-(time.monotonic()-last_request)))
                    evidence={'model':config.MODEL,'base_url':config.BASE_URL,'prompt':request_prompt,'attempt':attempt+1,'status':'started'}
                    attempt_path=output_dir/'runs'/run_id/f'{key}-attempt-{attempt+1}.json'
                    write_json(attempt_path,evidence)
                    try:
                        last_request=time.monotonic()
                        print(f'  Calling {config.MODEL or "test model"} (attempt {attempt+1}; request timeout 180s)...',flush=True)
                        response=call(request_prompt)
                        print('  Response received; validating...',flush=True)
                        evidence['raw_response']=response
                        # Persist raw response before parsing/validation, including invalid responses.
                        write_json(attempt_path,evidence)
                        value=analysis.validate_analysis(analysis.parse_response(response),parsed)
                        evidence['status']='completed';write_json(attempt_path,evidence)
                        write_json(cached_path,{'fingerprint':fingerprint,'model':config.MODEL,'analysis':value})
                        break
                    except Exception as exc:
                        evidence.update(status='failed',error_type=type(exc).__name__)
                        if isinstance(exc,ValueError):
                            evidence['validation_error']=str(exc)
                            request_prompt=prompt+'\nPrevious response failed validation: '+str(exc)+'\nCorrect the source references/timing. A payoff must be after the ending; use [] if no later payoff can be cited.'
                        write_json(attempt_path,evidence)
                        retryable=isinstance(exc,(TimeoutError,urllib.error.URLError,ValueError))
                        if isinstance(exc,urllib.error.HTTPError):
                            retryable=exc.code in (429,500,502,503,504)
                            evidence['http_status']=exc.code;write_json(attempt_path,evidence)
                        if retryable and attempt<retries:
                            backoff=min(60,5*(2**attempt))
                            reason = f'HTTP {exc.code}' if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
                            print(f'  Request/validation failure ({reason}); retrying in {backoff}s',flush=True)
                            time.sleep(backoff)
                        else:
                            record.update(status='failed',error_type=type(exc).__name__)
                            if isinstance(exc,urllib.error.HTTPError):
                                record['http_status']=exc.code
                            reason = f'HTTP {exc.code}' if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
                            print(f'  Episode {n} failed ({reason}); details saved in runs/',flush=True)
                            break
            if value is not None:
                record.update(status='analyzed')
                write_json(output_dir/'episodes'/f'{key}.json',{'number':n,'source_fingerprint':hashlib.sha256(raw).hexdigest(),'analysis_version':VERSION,'model':config.MODEL,'analysis':value})
        manifest['episodes'].append(record)
        write_json(manifest_path,manifest)
    manifest['status']='completed_with_errors' if any(e['status']=='failed' for e in manifest['episodes']) else 'completed'
    manifest['totals']={'episodes':len(episodes),'scenes':sum(len(p['scenes']) for _,_,p in episodes),
                        'blocks':sum(len(p['blocks']) for _,_,p in episodes),
                        'duration_seconds':round(sum(p['duration'] for _,_,p in episodes),2)}
    write_json(manifest_path,manifest)
    print(f'{manifest["status"]}: {manifest["totals"]}\nOutput: {output_dir}',flush=True)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--analyze',action='store_true',help='Send each episode to the configured LLM')
    parser.add_argument('--limit',type=int,help='Process the first N episodes in episode-number order')
    parser.add_argument('--delay',type=float,default=5,help='Minimum seconds between model requests')
    parser.add_argument('--retries',type=int,default=3)
    parser.add_argument('--env-file',type=Path,default=Path(__file__).parent/'.env')
    args=parser.parse_args()
    if args.limit is not None and args.limit<1 or args.delay<0 or not 0<=args.retries<=8:
        parser.error('limit must be positive; delay nonnegative; retries between 0 and 8')
    if args.env_file.exists():
        try:
            from dotenv import load_dotenv
        except ImportError:
            parser.error('Install python-dotenv to load .env, or export variables and use --env-file /dev/null')
        load_dotenv(args.env_file,override=False)
    try:
        result=process_folder(args.input,args.output,args.analyze,args.limit,args.delay,args.retries)
    except KeyboardInterrupt:
        parser.exit(130,'\nCancelled. Completed results are saved; rerun to resume.\n')
    except (ValueError,OSError) as exc:
        parser.exit(1,f'Processing failed: {exc}\n')
    if result['status']!='completed':
        parser.exit(1,'Processing incomplete: inspect episode status in project.json and runs/, then rerun to resume.\n')

if __name__=='__main__':
    main()
