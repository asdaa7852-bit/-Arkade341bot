import tempfile,time,unittest
from pathlib import Path
from bot import SurvivalBot
class API:
    def __init__(self):self.messages=[]
    def send(self,chat,text,keyboard=None):self.messages.append((str(chat),text,keyboard));return {}
    def call(self,*a,**kw):return {}
class KillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bot=SurvivalBot(API(),str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.bot.state['accounts']={'1':{'coins':2500,'wins':0,'games':0}}
        self.bot.remember_username({'id':2,'username':'VictimName'})
        self.g={'phase':'night','owner':'1','round':1,'nonce':'abc','deadline':time.time()+60,'votes':{},'players':{str(i):{'name':'Игрок'+str(i),'alive':True,'hp':100,'role':'armor','power':0} for i in range(1,5)}}
        self.bot.games['-1']=self.g
    def command(self,kind='private',text='/kill @victimname'):
        self.bot.message({'text':text,'from':{'id':1},'chat':{'id':1 if kind=='private' else -1,'type':kind}})
    def confirm(self):
        data=self.bot.api.messages[-1][2][0][0]['callback_data']
        q={'id':'q','from':{'id':1},'message':{'chat':{'id':1,'type':'private'}},'data':data}
        self.bot.callback(q);self.bot.callback(q)
    def test_confirm_charges_once_and_does_not_publish_buyer(self):
        self.command();self.assertEqual(self.bot.state['accounts']['1']['coins'],2500);self.assertTrue(self.g['players']['2']['alive'])
        self.confirm();self.assertEqual(self.bot.state['accounts']['1']['coins'],500);self.assertFalse(self.g['players']['2']['alive'])
        public=[text for chat,text,k in self.bot.api.messages if chat=='-1'];self.assertEqual(len(public),1);self.assertNotIn('Игрок1',public[0])
    def test_owned_item_preferred(self):
        self.bot.state['accounts']['1']['consumables']={'exile':1};self.command();self.confirm()
        self.assertEqual(self.bot.state['accounts']['1']['coins'],2500);self.assertEqual(self.bot.state['accounts']['1']['consumables']['exile'],0)
    def test_group_redirect_and_unknown_name(self):
        self.command('group');self.assertTrue(self.g['players']['2']['alive']);self.assertEqual(self.bot.state['accounts']['1']['coins'],2500)
        self.command(text='/kill @missingname');self.assertIsNone(self.bot.api.messages[-1][2])
    def test_changed_username_not_resolved_to_old_owner(self):
        self.bot.remember_username({'id':2,'username':'newname'});self.command();self.assertIsNone(self.bot.api.messages[-1][2])
