import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient, events

api_id = 23951839
api_hash = '91b77cf2c4d2c284f5336c50a9bbdb03'
session_name = 'my_account_session'

client = TelegramClient(session_name, api_id, api_hash)

last_replied = {}
REPLY_INTERVAL = timedelta(hours=3)

auto_reply_text = """
**Автоматическое сообщение**

Привет! 
Сейчас я немного занят, но обязательно приду позже и отвечу!
А пока вы можете задать вопрос, пока я нет 😄
Спасибо за ваше понимание — ответим при первой же возможности! :)
"""

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    sender = await event.get_sender()
    sender_id = sender.id
    now = datetime.now()

    if sender_id in last_replied and now - last_replied[sender_id] < REPLY_INTERVAL:
        print(f"Пропускаем ответ для {sender_id}, ещё не прошло 3 часа")
        return

    await event.reply(auto_reply_text, parse_mode='markdown')
    print(f"Ответил пользователю {sender_id} в {now}")
    last_replied[sender_id] = now

async def main():
    await client.start()
    print("Клиент запущен и слушает входящие сообщения...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
