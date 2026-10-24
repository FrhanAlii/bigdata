"""YouTube Data API v3 helpers, ported from the notebook (cells 9-13)."""
import os
import re

from googleapiclient.discovery import build


def get_client():
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set. Add it to your .env file.")
    return build("youtube", "v3", developerKey=key, cache_discovery=False)


def search_videos(youtube, query, region="PK", max_results=10, order="relevance"):
    response = youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        regionCode=region,
        order=order,
        maxResults=max_results,
    ).execute()

    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "published_at": item["snippet"]["publishedAt"],
            "video_url": "https://www.youtube.com/watch?v=" + item["id"]["videoId"],
        }
        for item in response.get("items", [])
    ]


def get_comments(youtube, video_id, max_comments=100):
    """Top-level comments for one video. Returns (comments, error_or_None)."""
    comments = []
    next_page_token = None
    error = None

    while len(comments) < max_comments:
        remaining = max_comments - len(comments)
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(100, remaining),
            pageToken=next_page_token,
            textFormat="plainText",
        )
        try:
            response = request.execute()
        except Exception as e:  # comments disabled, quota, etc.
            error = str(e)
            break

        for item in response.get("items", []):
            c = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "video_id": video_id,
                "comment_text": c["textDisplay"],
                "published_at": c["publishedAt"],
                "like_count": c["likeCount"],
            })

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return comments, error


def _channel_by(youtube, **kw):
    r = youtube.channels().list(part="snippet,contentDetails", **kw).execute()
    items = r.get("items", [])
    if not items:
        return None
    c = items[0]
    return {"channel_id": c["id"], "title": c["snippet"]["title"],
            "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"]}


def resolve_channel(youtube, text):
    """Accept a channel URL, @handle, channel id (UC...), or plain channel name."""
    text = text.strip()
    m = re.search(r"youtube\.com/channel/(UC[\w-]{20,})", text) or re.fullmatch(r"(UC[\w-]{20,})", text)
    if m:
        ch = _channel_by(youtube, id=m.group(1))
    else:
        m = re.search(r"youtube\.com/@([\w.\-%]+)", text) or re.fullmatch(r"@([\w.\-%]+)", text)
        u = re.search(r"youtube\.com/user/([\w.\-]+)", text)
        if m:
            ch = _channel_by(youtube, forHandle="@" + m.group(1))
        elif u:
            ch = _channel_by(youtube, forUsername=u.group(1))
        else:  # plain name (or /c/ custom url): search for the channel
            q = re.sub(r"^.*youtube\.com/(?:c/)?", "", text)
            r = youtube.search().list(part="snippet", q=q, type="channel", maxResults=1).execute()
            items = r.get("items", [])
            ch = _channel_by(youtube, id=items[0]["snippet"]["channelId"]) if items else None
    if not ch:
        raise RuntimeError(f'Could not find a YouTube channel for "{text}".')
    return ch


def list_channel_videos(youtube, channel, max_results=10):
    r = youtube.playlistItems().list(
        part="snippet,contentDetails", playlistId=channel["uploads"],
        maxResults=min(50, max_results),
    ).execute()
    return [
        {
            "video_id": it["contentDetails"]["videoId"],
            "title": it["snippet"]["title"],
            "channel": channel["title"],
            "published_at": it["contentDetails"].get("videoPublishedAt", it["snippet"]["publishedAt"]),
            "video_url": "https://www.youtube.com/watch?v=" + it["contentDetails"]["videoId"],
        }
        for it in r.get("items", [])
    ]
