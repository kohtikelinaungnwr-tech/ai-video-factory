import os
import time
import json
import base64
import pickle
import random
import asyncio
import requests
import google.generativeai as genai
import edge_tts
from moviepy.editor import (
    AudioFileClip,
    VideoFileClip,
    CompositeVideoClip,
    TextClip,
    ColorClip,
    vfx
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from fb_uploader import upload_fb_reel

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
TOKEN_PICKLE_BASE64 = os.environ.get("TOKEN_PICKLE_BASE64")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. TELEGRAM APPROVAL SYSTEM
# ==========================================
def ask_telegram_approval(title, video_path=None, timeout_seconds=600):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Config missing. Auto-proceeding.")
        return True

    base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🚀 Publish Now", "callback_data": "publish_now"},
                {"text": "❌ Cancel", "callback_data": "cancel_publish"}
            ]
        ]
    }
    caption_text = (
        f"🎬 *New AI Video Generated!*\n\n"
        f"📌 *Title:* {title}\n\n"
        f"⏳ *Auto-publishing in 10 minutes unless cancelled.*"
    )
    
    try:
        if video_path and os.path.exists(video_path) and os.path.getsize(video_path) < 45 * 1024 * 1024:
            with open(video_path, 'rb') as vf:
                requests.post(
                    f"{base_url}/sendVideo",
                    data={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "caption": caption_text,
                        "parse_mode": "Markdown",
                        "reply_markup": json.dumps(reply_markup)
                    },
                    files={"video": vf}
                )
        else:
            requests.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": caption_text,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup
                }
            )
    except Exception as e:
        print(f"[Telegram Error]: {e}")

    print(f"[Telegram] Waiting {timeout_seconds // 60} mins for approval...")
    start_time = time.time()
    last_update_id = 0
    
    try:
        init_up = requests.get(f"{base_url}/getUpdates").json()
        if init_up.get("result"):
            last_update_id = init_up["result"][-1]["update_id"]
    except Exception:
        pass

    while (time.time() - start_time) < timeout_seconds:
        try:
            res = requests.get(f"{base_url}/getUpdates", params={"offset": last_update_id + 1, "timeout": 5}).json()
            if res.get("result"):
                for item in res["result"]:
                    last_update_id = item["update_id"]
                    if "callback_query" in item:
                        callback = item["callback_query"]
                        data = callback.get("data")
                        if data == "publish_now":
                            requests.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": callback["id"], "text": "Publishing immediately!"})
                            requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "🚀 *Approved:* Uploading..."})
                            return True
                        elif data == "cancel_publish":
                            requests.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": callback["id"], "text": "Cancelled!"})
                            requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "❌ *Cancelled:* Video will NOT be uploaded."})
                            return False
        except Exception as e:
            print(f"[Polling Error]: {e}")
        time.sleep(3)

    requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "⏰ *10 mins timeout reached.* Auto-publishing..."})
    return True

def send_telegram_notification(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})

# ==========================================
# 3. CONTENT & PEXELS VIDEO DOWNLOADER
# ==========================================
def generate_content():
    topics = [
        "Dark Psychology and manipulation tricks people use",
        "Body language secrets that reveal hidden feelings",
        "Psychological tactics to instantly read anyone",
        "Unconscious psychological hacks that influence behavior"
    ]
    chosen_topic = random.choice(topics)
    
    prompt = f"""
    Create an engaging 35-second viral YouTube Short / Reel script about: {chosen_topic}.
    Return strictly JSON schema:
    {{
        "title": "Short viral title with hashtags",
        "description": "Engaging description with #Shorts #DarkPsychology",
        "search_query": "Single search keyword for dark background video (e.g., 'dark mystery', 'cinematic rain', 'shadows', 'cyberpunk city')",
        "hook": "Extreme hook sentence (max 8 words)",
        "body": ["Point 1 concise line", "Point 2 concise line", "Point 3 concise line"],
        "cta": "Follow for more psychology secrets."
    }}
    """
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    clean_text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_text)

def download_background_video(query="dark cinematic", output_path="bg_video.mp4"):
    """Pexels API မှ 9:16 Vertical Dark Background Video ကို Download လုပ်ခြင်း"""
    if not PEXELS_API_KEY:
        print("[Pexels] No API Key found, using fallback background.")
        return None
        
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=10"
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        videos = data.get("videos", [])
        if not videos:
            return None
            
        chosen_video = random.choice(videos)
        video_files = chosen_video.get("video_files", [])
        
        hd_file = next((f for f in video_files if f.get("width") == 1080 and f.get("height") == 1920), None)
        if not hd_file and video_files:
            hd_file = video_files[0]
            
        if hd_file:
            print(f"[Pexels] Downloading video from {hd_file['link']}...")
            v_res = requests.get(hd_file["link"], stream=True, timeout=20)
            with open(output_path, "wb") as f:
                for chunk in v_res.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            return output_path
    except Exception as e:
        print(f"[Pexels Download Error]: {e}")
    return None

async def generate_voice(text_script, output_audio_path="voice.mp3"):
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text_script, voice, rate="+6%", pitch="+0Hz")
    await communicate.save(output_audio_path)

