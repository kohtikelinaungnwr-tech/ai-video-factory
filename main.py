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
    CompositeAudioClip,
    TextClip,
    ColorClip,
    concatenate_videoclips,
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

DARK_BGM_URLS = [
    # မိုးသည်းထန်စွာရွာသွန်းသံနှင့် တည်ငြိမ်သောအသံ (Rain Ambient)
    "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8d1d6d95f.mp3?filename=rain-ambient-110397.mp3",
    
    # ရုပ်ရှင်ဆန်ဆန် မှိုင်းညို့ညို့ နောက်ခံအသံ (Ambient Atmospheric)
    "https://cdn.pixabay.com/download/audio/2021/06/07/audio_cdfb955189.mp3?filename=ambient-atmospheric-4947.mp3",
    
    # တိတ်ဆိတ်ငြိမ်သက်သော ရုပ်ရှင်နောက်ခံ သဘာဝအသံ (Dark Gameplay/Ambient)
    "https://cdn.pixabay.com/download/audio/2022/03/09/audio_eb16546260.mp3?filename=ambient-23335.mp3"
]

# --- ADDED: Policy Compliance Blacklist ---
BLOCKED_KEYWORDS = ["manipulate", "destroy", "control people", "coercion", "force someone", "dominance", "threat", "harm"]
MAX_VIDEO_DURATION = 58.0 # Maximum duration for Shorts (in seconds)

# ==========================================
# 2. TELEGRAM INTERACTIVE APPROVAL (10 Mins)
# ==========================================
def ask_telegram_approval(title, video_path=None, timeout_seconds=600):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
                requests.post(f"{base_url}/sendVideo", data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption_text, "parse_mode": "Markdown", "reply_markup": json.dumps(reply_markup)}, files={"video": vf})
        else:
            requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": caption_text, "parse_mode": "Markdown", "reply_markup": reply_markup})
    except Exception:
        pass

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
        except Exception:
            pass
        time.sleep(3)

    try:
        requests.post(f"{base_url}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": "⏰ *10 minutes timeout reached.* Auto-publishing..."}, timeout=10)
    except Exception as e:
        print(f"Telegram API Connection Error ignored: {e}")
    
    return True

def send_telegram_notification(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})


# --- ADDED: Function to check Policy Keywords ---
def is_content_safe(text_to_check):
    text_lower = text_to_check.lower()
    for word in BLOCKED_KEYWORDS:
        if word in text_lower:
            print(f"⚠️ Policy Warning: Blocked keyword '{word}' detected. Regenerating...")
            return False
    return True

