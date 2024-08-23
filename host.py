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
        message = update['message']
        event = events.NewMessage.Event(types.Message(
            id=message['message_id'],
            to_id=types.PeerChat(message['chat']['id']),
            message=message.get('text', ''),
            date=message['date'],
            from_id=types.PeerUser(message['from']['id']),
        ))
        event.chat_id = message['chat']['id']
        event.sender_id = message['from']['id']
    elif 'callback_query' in update:
        callback_query = update['callback_query']
        event = events.CallbackQuery.Event(types.UpdateBotCallbackQuery(
            query_id=int(callback_query['id']),
            user_id=callback_query['from']['id'],
            peer=types.PeerChat(callback_query['message']['chat']['id']),
            msg_id=callback_query['message']['message_id'],
            data=callback_query.get('data', b''),
        ))
        event.chat_id = callback_query['message']['chat']['id']
        event.sender_id = callback_query['from']['id']
    else:
        return
    
    event._set_client(bot.client)
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
    
    # Send startup notification
    with bot.client:
        bot.client.loop.run_until_complete(send_startup_notification())
    
    # Run the Flask app
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
