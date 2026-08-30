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
import numpy as np
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
# 2. TELEGRAM APPROVAL SYSTEM (10 Mins)
# ==========================================
def ask_telegram_approval(title, video_path=None, timeout_seconds=600):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Missing Bot Token or Chat ID. Proceeding automatically.")
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
        print(f"[Telegram Preview Error]: {e}")

    print(f"[Telegram] Waiting {timeout_seconds // 60} minutes for approval...")
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
                            requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "🚀 *Approved:* Uploading to YouTube & Facebook..."})
                            return True
                        elif data == "cancel_publish":
                            requests.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": callback["id"], "text": "Cancelled!"})
                            requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "❌ *Cancelled:* Video will NOT be uploaded."})
                            return False
        except Exception as e:
            print(f"[Polling Error]: {e}")
        time.sleep(3)

    requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "⏰ *10 minutes timeout reached.* Auto-publishing to YouTube & Facebook..."})
    return True

def send_telegram_notification(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})

# ==========================================
# 3. AI SCRIPT & PEXELS FETCHER
# ==========================================
def generate_content():
    topics = [
        "Dark Psychology and covert manipulation tricks",
        "Body language secrets that reveal hidden feelings",
        "Psychological tactics to instantly read anyone",
        "Unconscious psychological hacks that influence behavior"
    ]
    chosen_topic = random.choice(topics)
    
    prompt = f"""
    Create a viral 30-second YouTube Short / Reel script about: {chosen_topic}.
    Return strictly JSON format:
    {{
        "title": "Short viral title with hashtags",
        "description": "Engaging description with #Shorts #DarkPsychology #Mindset",
        "search_query": "rain night shadows city abstract",
        "hook": "Extreme hook sentence (max 6 words)",
        "body": ["Point 1 in short punchy words", "Point 2 in short punchy words", "Point 3 in short punchy words"],
        "cta": "Follow for daily psychology hacks."
    }}
    """
    
    selected_model_name = None
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'flash' in m.name:
                    selected_model_name = m.name
                    break
                elif not selected_model_name and 'gemini' in m.name:
                    selected_model_name = m.name
    except Exception as e:
        print(f"[Gemini Model Detection]: {e}")

    if not selected_model_name:
        selected_model_name = "models/gemini-1.5-flash"

    print(f"[Gemini] Using model: {selected_model_name}")
    model = genai.GenerativeModel(selected_model_name)
    response = model.generate_content(prompt)
    clean_text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_text)

def download_background_video(query="dark mood", output_path="bg_video.mp4"):
    """Pexels API မှ Vertical Dark Aesthetic Video ကို စိတ်ချရစွာ ရှာဖွေ ဒေါင်းလုဒ်ဆွဲခြင်း"""
    if not PEXELS_API_KEY:
        print("[Pexels] API Key missing.")
        return None
        
    headers = {"Authorization": PEXELS_API_KEY.strip()}
    
    # စုံစမ်းရှာဖွေမည့် Keywords များ
    search_terms = [query, "dark shadows", "moody night", "rain cinematic", "abstract dark neon"]
    
    for term in search_terms:
        try:
            url = f"https://api.pexels.com/videos/search?query={term}&orientation=portrait&per_page=15"
            r = requests.get(url, headers=headers, timeout=12)
            data = r.json()
            videos = data.get("videos", [])
            
            if videos:
                chosen_video = random.choice(videos)
                video_files = chosen_video.get("video_files", [])
                
                # အသင့်တော်ဆုံး Video file ကို ရွေးချယ်ခြင်း
                selected_file = None
                for vf in video_files:
                    if vf.get("file_type") == "video/mp4" and vf.get("link"):
                        selected_file = vf
                        if vf.get("height", 0) >= 1280:
                            break
                            
                if selected_file:
                    print(f"[Pexels] Downloading video from keyword '{term}'...")
                    v_res = requests.get(selected_file["link"], stream=True, timeout=30)
                    with open(output_path, "wb") as f:
                        for chunk in v_res.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    print("[Pexels] Background video download successful!")
                    return output_path
        except Exception as e:
            print(f"[Pexels Fetch Error for '{term}']: {e}")
            continue

    return None

