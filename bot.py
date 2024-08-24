from telethon import TelegramClient, events, Button
import aiohttp
from bs4 import BeautifulSoup
import os
import hashlib
from collections import defaultdict
import asyncio
import random
import time
from telethon.errors import FloodWaitError, MessageTooLongError, ChatIdInvalidError
from dotenv import load_dotenv
from datetime import datetime, timedelta

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

async def global_pdf_search(query, num_results=10, retries=3, backoff_factor=1):
    search_url = f"https://www.google.com/search?q=filetype:pdf+{query}"
    return await perform_search(search_url, num_results, retries, backoff_factor)

async def archive_pdf_search(query, num_results=10, retries=3, backoff_factor=1):
    search_url = f"https://www.google.com/search?q=site:archive.org+filetype:pdf+{query}"
    return await perform_search(search_url, num_results, retries, backoff_factor)

async def perform_search(search_url, num_results, retries, backoff_factor):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, headers=headers) as response:
                    if response.status == 200:
                        soup = BeautifulSoup(await response.text(), 'html.parser')
                        results = []
                        for g in soup.find_all('div', class_='g'):
                            link = g.find('a', href=True)
                            title = g.find('h3')
                            if link and title:
                                href = link['href']
                                url = href.split("&")[0].split("?q=")[-1]
                                results.append((title.text, url))
                        return results[:num_results]
                    elif response.status == 429:
                        raise Exception("Rate limit exceeded")
                    else:
                        raise Exception(f"Unexpected response status: {response.status}")
        except Exception as e:
            if attempt < retries - 1:
                sleep_time = backoff_factor * (2 ** attempt) + random.uniform(0, 1)
                print(f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {sleep_time:.2f} seconds...")
                await asyncio.sleep(sleep_time)
            else:
                print(f"All {retries} attempts failed. Giving up.")
                return []

async def send_results_page(event, global_results, archive_results, page, query):
    buttons = []
    results = global_results if page == 0 else archive_results
    
    for title, url in results:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        url_cache[event.chat_id][url_hash] = {'title': title, 'url': url}
        
        truncated_title = title[:47] + "..." if len(title) > 50 else title
        buttons.append([Button.inline(f"📚 {truncated_title}", f"pdf:{url_hash}")])
    
    nav_buttons = []
    if page == 0 and archive_results:
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

    await event.respond("Searching for PDFs, please wait...")
    
    try:
        global_results = await global_pdf_search(query)
        archive_results = await archive_pdf_search(query)
        
        if global_results or archive_results:
            await send_results_page(event, global_results, archive_results, 0, query)
        else:
            await event.respond("Sorry, I couldn't find any PDFs related to that query. 😔")
    except Exception as e:
        await event.respond(f"An error occurred while processing your request.")
        print(f"Error in handle_message: {str(e)}")

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
            
            try:
                await client.send_file(call.chat_id, url, caption=f"{title}\n\nSource: {url}")
                await call.answer("PDF sent successfully!")
                success = True
            except ChatIdInvalidError:
                await call.answer("Failed to send the PDF. Please start a chat with the bot first.")
                success = False
            except FloodWaitError as e:
                await call.answer(f"Rate limit exceeded. Please wait for {e.seconds} seconds.")
                await asyncio.sleep(e.seconds)
                success = False
            except Exception as e:
                await call.answer("An error occurred while sending the PDF. Please try again later.")
                print(f"Error in sending file to user: {str(e)}")
                success = False
            
            await log_pdf_request(user, pdf_info, success)
            
            if success:
                try:
                    await client.send_file(storage_group_id, url, caption=f"{title}\n\nSource: {url}")
                except Exception as e:
                    print(f"Failed to send to storage group: {str(e)}")
            
            countdown_message = await call.client.send_message(call.chat_id, "You can request another PDF in 60 seconds.")
            for i in range(59, 0, -1):
                await asyncio.sleep(1)
                await countdown_message.edit(f"You can request another PDF in {i} seconds.")
            await countdown_message.delete()
            
            del url_cache[call.chat_id][url_hash]
        else:
            await call.answer("Sorry, I couldn't retrieve the PDF. Please try searching again.")
    except Exception as e:
        await call.answer("An unexpected error occurred. Please try again.")
        print(f"Error in handle_pdf_request: {str(e)}")

async def log_pdf_request(user, pdf_info, success):
    status = "successfully received" if success else "failed to receive"
    log_message = (
        f"User: {user.first_name} {user.last_name} (ID: {user.id}, Username: @{user.username})\n"
        f"Action: {status} a PDF\n"
        f"Title: {pdf_info['title']}\n"
        f"URL: {pdf_info['url']}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    try:
        await client.send_message(log_channel_id, log_message)
    except Exception as e:
        print(f"Failed to send log message: {str(e)}")

@client.on(events.NewMessage(pattern='/addsuperuser'))
async def add_superuser(event):
    if event.sender_id not in admin_users:
        await event.respond("❌ You are not authorized to use this command.")
        return

    if event.is_reply:
        reply = await event.get_reply_message()
        new_user_id = reply.sender_id
        new_username = reply.sender.username

        if new_user_id in special_users:
            await event.respond(f"User {new_username} is already a super user.")
        else:
            special_users[new_user_id] = new_username
            await event.respond(f"✅ User {new_username} has been added as a super user.")
            print(f"Admin added {new_username} ({new_user_id}) as a super user.")
    else:
        await event.respond("Please reply to a message from the user you want to promote.")

@client.on(events.NewMessage(pattern='/removesuperuser'))
async def remove_superuser(event):
    if event.sender_id not in admin_users:
        await event.respond("❌ You are not authorized to use this command.")
        return

    if event.is_reply:
        reply = await event.get_reply_message()
        user_id = reply.sender_id

        if user_id in special_users:
            del special_users[user_id]
            await event.respond(f"✅ User has been removed from super users.")
        else:
            await event.respond("This user is not a super user.")
    else:
        await event.respond("Please reply to a message from the user you want to remove from super users.")

@client.on(events.NewMessage(pattern='/listsuperusers'))
async def list_superusers(event):
    if event.sender_id not in admin_users:
        await event.respond("❌ You are not authorized to use this command.")
        return

    if special_users:
        message = "Current super users:\n\n"
        for user_id, username in special_users.items():
            message += f"- {username} (ID: {user_id})\n"
    else:
        message = "There are no super users currently."

    await event.respond(message)

@client.on(events.NewMessage(pattern='/help'))
async def help(event):
    if event.sender_id in admin_users:
        await event.respond(
            "Admin Commands:\n"
            "/addsuperuser - Add a super user (reply to their message)\n"
            "/removesuperuser - Remove a super user (reply to their message)\n"
            "/listsuperusers - List all super users\n"
            "/broadcast - Send a message to all users\n"
            "/stats - View bot statistics\n\n"
            "User Commands:\n"
            "Just type the title or a keyword related to the PDF you're looking for.\n"
            "I will search the web for relevant PDFs and provide you with a list of options to choose from.\n"
            "Click on any of the options to get the PDF delivered directly to you.\n"
            "Non-super users have a limit of 2 searches every 2 hours."
        )
    else:
        await event.respond(
            "To use this bot, simply type the title or a keyword related to the PDF you're looking for.\n"
            "I will search the web for relevant PDFs and provide you with a list of options to choose from.\n"
            "Click on any of the options to get the PDF delivered directly to you.\n"
            "Non-super users have a limit of 2 searches every 2 hours."
        )

# Global set to store user IDs
all_user_ids = set()

@client.on(events.NewMessage)
async def message_handler(event):
    all_user_ids.add(event.sender_id)  # Store user ID
    await handle_message(event)

@client.on(events.NewMessage(pattern='/broadcast'))
async def broadcast(event):
    if event.sender_id not in admin_users:
        await event.respond("❌ You are not authorized to use this command.")
        return
    
    message_to_broadcast = event.message.text.split(maxsplit=1)[1] if len(event.message.text.split(maxsplit=1)) > 1 else ""
    if not message_to_broadcast:
        await event.respond("Please include a message to broadcast.")
        return
    
    failed = 0
    success = 0
    for user_id in all_user_ids:
        try:
            await client.send_message(user_id, message_to_broadcast)
            success += 1
        except Exception as e:
            print(f"Failed to send broadcast to {user_id}: {str(e)}")
            failed += 1
    
    await event.respond(f"Broadcast completed. Successful: {success}, Failed: {failed}")

@client.on(events.NewMessage(pattern='/stats'))
async def stats(event):
    if event.sender_id not in admin_users:
        await event.respond("❌ You are not authorized to use this command.")
        return

    total_users = len(all_user_ids)
    total_searches = sum(user['count'] for user in search_tracker.values())
    active_users = sum(1 for user in search_tracker.values() if user['last_search_time'] and (datetime.now() - user['last_search_time']).days < 7)

    stats_message = (
        f"📊 Bot Statistics 📊\n\n"
        f"Total Users: {total_users}\n"
        f"Total Searches: {total_searches}\n"
        f"Active Users (last 7 days): {active_users}\n"
        f"Super Users: {len(special_users)}\n"
        f"Admin Users: {len(admin_users)}"
    )

    await event.respond(stats_message)

def main():
    print("Bot is starting...")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