# ==========================================
# 3. AI SCRIPT, MULTI-VIDEO & BGM FETCHER
# ==========================================
def generate_content():
    topics = [
        "Dark Psychology facts (Safe influence tactics)",
        "Body language secrets that reveal hidden feelings",
        "Psychological tactics to read anyone instantly",
        "Unconscious psychological hacks to build confidence",
        "Subtle ways to assert presence in any conversation"
    ]
    
    prompt_template = """
    Create a highly engaging 45-second viral YouTube Short / Reel script about: {topic}.
    
    CRITICAL RULES:
    1. DO NOT use markdown formatting, asterisks (*), bolding, or any special characters. Write in plain, spoken English only.
    2. Avoid extreme words like 'manipulate', 'destroy', 'control people', 'dominance', or 'coercion'. Focus on influence, confidence, and reading people safely.
    3. Break down the body into VERY SHORT phrases (max 5 to 8 words per item) so subtitles appear rapidly and dynamic.
    
    Return strictly JSON format:
    {{
        "title": "Short viral title with hashtags",
        "description": "Engaging description with #Shorts #Psychology #Mindset",
        "search_query": "people walking dark cinematic shadows",
        "hook": "Extreme hook sentence (max 6 words)",
        "body": [
            "Short phrase 1 (max 7 words)", 
            "Short phrase 2 (max 7 words)", 
            "Short phrase 3 (max 7 words)",
            "Short phrase 4 (max 7 words)",
            "Short phrase 5 (max 7 words)",
            "Short phrase 6 (max 7 words)"
        ],
        "cta": "Follow for daily psychology hacks."
    }}
    """
    
    selected_model_name = "models/gemini-1.5-flash"
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods and 'flash' in m.name:
                selected_model_name = m.name
                break
    except Exception:
        pass

    model = genai.GenerativeModel(selected_model_name)
    
    max_retries = 5 # Increased retries to handle regeneration if content is unsafe
    for attempt in range(max_retries):
        try:
            chosen_topic = random.choice(topics)
            prompt = prompt_template.format(topic=chosen_topic)
            response = model.generate_content(prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            content_json = json.loads(clean_text)
            
            # --- ADDED: Check if content is safe before returning ---
            full_text_to_check = content_json.get("title", "") + " " + content_json.get("description", "") + " " + " ".join(content_json.get("body", []))
            if is_content_safe(full_text_to_check):
                 return content_json
            else:
                 print(f"🔄 Attempt {attempt + 1}: Unsafe content generated. Retrying generation...")
                 time.sleep(3) # Short pause before retry
                 continue # Loop back and generate again
                 
        except Exception as e:
            print(f"[Gemini API Error] Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print("⏳ Waiting before retrying...")
                time.sleep(20)
            else:
                raise RuntimeError("Failed to generate safe content after maximum retries.")
    
    raise RuntimeError("Failed to generate safe content after maximum retries due to policy restrictions.")

def download_background_videos(query="dark mood", count=3):
    if not PEXELS_API_KEY:
        return []
        
    headers = {"Authorization": PEXELS_API_KEY.strip()}
    search_terms = [query, "dark shadows", "moody night cinematic", "rain cinematic", "dark neon"]
    downloaded_paths = []
    
    for term in search_terms:
        if len(downloaded_paths) >= count: break
        try:
            url = f"https://api.pexels.com/videos/search?query={term}&orientation=portrait&per_page=15"
            r = requests.get(url, headers=headers, timeout=12)
            videos = r.json().get("videos", [])
            random.shuffle(videos)
            
            for v in videos:
                if len(downloaded_paths) >= count: break
                for vf in v.get("video_files", []):
                    if vf.get("file_type") == "video/mp4" and vf.get("link") and vf.get("height", 0) >= 1280:
                        out_path = f"bg_video_{len(downloaded_paths)}.mp4"
                        v_res = requests.get(vf["link"], stream=True, timeout=30)
                        with open(out_path, "wb") as f:
                            for chunk in v_res.iter_content(chunk_size=1024 * 1024):
                                if chunk: f.write(chunk)
                        downloaded_paths.append(out_path)
                        break 
        except Exception:
            continue
    return downloaded_paths

def download_dark_bgm(output_path="bgm.mp3"):
    bgm_url = random.choice(DARK_BGM_URLS)
    try:
        r = requests.get(bgm_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        with open(output_path, 'wb') as f: f.write(r.content)
        return output_path
    except Exception:
        return None

async def generate_voice(text_script, output_audio_path="voice.mp3"):
    communicate = edge_tts.Communicate(text_script, "en-US-ChristopherNeural", rate="+0%", pitch="+0Hz")
    await communicate.save(output_audio_path)

# ==========================================
# 4. VIRAL RETENTION MULTI-SCENE COMPOSER
# ==========================================
def create_engaging_short(content_data, voice_path, bg_video_paths=[], bgm_path=None, output_path="final_video.mp4"):
    voice_clip = AudioFileClip(voice_path)
    total_duration = voice_clip.duration
    
    # --- ADDED: Enforce Maximum Duration (58s) ---
    if total_duration > MAX_VIDEO_DURATION:
        print(f"⚠️ Voiceover is too long ({total_duration}s). Trimming to {MAX_VIDEO_DURATION}s to avoid YouTube Shorts block.")
        total_duration = MAX_VIDEO_DURATION
        voice_clip = voice_clip.subclip(0, total_duration)

    # Audio Mixing
    audio_clips = [voice_clip]
    if bgm_path and os.path.exists(bgm_path):
        try:
            bgm_clip = AudioFileClip(bgm_path)
            bgm_clip = bgm_clip.fx(vfx.loop, duration=total_duration) if bgm_clip.duration < total_duration else bgm_clip.subclip(0, total_duration)
            bgm_clip = bgm_clip.volumex(0.3)
            audio_clips.append(bgm_clip)
        except Exception:
            pass

    final_audio = CompositeAudioClip(audio_clips)

    # Multi-Scene Background Setup
    if bg_video_paths and isinstance(bg_video_paths, list) and len(bg_video_paths) > 0:
        segment_duration = total_duration / len(bg_video_paths)
        bg_clips = []
        for path in bg_video_paths:
            if os.path.exists(path):
                try:
                    raw_bg = VideoFileClip(path)
                    loops = int(segment_duration / raw_bg.duration) + 1 if raw_bg.duration < segment_duration else 1
                    clip = raw_bg.fx(vfx.loop, n=loops).subclip(0, segment_duration)
                    scale = max(1080 / clip.w, 1920 / clip.h)
                    clip = clip.resize(scale).crop(x_center=clip.resize(scale).w / 2, y_center=clip.resize(scale).h / 2, width=1080, height=1920).fx(vfx.colorx, 1.05)
                    bg_clips.append(clip)
                except Exception as e:
                    print(f"Error processing {path}: {e}")
        
        if bg_clips:
            bg_clip = concatenate_videoclips(bg_clips, method="compose").subclip(0, total_duration)
        else:
            bg_clip = ColorClip(size=(1080, 1920), color=(14, 14, 22), duration=total_duration)
    else:
        bg_clip = ColorClip(size=(1080, 1920), color=(14, 14, 22), duration=total_duration)

    clips = [bg_clip]
    
    # 1. MINDSET VAULT Watermarks
    wm_top = (
        TextClip("MINDSET VAULT", fontsize=45, color='white', font='Liberation-Sans-Bold', stroke_color='black', stroke_width=2)
        .set_opacity(0.35)
        .set_position(('center', 250))
        .set_duration(total_duration)
    )
    wm_bottom = (
        TextClip("MINDSET VAULT", fontsize=45, color='white', font='Liberation-Sans-Bold', stroke_color='black', stroke_width=2)
        .set_opacity(0.35)
        .set_position(('center', 1600))
        .set_duration(total_duration)
    )
    clips.extend([wm_top, wm_bottom])

    # 2. Viral Subtitles
    sections = [content_data["hook"]] + content_data["body"] + [content_data["cta"]]
    time_per_section = total_duration / len(sections)
    current_time = 0.0

    for i, section_text in enumerate(sections):
        font_color = '#FFE600' if i == 0 else ('#00F2FE' if i == len(sections) - 1 else '#FFFFFF')
        
        pill_box = ColorClip(size=(1000, 480), color=(0, 0, 0), duration=time_per_section).set_opacity(0.55).set_start(current_time).set_position(('center', 'center'))
        
        txt = (
            TextClip(
                section_text.upper(),
                fontsize=75,
                color=font_color,
                font='Liberation-Sans-Bold',
                method='caption',
                size=(960, 450),
                align='center',
                stroke_color='black',
                stroke_width=6
            )
            .set_start(current_time)
            .set_duration(time_per_section)
            .set_position(('center', 'center'))
        )
        clips.extend([pill_box, txt])
        current_time += time_per_section

    final_video = CompositeVideoClip(clips, size=(1080, 1920)).set_audio(final_audio)
    
    # --- ADDED: Final Safeguard check on final render duration ---
    if final_video.duration > MAX_VIDEO_DURATION:
         final_video = final_video.subclip(0, MAX_VIDEO_DURATION)
         
    final_video.write_videofile(output_path, fps=30, codec='libx264', audio_codec='aac', preset='ultrafast', threads=4)
    return output_path

# ==========================================
# 5. UPLOADERS
# ==========================================
def get_youtube_service():
    if not TOKEN_PICKLE_BASE64: return None
    try:
        token_bytes = base64.b64decode(TOKEN_PICKLE_BASE64)
        try:
            creds = Credentials.from_authorized_user_info(json.loads(token_bytes.decode('utf-8')))
        except Exception:
            creds = pickle.loads(token_bytes)
        return build('youtube', 'v3', credentials=creds)
    except Exception:
        return None

def upload_to_youtube(video_path, title, description):
    youtube = get_youtube_service()
    if not youtube: return False, "Auth failed"
    try:
        body = {'snippet': {'title': title[:100], 'description': description, 'tags': ['Shorts', 'DarkPsychology', 'Mindset', 'Facts'], 'categoryId': '22'}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
        media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
        response = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media).execute()
        return True, f"https://youtu.be/{response.get('id')}"
    except Exception as e:
        return False, str(e)

# ==========================================
# 6. MAIN PIPELINE
# ==========================================
def main():
    print("🚀 [1/6] Generating Safe Content...")
    content = generate_content()
    
    print("🎬 [2/6] Fetching Multi-Scene Background Videos...")
    bg_videos = download_background_videos(content.get("search_query", "dark moody shadows"), count=3)

    print("🎵 [3/6] Fetching BGM...")
    bgm_path = download_dark_bgm()

    print("🎙️ [4/6] Generating Voiceover...")
    asyncio.run(generate_voice(f"{content['hook']} {' '.join(content['body'])} {content['cta']}", "voice.mp3"))

    print("🎨 [5/6] Rendering Multi-Scene Video (Max 58s)...")
    video_path = create_engaging_short(content, "voice.mp3", bg_video_paths=bg_videos, bgm_path=bgm_path)

    print("⏳ [6/6] Telegram Approval...")
    if not ask_telegram_approval(content["title"], video_path, 600):
        return

    print("🚀 Uploading to YouTube & Facebook...")
    yt_success, yt_result = upload_to_youtube(video_path, content["title"], content["description"])
    
    fb_success, fb_result = False, "Skipped"
    try:
        result = upload_fb_reel(video_path, content["description"])
        if isinstance(result, tuple) and len(result) == 2:
            fb_success, fb_result = result
        else:
            fb_success = bool(result)
            fb_result = "Uploaded Successfully!" if fb_success else "Upload Failed"
    except Exception as e:
        fb_success = False
        fb_result = str(e)

    report_msg = f"🚀 *Completed!*\n📌 *Title:* {content['title']}\n{'✅ YT: ' + yt_result if yt_success else '⚠️ YT: ' + yt_result}\n{'✅ FB: ' + fb_result if fb_success else '⚠️ FB: ' + fb_result}"
    send_telegram_notification(report_msg)
    print("🎉 Done!")

if __name__ == "__main__":
    main()
