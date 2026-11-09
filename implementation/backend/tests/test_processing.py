import json
import os
from pathlib import Path
import tempfile
import unittest

_tmp=tempfile.TemporaryDirectory()
os.environ['DATA_DIR']=_tmp.name
from app.parser import parse_episode
from app.db import init_db, connect, decode
from app.worker import process_next
from app.analysis import validate_analysis
from fixtures import annotation

SOURCE='''EPISODE NUMBER: Episode 1
EPISODE LOGLINE: Test
CONTINUITY NOTES: Start
SCENE 01
SCENE HEADING: INT. ROOM
SCENE START: 00:00.00
SCENE END: 00:30.00
**CAMERA:**
Start: (00:00.00) | End: (00:30.00)
A room.
**JANE (Soft):**
Start: (00:01.00) | End: (00:04.00)
"Hello."
--- SCRIPT END ---
'''

class ProcessingTests(unittest.TestCase):
    def test_overlap_duration_and_source(self):
        p=parse_episode(SOURCE)
        self.assertEqual(p['duration'],30)
        self.assertEqual(len(p['blocks']),2)
        self.assertEqual(p['blocks'][1]['speaker'],'JANE')
        self.assertEqual(p['blocks'][1]['text'],'"Hello."')

    def test_invalid_times(self):
        with self.assertRaises(ValueError):
            parse_episode(SOURCE.replace('00:30.00','00:70.00'))

    def test_evidence_must_exist(self):
        parsed=parse_episode(SOURCE)
        value=annotation(parsed)
        value['scenes'][0]['hooks']=[{'description':'hello','hook_type':'dialogue','evidence_block_ids':['fake']}]
        with self.assertRaises(ValueError):
            validate_analysis(value,parsed)


    def test_durable_worker(self):
        init_db()
        with connect() as db:
            db.execute("INSERT INTO projects(id,name) VALUES('p','test')")
            db.execute('INSERT INTO episodes VALUES(?,?,?,?,?,?,NULL)',('p',1,'test.txt','digest',SOURCE,json.dumps(parse_episode(SOURCE))))
            db.execute("INSERT INTO jobs(id,project_id,mode,status) VALUES('j','p','parse','running')")
        self.assertTrue(process_next())
        with connect() as db:
            job=decode(db.execute("SELECT * FROM jobs WHERE id='j'").fetchone())
        self.assertEqual(job['status'],'completed')
        self.assertEqual(job['completed'],1)
        self.assertEqual(job['result']['processing_stage'],'parsed')

    def test_supplied_pack(self):
        folder=Path(__file__).resolve().parents[3]/'I Married a Broken Soldier. He was a Duke'
        files=sorted(folder.glob('*.txt'))
        if not files:
            self.skipTest('Confidential pack not present')
        episodes=[parse_episode(f.read_text()) for f in files]
        self.assertEqual([p['number'] for p in episodes],list(range(1,51)))
        self.assertEqual(sum(len(p['blocks']) for p in episodes),3727)
        self.assertEqual(sum(len(p['scenes']) for p in episodes),100)

if __name__=='__main__':
    unittest.main()
