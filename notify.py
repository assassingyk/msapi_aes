# -*- coding: utf-8 -*-
"""Optional failure notifications.

Enable any channel by setting its environment variables in the workflow
(or in your shell when running locally). All channels are best-effort:
a failure to deliver never crashes the keep-alive run.

  NOTIFY_SERVERCHAN_KEY            Server酱 Turbo SendKey  (https://sct.ftqq.com)
  NOTIFY_BARK_KEY                  Bark key                 (https://api.day.app)
  NOTIFY_TELEGRAM_BOT_TOKEN        plus NOTIFY_TELEGRAM_CHAT_ID
  NOTIFY_WEBHOOK_URL               generic webhook, receives POST JSON {"title","message"}
"""
import os
from urllib.parse import quote

import requests


def _post(url, **kwargs):
    try:
        requests.post(url, timeout=15, **kwargs)
        return True
    except Exception:
        return False


def send(title, message):
    """Send a notification through every configured channel.

    Returns the list of channel names that accepted the message.
    """
    sent = []

    key = os.environ.get('NOTIFY_SERVERCHAN_KEY')
    if key:
        if _post('https://sctapi.ftqq.com/{}.send'.format(key),
                 data={'title': title, 'desp': message}):
            sent.append('serverchan')

    key = os.environ.get('NOTIFY_BARK_KEY')
    if key:
        if _post('https://api.day.app/{}/{}/{}'.format(key, quote(title), quote(message))):
            sent.append('bark')

    bot = os.environ.get('NOTIFY_TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('NOTIFY_TELEGRAM_CHAT_ID')
    if bot and chat:
        if _post('https://api.telegram.org/bot{}/sendMessage'.format(bot),
                 json={'chat_id': chat, 'text': '{}\n\n{}'.format(title, message)}):
            sent.append('telegram')

    url = os.environ.get('NOTIFY_WEBHOOK_URL')
    if url:
        if _post(url, json={'title': title, 'message': message}):
            sent.append('webhook')

    return sent
