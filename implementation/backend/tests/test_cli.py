import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from process import process_folder
from test_processing import SOURCE
from app.parser import parse_episode
from fixtures import annotation

class CliTests(unittest.TestCase):
    def test_parse_and_cached_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'input';source.mkdir()
            (source/'one.txt').write_text(SOURCE)
            calls=[]
            def fake(prompt):
                calls.append(prompt)
                return json.dumps({'choices':[{'message':{'content':json.dumps(annotation(parse_episode(SOURCE)))}}]})
            out=root/'output'
            self.assertEqual(process_folder(source,out)['totals']['blocks'],2)
            self.assertEqual(process_folder(source,out,analyze=True,model_call=fake)['episodes'][0]['status'],'analyzed')
            result=process_folder(source,out,analyze=True,model_call=fake)
            self.assertTrue(result['episodes'][0]['cached'])
            self.assertEqual(len(calls),1)
            self.assertEqual((out/'sources/episode-001.txt').read_text(),SOURCE)
            self.assertEqual(len(list((out/'runs').rglob('*attempt*.json'))),1)

    def test_bad_response_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input';source.mkdir();(source/'one.txt').write_text(SOURCE)
            result=process_folder(source,root/'out',analyze=True,retries=0,model_call=lambda p:'not-json')
            self.assertEqual(result['status'],'completed_with_errors')
            raw=json.loads(next((root/'out/runs').rglob('*attempt*.json')).read_text())
            self.assertEqual(raw['raw_response'],'not-json')
            self.assertEqual(raw['status'],'failed')

    def test_duplicate_rejected_before_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input';source.mkdir()
            for name in ['one','two']:
                (source/f'{name}.txt').write_text(SOURCE)
            with self.assertRaises(ValueError):
                process_folder(source,root/'out',analyze=True,model_call=lambda p:self.fail('Model should not run'))
