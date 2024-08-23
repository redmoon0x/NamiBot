from flask import Flask, request
import bot
import asyncio
import os
from telethon import events, types

app = Flask(__name__)

# Initialize the bot
bot_module.client.start(bot_token=bot_module.bot_token)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        update = request.json
        asyncio.run(handle_update(update))
        return 'OK', 200
    return 'OK', 200

async def handle_update(update):
    if 'message' in update:
        event = events.NewMessage.Event(update['message'])
    elif 'callback_query' in update:
        event = events.CallbackQuery.Event(update['callback_query'])
    else:
        return
    
    event._set_client(bot_module.client)
    event.message = types.Message(
        id=event.id,
        to_id=types.PeerUser(event.sender_id),
        message=event.text,
        date=event.date,
        out=False,
        mentioned=False,
        media_unread=False,
        silent=False,
        post=False,
        from_scheduled=False,
        legacy=False,
        edit_hide=False,
        pinned=False,
        from_id=types.PeerUser(event.sender_id),
    )

    await bot_module.client._dispatch_event(event)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
