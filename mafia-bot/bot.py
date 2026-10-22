"""Telegram Mafia, Python 3.11+, standard library only."""
import payments
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

SHOP = {
    'medkit': ('consumable', '🩹 Аптечка: +20 HP', 200),
    'stim': ('consumable', '💉 Стимулятор: +5 к атаке до конца игры', 250),
    'antidote': ('consumable', '🧪 Антидот: снять текущие отравления', 150),
    'survivor': ('title', 'Выживший', 100),
    'raider': ('title', 'Покоритель арены', 300),
    'legend': ('title', 'Гроза арены', 700),
    'fire': ('badge', '🔥 Огонь', 150),
    'wolf': ('badge', '🐺 Волк', 250),
    'diamond': ('badge', '💎 Бриллиант', 500),
}


def cosmetics(account):
    owned = account.get('inventory', [])
    selected = account.get('equipped', {})
    return ' · '.join(SHOP[item][1] for kind in ('title', 'badge')
                      if (item := selected.get(kind)) in SHOP and item in owned and SHOP[item][0] == kind)


HELP = '''🔥 Выживает сильнейший
/start — набор и автоматический старт через 90 секунд
/newgame — новая арена
/join — вступить
/leave — выйти до старта
/begin — начать (4–20 игроков)
/players — здоровье участников
/roles — все 20 ролей
/myrole — ваша роль и оставшиеся способности
/stars — купить коины за Stars
/terms — условия покупки
/paysupport — помощь по оплате
/use код — использовать аптечку, стимулятор или антидот
/shop — магазин
/buy код — купить предмет
/inventory — ваши покупки
/equip код — надеть предмет
/unequip — снять украшения
/transfer сумма — перевод ответом на сообщение
/transfer ID сумма — перевод по Telegram ID
/balance — баланс коинов
/profile — победы и награды
/top — лучшие игроки
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
        self.discuss = 60
        self.voting = 45

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


    def update_lobby(self, chat, game, status=None):
        names = '\n'.join(f"{i}. {p['name']}" for i, p in enumerate(game['players'].values(), 1))
        if status is None:
            if 'autostart_at' in game:
                stamp = time.strftime('%H:%M:%S UTC', time.gmtime(game['autostart_at']))
                status = f'⏳ Автостарт через 90 секунд после /start (в {stamp}). Нужно минимум 4 игрока.'
            else:
                status = 'Набор открыт. /start — автостарт через 90 секунд; /begin — начать.'
        text = f"🎭 Участники: {len(game['players'])}/20\n" + (names or 'Пока никто не присоединился.') + '\n\n' + status + '\n/join — вступить · /leave — выйти\nСначала нажмите /start в личном чате бота.'
        keyboard = {'inline_keyboard': [[{'text': 'Открыть бота', 'url': f'https://t.me/{self.username}?start=mafia'}]]}
        if text == game.get('lobby_text'):
            return
        mid = game.get('lobby_message_id')
        if mid:
            try:
                self.api.call('editMessageText', chat_id=chat, message_id=mid, text=text, reply_markup=keyboard)
            except RuntimeError:
                logging.warning('Не удалось обновить список участников в чате %s', chat)
                return
        else:
            result = self.api.send(chat, text, keyboard['inline_keyboard'])
            if isinstance(result, dict) and 'message_id' in result:
                game['lobby_message_id'] = result['message_id']
        game['lobby_text'] = text
        self.save()


    def use_consumable(self, m, uid, chat):
        args = m.get('text', '').split()
        item = args[1].lower() if len(args) == 2 else ''
        if item not in SHOP or SHOP[item][0] != 'consumable':
            self.api.send(chat, 'Используйте /use medkit, /use stim или /use antidote. Описание: /shop')
            return
        match = next(((c, g) for c, g in self.games.items() if uid in g['players'] and g['phase'] != 'lobby'), None)
        if not match:
            self.api.send(chat, 'Предмет можно использовать только в начавшейся игре.')
            return
        game_chat, game = match
        player = game['players'][uid]
        if not player['alive'] or game['phase'] != 'night' or time.time() >= game['deadline']:
            self.api.send(chat, 'Предмет доступен только живому игроку до окончания ночи.')
            return
        if player.get('consumable_used'):
            self.api.send(chat, 'Вы уже использовали расходник в этой игре. Лимит: один за игру.')
            return
        stock = self.state.get('accounts', {}).get(uid, {}).get('consumables', {})
        if stock.get(item, 0) < 1:
            self.api.send(chat, 'Нет этого предмета. Купить: /buy ' + item)
            return
        if item == 'medkit':
            if player['hp'] >= 100:
                self.api.send(chat, 'Здоровье уже полное. Аптечка сохранена.')
                return
            player['hp'] = min(100, player['hp'] + 20)
            effect = f"Здоровье: {player['hp']}/100."
        elif item == 'stim':
            if player.get('power', 0) >= 20:
                self.api.send(chat, 'Усиление уже максимальное. Стимулятор сохранён.')
                return
            player['power'] = min(20, player.get('power', 0) + 5)
            effect = f"Усиление атаки: +{player['power']} до конца игры (может быть украдено ролью Вор)."
        else:
            if not player.get('poison'):
                self.api.send(chat, 'Вы не отравлены. Антидот сохранён.')
                return
            player['poison'] = []
            effect = 'Текущие отравления сняты. Новое отравление этой ночью всё ещё возможно.'
        stock[item] -= 1
        player['consumable_used'] = True
        self.save()
        self.safe_send(chat, '✅ Предмет использован. ' + effect)

    def transfer(self, m, uid, chat, unlimited):
        args = m.get('text', '').split()
        reply_user = m.get('reply_to_message', {}).get('from', {})
        if len(args) == 2 and reply_user:
            target, amount_text = str(reply_user['id']), args[1]
            if reply_user.get('is_bot'):
                self.api.send(chat, 'Нельзя передавать коины ботам.')
                return
        elif len(args) == 3 and args[1].isascii() and args[1].isdigit():
            target, amount_text = str(int(args[1])), args[2]
        else:
            self.api.send(chat, 'Ответьте на сообщение игрока: /transfer 100\\nИли укажите Telegram ID: /transfer 123456789 100\\nСвой ID можно посмотреть в /profile.')
            return
        if not amount_text.isascii() or not amount_text.isdigit() or len(amount_text) > 7 or not 1 <= int(amount_text) <= 1000000:
            self.api.send(chat, 'Сумма должна быть целым числом от 1 до 1000000.')
            return
        amount = int(amount_text)
        if target == uid:
            self.api.send(chat, 'Нельзя перевести коины самому себе.')
            return
        accounts = self.state.setdefault('accounts', {})
        known = set(accounts) | set(self.state.get('ready', []))
        known.update(u for g in self.games.values() for u in g['players'])
        if target not in known:
            self.api.send(chat, 'Игрок ещё не зарегистрирован. Пусть сначала нажмёт /start в личном чате бота.')
            return
        if 'message_id' not in m:
            self.api.send(chat, 'Не удалось определить сообщение перевода. Отправьте команду заново.')
            return
        key = f"{chat}:{m['message_id']}"
        ledger = self.state.setdefault('coin_transfers', {})
        if key in ledger:
            self.safe_send(chat, 'Этот перевод уже выполнен. Повторного списания нет.')
            return
        sender = accounts.get(uid, {'coins': 0, 'wins': 0, 'games': 0})
        if not unlimited and sender['coins'] < amount:
            self.api.send(chat, f"Недостаточно коинов. Баланс: {sender['coins']}.")
            return
        # Commit both balances and the receipt in one atomic state-file replacement.
        import copy
        previous = copy.deepcopy(self.state)
        try:
            sender = accounts.setdefault(uid, sender)
            recipient = accounts.setdefault(target, {'coins': 0, 'wins': 0, 'games': 0})
            if not unlimited:
                sender['coins'] -= amount
            recipient['coins'] += amount
            ledger[key] = {'from': uid, 'to': target, 'amount': amount, 'created': time.time()}
            self.save()
        except Exception:
            self.state = previous
            self.games = self.state['games']
            raise
        balance = '∞' if unlimited else sender['coins']
        self.safe_send(chat, f"✅ Передано {amount} 🪙 игроку ID {target}.\\nВаш баланс: {balance}. Комиссия: 0.")

    def active_elsewhere(self, uid, chat):
        return any(c != chat and uid in g['players'] for c, g in self.games.items())

    def message(self, m):
        if payments.delivery(self, m):
            return
        text = m.get('text', '')
        if not text.startswith('/') or m.get('from', {}).get('is_bot'):
            return
        uid, chat = str(m['from']['id']), str(m['chat']['id'])
        if not self.state.get('coin_owner_id') and m['from'].get('username', '').lower() == 'spaiki29':
            self.state['coin_owner_id'] = uid
            self.save()
        unlimited = self.state.get('coin_owner_id') == uid
        command = text.split()[0].split('@')
        if len(command) > 1 and command[1].lower() != self.username.lower():
            return
        cmd = command[0]
        if cmd == '/use':
            self.use_consumable(m, uid, chat)
            return
        if cmd == '/transfer':
            self.transfer(m, uid, chat, unlimited)
            return
        if payments.command(self, m, cmd):
            return
        if cmd in ('/shop', '/buy', '/inventory', '/equip', '/unequip'):
            accounts = self.state.setdefault('accounts', {})
            account = accounts.setdefault(uid, {'coins': 0, 'wins': 0, 'games': 0})
            owned = account.setdefault('inventory', [])
            stock = account.setdefault('consumables', {})
            if cmd == '/shop':
                lines = [f"{label} — {price} 🪙 · код: {item}" + (f' · в рюкзаке: {stock.get(item, 0)}' if kind == 'consumable' else ' ✅ Куплено' if item in owned else '') for item, (kind, label, price) in SHOP.items()]
                self.api.send(chat, '🛍 Магазин арены\n' + '\n'.join(lines) + f"\n\nБаланс: {'∞' if unlimited else account['coins']} 🪙\nНажмите на товар ниже, чтобы купить\nПополнить за Stars: /stars\nНадеть: /equip fire\nТитулы и значки постоянные. Расходники одноразовые: /use код. Только ночью, максимум один расходник за игру (включая владельца).", [[{'text': f'{label} · {price} 🪙', 'callback_data': f'shop:buy:{item}'}] for item, (kind, label, price) in SHOP.items()])
            elif cmd == '/inventory':
                lines = [f"{SHOP[item][1]} · /equip {item}" for item in owned if item in SHOP]
                lines += [f'{SHOP[item][1]} ×{count} · /use {item}' for item, count in stock.items() if item in SHOP and count > 0]
                self.api.send(chat, '🎒 Ваши покупки\n' + ('\n'.join(lines) or 'Пока пусто. Откройте /shop') + '\nНадето: ' + (cosmetics(account) or 'ничего'))
            elif cmd == '/unequip':
                account['equipped'] = {}
                self.save()
                self.api.send(chat, 'Украшения сняты. Покупки остались в /inventory.')
            else:
                args = text.split()
                if len(args) != 2 or args[1].lower() not in SHOP:
                    self.api.send(chat, 'Укажите код предмета из /shop. Пример: /buy fire или /equip fire')
                    return
                item = args[1].lower()
                kind, label, price = SHOP[item]
                if cmd == '/buy':
                    receipt = f"{chat}:{m['message_id']}" if 'message_id' in m else None
                    if receipt and receipt in self.state.get('shop_receipts', {}):
                        self.api.send(chat, 'Эта покупка уже выполнена. /inventory — ваши предметы.')
                        return
                    if kind != 'consumable' and item in owned:
                        self.api.send(chat, 'Этот предмет уже куплен. Надеть: /equip ' + item)
                        return
                    if not unlimited and account['coins'] < price:
                        self.api.send(chat, f"Не хватает коинов: нужно {price}, у вас {account['coins']}.")
                        return
                    if not unlimited:
                        account['coins'] -= price
                    if kind == 'consumable':
                        stock[item] = stock.get(item, 0) + 1
                    else:
                        owned.append(item)
                    if receipt:
                        self.state.setdefault('shop_receipts', {})[receipt] = item
                    self.save()
                    self.api.send(chat, f"✅ Куплено: {label}. Баланс: {'∞' if unlimited else account['coins']} 🪙.\n" + (f"Использовать: /use {item}" if kind == 'consumable' else f"Надеть: /equip {item}"))
                elif kind == 'consumable':
                    self.api.send(chat, 'Расходники используются командой /use ' + item)
                elif item not in owned:
                    self.api.send(chat, 'Сначала купите предмет: /buy ' + item)
                else:
                    account.setdefault('equipped', {})[kind] = item
                    self.save()
                    self.api.send(chat, '✅ Надето: ' + label + '. Посмотреть: /profile')
            return
        if cmd in ('/balance', '/profile', '/top'):
            accounts = self.state.get('accounts', {})
            account = accounts.get(uid, {})
            if cmd == '/top':
                ranked = sorted(accounts.items(), key=lambda item: (-item[1].get('wins', 0), -item[1].get('coins', 0), item[0]))
                ranked = [(u, a) for u, a in ranked if a.get('wins', 0) > 0][:10]
                lines = [f"{i}. {a['name']} {cosmetics(a)} — 🏆 {a['wins']} · 🪙 {a['coins']}" for i, (u, a) in enumerate(ranked, 1)]
                self.api.send(chat, '🏆 Топ игроков\n' + ('\n'.join(lines) or 'Побед пока нет. Станьте первым!'))
            elif cmd == '/balance':
                self.api.send(chat, f"🪙 Ваш баланс: {'∞' if unlimited else account.get('coins', 0)} коинов.\nПобеда: +100. Это игровые очки без денежной стоимости.")
            else:
                wins = account.get('wins', 0)
                badges = [name for count, name in [(1, '🥇 Первая победа'), (5, '🏅 Чемпион арены'), (10, '👑 Легенда арены')] if wins >= count]
                self.api.send(chat, f"👤 Ваш профиль\n🆔 {uid}\n{cosmetics(account)}\n🏆 Победы: {wins}\n🎮 Завершённые игры: {account.get('games', 0)}\n🪙 Коины: {'∞ (владелец)' if unlimited else account.get('coins', 0)}\n\nНаграды:\n" + ('\n'.join(badges) or 'Пока нет — выиграйте первую игру!'))
            return
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
        if cmd == '/start':
            if not g:
                g = {'owner': uid, 'phase': 'lobby', 'players': {}}
                self.games[chat] = g
            if g['phase'] != 'lobby':
                self.api.send(chat, 'Игра уже началась.')
                return
            if not self.authorized(chat, uid, g):
                self.api.send(chat, 'Команда доступна создателю игры и администраторам.')
                return
            if 'autostart_at' in g:
                self.update_lobby(chat, g)
                return
            g['autostart_at'] = time.time() + 90
            self.save()
            self.update_lobby(chat, g)
        elif cmd == '/help':
            self.api.send(chat, HELP)
        elif cmd == '/newgame':
            if g:
                self.api.send(chat, 'Игра уже существует. /join — вступить, /players — список.')
                return
            self.games[chat] = {'owner': uid, 'phase': 'lobby', 'players': {}}
            self.save()
            self.update_lobby(chat, self.games[chat])
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
                self.update_lobby(chat, g)
            else:
                self.api.send(chat, 'Не могу написать вам. Откройте личный чат бота и нажмите /start.')
        elif cmd == '/leave':
            if g['phase'] == 'lobby':
                g['players'].pop(uid, None)
                self.save()
                self.update_lobby(chat, g)
            else:
                self.api.send(chat, 'После начала выйти нельзя. Без ночного хода включается защита.')
        elif cmd in ('/begin', '/stop'):
            if not self.authorized(chat, uid, g):
                self.api.send(chat, 'Команда доступна создателю игры и администраторам.')
                return
            if cmd == '/stop':
                if g['phase'] == 'lobby':
                    self.update_lobby(chat, g, '❌ Набор отменён.')
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
                self.update_lobby(chat, g, '✅ Набор завершён. Игра началась!')
                g['round'] = 1
                self.phase(chat, g, 'night')

    def run(self):
        self.username = self.api.call('getMe')['username']
        self.api.call('deleteWebhook', drop_pending_updates=False)
        self.api.call('setMyCommands', commands=[{'command': c, 'description': d} for c, d in [('start','Набор и автостарт через 90 секунд'),('newgame','Новая игра'),('join','Вступить'),('leave','Выйти из набора'),('begin','Начать'),('players','Игроки'),('stop','Отменить'),('help','Правила'),('roles','Все 20 ролей'),('stars','Купить коины за Stars'),('terms','Условия покупки'),('paysupport','Помощь по оплате'),('use','Использовать предмет: /use medkit'),('shop','Магазин за коины'),('buy','Купить: /buy fire'),('inventory','Ваши покупки'),('equip','Надеть: /equip fire'),('unequip','Снять украшения'),('transfer','Передать коины: /transfer 100'),('balance','Баланс коинов'),('profile','Победы и награды'),('top','Лучшие игроки'),('myrole','Моя тайная роль')]])
        logging.info('Бот запущен: @%s', self.username)
        while True:
            try:
                self.tick()
                updates = self.api.call('getUpdates', offset=self.state['offset'], timeout=2, allowed_updates=['message', 'callback_query', 'pre_checkout_query'])
                for update in updates:
                    try:
                        if 'pre_checkout_query' in update:
                            payments.precheckout(self, update['pre_checkout_query'])
                        elif 'callback_query' in update:
                            self.callback(update['callback_query'])
                        elif 'message' in update:
                            self.message(update['message'])
                    except Exception as exc:
                        if 'pre_checkout_query' in update or any(k in update.get('message', {}) for k in ('successful_payment', 'refunded_payment')):
                            raise
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
        voting = self.voting
        game['phase_started'] = time.time()
        game.update(phase=phase, nonce=secrets.token_hex(4), votes={}, deadline=time.time() + {'night': self.night, 'discuss': self.discuss, 'vote': voting}[phase])
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
            self.safe_send(chat, f'🗳 Совет арены: {voting} сек. Выберите, кто потеряет 35 здоровья. При ничьей наказания нет.', rows)

    def callback(self, q):
        if payments.callback(self, q):
            return
        data = q.get('data', '')
        if data.startswith('shop:'):
            parts = data.split(':')
            message = q.get('message', {})
            if len(parts) != 3 or parts[1] != 'buy' or parts[2] not in SHOP or not message.get('chat') or q.get('from', {}).get('is_bot'):
                self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Товар недоступен. Откройте /shop.')
                return
            # Each Telegram callback is one purchase; replay uses the same receipt.
            self.message({'text': '/buy ' + parts[2], 'from': q['from'],
                          'chat': message['chat'], 'message_id': 'shop-' + q['id']})
            self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Результат покупки — в сообщении бота.')
            return
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
        # Persist the reward and game removal together to prevent double credit.
        if self.games.get(chat) is not game:
            return True
        alive = [(uid, p) for uid, p in game['players'].items() if p['alive']]
        if len(alive) > 1:
            return False
        accounts = self.state.setdefault('accounts', {})
        for uid, p in game['players'].items():
            account = accounts.setdefault(uid, {'coins': 0, 'wins': 0, 'games': 0})
            account['name'] = p['name']
            account['games'] += 1
        if alive:
            uid, winner = alive[0]
            account = accounts[uid]
            account['wins'] += 1
            bonus, badge = {1: (0, '🥇 Первая победа'), 5: (250, '🏅 Чемпион арены'), 10: (500, '👑 Легенда арены')}.get(account['wins'], (0, None))
            account['coins'] += 100 + bonus
            result = '🏆 Выжил сильнейший: ' + winner['name']
            result += f"\n🪙 Награда: +100 коинов. Баланс: {account['coins']}."
            if badge:
                result += '\nНовая награда: ' + badge
                if bonus:
                    result += f' · бонус +{bonus} коинов!'
        else:
            result = '💀 Арена забрала всех. Победителя нет. Коины не начислены.'
        roles = '\n'.join(f"{p['name']}: {ROLES[p['role']]}" for p in game['players'].values())
        del self.games[chat]
        self.save()
        self.safe_send(chat, result + '\n\nТайные роли:\n' + roles + '\n\n/profile — награды · /top — рейтинг\n/start — реванш')
        return True

    def tick(self):
        for chat, g in list(self.games.items()):
            if g['phase'] == 'lobby':
                if 'autostart_at' in g and time.time() >= g['autostart_at']:
                    del g['autostart_at']
                    self.save()
                    if len(g['players']) < 4:
                        self.update_lobby(chat, g, '⏳ Автостарт отменён: меньше 4 игроков. /start — новый отсчёт 90 секунд.')
                        self.safe_send(chat, '⏳ Автостарт отменён: нужно минимум 4 игрока. Набор остаётся открытым. /start — запустить новый отсчёт на 90 секунд.')
                    else:
                        self.message({'text': '/begin', 'from': {'id': int(g['owner'])},
                                      'chat': {'id': int(chat), 'type': 'group'}})
                continue
            if time.time() < g['deadline']:
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
