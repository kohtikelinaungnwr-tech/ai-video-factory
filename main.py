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
    ColorClip,
    CompositeVideoClip,
    TextClip
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from fb_uploader import upload_fb_reel

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TOKEN_PICKLE_BASE64 = os.environ.get("TOKEN_PICKLE_BASE64")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. TELEGRAM INTERACTIVE APPROVAL SYSTEM
# ==========================================
def ask_telegram_approval(title, video_path=None, timeout_seconds=600):
    """
    Telegram သို့ Video Preview နှင့် Inline Buttons များပို့ပြီး ၁၀ မိနစ် စောင့်ဆိုင်းပေးသော စနစ်
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Token or Chat ID not found. Proceeding automatically.")
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
        f"🎬 *New AI Video Ready for Review!*\n\n"
        f"📌 *Title:* {title}\n\n"
        f"⏳ *Auto-publishing in 10 minutes unless cancelled.*"
    )
    
    # Send Video Preview or Message
    try:
        if video_path and os.path.exists(video_path) and os.path.getsize(video_path) < 45 * 1024 * 1024:
            with open(video_path, 'rb') as video_file:
                requests.post(
                    f"{base_url}/sendVideo",
                    data={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "caption": caption_text,
                        "parse_mode": "Markdown",
                        "reply_markup": json.dumps(reply_markup)
                    },
                    files={"video": video_file}
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
        print(f"[Telegram] Failed to send preview: {e}")

    print(f"[Telegram] Waiting {timeout_seconds // 60} minutes for user approval...")

    start_time = time.time()
    last_update_id = 0
    
    # Catch initial update ID
    try:
        init_updates = requests.get(f"{base_url}/getUpdates").json()
        if init_updates.get("result"):
            last_update_id = init_updates["result"][-1]["update_id"]
    except Exception:
        pass

    # Polling for Button Clicks
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
                            requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "🚀 *Approved!* Uploading now..."})
                            return True
                            
                        elif data == "cancel_publish":
                            requests.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": callback["id"], "text": "Cancelled!"})
                            requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "❌ *Cancelled!* Video will NOT be uploaded."})
                            return False
        except Exception as e:
            print(f"[Telegram Polling Error]: {e}")
            
        time.sleep(3)

    # 10 Minutes Timeout Reached -> Auto Approve
    requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "⏰ *10 minutes timeout reached.* Auto-publishing now..."})
    return True

def send_telegram_notification(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"[Telegram] Failed to send notification: {e}")

# ==========================================
# 3. CONTENT GENERATION (GEMINI & TTS)
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
    Create an engaging 45-second YouTube Short / Reel script about: {chosen_topic}.
    Return strictly JSON with the following schema:
    {{
        "title": "Catchy short title with relevant hashtags",
        "description": "Short engaging description with hashtags #Shorts #DarkPsychology #Mindset",
        "hook": "Attention grabbing opening sentence (max 10 words)",
        "body": ["Point 1 explanation", "Point 2 explanation", "Point 3 explanation"],
        "cta": "Closing call to action sentence"
    }}
    """
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    clean_text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_text)

async def generate_voice(text_script, output_audio_path="voice.mp3"):
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text_script, voice, rate="+5%", pitch="+0Hz")
    await communicate.save(output_audio_path)

# ==========================================
# 4. VIDEO RENDERING ENGINE
# ==========================================
def create_short_video(content_data, audio_path, output_video_path="final_video.mp4"):
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    bg_clip = ColorClip(size=(1080, 1920), color=(15, 15, 20), duration=duration)
    
    full_text = f"{content_data['hook']}\n\n" + "\n\n".join(content_data['body']) + f"\n\n{content_data['cta']}"
    
    txt_clip = (
        TextClip(full_text, fontsize=46, color='white', font='Arial-Bold', method='caption', size=(900, 1500), align='center')
        .set_position('center')
        .set_duration(duration)
    )
    
    video = CompositeVideoClip([bg_clip, txt_clip]).set_audio(audio_clip)
    video.write_videofile(output_video_path, fps=30, codec='libx264', audio_codec='aac', preset='ultrafast')
    return output_video_path

# ==========================================
# 5. YOUTUBE UPLOADER
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
        request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
        response = request.execute()
        video_id = response.get('id')
        return True, f"https://youtu.be/{video_id}"
    except Exception as e:
        return False, str(e)

# ==========================================
# 6. MAIN EXECUTION PIPELINE
# ==========================================
def main():
    print("🚀 [1/4] Generating AI Content...")
    content = generate_content()
    title = content["title"]
    description = content["description"]
    full_script = f"{content['hook']} {' '.join(content['body'])} {content['cta']}"

    print("🎙️ [2/4] Generating Voiceover...")
    audio_path = "voice.mp3"
    asyncio.run(generate_voice(full_script, audio_path))

    print("🎬 [3/4] Rendering Video...")
    video_path = create_short_video(content, audio_path)

    # ----------------------------------------------------
    # TELEGRAM APPROVAL WAIT (10 Minutes Timeout)
    # ----------------------------------------------------
    print("⏳ [4/4] Sending Preview to Telegram & Waiting for Approval...")
    should_publish = ask_telegram_approval(title=title, video_path=video_path, timeout_seconds=600)

    if not should_publish:
        print("❌ Workflow cancelled by user via Telegram.")
        return

    # ----------------------------------------------------
    # PUBLISHING TO PLATFORMS
    # ----------------------------------------------------
    print("🚀 Publishing to YouTube Shorts...")
    yt_success, yt_result = upload_to_youtube(video_path, title, description)

    print("🚀 Publishing to Facebook Reels...")
    fb_success, fb_result = False, "Skipped"
    try:
        fb_success, fb_result = upload_fb_reel(video_path, description)
    except Exception as e:
        fb_result = str(e)

    # Final Report Notification
    report_msg = (
        f"🚀 *AI Video Engine Completed!*\n\n"
        f"📌 *Title:* {title}\n"
        f"{'✅ YouTube: ' + yt_result if yt_success else '⚠️ YouTube: ' + yt_result}\n"
        f"{'✅ Facebook Reel: Uploaded Successfully!' if fb_success else '⚠️ Facebook Reel: ' + fb_result}"
    )
    send_telegram_notification(report_msg)
    print("🎉 All tasks finished successfully!")

if __name__ == "__main__":
    main()
