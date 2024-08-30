from telethon import TelegramClient, events, Button
import os
import hashlib
from collections import defaultdict
import asyncio
import aiohttp
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sqlite3
import secrets


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
api_base_url = get_env('API_BASE_URL', 'https://namiapi.onrender.com')  # Add this to your .env file

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

    await event.respond("Searching for PDFs, please wait...")
    
    try:
        results = await perform_search(query)
        if results:
            await send_results_page(event, results, 0, query)
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



# SQLite setup and token management
def init_db():
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tokens
                 (token TEXT PRIMARY KEY, user_id INTEGER, expiry TIMESTAMP)''')
    conn.commit()
    conn.close()

def generate_token(user_id):
    token = secrets.token_urlsafe()
    expiry = datetime.now() + timedelta(hours=12)
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute("INSERT INTO tokens VALUES (?, ?, ?)", (token, user_id, expiry))
    conn.commit()
    conn.close()
    return token

def verify_token(token):
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute("SELECT expiry FROM tokens WHERE token = ?", (token,))
    result = c.fetchone()
    if result:
        expiry = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
        if expiry > datetime.now():
            return True
        else:
            c.execute("DELETE FROM tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()
    return False

# Telegram bot handler
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
            
            token = generate_token(user_id)
            # Assuming your Render app is at https://your-render-app.onrender.com
            pdf_url = f"https://shinobishelf.onrender.com/pdf?url={url}&token={token}"
            
            try:
                await client.send_message(
                    call.chat_id,
                    f"{title}\n\nView/Download PDF: {pdf_url}\n\nSource: {url}"
                )
                await call.answer("PDF link sent successfully!")
                success = True
            except Exception as e:
                await call.answer("An error occurred while sending the PDF link. Please try again later.")
                print(f"Error in sending message to user: {str(e)}")
                success = False
            
            await log_pdf_request(user, pdf_info, success)
            
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

# Initialize the database
init_db()

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
        
        # Check if the message is forwarded and if so, get the original sender's ID
        if reply.forward:
            new_user_id = reply.forward.sender_id
            new_username = reply.forward.sender.username if reply.forward.sender.username else reply.forward.sender.first_name
        else:
            # If the message is not forwarded, get the sender ID of the replied message
            new_user_id = reply.sender_id
            new_username = reply.sender.username if reply.sender.username else reply.sender.first_name

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
