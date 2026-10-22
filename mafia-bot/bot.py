"""Telegram Mafia, Python 3.11+, standard library only."""
import collections
import json
import logging
import os
from pathlib import Path
import random
import secrets
import time
import urllib.request
import urllib.error

from engine import ROLES, SPECIAL, LABELS, TARGETED, setup, defaults, valid_action, resolve_night, council

HELP = '''🔥 Выживает сильнейший
/newgame — новая арена
/join — вступить
/leave — выйти до старта
/begin — начать (4–20 игроков)
/players — здоровье участников
/roles — все 20 ролей
/myrole — ваша роль и оставшиеся способности
/stop — отменить

Каждый сначала нажимает /start в личном чате бота. Ночью выбирайте атаку, защиту или припасы. Днём обсуждение и голосование: выбранный теряет 35 HP. Роли тайные, команд нет. Побеждает последний живой. С третьей ночи арена наносит растущий урон всем. При одновременной гибели всех победителя нет. Без хода включается защита. Управление — у создателя и администраторов.'''


def leader(votes):
    counts = collections.Counter(votes)
    if not counts:
        return None
    best = counts.most_common()
    return best[0][0] if len(best) == 1 or best[0][1] > best[1][1] else None




class API:
    def __init__(self, token):
        self.base = 'https://api.telegram.org/bot' + token + '/'

    def call(self, method, **params):
        req = urllib.request.Request(self.base + method, json.dumps(params).encode(), {'Content-Type': 'application/json'})
        # Do not log request URLs: they contain the bot token.
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=40) as response:
                    result = json.load(response)
                if not result.get('ok'):
                    raise RuntimeError('Telegram отклонил запрос')
                return result['result']
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    try:
                        wait = int(json.loads(exc.read()).get('parameters',{}).get('retry_after',1))
                    except (ValueError, TypeError):
                        wait = 1
                    if 0 < wait <= 30:
                        time.sleep(wait)
                        continue
                raise RuntimeError('Telegram отклонил запрос') from None
            except RuntimeError:
                raise
            except Exception:
                raise RuntimeError('Ошибка соединения с Telegram') from None


    def send(self, chat, text, keyboard=None):
        params = {'chat_id': chat, 'text': text}
        if keyboard:
            params['reply_markup'] = {'inline_keyboard': keyboard}
        return self.call('sendMessage', **params)


