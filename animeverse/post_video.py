"""Publish a long video (the 7 minute fights) to a Facebook Page via the Graph API.

Needs env vars FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN, same as post_reel.py.
Set DRY_RUN=1 to skip the upload.

Usage: python post_video.py fight.mp4 fight.json
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

API = os.environ.get("FB_GRAPH_VERSION", "v23.0")


def main():
    video, post_file = sys.argv[1], sys.argv[2]
    with open(post_file) as f:
        post = json.load(f)

    if os.environ.get("DRY_RUN") == "1":
        print(f"DRY RUN, would post: {post['title']}\n{post['description']}")
        return

    page, token = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_ACCESS_TOKEN"]
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("access_token", token), ("title", post["title"]), ("description", post["description"])):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    with open(video, "rb") as f:
        data = f.read()
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="fight.mp4"\r\n'
                 f"Content-Type: video/mp4\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(f"https://graph-video.facebook.com/{API}/{page}/videos", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            print(f"Published video: {json.load(r)}")
    except urllib.error.HTTPError as e:
        sys.exit(f"Facebook API error {e.code}: {e.read().decode()}")


if __name__ == "__main__":
    main()
