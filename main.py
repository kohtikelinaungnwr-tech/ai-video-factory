import os, time, json, urllib.request, subprocess, base64, glob, random, requests
from google import genai
from google.genai import types

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TOKEN_PICKLE_BASE64 = os.environ.get("TOKEN_PICKLE_BASE64")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REVIEW_TIMEOUT_MINUTES = 10

ENABLE_YOUTUBE = True

base_dir = os.path.dirname(os.path.abspath(__file__))
temp_dir = os.path.join(base_dir, 'temp')
output_dir = os.path.join(base_dir, 'output')
db_dir = os.path.join(base_dir, 'database')
token_pickle_file = os.path.join(base_dir, 'token.pickle')

os.makedirs(temp_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)
os.makedirs(db_dir, exist_ok=True)

if TOKEN_PICKLE_BASE64:
    with open(token_pickle_file, 'wb') as f:
        f.write(base64.b64decode(TOKEN_PICKLE_BASE64))

import pickle
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

history_file = os.path.join(db_dir, "used_history.json")

def generate_trending_topic():
    if not os.path.exists(history_file):
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(history_file, "r", encoding="utf-8") as f:
        used_angles = json.load(f)

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    You are a viral YouTube Shorts creator specializing in Dark Psychology, Human Behavior, Body Language, and High-Status Mindset.
    
    Your goal: Generate ONE high-retention, psychology-based viral script for a 20-30 second Short.
    
    Rules:
    1. Stay strictly within the Master Plan: Dark Psychology, Subconscious Tricks, Influence, Stoicism, or Behavioral Secrets.
    2. Strong 3-second Hook at the beginning to stop scrolling.
    3. The script must be between 40 to 55 words (natural 20-25 seconds pace).
    4. Do NOT reuse any of these previously used themes: {used_angles[-15:]}
    5. Return ONLY a valid JSON object without markdown wrappers.
    
    JSON Format:
    {{
      "angle": "THE NAME OF THE EFFECT OR TRICK",
      "title1": "CATCHY TOP HEADER (Max 3-4 words)",
      "title2": "THE SPECIFIC TECHNIQUE NAME",
      "script": "The complete word-by-word voiceover script.",
      "keywords": ["keyword1", "keyword2", "keyword3"]
    }}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    
    data = json.loads(response.text)
    data["id"] = f"AI_{int(time.time())}"
    
    used_angles.append(data["angle"])
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(used_angles, f, indent=4)
        
    return data

def upload_to_youtube(video_path, topic):
    with open(token_pickle_file, 'rb') as token:
        creds = pickle.load(token)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    youtube = build('youtube', 'v3', credentials=creds)

    body = {
        'snippet': {'title': f"{topic['title1']} - {topic['title2']} #Shorts"[:95], 'description': f"{topic['script']}\n\n#shorts #psychology #darkpsychology #mindset #facts", 'categoryId': '27'},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }
    res = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=MediaFileUpload(video_path, resumable=True, mimetype='video/mp4')).execute()
    video_url = f"https://youtube.com/shorts/{res.get('id')}"
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data={'chat_id': TELEGRAM_CHAT_ID, 'text': f"🎉 *YouTube ပေါ်သို့ အောင်မြင်စွာ တင်ပြီးပါပြီ!*\n\n🔗 [Watch Short]({video_url})", 'parse_mode': 'Markdown'})

def build_clean_ass(script, topic, total_dur, ass_path):
    words = script.strip().split()
    chunks = [" ".join(words[i:i + 5]) for i in range(0, len(words), 5)]
    time_per_word = total_dur / max(len(words), 1)
    cur = 0.0
    dialogues = [
        f"Dialogue: 1,0:00:00.00,0:00:03.00,TitleCard,,0,0,0,,{{\\c&H0000FF&}}● {topic['title1']} ●\\N{{\\c&H00FFFF&}}{topic['title2']}",
        "Dialogue: 2,0:00:00.00,0:01:00.00,Watermark,,0,0,0,,@MindsetVault"
    ]
    for chunk in chunks:
        c_dur = len(chunk.split()) * time_per_word
        s_str = f"{int(cur//3600)}:{int((cur%3600)//60):02d}:{int(cur%60):02d}.{int((cur-int(cur))*100):02d}"
        e_str = f"{int((cur+c_dur)//3600)}:{int(((cur+c_dur)%3600)//60):02d}:{int((cur+c_dur)%60):02d}.{int(((cur+c_dur)-int(cur+c_dur))*100):02d}"
        cur += c_dur
        dialogues.append(f"Dialogue: 0,{s_str},{e_str},Subtitles,,0,0,0,,{chunk}")

    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TitleCard,Arial Black,72,&H0000FFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,6,3,5,40,40,0,1
Style: Subtitles,Arial Black,65,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,360,1
Style: Watermark,Arial,35,&H60FFFFFF,&H000000FF,&H40000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,1,8,40,40,150,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(dialogues)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

