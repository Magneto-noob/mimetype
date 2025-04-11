import os, mimetypes, time, requests
from tqdm import tqdm
from yt_dlp import YoutubeDL
from google.colab import files, drive

# === CONFIG ===
DOWNLOAD_DIR = "/content/downloads"
SUCCESS_LOG = "success_links.txt"
FAILED_LOG = "failed_links.txt"
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# === SETUP ===
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def mount_drive():
    drive.mount('/content/drive')
    return '/content/drive/MyDrive/ColabUploads'

def ensure_extension(filename, content_type):
    name, ext = os.path.splitext(filename)
    if ext:
        return filename
    guessed_ext = mimetypes.guess_extension(content_type)
    return filename + guessed_ext if guessed_ext else filename

def get_unique_filename(directory, filename):
    base, ext = os.path.splitext(filename)
    counter = 1
    unique = filename
    while os.path.exists(os.path.join(directory, unique)):
        unique = f"{base}({counter}){ext}"
        counter += 1
    return unique

def sanitize_url(url):
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url.lstrip('/')
    return url

def download_file(url, filename):
    try:
        url = sanitize_url(url)
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            content_type = r.headers.get('content-type', '').split(';')[0]
            filename = ensure_extension(filename, content_type)
            filename = get_unique_filename(DOWNLOAD_DIR, filename)
            path = os.path.join(DOWNLOAD_DIR, filename)
            with open(path, 'wb') as f, tqdm(total=total, unit='B', unit_scale=True, desc=filename) as bar:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
                    bar.update(len(chunk))
            return path
    except Exception as e:
        print(f"Error downloading: {url} -> {e}")
        return None

def choose_format(url):
    with YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        print("Available formats:")
        for f in formats:
            if f.get("vcodec") != "none":
                print(f"{f['format_id']} - {f.get('ext')} - {f.get('format_note')} - {f.get('filesize', 0)} bytes")
        return input("Choose format ID: ").strip()

def download_youtube(url, format_id, is_playlist=False):
    try:
        entries = []
        filenames = []
        options = {
            'format': format_id or 'bestvideo+bestaudio/best',
            'quiet': True,
            'nocheckcertificate': True,
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'noplaylist': not is_playlist,
            'extract_flat': False,
            'ignoreerrors': True,
        }
        with YoutubeDL(options) as ydl:
            result = ydl.extract_info(url, download=False)
            entries = result['entries'] if 'entries' in result else [result]

            for idx, entry in enumerate(entries):
                if not entry:
                    continue
                title = entry.get('title', f'video_{idx+1}')
                num_prefix = f"{idx+1:02d}_" if is_playlist else ""
                filename = get_unique_filename(DOWNLOAD_DIR, f"{num_prefix}{title}.%(ext)s")
                options['outtmpl'] = os.path.join(DOWNLOAD_DIR, filename)
                with YoutubeDL(options) as ydl2:
                    ydl2.download([entry['webpage_url']])
                for ext in ['mp4', 'webm', 'mkv']:
                    candidate = os.path.join(DOWNLOAD_DIR, f"{num_prefix}{title}.{ext}")
                    if os.path.exists(candidate):
                        filenames.append(candidate)
                        break
        return filenames
    except Exception as e:
        print(f"YT download failed: {e}")
        return []

def upload_to_drive(filepath, target_folder):
    os.makedirs(target_folder, exist_ok=True)
    target = os.path.join(target_folder, os.path.basename(filepath))
    with open(filepath, 'rb') as fsrc, open(target, 'wb') as fdst:
        total = os.path.getsize(filepath)
        bar = tqdm(total=total, unit='B', unit_scale=True, desc="Uploading")
        while True:
            chunk = fsrc.read(8192)
            if not chunk:
                break
            fdst.write(chunk)
            bar.update(len(chunk))
        bar.close()
    return target

def send_to_telegram(path):
    try:
        with open(path, 'rb') as f:
            res = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                data={"chat_id": TELEGRAM_CHAT_ID},
                files={"document": f},
                timeout=300
            )
            print("Telegram response:", res.text)
            res.raise_for_status()
            return True
    except Exception as e:
        print(f"Telegram upload failed: {e}")
        return False

def process_link(line, format_id, drive_folder):
    try:
        if ':' in line:
            name, url = line.split(':', 1)
        else:
            url = line.strip()
            name = os.path.basename(url).split('?')[0]

        url = sanitize_url(url)

        if 'youtube.com' in url or 'youtu.be' in url:
            is_playlist = 'list=' in url
            files = download_youtube(url, format_id, is_playlist)
        else:
            file_path = download_file(url, name.strip())
            files = [file_path] if file_path else []

        success = False
        for f in files:
            if f:
                upload_to_drive(f, drive_folder)
                success = True

        with open(SUCCESS_LOG if success else FAILED_LOG, 'a') as log:
            log.write(f"{name.strip()}:{url}\n")
    except Exception as e:
        print(f"Processing error: {e}")
        with open(FAILED_LOG, 'a') as f:
            f.write(f"{line}\n")

def main():
    choice = input("Enter URL or type 'batch' to upload .txt file: ").strip()
    if choice.lower() == 'batch':
        uploaded = files.upload()
        txt_path = next(iter(uploaded))
        with open(txt_path) as f:
            lines = [l.strip() for l in f if l.strip()]
    else:
        lines = [choice.strip()]

    format_id = None
    drive_folder = mount_drive()

    for line in lines:
        if ('youtube.com' in line or 'youtu.be' in line) and not format_id:
            format_id = choose_format(line.split(':')[-1])
        process_link(line, format_id, drive_folder)

    print("\nDownload completed.")
    if os.path.exists(SUCCESS_LOG):
        print("\nSuccess:\n", open(SUCCESS_LOG).read())
        send_to_telegram(SUCCESS_LOG)
        os.remove(SUCCESS_LOG)
    if os.path.exists(FAILED_LOG):
        print("\nFailed:\n", open(FAILED_LOG).read())
        send_to_telegram(FAILED_LOG)
        os.remove(FAILED_LOG)
    if 'txt_path' in locals() and os.path.exists(txt_path):
        os.remove(txt_path)

if __name__ == '__main__':
    main()
