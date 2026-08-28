import os
import json
import base64
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
# 2. AI SCRIPT GENERATION (GEMINI)
# ==========================================
def generate_content():
    print("🧠 Generating Psychology Dark Truth Script with Gemini...")
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = """
    Create a highly engaging, viral 30-second YouTube Short / Reel script about Dark Psychology, Human Behavior, or Mind Tricks.
    Return ONLY a valid JSON object with the following structure:
    {
        "title": "A catchy, curiosity-inducing title with hashtags (e.g. 3 Dark Psychology Tricks You Must Know #shorts #mindset)",
        "hook": "An intriguing first sentence that hooks the viewer instantly (max 10 words)",
        "points": [
            "Point 1: Deep psychological insight or fact",
            "Point 2: Deep psychological insight or fact",
            "Point 3: Powerful conclusion or warning"
        ],
        "full_script": "The full spoken voiceover text combining the hook and points naturally."
    }
    """
    
    response = model.generate_content(prompt)
    raw_text = response.text.strip()
    
    # Clean JSON format if markdown wraps it
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:-3].strip()
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:-3].strip()
        
    data = json.loads(raw_text)
    return data

# ==========================================
# 3. TEXT-TO-SPEECH (EDGE-TTS)
# ==========================================
async def generate_voice(text, output_audio_path="voice.mp3"):
    print("🎙️ Generating Voiceover via Edge-TTS...")
    # Using Christopher (Deep engaging US male voice)
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text, voice, rate="+5%", pitch="-2Hz")
    await communicate.save(output_audio_path)
    return output_audio_path

# ==========================================
# 4. VIDEO RENDERING (MOVIEPY)
# ==========================================
def create_video(content, audio_path, output_video_path="final_video.mp4"):
    print("🎬 Rendering Short/Reel Video...")
    audio = AudioFileClip(audio_path)
    duration = audio.duration + 0.5
    
    # Background (Dark aesthetic theme)
    bg = ColorClip(size=(1080, 1920), color=(15, 15, 20), duration=duration)
    
    # Title / Hook Header
    header_text = f"MINDSET VAULT\n{'─'*15}\n{content['hook']}"
    header_clip = TextClip(
        header_text,
        fontsize=48,
        color='gold',
        font='DejaVu-Sans-Bold',
        align='center',
        size=(950, None),
        method='caption'
    ).set_position(('center', 180)).set_duration(duration)
    
    # Spoken Points Body
    body_text = "\n\n".join(content['points'])
    body_clip = TextClip(
        body_text,
        fontsize=42,
        color='white',
        font='DejaVu-Sans',
        align='center',
        size=(920, None),
        method='caption'
    ).set_position(('center', 750)).set_duration(duration)
    
    # Final Composition
    video = CompositeVideoClip([bg, header_clip, body_clip], size=(1080, 1920))
    video = video.set_audio(audio)
    
    video.write_videofile(
        output_video_path,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='ultrafast',
        threads=4
    )
    return output_video_path

# ==========================================
# 5. YOUTUBE SHORTS UPLOAD
# ==========================================
def upload_to_youtube(video_path, title, description):
    if not TOKEN_PICKLE_BASE64:
        print("⚠️ TOKEN_PICKLE_BASE64 not found. Skipping YouTube upload.")
        return None
        
    print("📤 Uploading Video to YouTube Shorts...")
    try:
        creds_json = base64.b64decode(TOKEN_PICKLE_BASE64).decode("utf-8")
        creds_data = json.loads(creds_json)
        credentials = Credentials.from_authorized_user_info(creds_data)
        
        youtube = build("youtube", "v3", credentials=credentials)
        
        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": ["shorts", "psychology", "darkpsychology", "mindset", "facts"],
                "categoryId": "27"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            
        video_id = response.get("id")
        print(f"🎉 YouTube Short Uploaded Successfully! Video URL: https://youtu.be/{video_id}")
        return video_id
    except Exception as e:
        print(f"❌ YouTube Upload Error: {e}")
        return None

# ==========================================
# 6. TELEGRAM NOTIFICATION
# ==========================================
def send_telegram_alert(message):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
        except Exception as e:
            print(f"Telegram notification error: {e}")

# ==========================================
# 7. MAIN ENGINE EXECUTION
# ==========================================
def main():
    try:
        # Step 1: Script
        content = generate_content()
        title = content["title"]
        script = content["full_script"]
        
        # Step 2: Audio
        audio_file = "voice.mp3"
        asyncio.run(generate_voice(script, audio_file))
        
        # Step 3: Video
        video_file = "final_video.mp4"
        create_video(content, audio_file, video_file)
        
        # Step 4: YouTube Upload
        yt_id = upload_to_youtube(video_file, title, script)
        
        # Step 5: Facebook Reels Upload
        print("🚀 Initiating Facebook Reels Upload...")
        fb_success = upload_fb_reel(
            video_path=video_file,
            title=title,
            description=script
        )
        
        # Step 6: Notify Telegram
        status_msg = f"🚀 AI Video Engine Completed!\n\n📌 Title: {title}\n"
        if yt_id:
            status_msg += f"✅ YouTube: https://youtu.be/{yt_id}\n"
        if fb_success:
            status_msg += f"✅ Facebook Reel: Uploaded Successfully!\n"
            
        send_telegram_alert(status_msg)
        print("🎉 ALL PLATFORM TASKS COMPLETED!")
        
    except Exception as e:
        err_msg = f"❌ Engine Failure: {str(e)}"
        print(err_msg)
        send_telegram_alert(err_msg)

if __name__ == "__main__":
    main()
