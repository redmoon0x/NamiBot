import time
from flask import Flask, request
import bot  # Assuming you have a bot.py module
import asyncio
import os
from telethon import events, types
import requests  # For making HTTP requests

app = Flask(__name__)

# Initialize the bot
bot.client.start(bot_token=bot.bot_token)

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
    
    event._set_client(bot.client)
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

    await bot.client._dispatch_event(event)
    
    process_time = time.time() - start_time
    if process_time > 5:  # If processing took more than 5 seconds
        await bot.client.send_message(
            event.chat_id,
            "Sorry for the delay! I might have been asleep. I'm awake now and ready to help!🫡🤗"
        )

def set_webhook():
    webhook_url = f"{os.environ.get('RENDER_EXTERNAL_URL', 'https://namibot.onrender.com')}/webhook"
    response = requests.post(
        f'https://api.telegram.org/bot{bot.bot_token}/setWebhook',
        json={'url': webhook_url}
    )
    if response.status_code == 200:
        print(f"Webhook set to {webhook_url}")
    else:
        print(f"Error setting webhook: {response.text}")

async def send_startup_notification():
    await bot.client.send_message(bot.log_channel_id, "Bot has started up!")

if __name__ == '__main__':
    # Set the webhook
    set_webhook() 
    with bot.client:
        bot.client.loop.run_until_complete(send_startup_notification())
    
    # Run the Flask app
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