class Bot:
    def __init__(self, api, path='data/state.json'):
        self.api, self.path = api, Path(path)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'offset': 0, 'ready': [], 'games': {}}
        self.games = self.state['games']
        self.night = max(15, int(os.getenv('NIGHT_SECONDS', '60')))
        self.discuss = max(15, int(os.getenv('DISCUSS_SECONDS', '90')))
        self.voting = max(15, int(os.getenv('VOTE_SECONDS', '60')))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, ensure_ascii=False))
        os.chmod(temp, 0o600)
        temp.replace(self.path)

    def safe_send(self, chat, text, keyboard=None):
        try:
            self.api.send(chat, text, keyboard)
            return True
        except RuntimeError:
            logging.warning('Не удалось доставить сообщение в чат %s', chat)
            return False

    def authorized(self, chat, user, game):
        if game['owner'] == user:
            return True
        member = self.api.call('getChatMember', chat_id=int(chat), user_id=int(user))
        return member['status'] in ('creator', 'administrator')

    def active_elsewhere(self, uid, chat):
        return any(c != chat and uid in g['players'] for c, g in self.games.items())

    def message(self, m):
        text = m.get('text', '')
        if not text.startswith('/') or m.get('from', {}).get('is_bot'):
            return
        uid, chat = str(m['from']['id']), str(m['chat']['id'])
        command = text.split()[0].split('@')
        if len(command) > 1 and command[1].lower() != self.username.lower():
            return
        cmd = command[0]
        if cmd == '/roles':
            self.api.send(chat, '\n'.join(ROLES.values()))
            return
        if cmd == '/myrole':
            match = next((game for game in self.games.values() if uid in game['players'] and game['phase'] != 'lobby'), None)
            if not match:
                self.api.send(chat, 'Вы не участвуете в начавшейся игре.')
            elif m['chat']['type'] != 'private':
                self.api.send(chat, 'Отправьте /myrole в личный чат бота, чтобы сохранить роль в тайне.')
            else:
                p = match['players'][uid]
                defaults(p)
                ability = SPECIAL.get(p['role'])
                extra = f"\nОсталось применений: {ability[1] - p['used']}" if ability else ''
                if p['role']=='agitator': extra += '\nУсиление голоса: ' + ('использовано' if p['boost_used'] else 'доступно')
                self.api.send(chat, ROLES[p['role']] + f"\n❤️ {p['hp']} | Усиление +{p['power']}" + extra)
            return
        if m['chat']['type'] == 'private':
            if cmd == '/start':
                if uid not in self.state['ready']:
                    self.state['ready'].append(uid)
                    self.save()
                self.api.send(chat, '✅ Готово! Теперь добавьте бота в группу и отправьте /newgame.\n\n' + HELP)
            else:
                self.api.send(chat, HELP)
            return
        if m['chat']['type'] not in ('group', 'supergroup'):
            return
        g = self.games.get(chat)
        if cmd in ('/help', '/start'):
            self.api.send(chat, HELP)
        elif cmd == '/newgame':
            if g:
                self.api.send(chat, 'Игра уже существует. /join — вступить, /players — список.')
                return
            self.games[chat] = {'owner': uid, 'phase': 'lobby', 'players': {}}
            self.save()
            self.api.send(chat, '🎭 Набор открыт! От 4 до 20 игроков.\nСначала откройте бота, нажмите /start, затем /join здесь.\n/begin — начать игру.', [[{'text': 'Открыть бота', 'url': f'https://t.me/{self.username}?start=mafia'}]])
        elif not g:
            self.api.send(chat, 'Нет игры. Создайте: /newgame')
        elif cmd == '/players':
            self.api.send(chat, '👥 Участники:\n' + (self.players(g) or 'Пока никого. /join'))
        elif cmd == '/join':
            if g['phase'] != 'lobby':
                self.api.send(chat, 'Игра уже началась.')
            elif uid not in self.state['ready']:
                self.api.send(chat, f'Сначала нажмите /start в личном чате: https://t.me/{self.username}')
            elif uid in g['players']:
                self.api.send(chat, 'Вы уже в игре.')
            elif len(g['players']) >= 20 or self.active_elsewhere(uid, chat):
                self.api.send(chat, 'Набор заполнен либо вы уже участвуете в другой игре.')
            elif self.safe_send(uid, '✅ Вы присоединились к игре. Ожидайте раздачи ролей.'):
                g['players'][uid] = {'name': m['from'].get('first_name', 'Игрок')[:40] + ' ·' + uid[-4:], 'alive': True, 'role': 'citizen'}
                self.save()
                self.api.send(chat, f"✅ Игрок принят. Всего: {len(g['players'])}/20")
            else:
                self.api.send(chat, 'Не могу написать вам. Откройте личный чат бота и нажмите /start.')
        elif cmd == '/leave':
            if g['phase'] == 'lobby':
                g['players'].pop(uid, None)
                self.save()
                self.api.send(chat, 'Вы вышли из набора.')
            else:
                self.api.send(chat, 'После начала выйти нельзя. Без ночного хода включается защита.')
        elif cmd in ('/begin', '/stop'):
            if not self.authorized(chat, uid, g):
                self.api.send(chat, 'Команда доступна создателю игры и администраторам.')
                return
            if cmd == '/stop':
                del self.games[chat]
                self.save()
                self.api.send(chat, 'Игра отменена. /newgame — создать новую.')
            elif g['phase'] != 'lobby':
                self.api.send(chat, 'Игра уже началась.')
            elif len(g['players']) < 4:
                self.api.send(chat, 'Нужно минимум 4 игрока.')
            else:
                # Verify private delivery before any roles are exposed.
                failed = [p['name'] for u, p in g['players'].items() if not self.safe_send(u, '🎭 Начинаем игру. Сейчас придёт ваша роль.')]
                if failed:
                    self.api.send(chat, 'Запуск отменён: откройте личный чат бота: ' + ', '.join(failed))
                    return
                setup(g['players'])
                failed = False
                for u, p in g['players'].items():
                    info = ROLES[p['role']]
                    if p['role']=='hunter':
                        info += '\nВаша тайная цель: ' + g['players'][p['prey']]['name']
                    failed |= not self.safe_send(u, 'Ваша роль: ' + info)
                if failed:
                    del self.games[chat]
                    self.save()
                    self.api.send(chat, 'Раздать все роли не удалось. Игра отменена. Создайте новую: /newgame')
                    return
                g['round'] = 1
                self.phase(chat, g, 'night')

    def run(self):
        self.username = self.api.call('getMe')['username']
        self.api.call('deleteWebhook', drop_pending_updates=False)
        self.api.call('setMyCommands', commands=[{'command': c, 'description': d} for c, d in [('newgame','Новая игра'),('join','Вступить'),('leave','Выйти из набора'),('begin','Начать'),('players','Игроки'),('stop','Отменить'),('help','Правила'),('roles','Все 20 ролей'),('myrole','Моя тайная роль')]])
        logging.info('Бот запущен: @%s', self.username)
        while True:
            try:
                self.tick()
                updates = self.api.call('getUpdates', offset=self.state['offset'], timeout=2, allowed_updates=['message', 'callback_query'])
                for update in updates:
                    try:
                        if 'callback_query' in update:
                            self.callback(update['callback_query'])
                        elif 'message' in update:
                            self.message(update['message'])
                    except Exception as exc:
                        logging.warning('Ошибка обработки: %s', type(exc).__name__)
                    self.state['offset'] = update['update_id'] + 1
                    self.save()
            except KeyboardInterrupt:
                self.save()
                return
            except Exception as exc:
                logging.warning('Повтор подключения: %s', type(exc).__name__)
                time.sleep(3)


