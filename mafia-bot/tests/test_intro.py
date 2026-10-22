import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bot import SurvivalBot,API
class FakeAPI:
    def __init__(self):self.uploads=0;self.reuses=0;self.messages=[]
    def animation(self,chat,content):self.uploads+=1;assert b'ftyp' in content[:32];return {'animation':{'file_id':'cached'}}
    def call(self,*a,**kw):self.reuses+=1;return {'animation':{'file_id':'cached'}}
    def send(self,chat,text,keyboard=None):self.messages.append(text);return {}
class IntroTests(unittest.TestCase):
    def test_upload_then_cache(self):
        with tempfile.TemporaryDirectory() as d:
            a=FakeAPI();b=SurvivalBot(a,str(Path(d)/'s.json'));b.intro('1');b.intro('2')
            self.assertEqual((a.uploads,a.reuses),(1,1));self.assertEqual(SurvivalBot(a,b.path).state['intro_animation_v1'],'cached')
    def test_failure_keeps_welcome(self):
        with tempfile.TemporaryDirectory() as d:
            a=FakeAPI();b=SurvivalBot(a,str(Path(d)/'s.json'));b.username='Arkade341bot'
            with patch.object(a,'animation',side_effect=RuntimeError('failed')):
                b.message({'text':'/start','from':{'id':1},'chat':{'id':1,'type':'private'}})
            self.assertTrue(any('ДОБРО ПОЖАЛОВАТЬ' in x for x in a.messages))
    def test_multipart_bytes(self):
        import io
        seen=[]
        def request(req,timeout):seen.append(req);return io.BytesIO(b'{"ok":true,"result":{}}')
        with patch('urllib.request.urlopen',side_effect=request):API('test').animation(1,b'abc')
        self.assertIn(b'\r\nContent-Disposition:',seen[0].data)
        self.assertIn(b'filename="arena.mp4"',seen[0].data)