# ==========================================
# 4. HIGH-RETENTION DYNAMIC VIDEO RENDERER
# ==========================================
def create_engaging_short(content_data, audio_path, bg_video_path=None, output_path="final_video.mp4"):
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration

    # Background Setup
    if bg_video_path and os.path.exists(bg_video_path):
        raw_bg = VideoFileClip(bg_video_path)
        if raw_bg.duration < total_duration:
            loops = int(total_duration / raw_bg.duration) + 1
            raw_bg = raw_bg.fx(vfx.loop, n=loops)
            
        bg_clip = (
            raw_bg.subclip(0, total_duration)
            .resize(height=1920)
            .crop(x_center=raw_bg.w / 2, y_center=raw_bg.h / 2, width=1080, height=1920)
            .fx(vfx.colorx, 0.45)  # Darken for contrast
        )
    else:
        bg_clip = ColorClip(size=(1080, 1920), color=(10, 10, 15), duration=total_duration)

    # Dynamic Timed Subtitles
    sections = [content_data["hook"]] + content_data["body"] + [content_data["cta"]]
    time_per_section = total_duration / len(sections)
    
    text_clips = []
    current_time = 0.0

    for i, section_text in enumerate(sections):
        font_color = '#FFE600' if i == 0 else '#FFFFFF'  # Yellow Hook
        
        txt = (
            TextClip(
                section_text.upper(),
                fontsize=58,
                color=font_color,
                font='Arial-Bold',
                method='caption',
                size=(920, 900),
                align='center',
                stroke_color='black',
                stroke_width=3
            )
            .set_start(current_time)
            .set_duration(time_per_section)
            .set_position(('center', 'center'))
        )
        text_clips.append(txt)
        current_time += time_per_section

    final_video = CompositeVideoClip([bg_clip, *text_clips], size=(1080, 1920)).set_audio(audio_clip)
    final_video.write_videofile(
        output_path,
        fps=30,
        codec='libx264',
        audio_codec='aac',
        preset='ultrafast',
        threads=4
    )
    return output_path

# ==========================================
# 5. UPLOADERS
# ==========================================
def get_youtube_service():
    if not TOKEN_PICKLE_BASE64:
        return None
    try:
        token_bytes = base64.b64decode(TOKEN_PICKLE_BASE64)
        try:
            creds_data = json.loads(token_bytes.decode('utf-8'))
            creds = Credentials.from_authorized_user_info(creds_data)
        except Exception:
            creds = pickle.loads(token_bytes)
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"[YouTube Auth Error]: {e}")
        return None

def upload_to_youtube(video_path, title, description):
    youtube = get_youtube_service()
    if not youtube:
        return False, "Auth failed"
    try:
        body = {
            'snippet': {
                'title': title[:100],
                'description': description,
                'tags': ['Shorts', 'DarkPsychology', 'Mindset', 'Facts'],
                'categoryId': '22'
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False
            }
        }
        media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
        response = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media).execute()
        return True, f"https://youtu.be/{response.get('id')}"
    except Exception as e:
        return False, str(e)

# ==========================================
# 6. MAIN EXECUTION PIPELINE
# ==========================================
def main():
    print("🚀 [1/5] Generating Viral Script & Topic via Gemini...")
    content = generate_content()
    title = content["title"]
    description = content["description"]
    search_query = content.get("search_query", "dark mystery")
    full_script = f"{content['hook']} {' '.join(content['body'])} {content['cta']}"

    print(f"🎬 [2/5] Downloading Background Video for '{search_query}'...")
    bg_video = download_background_video(search_query)

    print("🎙️ [3/5] Generating Voiceover...")
    audio_path = "voice.mp3"
    asyncio.run(generate_voice(full_script, audio_path))

    print("🎨 [4/5] Rendering High-Retention Dynamic Short...")
    video_path = create_engaging_short(content, audio_path, bg_video_path=bg_video)

    print("⏳ [5/5] Sending Preview to Telegram & Waiting for Approval (10 mins)...")
    should_publish = ask_telegram_approval(title=title, video_path=video_path, timeout_seconds=600)

    if not should_publish:
        print("❌ Workflow cancelled by user via Telegram.")
        return

    print("🚀 Publishing to YouTube Shorts...")
    yt_success, yt_result = upload_to_youtube(video_path, title, description)

    print("🚀 Publishing to Facebook Reels...")
    fb_success, fb_result = False, "Skipped"
    try:
        fb_success, fb_result = upload_fb_reel(video_path, description)
    except Exception as e:
        fb_result = str(e)

    report_msg = (
        f"🚀 *AI Video Engine Completed!*\n\n"
        f"📌 *Title:* {title}\n"
        f"{'✅ YouTube: ' + yt_result if yt_success else '⚠️ YouTube: ' + yt_result}\n"
        f"{'✅ Facebook Reel: Uploaded Successfully!' if fb_success else '⚠️ Facebook Reel: ' + fb_result}"
    )
    send_telegram_notification(report_msg)
    print("🎉 Pipeline finished successfully!")

if __name__ == "__main__":
    main()
