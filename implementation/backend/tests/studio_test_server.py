"""Local browser-test harness with deterministic model responses and an isolated DB."""
import os
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
from test_studio import FakeRunner, archive_bytes
from app import db, worker
from app.main import app

os.environ['APP_API_KEY'] = ''
db.init_db()
worker.ModelRunner = FakeRunner
worker.configured = lambda: True
test_app = FastAPI()


@test_app.get('/test/fixture.zip')
def fixture():
    return Response(archive_bytes(), media_type='application/zip')


@test_app.post('/test/process')
def process():
    return {'processed': worker.process_next()}


test_app.mount('/', app)

if __name__ == '__main__':
    uvicorn.run(test_app, host='127.0.0.1', port=8765)
