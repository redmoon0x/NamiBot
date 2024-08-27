import os
import hashlib
import asyncio
import aiohttp
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.tl.types import InputPeerUser
from io import BytesIO
from dotenv import load_dotenv
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import List, Dict
from collections import defaultdict
import speedtest

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
PDF_SCRAPER_URL = get_env('PDF_SCRAPER_URL', 'https://namiapi.onrender.com')
DEVELOPER_ID = get_env('DEVELOPER_ID', convert=int)  # Get DEVELOPER_ID from env

client = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

# SQLite setup
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Create tables
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    is_super_user BOOLEAN DEFAULT 0,
    search_count INTEGER DEFAULT 0,
    last_search_time TIMESTAMP,
    last_pdf_request TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS pdf_cache (
    chat_id INTEGER,
    url_hash TEXT,
    title TEXT,
    url TEXT,
    PRIMARY KEY (chat_id, url_hash)
)
''')

conn.commit()

class SearchResult(BaseModel):
    title: str
    url: str

class SearchResponse(BaseModel):
    global_results: List[SearchResult]
    archive_results: List[SearchResult]

SEARCH_LIMIT = 2
RESET_TIME_HOURS = 2
MAX_DIRECT_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

async def perform_pdf_search(query: str, num_results: int = 10) -> SearchResponse:
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{PDF_SCRAPER_URL}/search", json={"query": query, "num_results": num_results}) as response:
            if response.status == 200:
                return SearchResponse(**await response.json())
            else:
                raise Exception(f"Error from PDF scraper service: {response.status}")

async def send_results_page(event, global_results, archive_results, page, query):
    buttons = []
    results = global_results if page == 0 else archive_results
    
    for result in results:
        url_hash = hashlib.md5(result.url.encode()).hexdigest()
        cursor.execute('''
        INSERT OR REPLACE INTO pdf_cache (chat_id, url_hash, title, url)
        VALUES (?, ?, ?, ?)
        ''', (event.chat_id, url_hash, result.title, result.url))
        conn.commit()
        
        truncated_title = result.title[:47] + "..." if len(result.title) > 50 else result.title
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
    
    cursor.execute('SELECT is_super_user, search_count, last_search_time FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()
    
    if not user_data:
        cursor.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        user_data = (0, 0, None)
    
    is_super_user, search_count, last_search_time = user_data
    
    if is_super_user or user_id == DEVELOPER_ID:  # Super users and developer have unlimited searches
        await event.respond("You have unlimited searches. 🚀")
    else:
        now = datetime.now()
        if last_search_time:
            last_search_time = datetime.fromisoformat(last_search_time)
            elapsed_time = now - last_search_time
            if elapsed_time > timedelta(hours=RESET_TIME_HOURS):
                search_count = 0
                last_search_time = None

        if search_count >= SEARCH_LIMIT:
            time_remaining = timedelta(hours=RESET_TIME_HOURS) - elapsed_time
            hours, remainder = divmod(time_remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await event.respond(f"⏳ You have reached your search limit. Please try again in {hours}h {minutes}m.")
            return
        else:
            search_count += 1
            last_search_time = now
            cursor.execute('''
            UPDATE users SET search_count = ?, last_search_time = ?
            WHERE user_id = ?
            ''', (search_count, last_search_time.isoformat(), user_id))
            conn.commit()

    await event.respond("Searching for PDFs, please wait...")
    
    try:
        search_response = await perform_pdf_search(query)
        
        if search_response.global_results or search_response.archive_results:
            await send_results_page(event, search_response.global_results, search_response.archive_results, 0, query)
        else:
            await event.respond("Sorry, I couldn't find any PDFs related to that query. 😔")
    except Exception as e:
        await event.respond(f"An error occurred while processing your request.")
        print(f"Error in handle_message: {str(e)}")

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    user_id = event.sender_id
    cursor.execute('SELECT is_super_user FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()
    
    if user_data and user_data[0]:
        await event.respond(
            f"✨ Welcome, Super User! ✨\n"
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
        search_response = await perform_pdf_search(query)
        await send_results_page(event, search_response.global_results, search_response.archive_results, page, query)

    elif data.startswith("pdf:"):
        await handle_pdf_request(event)

    else:
        print("Received unknown callback data:", data)
        await event.answer("Something went wrong, please try again.")

async def handle_pdf_request(call):
    user_id = call.sender_id
    current_time = datetime.now()

    cursor.execute('SELECT last_pdf_request FROM users WHERE user_id = ?', (user_id,))
    last_request = cursor.fetchone()

    if last_request and last_request[0]:
        last_request_time = datetime.fromisoformat(last_request[0])
        time_diff = current_time - last_request_time
        if time_diff.total_seconds() < 60:
            remaining_time = 60 - int(time_diff.total_seconds())
            await call.answer(f"Please wait {remaining_time} seconds before requesting another PDF.")
            return

    cursor.execute('UPDATE users SET last_pdf_request = ? WHERE user_id = ?', (current_time.isoformat(), user_id))
    conn.commit()

    try:
        url_hash = call.data.decode().split(':')[1]
        cursor.execute('SELECT title, url FROM pdf_cache WHERE chat_id = ? AND url_hash = ?', (call.chat_id, url_hash))
        pdf_info = cursor.fetchone()
        
        if pdf_info:
            title, url = pdf_info
            
            status_message = await client.send_message(call.chat_id, f"Fetching: {title}\nPlease wait...")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        file_size = len(content)
                        
                        await status_message.edit(f"Sending: {title}")
                        
                        if file_size <= MAX_DIRECT_FILE_SIZE:
                            # Send directly using send_document
                            file = BytesIO(content)
                            file.name = f"{title}.pdf"
                            await client.send_file(
                                entity=InputPeerUser(call.sender_id, 0),
                                file=file,
                                caption=f"{title}\n\nSource: {url}",
                                force_document=True,
                                progress_callback=lambda c, t: asyncio.create_task(progress_callback(status_message, c, t))
                            )
                            await status_message.delete()
                            await call.answer("PDF sent successfully!")
                            success = True
                        else:
                            # Stream the file
                            await status_message.edit(f"Streaming: {title}")
                            async with session.get(url) as response:
                                if response.status == 200:
                                    async for chunk in response.content.iter_chunked(5*1024 * 1024):  # Adjust chunk size as needed
                                        try:
                                            await client.send_file(
                                                entity=InputPeerUser(call.sender_id, 0),
                                                file=BytesIO(chunk),
                                                caption=f"{title}\n\nSource: {url}",
                                                force_document=True,
                                                progress_callback=lambda c, t: asyncio.create_task(progress_callback(status_message, c, t))
                                            )
                                        except Exception as e:
                                            await status_message.edit(f"Error sending file: {str(e)}")
                                            success = False
                                            break
                                    else:
                                        await status_message.delete()
                                        await call.answer("PDF sent successfully!")
                                        success = True
                                else:
                                    await status_message.edit(f"Failed to fetch PDF: HTTP {response.status}")
                                    success = False
            
            await log_pdf_request(await client.get_entity(call.sender_id), pdf_info, success)
            
            cursor.execute('DELETE FROM pdf_cache WHERE chat_id = ? AND url_hash = ?', (call.chat_id, url_hash))
            conn.commit()
        else:
            await call.answer("Sorry, I couldn't retrieve the PDF. Please try searching again.")
    except Exception as e:
        await call.answer("An unexpected error occurred. Please try again.")
        print(f"Error in handle_pdf_request: {str(e)}")

async def progress_callback(message, current, total):
    percent = int((current / total) * 100)
    if percent % 1 == 0:  # Update every 10%
        await message.edit(f"Uploading: {percent}% complete")

async def log_pdf_request(user, pdf_info, success):
    status = "successfully received" if success else "failed to receive"
    log_message = (
        f"User: {user.first_name} {user.last_name} (ID: {user.id}, Username: @{user.username})\n"
        f"Action: {status} a PDF\n"
        f"Title: {pdf_info[0]}\n"
        f"URL: {pdf_info[1]}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    try:
        await client.send_message(log_channel_id, log_message)
    except Exception as e:
        print(f"Failed to send log message: {str(e)}")

# ... (rest of your code)

@client.on(events.NewMessage(pattern='/addsuperuser', from_users=DEVELOPER_ID))  # Only admin can use this command
async def add_superuser(event):
    try:
        user_id = int(event.message.text.split()[1])
    except (IndexError, ValueError):
        await event.respond("Please provide a valid user ID. Usage: /addsuperuser <user_id>")
        return

    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    cursor.execute('UPDATE users SET is_super_user = 1 WHERE user_id = ?', (user_id,))
    conn.commit()

    await event.respond(f"✅ User (ID: {user_id}) has been added as a super user.")

    try:
        await client.send_message(user_id, "🎉 Congratulations! You have been promoted to super user status. You now have unlimited searches and additional privileges.")
    except Exception as e:
        await event.respond(f"Note: Failed to notify the user. They might have blocked the bot or have privacy settings enabled.")

@client.on(events.NewMessage(pattern='/removesuperuser', from_users=DEVELOPER_ID))  # Only admin can use this command
async def remove_superuser(event):
    try:
        user_id = int(event.message.text.split()[1])
    except (IndexError, ValueError):
        await event.respond("Please provide a valid user ID. Usage: /removesuperuser <user_id>")
        return

    cursor.execute('UPDATE users SET is_super_user = 0 WHERE user_id = ?', (user_id,))
    if cursor.rowcount > 0:
        conn.commit()
        await event.respond(f"✅ User (ID: {user_id}) has been removed from super users.")
        
        # Notify the user that they have been removed as a superuser
        try:
            await client.send_message(user_id, "⚠️ Your super user status has been revoked. You now have limited searches like regular users.")
        except Exception as e:
            await event.respond(f"Note: Failed to notify the user. They might have blocked the bot or have privacy settings enabled.")
    else:
        await event.respond(f"User (ID: {user_id}) is not a super user.")

# ... (rest of your code)
@client.on(events.NewMessage(pattern='/listsuperusers'))
async def list_superusers(event):
    if not await is_admin(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    cursor.execute('SELECT user_id FROM users WHERE is_super_user = 1')
    super_users = cursor.fetchall()

    if super_users:
        message = "Current super users:\n\n"
        for (user_id,) in super_users:
            try:
                user = await client.get_entity(user_id)
                message += f"- {user.first_name} {user.last_name} (ID: {user_id}, Username: @{user.username})\n"
            except Exception as e:
                message += f"- Unknown User (ID: {user_id})\n"
    else:
        message = "There are no super users currently."

    await event.respond(message)

@client.on(events.NewMessage(pattern='/help'))
async def help(event):
    is_admin_user = await is_admin(event.sender_id)
    cursor.execute('SELECT is_super_user FROM users WHERE user_id = ?', (event.sender_id,))
    user_data = cursor.fetchone()
    is_super_user = user_data and user_data[0] if user_data else False

    help_message = "Welcome to Nami's Library Bot! 📚\n\n"
    help_message += "To use this bot, simply type the title or a keyword related to the PDF you're looking for.\n"
    help_message += "I will search the web for relevant PDFs and provide you with a list of options to choose from.\n"
    help_message += "Click on any of the options to get the PDF delivered directly to you.\n"

    if is_super_user:
        help_message += "\nAs a super user, you have unlimited searches! 🌟\n"
    else:
        help_message += f"\nRegular users have a limit of {SEARCH_LIMIT} searches every {RESET_TIME_HOURS} hours.\n"

    if is_admin_user:
        help_message += "\nAdmin Commands:\n"
        help_message += "/addsuperuser <user_id> - Add a super user\n"
        help_message += "/removesuperuser <user_id> - Remove a super user\n"
        help_message += "/listsuperusers - List all super users\n"
        help_message += "/broadcast - Send a message to all users\n"
        help_message += "/stats - View bot statistics\n"

    buttons = [
        [Button.inline("🙏 Donate", data="donate")],
        [Button.url("Developer", "https://t.me/redmoon0x")]
    ]

    await event.respond(help_message, buttons=buttons)

async def is_admin(user_id):
    return user_id == DEVELOPER_ID  # Replace with your admin user ID

@client.on(events.NewMessage(pattern='/broadcast'))
async def broadcast(event):
    if not await is_admin(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return
    
    message_to_broadcast = event.message.text.split(maxsplit=1)[1] if len(event.message.text.split(maxsplit=1)) > 1 else ""
    if not message_to_broadcast:
        await event.respond("Please include a message to broadcast.")
        return
    
    cursor.execute('SELECT user_id FROM users')
    all_users = cursor.fetchall()
    
    failed = 0
    success = 0
    for (user_id,) in all_users:
        try:
            await client.send_message(user_id, message_to_broadcast)
            success += 1
        except Exception as e:
            print(f"Failed to send broadcast to {user_id}: {str(e)}")
            failed += 1
    
    await event.respond(f"Broadcast completed. Successful: {success}, Failed: {failed}")

@client.on(events.NewMessage(pattern='/stats'))
async def stats(event):
    if not await is_admin(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE is_super_user = 1')
    super_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE last_search_time > ?', (datetime.now() - timedelta(days=7),))
    active_users = cursor.fetchone()[0]

    cursor.execute('SELECT SUM(search_count) FROM users')
    total_searches = cursor.fetchone()[0] or 0

    stats_message = (
        f"📊 Bot Statistics 📊\n\n"
        f"Total Users: {total_users}\n"
        f"Total Searches: {total_searches}\n"
        f"Active Users (last 7 days): {active_users}\n"
        f"Super Users: {super_users}\n"
    )

    await event.respond(stats_message)

@client.on(events.NewMessage)
async def message_handler(event):
    await handle_message(event)



@client.on(events.NewMessage(pattern='/speedtest'))
async def speedtest_check(event):
    if event.sender_id != DEVELOPER_ID:  # Check if the user is the developer
        await event.respond("❌ You are not authorized to use this command.")
        return

    st = speedtest.Speedtest()
    st.download()
    st.upload()
    st.get_best_server()
    results = st.results.dict()

    # Format the results for better readability
    formatted_results = {
        "Download Speed": f"{results['download']} bps ({results['download'] / 1000000:.2f} Mbps)",
        "Upload Speed": f"{results['upload']} bps ({results['upload'] / 1000000:.2f} Mbps)",
        "Ping": f"{results['ping']} ms",
        "Server": results['server']['name'],
        "Location": f"{results['server']['country']}, {results['server']['sponsor']}" 
    }

    await event.respond(f"Speedtest Results:\n\n"
                       f"Download Speed: {formatted_results['Download Speed']}\n"
                       f"Upload Speed: {formatted_results['Upload Speed']}\n"
                       f"Ping: {formatted_results['Ping']}\n"
                       f"Server: {formatted_results['Server']}\n"
                       f"Location: {formatted_results['Location']}")
    

def main():
    print("Bot is starting...")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