def generate_video():
    for f in glob.glob(os.path.join(temp_dir, "*")):
        try: os.remove(f)
        except Exception: pass

    topic = generate_trending_topic()
    voice_path = os.path.join(temp_dir, "voice.mp3")
    subprocess.run(f'python -m edge_tts --voice en-US-ChristopherNeural --text "{topic["script"]}" --write-media "{voice_path}"', shell=True, check=True)

    out_dur = subprocess.check_output(f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{voice_path}"', shell=True).decode().strip()
    voice_dur = float(out_dur)
    ass_path = os.path.join(temp_dir, "subtitles.ass")
    build_clean_ass(topic["script"], topic, voice_dur, ass_path)

    headers = {'User-Agent': 'Mozilla/5.0'}
    for idx in range(1, 7):
        img_path = os.path.join(temp_dir, f"img_{idx}.jpg")
        r_seed = random.randint(1000, 999999)
        try:
            req = urllib.request.Request(f"https://picsum.photos/seed/{r_seed}/1080/1920", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp, open(img_path, "wb") as out:
                out.write(resp.read())
        except Exception:
            subprocess.run(f'ffmpeg -f lavfi -i color=c=0x111111:s=1080x1920:d=1 -frames:v 1 "{img_path}" -y', shell=True)

    bgm_path = os.path.join(temp_dir, "bgm.mp3")
    subprocess.run(f'ffmpeg -f lavfi -i "sine=frequency=55:duration=40" -filter:a "volume=0.1" "{bgm_path}" -y', shell=True)

    clip_dur = voice_dur / 6.0
    frames = int(clip_dur * 30)
    clips_txt = os.path.join(temp_dir, "clips.txt")
    with open(clips_txt, "w", encoding="utf-8") as f:
        for i in range(1, 7):
            in_img = os.path.join(temp_dir, f"img_{i}.jpg")
            out_clip = os.path.join(temp_dir, f"clip_{i}.mp4")
            subprocess.run(f'ffmpeg -i "{in_img}" -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z=\'min(zoom+0.0015,1.25)\':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':d={frames}:s=1080x1920:fps=30" -c:v libx264 -pix_fmt yuv420p -frames:v {frames} -y "{out_clip}"', shell=True, check=True)
            f.write(f"file '{out_clip}'\n")

    output_video = os.path.join(output_dir, f"{topic['id']}_{int(time.time())}.mp4")
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
    subprocess.run(f'ffmpeg -f concat -safe 0 -i "{clips_txt}" -i "{voice_path}" -i "{bgm_path}" -filter_complex "[0:v]ass=\'{escaped_ass}\'[v_out];[2:a]volume=0.12[bgm_vol];[1:a][bgm_vol]amix=inputs=2:duration=first[a_out]" -map "[v_out]" -map "[a_out]" -c:v libx264 -c:a aac -b:a 192k -pix_fmt yuv420p -shortest "{output_video}" -y', shell=True, check=True)
    return output_video, topic

while True:
    output_video, topic = generate_video()
    caption = f"🎬 *AI Trending Video Ready!*\n\n📌 *Title:* {topic['title1']} - {topic['title2']}\n\n📝 *Script:*\n{topic['script']}\n\n⏳ {REVIEW_TIMEOUT_MINUTES} မိနစ်အတွင်း မစစ်ပါက Auto တင်ပါမည်။"
    reply_markup = {
        "inline_keyboard": [
            [{"text": "🚀 Publish Now", "callback_data": "btn_publish"}, {"text": "🔄 Regenerate New", "callback_data": "btn_regenerate"}],
            [{"text": "❌ Cancel / Skip", "callback_data": "btn_discard"}]
        ]
    }
    
    with open(output_video, 'rb') as vf:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo", files={'video': vf}, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(reply_markup)})

    start_time = time.time()
    decision = None
    timeout_sec = REVIEW_TIMEOUT_MINUTES * 60
    
    while (time.time() - start_time) < timeout_sec:
        try:
            updates = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", params={"timeout": 5}, timeout=15).json()
            if "result" in updates:
                for item in updates["result"]:
                    requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", params={"offset": item["update_id"] + 1})
                    if "callback_query" in item:
                        action = item["callback_query"].get("data")
                        if action == "btn_publish": decision = "PUBLISH"; break
                        elif action == "btn_regenerate": decision = "REGENERATE"; break
                        elif action == "btn_discard": decision = "DISCARD"; break
            if decision: break
        except Exception: pass
        time.sleep(2)

    if not decision or decision == "PUBLISH":
        upload_to_youtube(output_video, topic)
        break
    elif decision == "REGENERATE":
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data={'chat_id': TELEGRAM_CHAT_ID, 'text': "🔄 AI ဖြင့် နောက်ထပ် အကြောင်းအရာအသစ် ရှာဖွေဖန်တီးနေပါသည်..."})
        continue
    elif decision == "DISCARD":
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data={'chat_id': TELEGRAM_CHAT_ID, 'text': "❌ Cancelled."})
        break
