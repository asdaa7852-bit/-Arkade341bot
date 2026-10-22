import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot import SurvivalBot
class API:
    def __init__(self):self.messages=[]
    def send(self,chat,text,keyboard=None):self.messages.append(text);return {}
class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bot=SurvivalBot(API(),str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.bot.state['accounts']={'1':{'coins':200,'wins':0,'games':0},'2':{'coins':0,'wins':0,'games':0}}
    def cmd(self,text,mid=1,reply=None):
        m={'text':text,'message_id':mid,'from':{'id':1},'chat':{'id':-1,'type':'group'}}
        if reply:m['reply_to_message']={'from':reply}
        self.bot.message(m)
    def balances(self):return [self.bot.state['accounts'][u]['coins'] for u in ('1','2')]
    def test_transfer_replay_and_restart(self):
        self.cmd('/transfer 2 100');self.cmd('/transfer 2 100')
        self.assertEqual(self.balances(),[100,100])
        self.bot=SurvivalBot(API(),self.bot.path);self.bot.username='Arkade341bot'
        self.cmd('/transfer 2 100');self.assertEqual(self.balances(),[100,100])
    def test_reply_and_validation(self):
        self.cmd('/transfer 50',reply={'id':2});self.assertEqual(self.balances(),[150,50])
        for i,text in enumerate(['/transfer 2 -5','/transfer 2 0','/transfer 2 99999999','/transfer 1 10','/transfer 999 10','/transfer 2 151'],2):self.cmd(text,i)
        self.cmd('/transfer 10',mid=20,reply={'id':2,'is_bot':True})
        self.assertEqual(self.balances(),[150,50])
    def test_owner_can_gift_without_deduction(self):
        self.bot.state['coin_owner_id']='1';self.cmd('/transfer 2 1000')
        self.assertEqual(self.balances(),[200,1000])
    def test_save_failure_rolls_back_both_balances(self):
        with patch.object(self.bot,'save',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.cmd('/transfer 2 100')
        self.assertEqual(self.balances(),[200,0]);self.assertFalse(self.bot.state['coin_transfers'])
