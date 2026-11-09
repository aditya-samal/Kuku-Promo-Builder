import unittest
from app.parser import parse_episode
from app.promos import safe_boundary,windows,validate_cuts,validate_reviews,rank_candidates,build_graph
from app.analysis import validate_analysis
from fixtures import annotation
from test_processing import SOURCE

LONG=SOURCE.replace('00:30.00','01:00.00')+''

class PromoTests(unittest.TestCase):
    def test_dialogue_split_rejected(self):
        parsed=parse_episode(SOURCE)
        self.assertFalse(safe_boundary(parsed,2))
        self.assertTrue(safe_boundary(parsed,4))

    def test_enumerated_windows_are_legal(self):
        p=parse_episode(LONG);a=annotation(p)
        result=windows(p,a)
        self.assertTrue(result)
        for w in result:
            self.assertTrue(20<=w['duration']<=60)
            self.assertTrue(safe_boundary(p,w['start']))
            self.assertTrue(safe_boundary(p,w['end']))

    def test_missing_scene_rejected(self):
        p=parse_episode(SOURCE)
        with self.assertRaises(ValueError):validate_analysis({'summary':'test','scenes':[]},p)

    def test_evidence_must_belong_to_scene(self):
        p=parse_episode(SOURCE);a=annotation(p)
        a['scenes'][0]['hooks']=[{'description':'test','hook_type':'dialogue','evidence_block_ids':['ep002-block0001']}]
        with self.assertRaises(ValueError):validate_analysis(a,p)

    def test_disallowed_cut_rejected(self):
        p=parse_episode(LONG);a=annotation(p)
        with self.assertRaises(ValueError):validate_cuts({'candidates':[{'start_block_id':'fake','end_block_id':'fake'}],'no_suitable_clip_reason':''},p,windows(p,a))

    def test_no_suitable_clip_graph_terminates(self):
        class Runner:
            def request(self,stage,prompt,validate):
                return validate({'candidates':[],'no_suitable_clip_reason':'No specific unresolved ending.'})
        p=parse_episode(LONG)
        result=build_graph(Runner()).invoke({'parsed':p,'analysis':annotation(p)})
        self.assertEqual(result['accepted'],[])
        self.assertEqual(result['repair_count'],0)

    def test_reviewer_cannot_cite_outside_first_three_seconds(self):
        p=parse_episode(LONG);p['blocks'][1]['start']=10;p['blocks'][1]['end']=14
        c={'id':'c','start':0,'end':60}
        points = dict(hook=25, clarity=20, cliffhanger=28, pacing=7)
        review = {'candidate_id': 'c', 'suitable': True, 'points': points,
                  'score_notes': dict.fromkeys(points, 'Test evidence.'),
                  'hook_evidence_block_ids': [p['blocks'][1]['id']],
                  'ending_evidence_block_ids': [p['blocks'][0]['id']],
                  'clarity_evidence_block_ids': [], 'pacing_evidence_block_ids': [],
                  'open_question': 'What?', 'concerns': [], 'reason': 'test'}
        validate_reviews({'reviews': [review]}, p, [c])
        self.assertEqual(review['hook_evidence_block_ids'], [])

    def test_duplicate_ranking(self):
        base={'episode_number':1,'start':0,'end':40,'duration':40,'editorial_score':85,'review':{'scores':dict(hook=4,clarity=4,cliffhanger=5,pacing=4),'reason':'test'}}
        ranked,duplicates=rank_candidates([dict(base,id='a'),dict(base,id='b',start=2,end=42,editorial_score=80)])
        self.assertEqual(len(ranked),1);self.assertEqual(len(duplicates),1)
        self.assertEqual(ranked[0]['review']['scores']['cliffhanger'], 100)
        self.assertIn('cliffhanger 100/100', ranked[0]['ranking_rationale'])
