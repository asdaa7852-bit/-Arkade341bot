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
    def test_removed_commands_redirect_without_spending(self):
        for text in ('/kill @victimname','/use medkit','/equip fire','/unequip','/buy fire'):
            self.command(text=text)
            self.assertIn('через кнопки',self.bot.api.messages[-1][1])
            self.assertEqual(self.bot.state['accounts']['1']['coins'],2500)
            self.assertTrue(self.g['players']['2']['alive'])
    def test_inventory_buttons_equip_and_remove(self):
        self.bot.state['accounts']['1']['inventory']=['fire']
        self.command(text='/inventory')
        rows=self.bot.api.messages[-1][2]
        self.assertEqual(rows[0][0]['callback_data'],'inv:equip:fire')
        for data in ('inv:equip:fire','inv:unequip:all'):
            self.bot.callback({'id':data,'from':{'id':1},'message':{'chat':{'id':1,'type':'private'}},'data':data})
        self.assertEqual(self.bot.state['accounts']['1']['equipped'],{})
    def test_group_inventory_button_cannot_apply(self):
        self.bot.state['accounts']['1']['inventory']=['fire']
        self.bot.callback({'id':'q','from':{'id':1},'message':{'chat':{'id':-1,'type':'group'}},'data':'inv:equip:fire'})
        self.assertNotIn('equipped',self.bot.state['accounts']['1'])
