from telethon import TelegramClient, events, Button
import os
import hashlib
from collections import defaultdict
import asyncio
import aiohttp
from datetime import datetime, timedelta
from dotenv import load_dotenv
import secrets
import logging
from shortuuid import ShortUUID
from pyshorteners import Shortener  # Import pyshorteners library

logging.basicConfig(level=logging.INFO)

load_dotenv()

def get_env(key, default=None, convert=str):
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Environment variable {key} is not set")
    try:
        return convert(value)
    except ValueError:
        raise ValueError(f"Failed to convert {key}={value} to {convert.__name__}")

api_id = get_env('TELEGRAM_API_ID', convert=int)
api_hash = get_env('TELEGRAM_API_HASH')
bot_token = get_env('TELEGRAM_BOT_TOKEN')
storage_group_id = get_env('STORAGE_GROUP_ID', convert=int)
log_channel_id = get_env('LOG_CHANNEL_ID', convert=int)
api_base_url = get_env('API_BASE_URL', 'https://namiapi.onrender.com')

client = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

url_cache = defaultdict(dict)
user_cooldowns = {}

# Define special users by their Telegram IDs or usernames
special_users = {
    1502110448: "Deviprasad Shetty",
    5792840252: "Abhiiiiiiiiii",
    1669299995: "Ravina Mam"
}

# Define admin users
admin_users = {1502110448}  # Add admin user IDs here

# Track search usage for non-special users
search_tracker = defaultdict(lambda: {'count': 0, 'last_search_time': None})
SEARCH_LIMIT = 2
RESET_TIME_HOURS = 2

async def perform_search(query, num_results=10):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{api_base_url}/search", json={"query": query, "num_results": num_results}) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"API request failed with status {response.status}")
                    return None
        except Exception as e:
            print(f"Error in API request: {str(e)}")
            return None

async def send_results_page(event, results, page, query):
    buttons = []
    results_list = results['global_results'] if page == 0 else results['archive_results']

    for result in results_list:
        url_hash = hashlib.md5(result['url'].encode()).hexdigest()
        url_cache[event.chat_id][url_hash] = {'title': result['title'], 'url': result['url']}

        truncated_title = result['title'][:47] + "..." if len(result['title']) > 50 else result['title']
        buttons.append([Button.inline(f"📚 {truncated_title}", f"pdf:{url_hash}")])

    nav_buttons = []
    if page == 0 and results['archive_results']:
        nav_buttons.append(Button.inline("➡️ Next Page (Archive.org)", data=f"next_page:{query}"))
    elif page == 1:
        nav_buttons.append(Button.inline("⬅️ Previous Page (Global)", data=f"prev_page:{query}"))

    buttons.append(nav_buttons)

    page_title = "🌐 Global PDF Results" if page == 0 else "🏛️ Internet Archive PDF Results"
    header = f"📚 {page_title} 📚\n\n🔍 Search query: {query}\n\n"

    if isinstance(event, events.CallbackQuery.Event):
        await event.edit(header, buttons=buttons)
    else:
        await event.respond(header, buttons=buttons)

