"""Sequential model calls with provenance, schema-aware caching and bounded repairs."""
import hashlib
import json
from pathlib import Path
import time
import urllib.error
from .analysis import call_model,parse_response
from .schemas import response_format
from . import config


def save_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


class ModelRunner:
    def __init__(self,root,delay=5,retries=2,call=None,on_attempt=None):
        self.root=Path(root);self.delay=delay;self.retries=retries;self.call=call or call_model
        self.on_attempt=on_attempt
        self.last=None;self.calls=0;self.hits=0

    def request(self,stage,prompt,validate):
        fingerprint=hashlib.sha256(json.dumps([config.MODEL,config.BASE_URL,prompt,response_format(prompt)],sort_keys=True).encode()).hexdigest()
        cache=self.root/'cache'/f'{fingerprint}.json'
        if cache.exists():
            try:
                value=validate(json.loads(cache.read_text())['result']);self.hits+=1;return value
            except (ValueError,KeyError,TypeError):
                pass
        current_prompt=prompt
        for attempt in range(self.retries+1):
            if self.last is not None:
                time.sleep(max(0,self.delay-(time.monotonic()-self.last)))
            path=self.root/'raw'/f'{stage}-{fingerprint[:12]}-{time.time_ns()}.json'
            audit={'stage':stage,'model':config.MODEL,'fingerprint':fingerprint,'prompt':current_prompt,'status':'started','attempt':attempt+1}
            save_json(path,audit)
            print(f'  {stage}: calling {config.MODEL}, attempt {attempt+1}',flush=True)
            try:
                if self.on_attempt:
                    self.on_attempt(attempt + 1)
                self.last=time.monotonic();self.calls+=1
                raw=self.call(current_prompt)
                audit['raw_response']=raw;save_json(path,audit)
                value=validate(parse_response(raw))
                audit['status']='completed';save_json(path,audit)
                save_json(cache,{'result':value,'fingerprint':fingerprint,'model':config.MODEL})
                return value
            except Exception as exc:
                audit.update(status='failed',error_type=type(exc).__name__)
                retryable=isinstance(exc,(ValueError,TimeoutError,urllib.error.URLError))
                if isinstance(exc,urllib.error.HTTPError):
                    audit['http_status']=exc.code;retryable=exc.code in (429,500,502,503,504)
                if isinstance(exc,ValueError):
                    audit['validation_error']=str(exc)
                    current_prompt=prompt+'\nYour previous response failed validation: '+str(exc)+'\nCorrect this specific issue. Return the required schema.'
                save_json(path,audit)
                if attempt>=self.retries or not retryable:
                    raise
                detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                print(f'  {stage}: {detail}; retrying with feedback/backoff', flush=True)
                time.sleep(min(30,5*2**attempt))
        raise RuntimeError('Model retries exhausted')
