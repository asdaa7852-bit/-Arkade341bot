import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import SurvivalBot
import payments

class API:
    def __init__(self): self.calls=[];self.messages=[]
    def send(self,*args,**kw):self.messages.append(args);return {}
    def call(self,method,**kw):self.calls.append((method,kw));return True

class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=API();self.bot=SurvivalBot(self.api,str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.msg={'text':'/stars 100 agree','from':{'id':1},'chat':{'id':1,'type':'private'}}
    def invoice(self):
        with patch.dict(os.environ,{'PAYMENT_SUPPORT':'@owner_test'}):
            payments.command(self.bot,self.msg,'/stars')
        params=self.api.calls[-1][1]
        return {'invoice_payload':params['payload'],'currency':'XTR','total_amount':10,'telegram_payment_charge_id':'charge1'}
    def test_disabled_without_contact_or_consent(self):
        with patch.dict(os.environ,{'PAYMENT_SUPPORT':''}):payments.command(self.bot,self.msg,'/stars')
        self.assertFalse(self.api.calls)
        self.msg['text']='/stars 100'
        with patch.dict(os.environ,{'PAYMENT_SUPPORT':'@owner_test'}):payments.command(self.bot,self.msg,'/stars')
        self.assertFalse(self.api.calls)
    def test_invoice_precheckout_and_exactly_once(self):
        p=self.invoice();self.assertEqual(self.api.calls[-1][1]['prices'],[{'label':'100 коинов','amount':10}])
        q=dict(p,id='q',**{'from':{'id':1}})
        with patch.dict(os.environ,{'PAYMENT_SUPPORT':'@owner_test'}):payments.precheckout(self.bot,q)
        self.assertTrue(self.api.calls[-1][1]['ok']);self.assertNotIn('accounts',self.bot.state)
        m=dict(self.msg,successful_payment=p)
        payments.delivery(self.bot,m);payments.delivery(self.bot,m)
        self.assertEqual(self.bot.state['accounts']['1']['coins'],100)
        restored=SurvivalBot(self.api,self.bot.path);payments.delivery(restored,m)
        self.assertEqual(restored.state['accounts']['1']['coins'],100)
    def test_reject_wrong_user_currency_and_price(self):
        p=self.invoice()
        self.assertIsNone(payments.valid(self.bot,2,p))
        self.assertIsNone(payments.valid(self.bot,1,dict(p,currency='USD')))
        self.assertIsNone(payments.valid(self.bot,1,dict(p,total_amount=1)))
    def test_refund_deducts_once(self):
        p=self.invoice();payments.delivery(self.bot,dict(self.msg,successful_payment=p))
        m=dict(self.msg,refunded_payment=p);payments.delivery(self.bot,m);payments.delivery(self.bot,m)
        self.assertEqual(self.bot.state['accounts']['1']['coins'],0)
