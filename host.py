import time
from flask import Flask, request
import bot
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

@app.route('/keepalive')
def keepalive():
    return "I'm alive!", 200

async def handle_update(update):
    start_time = time.time()
    
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
    
    process_time = time.time() - start_time
    if process_time > 5:  # If processing took more than 5 seconds
        await bot_module.client.send_message(
            event.chat_id,
            "Sorry for the delay! I might have been asleep. I'm awake now and ready to help!"
        )

async def set_webhook():
    webhook_url = f"{os.environ.get('RENDER_EXTERNAL_URL', 'https://namibot.onrender.com')}/webhook"
    await bot_module.client(functions.bots.SetBotWebhookRequest(
        url=webhook_url,
        drop_pending_updates=True
    ))
    print(f"Webhook set to {webhook_url}")

async def send_startup_notification():
    await bot_module.client.send_message(bot_module.log_channel_id, "Bot has started up!")

if __name__ == '__main__':
    # Set the webhook and send startup notification when the app starts
    with bot_module.client:
        bot_module.client.loop.run_until_complete(set_webhook())
        bot_module.client.loop.run_until_complete(send_startup_notification())
    
    # Run the Flask app
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
