# AnimeVerse Hub: automatic Reels

Every 4 hours a GitHub Action makes a new **original anime story short** (a 45–60 second Reel, 1080x1920) and posts it to the AnimeVerse Hub Facebook Page.

- `story.py`: writes and animates the story. It invents two characters each time (name, hair, eyes, outfit, accessory) and picks a genre (fantasy, school, sci-fi or spirit mystery) and a setting. It builds a seven-beat plot from a built-in bank of story pieces, with a looming villain in most genres. The story plays visual-novel style: the characters blink, talk and react, and it adds narration, effects, music and per-character voice blips. Everything is drawn and generated from scratch, so there is no copyrighted footage or audio, and no AI service or API key is needed. To add variety, add more options to the `GENRES` bank at the top of the file.
- `art/chars/`: the recurring cast, generated as AI art in a realistic Korean-webtoon style and cut out of a green background by `art/key.py`. Fantasy has Kael, Seris and Riven, school has Haruto, Aoi and Mina, and sci-fi has Nova, Rook and Iris. Spirit mystery so far has only Shiro, the fox spirit. Each story picks two from one genre. The speaker steps forward and lights up, the other dims, and there's breathing and talk bounce, a power glow, camera shake and a smoky villain. A genre is only used once it has at least two characters, so spirit mystery is skipped until Ren or Sayo is added. To add a character, put a waist-up PNG on a flat green background in `art/raw/`, run `python art/key.py`, and add it to `CAST` in `story.py`.
- `post_reel.py`: uploads the clip as a Reel through the Facebook Graph API.
- `../.github/workflows/animeverse-reels.yml` ("AnimeVerse Hub Story Shorts"): the every-4-hours schedule.
- `make_clip.py` and `content.json`: the old 12-second quote Reels. They're no longer scheduled; to switch back, change the workflow's render step to `python make_clip.py --out clip.mp4`.

It also posts a **7 minute fight video** every 4 hours, half-way between the Reels:

- `fight.py`: makes a random best-of-three fight. Each video is either a power battle with energy blasts and beam clashes or a silhouette sword duel (the stick figure style only runs with `--style stick`), plus two fighter names and a new choreography. It also adds health bars, round cards, a K.O. screen, battle music and sound effects, all generated from scratch.
- `post_video.py`: uploads it as a regular Page video. Facebook only allows Reels up to 90 seconds.
- `../.github/workflows/animeverse-fights.yml`: the schedule. To make one by hand, use **Run workflow** and pick a style, or tick "dry run" to only render it.

Preview a short one locally: `python fight.py --style sword --duration 60 --out fight.mp4`.

## One-time setup (about 15 minutes)

1. Go to https://developers.facebook.com, choose **My Apps → Create App**, and pick the **Business** type.
2. Open **Tools → Graph API Explorer**. Select your app, then **Get Page Access Token**. Grant these permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`. Choose AnimeVerse Hub.
3. Turn it into a token that doesn't expire:
   - Swap it for a long-lived user token: `GET /oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN`
   - Then call `GET /me/accounts?access_token=LONG_USER_TOKEN`. The `access_token` listed for AnimeVerse Hub is a Page token that never expires. Also copy its `id`.
4. In this GitHub repo, go to **Settings → Secrets and variables → Actions** and add:
   - `FB_PAGE_ID`: the Page id
   - `FB_PAGE_ACCESS_TOKEN`: the Page token
5. Merge this into the default branch. Scheduled workflows only run from the default branch.
6. Test it under **Actions → AnimeVerse Hub Story Shorts → Run workflow**. Tick "dry run" to only render; you can download the clip from the run.

If either secret is missing, the run fails with a red X instead of quietly posting nothing.

Preview locally: `python story.py --seed 1 --out clip.mp4` (needs ffmpeg, Pillow and numpy).

## Making money: what you still have to do yourself

Facebook decides who gets paid, and these steps happen in the app. They can't be automated.

- **Get eligible.** Open **Professional Dashboard → Monetization** to see which programs you qualify for and what's still missing. Facebook's content monetization program (Reels/video earnings) is invite or apply based. Stars and subscriptions usually need a follower count and some recent engagement. Facebook changes the exact thresholds, so check that page rather than relying on a number here.
- **Grow followers.** At 3 followers, this is the real bottleneck. Posting every day helps, and so does replying to every comment. The clips are written to ask questions on purpose. Share the Reels into anime Facebook groups where the group rules allow it. Pin your best post.
- **Avoid strikes.** Don't post clips ripped from anime. Copyright claims block monetization. That's why this generator makes original animation.
- **Affiliate links.** You can add affiliate links (Crunchyroll, manga, figures) to post captions or the Page's About section once you join those programs.
- **"Advertise" / "Grow your business"** in the app means paying Facebook. Skip it until you have something to sell.
