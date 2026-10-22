"""Telegram Stars purchase flow; persistent orders and idempotent delivery."""
import secrets
import time

PACKS = {'100': (100, 10), '500': (500, 40), '1500': (1500, 100)}
TERMS = ('Коины — игровые очки для товаров из /shop, не деньги и не выводятся. '
         'Пакет начисляется после подтверждения Telegram. Разовый платёж, без подписки. '
         'Помощь и возвраты: /paysupport. Прочитайте условия и нажмите «Согласен, перейти к оплате». Также доступна команда '
         '/stars 100 agree (или 500, 1500).')


def support(bot):
    import os
    value = os.getenv('PAYMENT_SUPPORT', '').strip()
    return value if value.startswith('@') and len(value) >= 6 and all(c.isalnum() or c == '_' for c in value[1:]) else None


def command(bot, m, cmd):
    if cmd not in ('/stars', '/terms', '/paysupport', '/support'):
        return False
    chat, uid = str(m['chat']['id']), str(m['from']['id'])
    contact = support(bot)
    if cmd in ('/paysupport', '/support'):
        bot.api.send(chat, ('По оплате и возвратам напишите ' + contact + '. Укажите номер заказа из чека бота. Telegram не обрабатывает споры по этой покупке.') if contact else 'Покупка за Stars пока отключена: владелец настраивает контакт поддержки.')
    elif cmd == '/terms':
        bot.api.send(chat, TERMS + (' Контакт: ' + contact if contact else ' Продажи пока отключены.'))
    elif m['chat']['type'] != 'private':
        bot.api.send(chat, f'Покупка коинов — в личном чате: https://t.me/{bot.username}')
    else:
        args = m.get('text', '').split()
        if len(args) != 3 or args[1] not in PACKS or args[2].lower() != 'agree':
            lines = [f'{coins} коинов — {stars} ⭐' for key, (coins, stars) in PACKS.items()]
            bot.api.send(chat, '⭐ Купить коины\n' + '\n'.join(lines) + '\n\n' + TERMS + ('\nПоддержка: ' + contact if contact else '\nПродажи пока отключены: ожидается контакт поддержки владельца.'), [[{'text': f'{coins} коинов · {stars} ⭐', 'callback_data': f'stars:select:{key}'}] for key, (coins, stars) in PACKS.items()] if contact else None)
        elif not contact:
            bot.api.send(chat, 'Оплата пока отключена: не настроена поддержка. Коины можно заработать победами.')
        else:
            coins, stars = PACKS[args[1]]
            payload = 'coins_' + secrets.token_hex(16)
            order = {'uid': uid, 'coins': coins, 'stars': stars, 'created': time.time(), 'terms': 1}
            bot.state.setdefault('star_orders', {})[payload] = order
            bot.save()
            bot.api.call('sendInvoice', chat_id=chat, title=f'{coins} игровых коинов', description=f'{coins} коинов для украшений профиля. Разовая покупка. Поддержка: {contact}', payload=payload, provider_token='', currency='XTR', prices=[{'label':f'{coins} коинов','amount':stars}], start_parameter='stars')
    return True


def valid(bot, uid, payment):
    order = bot.state.get('star_orders', {}).get(payment.get('invoice_payload'))
    if not order or order['uid'] != str(uid) or payment.get('currency') != 'XTR' or payment.get('total_amount') != order['stars']:
        return None
    return order


def precheckout(bot, query):
    order = valid(bot, query['from']['id'], query)
    ok = bool(order and not order.get('charge') and support(bot))
    params = {'pre_checkout_query_id': query['id'], 'ok': ok}
    if not ok:
        params['error_message'] = 'Заказ недоступен. Откройте /stars в личном чате и создайте новый счёт.'
    bot.api.call('answerPreCheckoutQuery', **params)


def delivery(bot, message):
    payment = message.get('successful_payment')
    refunded = message.get('refunded_payment')
    if not payment and not refunded:
        return False
    data = payment or refunded
    uid = str(message['from']['id'])
    order = valid(bot, uid, data)
    charge = data.get('telegram_payment_charge_id')
    if not order or not charge:
        raise RuntimeError('Платёж не соответствует заказу')
    ledger = bot.state.setdefault('star_charges', {})
    account = bot.state.setdefault('accounts', {}).setdefault(uid, {'coins': 0, 'wins': 0, 'games': 0})
    if refunded:
        if charge in ledger and not ledger[charge].get('refunded'):
            account['coins'] -= ledger[charge]['coins']
            ledger[charge]['refunded'] = True
        bot.save()
        return True
    if charge not in ledger:
        if order.get('charge'):
            raise RuntimeError('Другой платёж для уже оплаченного заказа')
        account['coins'] += order['coins']
        ledger[charge] = {'uid': uid, 'coins': order['coins'], 'stars': order['stars'], 'payload': data['invoice_payload']}
        order['charge'] = charge
    bot.save()
    bot.safe_send(message['chat']['id'], f"✅ Оплата получена! +{order['coins']} коинов. Баланс: {account['coins']}.\nЗаказ: {data['invoice_payload']}\n/balance · /shop · /paysupport")
    return True

def callback(bot, q):
    data = q.get('data', '')
    if not data.startswith('stars:'):
        return False
    message = q.get('message', {})
    chat = message.get('chat', {})
    uid = str(q.get('from', {}).get('id', ''))
    def answer(text):
        bot.api.call('answerCallbackQuery', callback_query_id=q['id'], text=text)
    parts = data.split(':')
    if chat.get('type') != 'private' or str(chat.get('id')) != uid or len(parts) != 3 or not support(bot):
        answer('Откройте /stars в личном чате бота.')
        return True
    action, key = parts[1:]
    if action == 'select' and key in PACKS:
        coins, stars = PACKS[key]
        nonce = secrets.token_hex(12)
        bot.state.setdefault('star_consents', {})[nonce] = {'uid': uid, 'pack': key, 'created': time.time()}
        bot.save()
        bot.api.send(chat['id'], f'⭐ {coins} коинов за {stars} Stars\\n\\n' + TERMS + '\\nПоддержка: ' + support(bot),
                     [[{'text': f'Согласен, перейти к оплате · {stars} ⭐', 'callback_data': 'stars:pay:' + nonce}]])
        answer('Проверьте пакет и условия покупки.')
    elif action == 'pay':
        consent = bot.state.get('star_consents', {}).get(key)
        if not consent or consent['uid'] != uid or consent.get('issued') or time.time() - consent['created'] > 3600:
            answer('Подтверждение устарело или счёт уже выдан. Откройте /stars.')
            return True
        # Native Telegram payment UI performs the final payment confirmation.
        command(bot, {'text': '/stars ' + consent['pack'] + ' agree', 'from': q['from'], 'chat': chat}, '/stars')
        consent['issued'] = True
        bot.save()
        answer('Счёт готов. Оплата — кнопкой Telegram в сообщении.')
    else:
        answer('Пакет недоступен. Откройте /stars.')
    return True
