import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bot import SurvivalBot
import payments
class API:
    def __init__(self):self.messages=[];self.calls=[]
    def send(self,chat,text,keyboard=None):self.messages.append((chat,text,keyboard));return {}
    def call(self,method,**kw):self.calls.append((method,kw));return True
class StarButtonTests(unittest.TestCase):
    def test_buttons_consent_invoice_and_replay(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'PAYMENT_SUPPORT':'@owner_test'}):
            api=API();b=SurvivalBot(api,str(Path(d)/'s.json'));b.username='Arkade341bot'
            m={'text':'/stars','from':{'id':1},'chat':{'id':1,'type':'private'}}
            payments.command(b,m,'/stars')
            self.assertEqual(len(api.messages[-1][2]),3)
            q={'id':'q1','from':{'id':1},'message':{'chat':m['chat']},'data':'stars:select:500'}
            b.callback(q);paydata=api.messages[-1][2][0][0]['callback_data']
            self.assertFalse(any(method=='sendInvoice' for method,kw in api.calls))
            b.callback(dict(q,id='q2',data=paydata));b.callback(dict(q,id='q3',data=paydata))
            invoices=[kw for method,kw in api.calls if method=='sendInvoice']
            self.assertEqual(len(invoices),1);self.assertEqual(invoices[0]['prices'][0]['amount'],40)
            self.assertNotIn('accounts',b.state)
    def test_other_user_cannot_confirm(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'PAYMENT_SUPPORT':'@owner_test'}):
            api=API();b=SurvivalBot(api,str(Path(d)/'s.json'));b.username='Arkade341bot'
            b.state['star_consents']={'abc':{'uid':'1','pack':'100','created':__import__('time').time()}}
            b.callback({'id':'q','data':'stars:pay:abc','from':{'id':2},'message':{'chat':{'id':2,'type':'private'}}})
            self.assertFalse(any(method=='sendInvoice' for method,kw in api.calls))
