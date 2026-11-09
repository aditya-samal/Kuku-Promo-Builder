"""Serve the built interface and launch one durable worker on this machine."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values, load_dotenv
import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    os.chdir(root)
    env_file = root / '.env'
    configured_model = dotenv_values(env_file).get('LLM_MODEL')
    load_dotenv(env_file)
    if configured_model:
        os.environ['LLM_MODEL'] = configured_model
    os.environ.setdefault('LLM_MODEL', 'gemini-3.1-flash-lite')
    if not (root.parent / 'frontend' / 'dist' / 'index.html').is_file():
        parser.error('Build implementation/frontend with npm install and npm run build first')
    print(f"Studio model: {os.environ['LLM_MODEL']}", flush=True)
    worker = subprocess.Popen([sys.executable, '-m', 'app.worker'])
    try:
        uvicorn.run('app.main:app', host='127.0.0.1', port=args.port)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()


if __name__ == '__main__':
    main()
