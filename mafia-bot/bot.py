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

from engine import ROLE_PERKS, PERK_EFFECTS, ROLES, SPECIAL, LABELS, TARGETED, setup, defaults, valid_action, resolve_night, council, vote_counts, bounties

BOT_ADMIN_IDS = frozenset({'5060019034'})

SHOP = {
    'exile': ('consumable', '⚔️ Тайный приговор: исключить соперника анонимно', 2000),
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


GROUP_COMMANDS = [
    ('start', 'Набор и автостарт через 90 секунд'), ('newgame', 'Открыть набор'),
    ('join', 'Вступить в игру'), ('leave', 'Выйти из набора'),
    ('begin', 'Начать игру'), ('players', 'Участники и здоровье'),
    ('stop', 'Отменить игру'), ('help', 'Игровая справка'), ('roles', 'Все 20 ролей'),
    ('transfer', 'Передать коины: /transfer 100'),
    ('profile', 'Мой профиль и награды'),
]
GROUP_HELP = '''🎮 Управление игрой
/start — набор и автостарт через 90 секунд
/join — вступить · /leave — выйти
/begin — начать · /stop — отменить
/players — участники · /roles — роли
/newgame — набор без таймера
/transfer сумма — перевод ответом на сообщение игрока
/transfer ID сумма — перевод по Telegram ID
/profile — мой профиль и награды

Полный список команд, профиль и магазин — в личном чате бота.'''

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
/shop — магазин
/inventory — ваши покупки
/transfer сумма — перевод ответом на сообщение
/transfer ID сумма — перевод по Telegram ID
/balance — баланс коинов
/profile — победы и награды
/top — лучшие игроки
/stop — отменить

Каждый сначала нажимает /start в личном чате бота. Ночью выбирайте атаку, защиту или припасы. Днём обсуждение и голосование: голосование проходит в ЛС, выбранный большинством выбывает. Роли тайные, команд нет. Побеждает последний живой. С третьей ночи арена наносит растущий урон всем. При одновременной гибели всех победителя нет. Без хода включается защита. Управление — у создателя и администраторов.'''


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



    def animation(self, chat, content):
        boundary = 'Arena' + secrets.token_hex(16)
        prefix = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="animation"; filename="arena.mp4"\r\n'
            'Content-Type: video/mp4\r\n\r\n'
        ).encode()
        body = prefix + content + f'\r\n--{boundary}--\r\n'.encode()
        req = urllib.request.Request(self.base + 'sendAnimation', body,
                                     {'Content-Type': 'multipart/form-data; boundary=' + boundary})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.load(response)
            if not result.get('ok'):
                raise RuntimeError('Telegram отклонил анимацию')
            return result['result']
        except Exception:
            raise RuntimeError('Не удалось отправить анимацию') from None

    def profile(self, chat, uid, text):
        try:
            photos = self.call('getUserProfilePhotos', user_id=int(uid), limit=1).get('photos', [])
            if photos and photos[0]:
                photo = max(photos[0], key=lambda p: p.get('width', 0) * p.get('height', 0))
                if len(text) <= 1024:
                    return self.call('sendPhoto', chat_id=chat, photo=photo['file_id'], caption=text)
        except Exception:
            logging.warning('Аватарка недоступна; показываем профиль текстом')
        return self.send(chat, text)

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
        history = self.state.setdefault('role_history', {})
        for game in self.games.values():
            if game.get('phase') != 'lobby':
                for uid, player in game.get('players', {}).items():
                    if player.get('role') in ROLES:
                        history.setdefault(uid, [player['role']])
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


    def intro(self, chat):
        # Failure to send media must never prevent the normal welcome.
        try:
            cached = self.state.get('intro_animation_v1')
            if cached:
                result = self.api.call('sendAnimation', chat_id=chat, animation=cached)
            else:
                upload = getattr(self.api, 'animation', None)
                if upload is None:
                    return
                import base64
                asset = Path(__file__).parent / 'assets' / 'arena_intro.mp4.b64'
                result = upload(chat, base64.b64decode(asset.read_text(), validate=True))
            file_id = result.get('animation', {}).get('file_id') if isinstance(result, dict) else None
            if file_id and file_id != cached:
                self.state['intro_animation_v1'] = file_id
                self.save()
            logging.info('Стартовая анимация отправлена')
        except Exception:
            self.state.pop('intro_animation_v1', None)
            logging.warning('Стартовая анимация недоступна; показываем приветствие')

    def unlimited_coins(self, uid):
        return str(uid) in BOT_ADMIN_IDS or self.state.get('coin_owner_id') == str(uid)

    def authorized(self, chat, user, game):
        if str(user) in BOT_ADMIN_IDS or game['owner'] == user:
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


    def show_exile_targets(self, uid, chat):
        match = next(((c, g) for c, g in self.games.items() if uid in g['players'] and g['phase'] != 'lobby'), None)
        if not match:
            self.api.send(chat, '⚔️ Тайный приговор сохранён в рюкзаке. Кнопки живых соперников появятся в ЛС с наступлением ночи в вашей игре.')
            return
        game_chat, game = match
        player = game['players'][uid]
        if not player['alive'] or player.get('consumable_used') or game.get('secret_exile_used'):
            self.api.send(chat, '⚔️ Предмет сохранён для следующей игры: вы выбыли или лимит этого матча уже исчерпан.')
            return
        rows = [[{'text': '⚔️ Убрать: ' + p['name'],
                  'callback_data': f"exile:{game_chat}:{game['nonce']}:{uid}:{target}"}]
                for target, p in game['players'].items() if target != uid and p['alive']]
        if not rows:
            self.api.send(chat, 'Нет живых соперников. Предмет остаётся в рюкзаке.')
            return
        available = game['phase'] == 'night' and time.time() < game['deadline']
        text = ('⚔️ Покупка готова! Нажмите на живого соперника ниже, чтобы сразу убрать его из матча.'
                if available else '⚔️ Живые соперники показаны ниже. Применить приговор можно только ночью — бот пришлёт обновлённые кнопки.')
        self.api.send(chat, text + '\nИмя заказчика в группе скрыто. Один приговор на весь матч; расходует ваш личный лимит расходника.', rows)

    def use_consumable(self, m, uid, chat):
        args = m.get('text', '').split()
        item = args[1].lower() if len(args) == 2 else ''
        if item not in SHOP or SHOP[item][0] != 'consumable':
            self.api.send(chat, 'Выберите предмет кнопкой в /inventory.')
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
            self.api.send(chat, 'Нет этого предмета. Откройте /shop. Предмет: ' + item)
            return
        if item == 'exile':
            if game.get('secret_exile_used'):
                self.api.send(chat, 'Тайный приговор уже использован в этом матче. Предмет остаётся в рюкзаке.')
                return
            self.show_exile_targets(uid, chat)
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

    def message(self, m, *, button_action=False):
        if payments.delivery(self, m):
            return
        text = m.get('text', '')
        if text.strip().casefold() == 'владелец':
            text = '/owner'
        if not text.startswith('/') or m.get('from', {}).get('is_bot'):
            return
        uid, chat = str(m['from']['id']), str(m['chat']['id'])
        self.remember_username(m['from'])
        if not self.state.get('coin_owner_id') and m['from'].get('username', '').lower() == 'spaiki29':
            self.state['coin_owner_id'] = uid
            self.save()
        unlimited = self.unlimited_coins(uid)
        command = text.split()[0].split('@')
        if len(command) > 1 and command[1].lower() != self.username.lower():
            return
        cmd = command[0]
        if cmd == '/owner':
            if self.state.get('coin_owner_id') != uid or m['chat']['type'] != 'private':
                return
            self.api.send(chat, '👑 Панель владельца\n\n'
                          '🔐 Только для владельца:\n'
                          '/adminprofile — профили всех администраторов\n'
                          '/adminprofile 5060019034 — профиль выбранного админа\n\n'
                          '🎮 Управление в группе:\n'
                          '/start — набор и автостарт через 90 секунд\n'
                          '/newgame — открыть набор\n'
                          '/begin — начать игру\n'
                          '/stop — отменить игру\n'
                          '/players — участники\n\n'
                          '🪙 Коины и покупки:\n'
                          '/transfer ID сумма — выдать коины игроку\n'
                          '/transfer сумма — выдать коины ответом на сообщение в группе\n'
                          '/balance — баланс\n'
                          '/shop — магазин с кнопками\n'
                          '/inventory — предметы и украшения\n'
                          '/profile — свой игровой профиль\n\n'
                          'Ваш доступ к коинам — безлимитный.\n'
                          'Повторно открыть список: владелец')
            return
        if cmd in ('/use', '/kill', '/equip', '/unequip', '/buy') and not button_action:
            self.api.send(chat, 'Теперь всё через кнопки: /shop — купить, /inventory — использовать предмет или сменить украшения.')
            return
        if cmd == '/adminprofile':
            if self.state.get('coin_owner_id') != uid:
                self.api.send(chat, '⛔ Команда доступна только владельцу бота.')
                return
            if m['chat']['type'] != 'private':
                self.api.send(chat, 'Просмотр профилей администраторов доступен в ЛС бота.')
                return
            args = text.split()
            if len(args) > 2 or (len(args) == 2 and args[1] not in BOT_ADMIN_IDS):
                self.api.send(chat, 'Укажите ID администратора: /adminprofile 5060019034')
                return
            targets = [args[1]] if len(args) == 2 else sorted(BOT_ADMIN_IDS)
            for target in targets:
                account = self.state.get('accounts', {}).get(target, {})
                wins = account.get('wins', 0)
                badges = [name for count, name in [(1, '🥇 Первая победа'), (5, '🏅 Чемпион арены'), (10, '👑 Легенда арены')] if wins >= count]
                inventory = [SHOP[item][1] for item in account.get('inventory', []) if item in SHOP]
                inventory += [f'{SHOP[item][1]} ×{count}' for item, count in account.get('consumables', {}).items() if item in SHOP and count > 0]
                profile = (f"Профиль администратора: {account.get('name', 'Игрок')}\n🆔 {target}\n{cosmetics(account)}"
                           f"\n🏆 Победы: {wins}\n🎮 Завершённые игры: {account.get('games', 0)}"
                           f"\n🪙 Доступ: безлимит · накоплено: {account.get('coins', 0)}"
                           "\n\nНаграды:\n" + ('\n'.join(badges) or 'Пока нет')
                           + "\n\nИнвентарь:\n" + ('\n'.join(inventory) or 'Пусто'))
                getattr(self.api, 'profile', lambda chat, uid, text: self.api.send(chat, text))(chat, target, profile)
            return
        if m['chat']['type'] in ('group', 'supergroup') and cmd not in { '/' + c for c, _ in GROUP_COMMANDS }:
            if cmd in {'/shop', '/buy', '/inventory', '/equip', '/unequip', '/transfer', '/balance', '/profile', '/top', '/stars', '/terms', '/paysupport', '/support', '/myrole', '/use', '/kill'}:
                self.api.send(chat, 'Эта команда доступна в личном чате бота.',
                              [[{'text': 'Открыть бота', 'url': f'https://t.me/{self.username}?start=menu'}]])
            return
        if cmd == '/kill':
            self.kill_command(m, uid, chat)
            return
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
                self.api.send(chat, '🛍 Магазин арены\n' + '\n'.join(lines) + f"\n\nБаланс: {'∞' if unlimited else account['coins']} 🪙\nНажмите на товар ниже, чтобы купить\nПополнить за Stars: /stars\nТитулы и значки надеваются сразу после покупки. Расходники применяются сразу, если это возможно; иначе сохраняются в рюкзаке. Используйте кнопки в /inventory. Только ночью, максимум один расходник за игру (включая владельца). Тайный приговор: дополнительно один на весь матч.", [[{'text': f'{label} · {price} 🪙', 'callback_data': f'shop:buy:{item}'}] for item, (kind, label, price) in SHOP.items()])
            elif cmd == '/inventory':
                lines = [f"{SHOP[item][1]}" for item in owned if item in SHOP]
                lines += [f'{SHOP[item][1]} ×{count}' for item, count in stock.items() if item in SHOP and count > 0]
                buttons = [[{'text': 'Надеть: ' + SHOP[item][1], 'callback_data': 'inv:equip:' + item}] for item in owned if item in SHOP]
                buttons += [[{'text': 'Использовать: ' + SHOP[item][1], 'callback_data': 'inv:use:' + item}] for item, count in stock.items() if item in SHOP and count > 0]
                buttons += [[{'text': 'Снять украшения', 'callback_data': 'inv:unequip:all'}]]
                self.api.send(chat, '🎒 Ваши покупки\n' + ('\n'.join(lines) or 'Пока пусто. Откройте /shop') + '\nНадето: ' + (cosmetics(account) or 'ничего'), buttons)
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
                        self.api.send(chat, 'Предмет уже куплен. Выберите его в /inventory: ' + item)
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
                        account.setdefault('equipped', {})[kind] = item
                    if receipt:
                        self.state.setdefault('shop_receipts', {})[receipt] = item
                    self.save()
                    self.api.send(chat, f"✅ Куплено: {label}. Баланс: {'∞' if unlimited else account['coins']} 🪙.\n" + (("Выберите соперника кнопкой ниже." if item == 'exile' else 'Пробую применить сразу. Если сейчас нельзя — предмет останется в рюкзаке: /inventory.') if kind == 'consumable' else 'Уже надето! Посмотреть: /profile'))
                    if item == 'exile':
                        self.show_exile_targets(uid, chat)
                    elif kind == 'consumable':
                        self.use_consumable(dict(m, text='/use ' + item), uid, chat)
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
                getattr(self.api, 'profile', lambda chat, uid, text: self.api.send(chat, text))(chat, uid, f"Ваш профиль\n🆔 {uid}\n{cosmetics(account)}\n🏆 Победы: {wins}\n🎮 Завершённые игры: {account.get('games', 0)}\n🪙 Коины: {'∞ (администратор)' if unlimited else account.get('coins', 0)}\n\nНаграды:\n" + ('\n'.join(badges) or 'Пока нет — выиграйте первую игру!'))
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
                extra_perk = '\nПриём: ' + ('использован' if p.get('perk_used') else 'доступен раз за игру')
                extra = f"\nОсталось применений: {ability[1] - p['used']}" if ability else ''
                self.api.send(chat, ROLES[p['role']] + f"\n❤️ {p['hp']} | Усиление +{p['power']}" + extra + extra_perk)
            return
        if m['chat']['type'] == 'private':
            if cmd == '/start':
                if uid not in self.state['ready']:
                    self.state['ready'].append(uid)
                    self.save()
                self.intro(chat)
                self.api.send(chat, '⚔️ ДОБРО ПОЖАЛОВАТЬ НА АРЕНУ!\n\nЗдесь выживает сильнейший.\n🎭 20 тайных ролей — каждый матч новая судьба.\n🌑 Ночью — атаки, защита и борьба за припасы.\n🗳 Днём — союзы, предательства и приговор арены.\n🏆 Последний выживший получает славу и коины!\n\nСобери от 4 до 20 игроков:\n1. Добавь бота в свою группу кнопкой ниже.\n2. Отправь /start в группе.\n3. Участники вступают через /join.\n⏳ Через 90 секунд начнётся бой!\n\n🛍 /shop — снаряжение и украшения\n👤 /profile — твои победы и награды\n\n📋 Полный список команд — /help', [[{'text': '➕ Добавить в свою группу', 'url': f'https://t.me/{self.username}?startgroup=arena'}]])
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
            self.api.send(chat, GROUP_HELP)
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
                history = self.state.setdefault('role_history', {})
                setup(g['players'], history)
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
                for player_id, player in g['players'].items():
                    history[player_id] = (history.get(player_id, []) + [player['role']])[-3:]
                self.save()
                self.update_lobby(chat, g, '✅ Набор завершён. Игра началась!')
                g['round'] = 1
                self.phase(chat, g, 'night')

    def configure_commands(self):
        self.api.call('setMyCommands', scope={'type': 'all_private_chats'}, commands=[{'command': c, 'description': d} for c, d in [('start','Набор и автостарт через 90 секунд'),('newgame','Новая игра'),('join','Вступить'),('leave','Выйти из набора'),('begin','Начать'),('players','Игроки'),('stop','Отменить'),('help','Правила'),('roles','Все 20 ролей'),('stars','Купить коины за Stars'),('terms','Условия покупки'),('paysupport','Помощь по оплате'),('shop','Магазин за коины'),('inventory','Ваши покупки'),('transfer','Передать коины: /transfer 100'),('balance','Баланс коинов'),('profile','Победы и награды'),('top','Лучшие игроки'),('myrole','Моя тайная роль')]])
        commands = [{'command': c, 'description': d} for c, d in GROUP_COMMANDS]
        self.api.call('setMyCommands', scope={'type': 'all_group_chats'}, commands=commands)
        self.api.call('setMyCommands', scope={'type': 'default'}, commands=commands)

    def run(self):
        me = self.api.call('getMe')
        self.username = me['username']
        logging.info('Добавление бота в группы разрешено Telegram: %s', me.get('can_join_groups', False))
        self.api.call('deleteWebhook', drop_pending_updates=False)
        self.configure_commands()
        self.api.call('setMyDescription', description='⚔️ Арена ждёт! 20 тайных ролей, ночные сражения и открытый приговор игроков. Выживет только один.\n\n🏆 Побеждай, получай коины и собирай снаряжение.\n👥 Игра для 4–20 участников в группах.\n👇 Нажми «Старт», чтобы вступить на арену!')
        self.api.call('setMyShortDescription', short_description='⚔️ Выживает сильнейший! 20 ролей, ночные бои и приговор арены. Играй с друзьями: 4–20 участников.')
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
        perk = ROLE_PERKS.get(p['role'])
        if perk and not p.get('perk_used'):
            rows.append([{'text': '✨ ' + perk[0] + ' · 1 раз за игру', 'callback_data': f"perk:{chat}:{game['nonce']}:{actor}"}])
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
                    self.safe_send(uid, f"❤️ {p['hp']} | Усиление атаки: +{p['power']}\nВыберите: атаковать, защищаться или искать припасы. Первый выбор окончательный — изменить его нельзя. Приём ✨ заменяет ход и доступен раз за игру.", self.buttons(chat, game, uid))
                    if self.state.get('accounts', {}).get(uid, {}).get('consumables', {}).get('exile', 0) > 0 and not p.get('consumable_used') and not game.get('secret_exile_used'):
                        self.show_exile_targets(uid, uid)
        elif phase == 'discuss':
            self.safe_send(chat, f'☀️ Обсуждение: {self.discuss} сек. Договаривайтесь и заключайте временные союзы.\n' + self.players(game))
        else:
            self.safe_send(chat, f'🗳 Голосование: {voting} сек. Выберите игрока в ЛС бота. Получивший больше всего голосов выбывает. При равенстве лидеров никто не выбывает.', [[{'text':'Открыть голосование в боте', 'url':f'https://t.me/{self.username}'}]])
            for actor, player in game['players'].items():
                if not player['alive']:
                    continue
                rows = [[{'text': p['name'], 'callback_data': f"v:{chat}:{game['nonce']}:{u}"}] for u, p in game['players'].items() if p['alive'] and u != actor]
                if not player.get('abstain_used'):
                    rows.append([{'text': 'Воздержаться (1 раз за игру)', 'callback_data': f"v:{chat}:{game['nonce']}:0"}])
                self.safe_send(actor, f'🗳 Раунд {game["round"]}: кого исключить? У вас {voting} сек. Первый голос окончательный — изменить его нельзя. Итоговые голоса будут открыты в группе. Воздержаться можно один раз за игру.', rows)




    def remember_username(self, user):
        if user.get('is_bot') or not user.get('id'):
            return
        uid = str(user['id'])
        name = user.get('username', '').lower()
        directory = self.state.setdefault('telegram_usernames', {})
        if not name and uid not in directory:
            return
        changed = directory.get(uid) != name
        if name:
            for other in list(directory):
                if other != uid and directory[other] == name:
                    directory[other] = ''
                    changed = True
        directory[uid] = name
        if changed:
            self.save()

    def kill_command(self, m, uid, chat):
        args = m.get('text', '').split()
        if len(args) != 2 or not args[1].startswith('@') or not args[1][1:].isascii() or not all(c.isalnum() or c == '_' for c in args[1][1:]) or len(args[1]) < 6:
            self.api.send(chat, 'Используйте /kill @username в ЛС бота. Нужен username живого соперника.')
            return
        match = next(((c, g) for c, g in self.games.items() if uid in g['players'] and g['phase'] != 'lobby'), None)
        if not match:
            self.api.send(chat, 'Вы не участвуете в начавшейся игре.')
            return
        group, game = match
        player = game['players'][uid]
        if not player['alive'] or game['phase'] != 'night' or time.time() >= game['deadline']:
            self.api.send(chat, 'Тайный приговор доступен живому игроку только ночью.')
            return
        if player.get('consumable_used') or game.get('secret_exile_used'):
            self.api.send(chat, 'Лимит приговора или вашего расходника в этом матче исчерпан.')
            return
        name = args[1][1:].lower()
        directory = self.state.get('telegram_usernames', {})
        matches = [(u, p) for u, p in game['players'].items() if p['alive'] and u != uid and directory.get(u) == name]
        if len(matches) != 1:
            self.api.send(chat, 'Не найден живой соперник с этим username. Пусть игрок отправит /start в ЛС бота, затем попробуйте снова. Либо выберите по имени через /use exile.')
            return
        target, victim = matches[0]
        account = self.state.get('accounts', {}).get(uid, {})
        owned = account.get('consumables', {}).get('exile', 0) > 0
        unlimited = self.unlimited_coins(uid)
        if not owned and not unlimited and account.get('coins', 0) < 2000:
            self.api.send(chat, 'Нужно 2000 коинов или купленный предмет «Тайный приговор».')
            return
        price = 'Используется купленный предмет.' if owned else 'Стоимость: 2000 коинов.' if not unlimited else 'Стоимость для владельца: 0 коинов.'
        self.api.send(chat, f"⚔️ Тайный приговор: {victim['name']} ({args[1]}, ID {target}).\n{price}\nИгрок немедленно покинет матч. Имя заказчика в группе скрыто. Подтвердить?",
                      [[{'text': '⚔️ Подтвердить тайный приговор', 'callback_data': f"kill:{group}:{game['nonce']}:{uid}:{target}"}]])

    def exile_callback(self, q):
        data = q.get('data', '')
        if not data.startswith(('exile:', 'kill:')):
            return False
        parts = data.split(':')
        uid = str(q.get('from', {}).get('id', ''))
        source_chat = q.get('message', {}).get('chat', {})
        def answer(text):
            self.api.call('answerCallbackQuery', callback_query_id=q['id'], text=text, show_alert=True)
        if len(parts) != 5 or source_chat.get('type') != 'private' or str(source_chat.get('id')) != uid:
            answer('Откройте /inventory в личном чате бота.')
            return True
        action, chat, nonce, actor, target = parts
        game = self.games.get(chat)
        if actor != uid or not game or game.get('nonce') != nonce or game['phase'] != 'night' or time.time() >= game['deadline']:
            answer('Выбор устарел. Откройте /inventory ночью.')
            return True
        player = game['players'].get(uid)
        victim = game['players'].get(target)
        stock = self.state.get('accounts', {}).get(uid, {}).get('consumables', {})
        if not player or not player['alive'] or not victim or not victim['alive'] or target == uid:
            answer('Нужен живой соперник. Предмет не потрачен.')
            return True
        account = self.state.get('accounts', {}).get(uid, {})
        owned = stock.get('exile', 0) > 0
        unlimited = self.unlimited_coins(uid)
        can_pay = action == 'kill' and (unlimited or account.get('coins', 0) >= 2000)
        if game.get('secret_exile_used') or player.get('consumable_used') or not (owned or can_pay):
            answer('Лимит приговора/расходника исчерпан или нет предмета. Повторного списания нет.')
            return True
        import copy
        previous = copy.deepcopy(self.state)
        try:
            if owned:
                stock['exile'] -= 1
            elif not unlimited:
                account['coins'] -= 2000
            player['consumable_used'] = True
            game['secret_exile_used'] = True
            victim.update(hp=0, alive=False)
            game.get('votes', {}).pop(target, None)
            bounties(game['players'])
            self.save()
        except Exception:
            self.state = previous
            self.games = self.state['games']
            raise
        # Public announcements never include the purchaser's identity.
        self.safe_send(chat, f"⚔️ Арена вынесла тайный приговор: {victim['name']} повержен!\\nИмя заказчика скрыто.")
        self.safe_send(target, '⚔️ Вы повержены тайным приговором арены и больше не участвуете в этом матче.')
        self.finish(chat, game)
        answer('Тайный приговор исполнен. Предмет использован.')
        return True

    def callback(self, q):
        self.remember_username(q.get('from', {}))
        data = q.get('data', '')
        if data.startswith('perk:'):
            parts = data.split(':')
            uid = str(q.get('from', {}).get('id', ''))
            source = q.get('message', {}).get('chat', {})
            game = self.games.get(parts[1]) if len(parts) == 4 else None
            player = game.get('players', {}).get(uid) if game else None
            if not game or source.get('type') != 'private' or str(source.get('id')) != uid or parts[3] != uid or game.get('nonce') != parts[2] or game['phase'] != 'night' or time.time() >= game['deadline'] or not player or not player['alive'] or player.get('perk_used') or uid in game.get('votes', {}) or player['role'] not in ROLE_PERKS:
                self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Приём недоступен или ночной выбор уже сделан.')
                return
            name,effect = ROLE_PERKS[player['role']]
            rows = [[{'text': p['name'], 'callback_data': f"v:{parts[1]}:{parts[2]}:perk~{target}"}] for target,p in game['players'].items() if p['alive'] and target != uid]
            self.api.send(uid, '✨ ' + name + ' — ' + PERK_EFFECTS[effect] + '.\nВыберите другого живого игрока. Приём заменяет ночной ход. После выбора цели изменить решение нельзя.', rows)
            self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Выберите цель в сообщении бота.')
            return
        if data.startswith('inv:'):
            parts = data.split(':')
            chat = q.get('message', {}).get('chat', {})
            uid = str(q.get('from', {}).get('id', ''))
            if chat.get('type') != 'private' or str(chat.get('id')) != uid or len(parts) != 3 or parts[1] not in ('use', 'equip', 'unequip') or (parts[1] != 'unequip' and parts[2] not in SHOP):
                self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Откройте свой /inventory в ЛС.')
                return
            command = '/' + parts[1] + (' ' + parts[2] if parts[1] != 'unequip' else '')
            self.message({'text': command, 'from': q['from'], 'chat': chat}, button_action=True)
            self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Результат — в сообщении бота.')
            return
        if data.startswith('kill:'):
            self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Старая кнопка. Выберите предмет в /shop или /inventory.')
            return
        if self.exile_callback(q):
            return
        if payments.callback(self, q):
            return
        data = q.get('data', '')
        if data.startswith('shop:') and q.get('message', {}).get('chat', {}).get('type') != 'private':
            self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Магазин теперь доступен в личном чате бота: /shop', show_alert=True)
            return
        if data.startswith('shop:'):
            parts = data.split(':')
            message = q.get('message', {})
            if len(parts) != 3 or parts[1] != 'buy' or parts[2] not in SHOP or not message.get('chat') or q.get('from', {}).get('is_bot'):
                self.api.call('answerCallbackQuery', callback_query_id=q['id'], text='Товар недоступен. Откройте /shop.')
                return
            # Each Telegram callback is one purchase; replay uses the same receipt.
            self.message({'text': '/buy ' + parts[2], 'from': q['from'],
                          'chat': message['chat'], 'message_id': 'shop-' + q['id']}, button_action=True)
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
                    if g['phase'] in ('night', 'vote') and uid in g.get('votes', {}):
                        answer = '🔒 Ваш выбор уже принят. Изменить его нельзя.'
                    elif g['phase']=='night' and valid_action(g['players'],uid,target) and (not target.startswith('perk~') or q.get('message', {}).get('chat', {}).get('type') == 'private' and str(q['message']['chat'].get('id')) == uid):
                        g['votes'][uid]=target
                        self.save()
                        answer = '🔒 Выбор принят. Изменить его нельзя.'
                    elif g['phase']=='vote' and q.get('message', {}).get('chat', {}).get('type') == 'private' and str(q.get('message', {}).get('chat', {}).get('id')) == uid and (target=='0' and not p.get('abstain_used') or target in g['players'] and g['players'][target]['alive'] and target!=uid):
                        g['votes'][uid]=target
                        self.save()
                        answer = '🔒 Голос принят. Изменить его нельзя.'
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
                counts = vote_counts(g)
                report = ['🗳 Итоги голосования', '', 'Кто за кого:']
                for voter, player in alive.items():
                    choice = votes.get(voter)
                    valid = choice == '0' and not player.get('abstain_used') or choice in alive and choice != voter
                    label = 'воздержался' if choice == '0' and valid else alive[choice]['name'] if valid else 'не голосовал'
                    weight = ''
                    report.append(f"{player['name']} → {label}{weight}")
                report += ['', 'Количество голосов:']
                for target_id, player in sorted(alive.items(), key=lambda item: (-counts.get(item[0], 0), item[0])):
                    report.append(f"{player['name']}: {counts.get(target_id, 0)}")
                report.append(f"Воздержались: {counts.get('0', 0)} голосов")
                target, damage = council(g)
                self.save()
                if target:
                    report.append(f"\n⚔️ Арена вынесла приговор: {ps[target]['name']} повержен!\n🗳 Голосов против: {counts[target]}.")
                elif any(key != '0' for key in counts):
                    report.append('\n⚖️ Равенство голосов у лидеров. Никто не выбывает.')
                else:
                    report.append('\n⚖️ Нет голосов за исключение. Никто не выбывает.')
                self.safe_send(chat, '\n'.join(report))
                if not self.finish(chat,g):
                    g['round'] += 1
                    self.phase(chat,g,'night')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token = os.getenv('BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Укажите BOT_TOKEN в переменных окружения. См. README.md')
    SurvivalBot(API(token), os.getenv('STATE_PATH', 'data/state.json')).run()
