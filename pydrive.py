import os
import mimetypes
import time
import requests
import asyncio
import json
from tqdm import tqdm
from yt_dlp import YoutubeDL
from telegram import Bot
from telegram.error import TelegramError
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

# === CONFIG ===
DOWNLOAD_DIR = "downloads"
SUCCESS_LOG = "success_links.txt"
FAILED_LOG = "failed_links.txt"
BOT_TOKEN = "your_telegram_bot_token"
CHAT_ID = "your_chat_id"

# === Ensure download directory ===
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_drive():
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    return GoogleDrive(gauth)

def download_file(url, filename):
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            content_type = r.headers.get('content-type', '').split(';')[0]
            ext = mimetypes.guess_extension(content_type)
            if ext and not filename.endswith(ext):
                filename += ext
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            with open(filepath, 'wb') as f, tqdm(total=total, unit='B', unit_scale=True, desc=filename) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    bar.update(len(chunk))
            return filepath
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return None

def choose_format(url):
    with YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        print("Available formats:")
        for f in formats:
            if f.get("vcodec") != "none":
                print(f"{f['format_id']} - {f.get('ext')} - {f.get('format_note')} - {f.get('filesize', 0)} bytes")
        return input("Choose format ID: ")

def download_youtube(url, filename, format_id):
    outtmpl = os.path.join(DOWNLOAD_DIR, filename + ".%(ext)s")
    try:
        ydl_opts = {
            'format': format_id,
            'outtmpl': outtmpl
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        for ext in ['mp4', 'mkv', 'webm']:
            path = os.path.join(DOWNLOAD_DIR, f"{filename}.{ext}")
            if os.path.exists(path):
                return path
    except Exception as e:
        print(f"Failed to download YouTube video: {e}")
        return None

def upload_to_drive(filepath, drive):
    file_drive = drive.CreateFile({'title': os.path.basename(filepath)})
    file_drive.SetContentFile(filepath)
    pbar = tqdm(total=os.path.getsize(filepath), unit='B', unit_scale=True, desc="Uploading")
    file_drive.Upload(progress_callback=lambda c, t: pbar.update(c - pbar.n))
    pbar.close()
    return file_drive['id']

async def send_telegram_log(bot_token, chat_id, success_log, failed_log):
    bot = Bot(token=bot_token)
    text = ""
    if os.path.exists(success_log):
        with open(success_log, 'r') as f:
            text += "✅ Success Links:\n" + f.read() + "\n"
    if os.path.exists(failed_log):
        with open(failed_log, 'r') as f:
            text += "\n❌ Failed Links:\n" + f.read()
    if text:
        await bot.send_message(chat_id=chat_id, text=text[:4096])

def process_line(line, format_id, drive):
    try:
        if ':' in line:
            name, url = line.split(':', 1)
        else:
            url = line.strip()
            name = os.path.basename(url).split('?')[0]

        if 'youtube.com' in url or 'youtu.be' in url:
            downloaded = download_youtube(url, name.strip(), format_id)
        else:
            downloaded = download_file(url.strip(), name.strip())

        if downloaded:
            upload_to_drive(downloaded, drive)
            with open(SUCCESS_LOG, 'a') as f:
                f.write(f"{name}:{url}\n")
        else:
            with open(FAILED_LOG, 'a') as f:
                f.write(f"{name}:{url}\n")

    except Exception as e:
        print(f"Error processing {line}: {e}")
        with open(FAILED_LOG, 'a') as f:
            f.write(f"{line}\n")

def main():
    inp = input("Enter a single URL or path to .txt file: ").strip()
    lines = []
    if os.path.isfile(inp):
        with open(inp, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
    else:
        lines = [inp.strip()]

    format_id = None
    drive = get_drive()
    for line in lines:
        if ('youtube.com' in line or 'youtu.be' in line) and not format_id:
            format_id = choose_format(line.split(':')[-1])
        process_line(line, format_id, drive)

    asyncio.run(send_telegram_log(BOT_TOKEN, CHAT_ID, SUCCESS_LOG, FAILED_LOG))

if __name__ == '__main__':
    main()
