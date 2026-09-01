#!/usr/bin/env python3
"""Refresh the Manga Spark Radar with a small, playable weekly sample.

The site is intentionally static. This script is the scheduled build step used
by GitHub Actions: it discovers recent uploads from the configured channels,
checks YouTube playability, ranks candidates by recency and views, and rewrites
the inline `videos` array while keeping exactly 30 records.

No API key is required. YouTube's public Atom feed discovers uploads and the
watch page supplies duration, view count, and playability status. If a request
fails transiently, the previous record is retained rather than deleting the
whole catalogue. A record is removed only when YouTube explicitly reports it
as unavailable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = SITE_ROOT / "index.html"
CONFIG_PATH = SITE_ROOT / "config" / "channels.json"
STORY_NODES_PATH = SITE_ROOT / "story_nodes.json"
STORYBOARDS_PATH = SITE_ROOT / "storyboards.json"
COVERS_DIR = SITE_ROOT / "assets" / "covers"
USER_AGENT = "Mozilla/5.0 (compatible; MangaSparkRadarBot/1.0; +https://github.com/)"
ATOM = "{http://www.w3.org/2005/Atom}"

TAG_RULES = {
    "system": "系统",
    "apocalypse": "末日",
    "cultivat": "修仙",
    "immortal": "修仙",
    "reborn": "重生",
    "reincarnat": "重生",
    "beast": "异兽",
    "monster": "异兽",
    "evolv": "进化",
    "dragon": "巨龙",
    "revenge": "复仇",
    "zombie": "丧尸",
    "ninja": "忍者",
    "harem": "群像",
    "empire": "经营",
    "business": "经营",
    "surviv": "生存",
    "god": "弑神",
}


class FetchError(RuntimeError):
    """A transient network or parsing failure; do not delete old data."""


def fetch_text(url: str, timeout: int = 12) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "ignore")
    except Exception as exc:  # pragma: no cover - depends on network
        raise FetchError(str(exc)) from exc


def fetch_bytes(url: str, timeout: int = 12) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:  # pragma: no cover - depends on network
        raise FetchError(str(exc)) from exc


def parse_iso_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def relative_age(published: dt.date, today: dt.date) -> str:
    days = max(0, (today - published).days)
    if days == 0:
        return "今天"
    if days == 1:
        return "1 天前"
    if days < 7:
        return f"{days} 天前"
    weeks = max(1, days // 7)
    return f"{weeks} 周前"


def duration_text(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def discover_channel_id(channel: dict) -> str:
    if channel.get("channel_id"):
        return str(channel["channel_id"])
    handle = channel.get("handle")
    if not handle:
        raise FetchError(f"channel {channel.get('name', '?')} has no handle or channel_id")
    page = fetch_text(f"https://www.youtube.com/{handle}/videos")
    patterns = (
        r'"channelId":"(UC[\w-]+)"',
        r'"externalId":"(UC[\w-]+)"',
        r"/channel/(UC[\w-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, page)
        if match:
            return match.group(1)
    raise FetchError(f"channel id not found for {handle}")


def parse_feed(xml_text: str, source: str, limit: int) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"invalid channel feed: {exc}") from exc
    rows: list[dict] = []
    for entry in root.findall(f"{ATOM}entry")[:limit]:
        video_id = entry.findtext(f"{ATOM}id", "").rsplit(":", 1)[-1]
        title = html.unescape(entry.findtext(f"{ATOM}title", "").strip())
        published = entry.findtext(f"{ATOM}published", "").strip()
        published_date = parse_iso_date(published)
        if not video_id or not title or not published_date:
            continue
        rows.append(
            {
                "id": video_id,
                "original": title,
                "source": source,
                "published_date": published_date,
            }
        )
    return rows


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def renderer_text(value: dict | None) -> str:
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    if isinstance(value.get("content"), str):
        return value["content"]
    return "".join(run.get("text", "") for run in value.get("runs", []) if isinstance(run, dict))


def relative_publish_date(value: str, today: dt.date) -> dt.date:
    lowered = value.lower().strip()
    match = re.search(r"(\d+)\s+(minute|hour|day|week|month|year)", lowered)
    if not match:
        return today
    amount = int(match.group(1))
    unit = match.group(2)
    days = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}[unit]
    return today - dt.timedelta(days=amount * days)


def parse_channel_page(page: str, source: str, limit: int, today: dt.date) -> list[dict]:
    marker = "var ytInitialData = "
    start = page.find(marker)
    if start < 0:
        raise FetchError("ytInitialData not found on channel page")
    try:
        data, _ = json.JSONDecoder().raw_decode(page[start + len(marker) :])
    except json.JSONDecodeError as exc:
        raise FetchError(f"invalid channel page data: {exc}") from exc

    rows: list[dict] = []
    seen: set[str] = set()
    for node in walk_json(data):
        renderer = node.get("videoRenderer")
        if isinstance(renderer, dict):
            video_id = renderer.get("videoId")
            title = renderer_text(renderer.get("title"))
            relative = renderer_text(renderer.get("publishedTimeText"))
        else:
            lockup = node.get("lockupViewModel")
            if not isinstance(lockup, dict) or lockup.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
                continue
            video_id = lockup.get("contentId")
            metadata = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
            title = renderer_text(metadata.get("title"))
            parts = metadata.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
            relative = ""
            for part in walk_json(parts):
                content = renderer_text(part.get("text"))
                if " ago" in content.lower() or content.lower().startswith(("streamed ", "premiered ")):
                    relative = content
                    break
        if not video_id or not title or video_id in seen:
            continue
        seen.add(video_id)
        rows.append(
            {
                "id": video_id,
                "original": html.unescape(title),
                "source": source,
                "published_date": relative_publish_date(relative, today),
            }
        )
        if len(rows) >= limit:
            break
    if not rows:
        raise FetchError("no videos found on channel page")
    return rows


def extract_json_string(page: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}":"((?:\\.|[^"\\])*)"', page)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        return match.group(1)


def watch_metadata(row: dict) -> tuple[dict | None, str]:
    """Return metadata and one of ok/invalid/error."""
    try:
        page = fetch_text(f"https://www.youtube.com/watch?v={row['id']}")
    except FetchError:
        return None, "error"

    playability_start = page.find('"playabilityStatus"')
    playability = page[playability_start : playability_start + 5000] if playability_start >= 0 else ""
    status_match = re.search(r'"status"\s*:\s*"([A-Z_]+)"', playability)
    status = status_match.group(1) if status_match else None
    if status and status != "OK":
        return None, "invalid"
    if not status and '"videoDetails"' not in page:
        return None, "error"

    duration_raw = extract_json_string(page, "lengthSeconds")
    views_raw = extract_json_string(page, "viewCount")
    try:
        duration = int(duration_raw or 0)
        views = int(views_raw or 0)
    except ValueError:
        return None, "error"
    if duration <= 0:
        return None, "error"

    title = extract_json_string(page, "title") or row["original"]
    published = parse_iso_date(extract_json_string(page, "publishDate") or extract_json_string(page, "uploadDate"))
    metadata = {**row, "original": html.unescape(title), "duration": duration, "views": views}
    if published:
        metadata["published_date"] = published
    return metadata, "ok"


def existing_videos() -> list[dict]:
    source = INDEX_PATH.read_text(encoding="utf-8")
    marker = "const videos=["
    start = source.find(marker)
    if start < 0:
        raise RuntimeError("const videos=[ not found in index.html")
    end = source.find("];", start)
    if end < 0:
        raise RuntimeError("videos array terminator not found in index.html")
    literal = source[start + len("const videos=") : end + 1]
    # After the first scheduled run the array is emitted as valid JSON. Read
    # that form first so subsequent weekly runs retain the existing editorial
    # Chinese copy as their fallback records.
    try:
        parsed = json.loads(literal)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        rows: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict) or not item.get("id") or not item.get("published"):
                continue
            try:
                published_date = dt.date.fromisoformat(str(item["published"]))
            except ValueError:
                continue
            rows.append({**item, "published_date": published_date})
        return rows
    # The checked-in array uses JavaScript object syntax with unquoted keys and
    # single quotes, so extract only the fields needed for fallback records.
    rows: list[dict] = []
    pattern = re.compile(
        r"\{id:'(?P<id>[^']+)',title:'(?P<title>(?:\\.|[^'])*)',original:'(?P<original>(?:\\.|[^'])*)',"
        r"source:'(?P<source>[^']+)',duration:(?P<duration>\d+),durationText:'(?P<duration_text>[^']+)',"
        r"views:(?P<views>\d+),age:'(?P<age>[^']*)',published:'(?P<published>\d{4}-\d{2}-\d{2})',"
    )
    for match in pattern.finditer(literal):
        row = match.groupdict()
        rows.append(
            {
                "id": row["id"],
                "title": row["title"],
                "original": row["original"],
                "source": row["source"],
                "duration": int(row["duration"]),
                "durationText": row["duration_text"],
                "views": int(row["views"]),
                "age": row["age"],
                "published": row["published"],
                "published_date": dt.date.fromisoformat(row["published"]),
            }
        )
    return rows


def tags_for(title: str) -> list[str]:
    lowered = title.lower()
    tags: list[str] = []
    for keyword, tag in TAG_RULES.items():
        if keyword in lowered and tag not in tags:
            tags.append(tag)
    return tags[:3] or ["漫剧"]


def editorial_copy(title: str, tags: list[str]) -> tuple[str, str, str]:
    if "系统" in tags:
        return (
            "系统机制在标题中直接亮相，规则清晰、点击门槛低。",
            "先用低位处境制造压力，再让系统给出第一项可见能力。",
            "系统的下一次奖励和隐藏代价，会推动观众继续观看。",
        )
    if "末日" in tags:
        return (
            "灾难场景提供即时视觉压力，生存目标容易被快速理解。",
            "先交代资源或安全区倒计时，再展示主角的破局手段。",
            "下一轮灾难会把生存边界推到哪里，是核心留存问题。",
        )
    if "重生" in tags or "复仇" in tags:
        return (
            "失去一切后的归来与反击目标明确，情绪入口集中。",
            "先兑现羞辱或损失，再逐步揭开主角保留的底牌。",
            "复仇对象和前世真相何时公开，会形成连续追看动力。",
        )
    return (
        f"“{title[:24]}”提供清晰的身份或能力反差，适合做开场钩子。",
        "先让主角遭遇具体阻碍，再用一次可见变化证明故事规则。",
        "新的能力、敌人或身份线索会把观众带向下一次冲突。",
    )


def score_for(views: int, age_days: int) -> int:
    # This is an editorial ordering score, not a YouTube metric.
    score = 76 + math.log10(max(views, 1) + 1) * 4 + max(0, 7 - age_days) * 0.55
    return max(70, min(99, round(score)))


def normalise(row: dict, today: dt.date) -> dict:
    published_date = row.get("published_date") or dt.date.fromisoformat(row["published"])
    title = row.get("title") or row.get("original", "未命名漫剧")
    original = row.get("original", title)
    tags = row.get("tags") or tags_for(original)
    hook, rise, promise = editorial_copy(title, tags)
    age_days = max(0, (today - published_date).days)
    views = int(row.get("views", 0) or 0)
    return {
        "id": row["id"],
        "title": title,
        "original": original,
        "source": row.get("source", "未知频道"),
        "duration": int(row.get("duration", 0) or 0),
        "durationText": row.get("durationText") or duration_text(int(row.get("duration", 0) or 0)),
        "views": views,
        "age": row.get("age") or relative_age(published_date, today),
        "published": published_date.isoformat(),
        "tags": tags,
        "score": int(row.get("score") or score_for(views, age_days)),
        "hook": row.get("hook") or hook,
        "rise": row.get("rise") or rise,
        "promise": row.get("promise") or promise,
    }


def rank_key(video: dict, today: dt.date, recent_days: int) -> tuple:
    published = dt.date.fromisoformat(video["published"])
    age_days = max(0, (today - published).days)
    recent = age_days <= recent_days
    # Recent uploads are considered first; among them, views per day wins.
    velocity = video["views"] / max(1, age_days + 1)
    return (1 if recent else 0, velocity, video["views"], video["score"], published)


def choose_sample(pool: list[dict], today: dt.date, sample_size: int, recent_days: int, min_views: int) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in pool:
        unique.setdefault(item["id"], item)
    rows = list(unique.values())
    eligible = [item for item in rows if item["views"] >= min_views]
    if len(eligible) < sample_size:
        # Keep the fixed size even during a quiet week, but use low-view items
        # only after every sufficiently popular candidate has been exhausted.
        eligible = rows
    eligible.sort(key=lambda item: rank_key(item, today, recent_days), reverse=True)
    return eligible[:sample_size]


def replace_videos_array(source: str, videos: list[dict]) -> str:
    marker = "const videos=["
    start = source.find(marker)
    if start < 0:
        raise RuntimeError("const videos=[ not found in index.html")
    array_start = start + len("const videos=")
    array_end = source.find("];", array_start)
    if array_end < 0:
        raise RuntimeError("videos array terminator not found in index.html")
    literal = json.dumps(videos, ensure_ascii=False, indent=2)
    return source[:array_start] + literal + source[array_end + 1 :]


def update_snapshot_labels(source: str, snapshot: str) -> str:
    source = re.sub(r"const DATA_SNAPSHOT='[^']*';", f"const DATA_SNAPSHOT='{snapshot}';", source, count=1)
    source = re.sub(r"最近一次快照：<span id=\"snapshotDate\">[^<]*</span>", f"最近一次快照：<span id=\"snapshotDate\">{snapshot}</span>", source, count=1)
    source = re.sub(r"<span id=\"snapshotDateHero\">[^<]*</span>", f"<span id=\"snapshotDateHero\">{snapshot.replace('-', '.')}</span>", source, count=1)
    source = re.sub(r"story_nodes\.json\?v=[^']+", f"story_nodes.json?v={snapshot}-zh", source, count=1)
    source = re.sub(r"storyboards\.json\?v=[^']+", f"storyboards.json?v={snapshot}", source, count=1)
    return source


def prune_asset(path: Path, selected_ids: set[str]) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, dict):
        trimmed = {key: value for key, value in data.items() if key in selected_ids}
        path.write_text(json.dumps(trimmed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def sync_covers(selected_ids: set[str]) -> None:
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for cover in COVERS_DIR.glob("*.jpg"):
        if cover.stem not in selected_ids:
            cover.unlink()
    for video_id in sorted(selected_ids):
        destination = COVERS_DIR / f"{video_id}.jpg"
        if destination.exists() and destination.stat().st_size >= 1500:
            continue
        try:
            data = fetch_bytes(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
            if len(data) < 1500:
                raise FetchError("thumbnail response is only a placeholder")
            destination.write_bytes(data)
        except FetchError as exc:
            print(f"warning: cover {video_id}: {exc}", file=sys.stderr)


def collect_candidates(config: dict, existing: list[dict], today: dt.date) -> list[dict]:
    pool_limit = int(config.get("pool_per_channel", 35))
    candidates: list[dict] = []
    existing_by_id = {item["id"]: item for item in existing}
    for channel in config.get("channels", []):
        try:
            channel_id = discover_channel_id(channel)
            feed = fetch_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}")
            feed_rows = parse_feed(feed, channel["name"], pool_limit)
        except FetchError as exc:
            print(f"warning: {channel.get('name', '?')} RSS: {exc}; trying channel page", file=sys.stderr)
            try:
                page = fetch_text(f"https://www.youtube.com/{channel['handle']}/videos")
                feed_rows = parse_channel_page(page, channel["name"], pool_limit, today)
            except (FetchError, KeyError) as page_exc:
                print(f"warning: {channel.get('name', '?')} page: {page_exc}", file=sys.stderr)
                continue
        for row in feed_rows:
            metadata, status = watch_metadata(row)
            if status == "invalid":
                print(f"drop unavailable: {row['id']} ({row['original'][:70]})", file=sys.stderr)
                continue
            if status == "ok" and metadata:
                # Keep the operator's Chinese title and editorial copy when an
                # existing sample is still present in this week's feed.
                old = existing_by_id.get(row["id"])
                if old:
                    metadata = {**old, **metadata, "title": old.get("title", metadata["original"]),
                                "tags": old.get("tags"), "score": old.get("score"),
                                "hook": old.get("hook"), "rise": old.get("rise"), "promise": old.get("promise")}
                candidates.append(normalise(metadata, today))
            # A transient error is ignored here; the previous catalogue below
            # remains available as a safe fallback.
            time.sleep(0.08)

    # Validate existing entries as well. Only an explicit non-OK playability
    # response removes them; network failures retain the previous record.
    for old in existing:
        row = {
            "id": old["id"],
            "original": old.get("original", old.get("title", "")),
            "source": old.get("source", ""),
            "published_date": dt.date.fromisoformat(old["published"]),
        }
        metadata, status = watch_metadata(row)
        if status == "invalid":
            print(f"drop unavailable existing: {old['id']}", file=sys.stderr)
            continue
        if status == "ok" and metadata:
            # Keep the editorial Chinese copy already written by the operator.
            merged = {**old, **metadata, "title": old.get("title", metadata["original"])}
            candidates.append(normalise(merged, today))
        else:
            candidates.append(normalise(old, today))
        time.sleep(0.08)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="discover and print the next sample without writing files")
    parser.add_argument("--today", help="override run date (YYYY-MM-DD), useful for tests")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    existing = existing_videos()
    pool = collect_candidates(config, existing, today)
    selected = choose_sample(
        pool,
        today,
        int(config.get("sample_size", 30)),
        int(config.get("recent_days", 7)),
        int(config.get("min_views", 200)),
    )
    if len(selected) < int(config.get("sample_size", 30)):
        raise RuntimeError(f"only {len(selected)} playable candidates; refusing to publish a short sample")

    if args.dry_run:
        print(json.dumps(selected, ensure_ascii=False, indent=2))
        return 0

    source = INDEX_PATH.read_text(encoding="utf-8")
    source = replace_videos_array(source, selected)
    source = update_snapshot_labels(source, today.isoformat())
    INDEX_PATH.write_text(source, encoding="utf-8")

    selected_ids = {video["id"] for video in selected}
    prune_asset(STORY_NODES_PATH, selected_ids)
    prune_asset(STORYBOARDS_PATH, selected_ids)
    sync_covers(selected_ids)
    recent = sum(
        (today - dt.date.fromisoformat(video["published"])).days <= int(config.get("recent_days", 7))
        for video in selected
    )
    print(f"published {len(selected)} playable videos ({recent} from the last week) for {today.isoformat()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"weekly update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
