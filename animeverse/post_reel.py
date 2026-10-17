"""Publish a video to a Facebook Page as a Reel via the Graph API.

Needs env vars FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN (a Page token with
pages_manage_posts, pages_read_engagement and pages_show_list).
Set DRY_RUN=1 to skip the upload.

Usage: python post_reel.py clip.mp4 post.json
"""
import json
import os
import sys
import urllib.parse
import urllib.request

API = os.environ.get("FB_GRAPH_VERSION", "v23.0")


def call(url, data=None, headers=None, body=None):
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Facebook API error {e.code}: {e.read().decode()}")


def main():
    video, post_file = sys.argv[1], sys.argv[2]
    with open(post_file) as f:
        post = json.load(f)
    description = post["caption"] + "\n\n" + " ".join(post["tags"] + ["#AnimeVerseHub"])

    if os.environ.get("DRY_RUN") == "1":
        print("DRY RUN, would post:\n" + description)
        return

    page, token = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_ACCESS_TOKEN"]
    base = f"https://graph.facebook.com/{API}/{page}/video_reels"

    start = call(base, {"upload_phase": "start", "access_token": token})
    video_id = start["video_id"]

    with open(video, "rb") as f:
        data = f.read()
    call(start.get("upload_url", f"https://rupload.facebook.com/video-upload/{API}/{video_id}"),
         body=data, headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))})

    done = call(base, {"upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
                       "description": description, "access_token": token})
    print(f"Published Reel {video_id}: {done}")


if __name__ == "__main__":
    main()