async def generate_voice(text_script, output_audio_path="voice.mp3"):
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text_script, voice, rate="+7%", pitch="+0Hz")
    await communicate.save(output_audio_path)

# ==========================================
# 4. MASTERPLAN VIRAL VIDEO RENDERER
# ==========================================
def create_engaging_short(content_data, audio_path, bg_video_path=None, output_path="final_video.mp4"):
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration

    # 1. Background Video Setup
    if bg_video_path and os.path.exists(bg_video_path):
        try:
            raw_bg = VideoFileClip(bg_video_path)
            if raw_bg.duration < total_duration:
                loops = int(total_duration / raw_bg.duration) + 1
                raw_bg = raw_bg.fx(vfx.loop, n=loops)
                
            bg_clip = (
                raw_bg.subclip(0, total_duration)
                .resize(height=1920)
                .crop(x_center=raw_bg.w / 2, y_center=raw_bg.h / 2, width=1080, height=1920)
                .fx(vfx.colorx, 0.45) # Dark cinematic contrast
            )
        except Exception as e:
            print(f"[Video Crop Error]: {e}, using dynamic fallback background.")
            bg_clip = ColorClip(size=(1080, 1920), color=(14, 14, 22), duration=total_duration)
    else:
        # Fallback dynamic dark cinematic color
        bg_clip = ColorClip(size=(1080, 1920), color=(14, 14, 22), duration=total_duration)

    # 2. Viral Dynamic Subtitles with Semi-Transparent Highlight Pill
    sections = [content_data["hook"]] + content_data["body"] + [content_data["cta"]]
    time_per_section = total_duration / len(sections)
    
    clips = [bg_clip]
    current_time = 0.0

    for i, section_text in enumerate(sections):
        # Hook = Gold Yellow, Body = High White, CTA = Vibrant Cyan
        if i == 0:
            font_color = '#FFE600'
        elif i == len(sections) - 1:
            font_color = '#00FFFF'
        else:
            font_color = '#FFFFFF'
        
        # Semi-transparent dark pill behind subtitles for 100% readability
        pill_box = (
            ColorClip(size=(960, 420), color=(0, 0, 0), duration=time_per_section)
            .set_opacity(0.60)
            .set_start(current_time)
            .set_position(('center', 'center'))
        )
        
        # High Impact Bold Text
        txt = (
            TextClip(
                section_text.upper(),
                fontsize=58,
                color=font_color,
                font='Liberation-Sans-Bold',
                method='caption',
                size=(900, 380),
                align='center',
                stroke_color='black',
                stroke_width=3
            )
            .set_start(current_time)
            .set_duration(time_per_section)
            .set_position(('center', 'center'))
        )
        clips.extend([pill_box, txt])
        current_time += time_per_section

    final_video = CompositeVideoClip(clips, size=(1080, 1920)).set_audio(audio_clip)
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
# 6. MAIN PIPELINE
# ==========================================
def main():
    print("🚀 [1/5] Generating Content via Gemini...")
    content = generate_content()
    title = content["title"]
    description = content["description"]
    search_query = content.get("search_query", "dark mood")
    full_script = f"{content['hook']} {' '.join(content['body'])} {content['cta']}"

    print(f"🎬 [2/5] Fetching Pexels Background Video for '{search_query}'...")
    bg_video = download_background_video(search_query)

    print("🎙️ [3/5] Generating Voiceover...")
    audio_path = "voice.mp3"
    asyncio.run(generate_voice(full_script, audio_path))

    print("🎨 [4/5] Rendering High-Retention Short Video...")
    video_path = create_engaging_short(content, audio_path, bg_video_path=bg_video)

    print("⏳ [5/5] Sending Preview to Telegram (Waiting 10 mins)...")
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
