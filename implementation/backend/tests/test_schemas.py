import json
import unittest
from unittest.mock import patch
from app.analysis import call_model,parse_response
from app.schemas import response_format

class SchemaTests(unittest.TestCase):
    def test_only_supported_analysis_fields(self):
        f=response_format('episode data')
        self.assertEqual(f['type'],'json_schema')
        self.assertEqual(set(f['json_schema']['schema']['properties']),{'summary','scenes'})
        self.assertTrue(f['json_schema']['strict'])

    def test_request_uses_schema(self):
        with patch('app.analysis.urllib.request.urlopen') as mocked:
            mocked.return_value.__enter__.return_value.read.return_value=b'{}'
            call_model('analyze')
            payload=json.loads(mocked.call_args.args[0].data)
        self.assertEqual(payload['response_format']['type'],'json_schema')

    def test_truncated_response_rejected(self):
        with self.assertRaises(ValueError):
            parse_response(json.dumps({'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}))
