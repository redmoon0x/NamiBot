from flask import Flask, request
import bot_module
import asyncio
import os
from telethon import events, types, functions

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

async def set_webhook():
    webhook_url = f"{os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:10000')}/webhook"
    await bot_module.client(functions.bots.SetBotWebhookRequest(
        url=webhook_url,
        drop_pending_updates=True
    ))
    print(f"Webhook set to {webhook_url}")

if __name__ == '__main__':
    # Set the webhook when the app starts
    with bot_module.client:
        bot_module.client.loop.run_until_complete(set_webhook())
    
    # Run the Flask app
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
