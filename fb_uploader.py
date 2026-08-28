import os
import requests
import time

def upload_fb_reel(video_path, title, description=""):
    page_id = os.environ.get("FB_PAGE_ID")
    access_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")

    if not page_id or not access_token:
        print("⚠️ Facebook credentials (FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN) not found. Skipping Facebook Reel upload.")
        return False

    file_size = os.path.getsize(video_path)
    full_description = f"{title}\n\n{description}\n\n#mindset #psychology #darkpsychology #shorts #reels #viral"

    print(f"🚀 Starting Facebook Reel upload to Page: {page_id}...")

    # Step 1: Initialize Upload Session
    init_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
    init_payload = {
        "upload_phase": "start",
        "access_token": access_token
    }
    
    try:
        init_res = requests.post(init_url, data=init_payload).json()
        if "video_id" not in init_res:
            print(f"❌ Facebook Init Error: {init_res}")
            return False
            
        video_id = init_res["video_id"]
        upload_url = init_res.get("upload_url", f"https://rupload.facebook.com/video-upload/v20.0/{video_id}")
        print(f"✅ Session initialized. Video ID: {video_id}")

        # Step 2: Binary Video Data Upload
        headers = {
            "Authorization": f"OAuth {access_token}",
            "offset": "0",
            "file_size": str(file_size)
        }
        
        with open(video_path, "rb") as video_file:
            upload_res = requests.post(upload_url, headers=headers, data=video_file).json()
            
        if not upload_res.get("success", False) and "id" not in upload_res:
            print(f"❌ Video Upload Transfer Error: {upload_res}")
            return False
            
        print("✅ Video binary uploaded successfully. Processing publish step...")

        # Step 3: Publish Reel
        publish_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
        publish_payload = {
            "upload_phase": "finish",
            "access_token": access_token,
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": full_description,
            "title": title
        }
        
        publish_res = requests.post(publish_url, data=publish_payload).json()
        if publish_res.get("success", False):
            print(f"🎉 Facebook Reel published successfully! Video ID: {video_id}")
            return True
        else:
            print(f"❌ Facebook Publish Error: {publish_res}")
            return False

    except Exception as e:
        print(f"❌ Exception during Facebook Reel upload: {e}")
        return False