async def handle_message(event):
    user_id = event.sender_id
    if event.text.startswith('/'):
        return

    query = event.text.strip()
    if not query:
        await event.respond("Please provide a search term for the PDF.")
        return

    if user_id in special_users or user_id in admin_users:
        await event.respond("You have unlimited searches. 🚀")
    else:
        user_data = search_tracker[user_id]
        now = datetime.now()

        if user_data['last_search_time']:
            elapsed_time = now - user_data['last_search_time']
            if elapsed_time > timedelta(hours=RESET_TIME_HOURS):
                search_tracker[user_id]['count'] = 0
                search_tracker[user_id]['last_search_time'] = None

        if user_data['count'] >= SEARCH_LIMIT:
            time_remaining = timedelta(hours=RESET_TIME_HOURS) - elapsed_time
            hours, remainder = divmod(time_remaining.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            await event.respond(f"⏳ You have reached your search limit. Please try again in {hours}h {minutes}m.")
            return
        else:
            search_tracker[user_id]['count'] += 1
            search_tracker[user_id]['last_search_time'] = now

    # Send a message with a progress bar
    progress_message = await event.respond("Searching for PDFs, please wait...\n\n[🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨]")

    try:
        results = await perform_search(query)
        if results:
            await send_results_page(event, results, 0, query)
        else:
            await event.respond("Sorry, I couldn't find any PDFs related to that query. 😔")
    except Exception as e:
        await event.respond(f"An error occurred while processing your request.")
        print(f"Error in handle_message: {str(e)}")
    finally:
        # Delete the progress bar message
        await progress_message.delete()


@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    user_id = event.sender_id
    user_name = event.sender.username

    if user_id in special_users or user_id in admin_users:
        special_name = special_users.get(user_id, "Admin")
        await event.respond(
            f"✨ Welcome, {special_name}! ✨\n"
            "It's always a pleasure to have you here. You have unlimited access to the best PDFs in Nami's Library! 📚\n"
            "Just type the title or topic you're interested in, and I'll find the perfect PDFs for you.\n"
            "Developed by @redmoon0x(Deviprasad Shetty)",
            buttons=[
                [Button.inline("🙏 Donate", data="donate")],
                [Button.url("Developer", "https://t.me/redmoon0x")]
            ]
        )
    else:
        await event.respond(
            "Welcome to Nami's Library! 📚\n"
            "I can help you find PDFs from the web.\n"
            "Just type the title or topic you're looking for, and I'll search for it.\n"
            "If you find this service helpful, consider supporting us:\n"
            "Developed by @redmoon0x(Deviprasad Shetty)",
            buttons=[
                [Button.inline("🙏 Donate", data="donate")],
                [Button.url("Developer", "https://t.me/redmoon0x")]
            ]
        )

@client.on(events.CallbackQuery)
async def callback_query_handler(event):
    data = event.data.decode()

    if data == "donate":
        await event.answer("Thank you for considering a donation! 🙏")
        try:
            await client.send_message(event.chat_id, "If you'd like to support this service, you can scan the QR code below to donate via UPI. Your support helps us keep improving. Thank you for considering a donation! 🙏")
            await client.send_file(event.chat_id, 'donation.jpg')
        except Exception as e:
            print(f"Failed to send donation information or QR code: {str(e)}")

    elif data.startswith("next_page:") or data.startswith("prev_page:"):
        page = 1 if data.startswith("next_page:") else 0
        query = data.split(':', 1)[1]
        global_results = await global_pdf_search(query)
        archive_results = await archive_pdf_search(query)
        await send_results_page(event, global_results, archive_results, page, query)

    elif data.startswith("pdf:"):
        await handle_pdf_request(event)

    else:
        print("Received unknown callback data:", data)
        await event.answer("Something went wrong, please try again.")

async def handle_pdf_request(call):
    user_id = call.sender_id
    current_time = datetime.now()

    if user_id in user_cooldowns:
        time_diff = current_time - user_cooldowns[user_id]
        if time_diff.total_seconds() < 60:  # 1 minute cooldown
            remaining_time = 60 - int(time_diff.total_seconds())
            await call.answer(f"Please wait {remaining_time} seconds before requesting another PDF.")
            return

    user_cooldowns[user_id] = current_time

    try:
        user = await client.get_entity(call.sender_id)
        url_hash = call.data.decode().split(':')[1]
        pdf_info = url_cache[call.chat_id].get(url_hash)

        if pdf_info:
            title, url = pdf_info['title'], pdf_info['url']

            # Shorten the PDF URL using pyshorteners
            short_url = await shorten_url(url)

            try:
                # More engaging message with emojis and call-to-action
                await client.send_message(
                    call.chat_id,
                    f"🎉  **Found it!** 🎉\n\n"
                    f"📖 **{title}** is ready for you!\n\n"
                    f"🚀 Click here to access the PDF: {short_url}\n\n"
                    f"💌 Enjoy reading! If you find this service helpful, consider supporting us by scanning the QR code below to donate via UPI. Your support helps us keep improving. Thank you for considering a donation! 🙏"
                )
                await call.answer("PDF link sent successfully!")
                success = True
                logging.info(f"PDF link sent to user {user_id}")
            except Exception as e:
                await call.answer("An error occurred while sending the PDF link. Please try again later.")
                logging.error(f"Error in sending message to user {user_id}: {str(e)}")
                success = False

            await log_pdf_request(user, pdf_info, success)

            countdown_message = await call.client.send_message(call.chat_id, "⏳ You can request another PDF in 60 seconds.")
            for i in range(59, 0, -1):
                await asyncio.sleep(1)
                await countdown_message.edit(f"⏳ You can request another PDF in {i} seconds.")
            await countdown_message.delete()

            del url_cache[call.chat_id][url_hash]
        else:
            await call.answer("Sorry, I couldn't retrieve the PDF. Please try searching again.")
            logging.warning(f"PDF not found in cache for user {user_id}")
    except Exception as e:
        await call.answer("An unexpected error occurred. Please try again.")
        logging.error(f"Error in handle_pdf_request for user {user_id}: {str(e)}")

# Shorten URL using pyshorteners
async def shorten_url(url):
    shortener = Shortener()
    try:
        short_url = shortener.tinyurl.short(url)  # Use TinyURL service
        return short_url
    except Exception as e:
        print(f"Error shortening URL: {str(e)}")
        return url

def main():
    print("Bot is starting...")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
