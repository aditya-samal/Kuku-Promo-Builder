import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from test_processing import SOURCE
from app.main import app
from app import db, worker


def archive_bytes(entries=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, content in (entries or [('season/episode-001.txt', SOURCE)]):
            archive.writestr(name, content)
    return stream.getvalue()


class FakeRunner:
    """Controlled responses exercise the real graph and validators."""
    def __init__(self, *args, on_attempt=None, **kwargs):
        self.on_attempt = on_attempt

    def request(self, stage, prompt, validate):
        if self.on_attempt:
            self.on_attempt(1)
        prefix, episode = stage.rsplit('-ep', 1)
        source = f'ep{episode}'
        first, second = f'{source}-block0001', f'{source}-block0002'
        if prefix == 'analysis':
            return validate({'summary': 'A conversation begins.', 'scenes': [{
                'scene_id': f'{source}-scene001', 'summary': 'A room', 'tags': [],
                'hooks': [], 'endings': [], 'context_needed': [],
            }]})
        if prefix == 'cuts':
            return validate({'no_suitable_clip_reason': '', 'candidates': [{
                'start_block_id': first, 'end_block_id': first, 'title': 'Test promo',
                'hook': 'Jane speaks', 'cliffhanger': 'A question remains',
                'open_question': 'What happens next?', 'why_it_works': 'A complete test cut.',
                'clip_tags': ['dialogue'], 'ending_tags': ['question'],
            }]})
        import json
        candidates = json.loads(prompt.split('CUTS:\n', 1)[1])
        return validate({'reviews': [{
            'candidate_id': entry['candidate']['id'], 'suitable': True,
            'points': dict(hook=25, clarity=20, cliffhanger=28, pacing=7),
            'score_notes': dict.fromkeys(('hook', 'clarity', 'cliffhanger', 'pacing'), 'Test evidence.'),
            'clarity_evidence_block_ids': [first], 'pacing_evidence_block_ids': [first],
            'hook_evidence_block_ids': [second], 'ending_evidence_block_ids': [first],
            'open_question': 'What happens next?', 'concerns': [], 'reason': 'Test evidence.',
        } for entry in candidates]})


class StudioTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, 'DATA_DIR', Path(temp)))
        self.enterContext(patch.object(db, 'DB_PATH', Path(temp) / 'studio.sqlite3'))
        self.enterContext(patch.dict(os.environ, {'APP_API_KEY': ''}))
        self.client = self.enterContext(TestClient(app))
        self.enterContext(patch.object(worker, 'configured', return_value=True))
        self.enterContext(patch.object(worker, 'ModelRunner', FakeRunner))

    def create(self, archive=None):
        return self.client.post('/studio/projects', data={'name': 'Studio test'},
                                files={'archive': ('scripts.zip', archive if archive is not None else archive_bytes())})

    def test_invalid_archives_leave_no_project_or_job(self):
        for archive in (b'broken archive', archive_bytes([('picture.png', 'image')]),
                        archive_bytes([('../episode.txt', SOURCE)]),
                        archive_bytes([('a.txt', SOURCE), ('b.txt', SOURCE)]),
                        archive_bytes([('bad.txt', 'not a script')])):
            self.assertEqual(self.create(archive).status_code, 422)
        self.assertEqual(self.client.get('/studio/projects').json(), [])
        self.assertFalse(worker.process_next())

    def test_create_process_bookmark_and_export(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.text)
        pid = response.json()['id']
        base = '/studio/projects/' + pid
        self.assertEqual(response.json()['job']['status'], 'queued')
        self.assertEqual(self.client.post(base + '/retry').status_code, 409)
        self.assertTrue(worker.process_next())
        result = self.client.get(base).json()
        self.assertEqual(result['job']['status'], 'completed', result['job'])
        self.assertEqual(result['job']['completed'], 1)
        promo = result['promos'][0]
        self.assertEqual(promo['editorial_score'], 80)
        self.assertEqual(self.client.get(base + '/promos/' + promo['id']).json()[0]['speaker'], 'JANE')
        saved = base + '/saved/' + promo['id']
        self.assertEqual(self.client.put(saved).status_code, 204)
        self.assertEqual(self.client.put(saved).status_code, 204)
        self.assertEqual(self.client.get(base).json()['saved_ids'], [promo['id']])
        export = self.client.get(base + '/export?saved=true')
        self.assertIn('Test promo', export.text)
        self.assertIn('filename="Studio test_promos.csv"', export.headers['content-disposition'])
        self.assertEqual(self.client.delete(saved).status_code, 204)
        self.assertNotIn('Test promo', self.client.get(base + '/export?saved=true').text)
        self.assertEqual(len(self.client.get(base).json()['promos']), 1)

    def test_delete_project_after_processing(self):
        base = '/studio/projects/' + self.create().json()['id']
        self.assertEqual(self.client.delete(base).status_code, 409)
        self.assertTrue(worker.process_next())
        promo = self.client.get(base).json()['promos'][0]
        self.assertEqual(self.client.put(base + '/saved/' + promo['id']).status_code, 204)
        self.assertEqual(self.client.delete(base).status_code, 204)
        self.assertEqual(self.client.get(base).status_code, 404)
        self.assertEqual(self.client.get('/studio/projects').json(), [])
        with db.connect() as connection:
            for table in ('episodes', 'jobs', 'promo_runs', 'saved_promos'):
                self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_retry_preserves_completed_episode_and_partial_results(self):
        class FailSecond(FakeRunner):
            def request(self, stage, prompt, validate):
                if stage == 'cuts-ep002':
                    raise ValueError('Simulated temporary failure')
                return super().request(stage, prompt, validate)
        pid = self.create(archive_bytes([('one.txt', SOURCE), ('two.txt', SOURCE.replace('Episode 1', 'Episode 2', 1))])).json()['id']
        base = '/studio/projects/' + pid
        with patch.object(worker, 'ModelRunner', FailSecond):
            self.assertTrue(worker.process_next())
        partial = self.client.get(base).json()
        self.assertEqual(partial['job']['status'], 'failed')
        self.assertEqual(partial['job']['stage'], 'promos')
        self.assertEqual(len(partial['promos']), 1)
        self.assertEqual(self.client.post(base + '/retry').status_code, 202)
        self.assertTrue(worker.process_next())
        complete = self.client.get(base).json()
        self.assertEqual(complete['job']['status'], 'completed')
        self.assertEqual(complete['job']['completed'], 2)
        self.assertEqual(len(complete['promos']), 2)
        self.assertIn(partial['promos'][0]['id'], {cut['id'] for cut in complete['promos']})