class SurvivalBot(Bot):
    def players(self, game):
        return '\n'.join(f"{p['name']} — ❤️ {p.get('hp', 100)}" for p in game['players'].values() if p['alive'])

    def buttons(self, chat, game, actor=None):
        rows = []
        for uid, p in game['players'].items():
            if p['alive'] and uid != actor:
                rows.append([{'text': '⚔️ ' + p['name'], 'callback_data': f"v:{chat}:{game['nonce']}:{uid}"}])
        rows += [[{'text': '🛡 Защита', 'callback_data': f"v:{chat}:{game['nonce']}:guard"}], [{'text': '🎒 Искать припасы', 'callback_data': f"v:{chat}:{game['nonce']}:loot"}]]
        p = game['players'][actor]
        ability = SPECIAL.get(p['role'])
        if ability and p.get('used',0) < ability[1]:
            kind,limit=ability
            if kind in TARGETED:
                for uid,target in game['players'].items():
                    if target['alive'] and uid!=actor:
                        rows.append([{'text':LABELS[kind] + ': ' + target['name'], 'callback_data':f"v:{chat}:{game['nonce']}:{kind}~{uid}"}])
            else:
                rows.append([{'text':LABELS[kind], 'callback_data':f"v:{chat}:{game['nonce']}:{kind}"}])
        return rows

    def phase(self, chat, game, phase):
        for p in game['players'].values():
            defaults(p)
            if phase=='night' and p['alive'] and p['role']=='mutant':
                p['hp']=min(100,p['hp']+5)
        game.update(phase=phase, nonce=secrets.token_hex(4), votes={}, deadline=time.time() + {'night': self.night, 'discuss': self.discuss, 'vote': self.voting}[phase])
        self.save()
        if phase == 'night':
            self.safe_send(chat, f"🌑 Раунд {game['round']}. Ночь: {self.night} сек.\nВыбирайте действие в личном чате. Без хода — защита.")
            for uid, p in game['players'].items():
                if p['alive']:
                    self.safe_send(uid, f"❤️ {p['hp']} | Усиление атаки: +{p['power']}\nВыберите: атаковать, защищаться или искать припасы. Последний выбор учитывается.", self.buttons(chat, game, uid))
        elif phase == 'discuss':
            for uid,p in game['players'].items():
                if p['alive'] and p['role']=='agitator' and not p['boost_used']:
                    self.safe_send(uid, '📢 До начала голосования можно один раз усилить свой голос. Это раскроет ваше участие в агитации.', [[{'text':'📢 Удвоить голос', 'callback_data':f"v:{chat}:{game['nonce']}:boost"}]])
            self.safe_send(chat, f'☀️ Обсуждение: {self.discuss} сек. Договаривайтесь и заключайте временные союзы.\n' + self.players(game))
        else:
            rows = [[{'text': p['name'], 'callback_data': f"v:{chat}:{game['nonce']}:{u}"}] for u,p in game['players'].items() if p['alive']]
            rows.append([{'text': 'Воздержаться', 'callback_data': f"v:{chat}:{game['nonce']}:0"}])
            self.safe_send(chat, f'🗳 Совет арены: {self.voting} сек. Выберите, кто потеряет 35 здоровья. При ничьей наказания нет.', rows)

    def callback(self, q):
        answer = 'Кнопка устарела или ход недоступен.'
        parts = q.get('data', '').split(':')
        uid = str(q['from']['id'])
        announcement = None
        if len(parts) == 4 and parts[0] == 'v':
            _, chat, nonce, target = parts
            g = self.games.get(chat)
            if g and g.get('nonce') == nonce and time.time() < g['deadline']:
                p = g['players'].get(uid)
                if p and p['alive']:
                    defaults(p)
                    if g['phase']=='discuss' and target=='boost' and p['role']=='agitator' and not p['boost_used']:
                        p.update(boost_used=True,boosted=True)
                        announcement = p['name'] + ': 📢 мой голос на ближайшем совете считается за два!'
                        self.save()
                        answer = 'Усиление активировано.'
                    elif g['phase']=='night' and valid_action(g['players'],uid,target):
                        g['votes'][uid]=target
                        self.save()
                        answer = 'Выбор принят. Можно изменить до конца ночи.'
                    elif g['phase']=='vote' and (target=='0' or target in g['players'] and g['players'][target]['alive'] and target!=uid):
                        g['votes'][uid]=target
                        self.save()
                        answer = 'Голос принят.'
        self.api.call('answerCallbackQuery', callback_query_id=q['id'], text=answer)
        if announcement:
            self.safe_send(chat,announcement)

    def finish(self, chat, game):
        alive = [p for p in game['players'].values() if p['alive']]
        if len(alive) > 1:
            return False
        result = '🏆 Выжил сильнейший: ' + alive[0]['name'] if alive else '💀 Арена забрала всех. Победителя нет.'
        roles = '\n'.join(f"{p['name']}: {ROLES[p['role']]}" for p in game['players'].values())
        del self.games[chat]
        self.save()
        self.safe_send(chat, result + '\n\nТайные роли:\n' + roles + '\n\n/newgame — реванш')
        return True

    def tick(self):
        for chat, g in list(self.games.items()):
            if g['phase'] == 'lobby' or time.time() < g['deadline']:
                continue
            if g['phase'] == 'discuss':
                self.phase(chat, g, 'vote')
                continue
            ps, votes = g['players'], g['votes']
            alive = {u:p for u,p in ps.items() if p['alive']}
            if g['phase'] == 'night':
                hazard,notes = resolve_night(g)
                self.save()
                for uid,text in notes:
                    self.safe_send(uid,text)
                report = [f"🌅 Итоги ночи. Урон арены каждому: {hazard}."]
                for p in alive.values():
                    report.append(f"{p['name']}: ❤️ {p['hp']}" + (' — выбыл' if not p['alive'] else ''))
                self.safe_send(chat, '\n'.join(report))
                if not self.finish(chat,g):
                    self.phase(chat,g,'discuss')
            else:
                target,damage = council(g)
                self.save()
                if target:
                    p = ps[target]
                    self.safe_send(chat, f"⚖️ {p['name']}: −{damage} здоровья, осталось {p['hp']}." + (' Выбыл.' if not p['alive'] else ''))
                else:
                    self.safe_send(chat,'⚖️ Совет никого не наказал.')
                if not self.finish(chat,g):
                    g['round'] += 1
                    self.phase(chat,g,'night')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token = os.getenv('BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Укажите BOT_TOKEN в переменных окружения. См. README.md')
    SurvivalBot(API(token), os.getenv('STATE_PATH', 'data/state.json')).run()
