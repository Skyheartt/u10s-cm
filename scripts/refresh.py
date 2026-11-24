"""Build the static leaderboard for the Everios U10S champion medals.

Nadeo has no published quota. Their own guidance, relayed by Openplanet, is
that about 2 requests per second is the ceiling for a short burst, and that a
long scan has to stay slower. This script sends one Live API request per
second, stops each map once the records are slower than the champion time,
and will not start another scan when the published file is under 30 minutes old.
A second pass then asks for the personal best of the top 100 medal
holders on every map, including times slower than the champion medal.
"""

from __future__ import annotations

import argparse
import base64
import calendar
import csv
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "u10s-cm-time.csv"
MAPS_PATH = ROOT / "data" / "maps.json"
NAMES_PATH = ROOT / "data" / "names.json"
OUT_PATH = ROOT / "web" / "data" / "standings.json"
HISTORY_PATH = ROOT / "web" / "data" / "history.json"
HISTORY_TOP = 100
HISTORY_DETAIL_SECONDS = 21 * 24 * 60 * 60

AUTHOR = "Everios96_2"
MIN_AGE_SECONDS = 30 * 60
LIVE_INTERVAL = 1.0
PAGE_SIZE = 100
MAX_OFFSET = 9900
TOP_TRACKED = 100
HIDDEN_TIME = 4294967295
USER_AGENT_FALLBACK = "u10s-cm.fr champion medal leaderboard"

PREFERRED_AUTHORS = ("Everios96_2", "Everios96")


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def unwrap(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def load_env() -> None:
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), unwrap(value))
    for key in ("NADEO_LOGIN", "NADEO_PASSWORD", "TM_CLIENT_ID", "TM_CLIENT_SECRET", "CONTACT"):
        if key in os.environ:
            os.environ[key] = unwrap(os.environ[key])


def user_agent() -> str:
    contact = os.environ.get("CONTACT", "").strip()
    if contact:
        return f"{USER_AGENT_FALLBACK} / {contact}"
    return USER_AGENT_FALLBACK


def read_csv() -> list[dict]:
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    maps = []
    seen = set()
    for row in rows:
        name = (row.get("map_name") or "").strip()
        raw_time = (row.get("cm_time") or "").strip()
        if not name:
            continue
        if name in seen:
            raise SystemExit(f"Duplicate map name in CSV: {name}")
        seen.add(name)
        try:
            cm_time = int(raw_time)
        except ValueError as exc:
            raise SystemExit(f"Bad champion time for {name}: {raw_time}") from exc
        maps.append({"name": name, "cm": cm_time})
    if len(maps) != 700:
        raise SystemExit(f"Expected 700 maps in the CSV, found {len(maps)}")
    return maps


def csv_digest() -> str:
    return hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()


def request_json(url: str, *, method: str = "GET", headers: dict | None = None,
                  body: bytes | None = None, timeout: int = 40, retries: int = 4):
    last_error = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
                if not payload:
                    return {}
                return json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            last_error = ApiError(f"{exc.code} {url} {detail}", exc.code)
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                wait = 5 * (attempt + 1)
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = max(wait, int(retry_after))
                print(f"  retry in {wait}s after HTTP {exc.code}", flush=True)
                time.sleep(wait)
                continue
            raise last_error from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise last_error


def resolve_maps(catalog: list[dict]) -> list[dict]:
    digest = csv_digest()
    if MAPS_PATH.exists():
        cached = json.loads(MAPS_PATH.read_text(encoding="utf-8"))
        cached_maps = cached.get("maps") or []
        names = [item["name"] for item in cached_maps]
        if cached.get("csvSha256") == digest and names == [item["name"] for item in catalog]:
            print(f"Map list already resolved ({len(cached_maps)} maps).")
            return cached_maps

    resolved = []
    missing = []
    warnings = []
    headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    for index, item in enumerate(catalog, start=1):
        name = item["name"]
        query = urllib.parse.urlencode({
            "api": "on",
            "author": AUTHOR,
            "trackname": name,
            "limit": 50,
        })
        url = f"https://trackmania.exchange/mapsearch2/search?{query}"
        try:
            payload = request_json(url, headers=headers)
        except Exception as exc:
            missing.append(name)
            print(f"[{index}/700] {name} FAILED {exc}", flush=True)
            time.sleep(0.25)
            continue
        exact = [
            row for row in payload.get("results") or []
            if row.get("Name") == name and row.get("Username") in PREFERRED_AUTHORS
        ]
        exact.sort(key=lambda row: (0 if row.get("Username") == AUTHOR else 1, -int(row.get("TrackID") or 0)))
        if not exact:
            missing.append(name)
            print(f"[{index}/700] {name} not found", flush=True)
        else:
            row = exact[0]
            author_time = row.get("AuthorTime")
            if isinstance(author_time, int) and item["cm"] >= author_time:
                warnings.append(f"{name}: champion {item['cm']} ms is not faster than author {author_time} ms")
            resolved.append({
                "name": name,
                "uid": row["TrackUID"],
                "mxId": row["TrackID"],
                "cm": item["cm"],
                "authorTime": author_time,
            })
            if index % 25 == 0 or index == 700:
                print(f"[{index}/700] resolved", flush=True)
        time.sleep(0.2)

    MAPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAPS_PATH.write_text(json.dumps({
        "csvSha256": digest,
        "author": AUTHOR,
        "maps": resolved,
        "missing": missing,
        "warnings": warnings,
    }, indent=2), encoding="utf-8")
    print(f"Resolved {len(resolved)} maps, missing {len(missing)}, warnings {len(warnings)}")
    for line in warnings[:20]:
        print("  warn", line)
    for name in missing:
        print("  missing", name)
    if missing:
        raise SystemExit(1)
    return resolved


def require_credentials() -> None:
    needed = ("NADEO_LOGIN", "NADEO_PASSWORD", "TM_CLIENT_ID", "TM_CLIENT_SECRET")
    absent = [key for key in needed if not os.environ.get(key)]
    if absent:
        raise SystemExit(
            "Missing credentials in .env or the environment: " + ", ".join(absent)
        )


class Nadeo:
    def __init__(self):
        self.agent = user_agent()
        self.live_token = None
        self.live_deadline = 0.0
        self.core_token = None
        self.core_deadline = 0.0
        self.oauth_token = None
        self.oauth_deadline = 0.0
        self.next_request = 0.0

    def _basic_auth(self) -> str:
        raw = f"{os.environ['NADEO_LOGIN']}:{os.environ['NADEO_PASSWORD']}".encode()
        return base64.b64encode(raw).decode("ascii")

    def live_token_value(self) -> str:
        now = time.time()
        if self.live_token and now < self.live_deadline:
            return self.live_token
        payload = request_json(
            "https://prod.trackmania.core.nadeo.online/v2/authentication/token/basic",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {self._basic_auth()}",
                "User-Agent": self.agent,
            },
            body=json.dumps({"audience": "NadeoLiveServices"}).encode(),
        )
        token = payload.get("accessToken")
        if not token:
            raise SystemExit("Nadeo did not return an access token. Check the service account login and password.")
        self.live_token = token
        self.live_deadline = now + 50 * 60
        return token

    def core_token_value(self) -> str:
        now = time.time()
        if self.core_token and now < self.core_deadline:
            return self.core_token
        payload = request_json(
            "https://prod.trackmania.core.nadeo.online/v2/authentication/token/basic",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {self._basic_auth()}",
                "User-Agent": self.agent,
            },
            body=json.dumps({"audience": "NadeoServices"}).encode(),
        )
        token = payload.get("accessToken")
        if not token:
            raise SystemExit("Nadeo did not return a core token. Check the service account login and password.")
        self.core_token = token
        self.core_deadline = now + 50 * 60
        return token

    def pace(self) -> None:
        wait = self.next_request - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.next_request = time.monotonic() + LIVE_INTERVAL

    def oauth_token_value(self) -> str:
        now = time.time()
        if self.oauth_token and now < self.oauth_deadline:
            return self.oauth_token
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": os.environ["TM_CLIENT_ID"],
            "client_secret": os.environ["TM_CLIENT_SECRET"],
        }).encode()
        payload = request_json(
            "https://api.trackmania.com/api/access_token",
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.agent,
            },
            body=body,
        )
        token = payload.get("access_token")
        if not token:
            raise SystemExit("Trackmania OAuth did not return a token. Check the API application id and secret.")
        self.oauth_token = token
        self.oauth_deadline = now + 50 * 60
        return token

    def leaderboard_page(self, uid: str, offset: int) -> list[dict]:
        self.pace()
        quoted = urllib.parse.quote(uid, safe="")
        url = (
            "https://live-services.trackmania.nadeo.live/api/token/leaderboard/group/"
            f"Personal_Best/map/{quoted}/top?onlyWorld=true&length={PAGE_SIZE}&offset={offset}"
        )
        try:
            payload = request_json(url, headers={
                "Authorization": f"nadeo_v1 t={self.live_token_value()}",
                "User-Agent": self.agent,
                "Accept": "application/json",
            })
        except ApiError as exc:
            if exc.status == 401:
                self.live_token = None
                payload = request_json(url, headers={
                    "Authorization": f"nadeo_v1 t={self.live_token_value()}",
                    "User-Agent": self.agent,
                    "Accept": "application/json",
                })
            else:
                raise
        tops = payload.get("tops") or []
        if not tops:
            return []
        return tops[0].get("top") or []

    def records_under(self, uid: str, cm_time: int) -> tuple[list[tuple[str, int]], int]:
        found = {}
        offset = 0
        pages = 0
        while offset <= MAX_OFFSET:
            page = self.leaderboard_page(uid, offset)
            pages += 1
            if not page:
                break
            countable = []
            for entry in page:
                score = entry.get("score")
                account_id = entry.get("accountId")
                if account_id and isinstance(score, int) and score > 0:
                    countable.append((account_id, score))
            # A page of hidden scores (-1) cannot be ordered against the medal.
            if not countable:
                break
            passed = False
            for account_id, score in countable:
                if score <= cm_time:
                    previous = found.get(account_id)
                    if previous is None or score < previous:
                        found[account_id] = score
                else:
                    passed = True
            if passed or len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        return list(found.items()), pages

    def core_json(self, url: str):
        self.pace()
        headers = {
            "Authorization": f"nadeo_v1 t={self.core_token_value()}",
            "User-Agent": self.agent,
            "Accept": "application/json",
        }
        try:
            return request_json(url, headers=headers)
        except ApiError as exc:
            if exc.status != 401:
                raise
            self.core_token = None
            headers["Authorization"] = f"nadeo_v1 t={self.core_token_value()}"
            return request_json(url, headers=headers)

    def map_info_by_uid(self, uids: list[str]) -> list[dict]:
        query = urllib.parse.urlencode({"mapUidList": ",".join(uids)})
        payload = self.core_json(
            f"https://prod.trackmania.core.nadeo.online/maps/by-uid/?{query}"
        )
        if not isinstance(payload, list):
            raise ApiError("Map info response was not a list")
        return payload

    def records_for_accounts(self, map_id: str, account_ids: list[str], game_mode: str) -> dict[str, int]:
        def load(mode: str):
            query = urllib.parse.urlencode({
                "accountIdList": ",".join(account_ids),
                "mapId": map_id,
                "gameMode": mode,
            })
            return self.core_json(
                "https://prod.trackmania.core.nadeo.online/v2/mapRecords/by-account/?" + query
            )

        payload = load(game_mode)
        if game_mode == "TimeAttack" and (isinstance(payload, dict) or payload == []):
            payload = load("TimeAttackClone")
        if not isinstance(payload, list):
            message = payload.get("message") if isinstance(payload, dict) else "record lookup failed"
            raise ApiError(str(message))
        found = {}
        for row in payload:
            if row.get("removed"):
                continue
            account_id = row.get("accountId")
            score = (row.get("recordScore") or {}).get("time")
            if account_id and is_real_time(score):
                found[account_id] = score
        return found

    def display_names(self, account_ids: list[str]) -> dict[str, str]:
        if not account_ids:
            return {}
        query = "&".join(
            "accountId[]=" + urllib.parse.quote(account_id) for account_id in account_ids
        )
        url = f"https://api.trackmania.com/api/display-names?{query}"
        payload = request_json(url, headers={
            "Authorization": f"Bearer {self.oauth_token_value()}",
            "User-Agent": self.agent,
            "Accept": "application/json",
        })
        if not isinstance(payload, dict):
            return {}
        return {
            account_id: name
            for account_id, name in payload.items()
            if isinstance(name, str) and name
        }


def load_previous() -> dict:
    if not OUT_PATH.exists():
        return {}
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def previous_records(previous: dict, maps: list[dict]) -> dict[str, dict[str, int]]:
    """uid -> account id -> time, recovered from the last published file."""
    old_maps = previous.get("maps") or []
    index_to_uid = {}
    for index, item in enumerate(old_maps):
        uid = item.get("uid")
        if uid:
            index_to_uid[index] = uid
    recovered = {item["uid"]: {} for item in maps}
    for player in previous.get("players") or []:
        account_id = player.get("id")
        if not account_id:
            continue
        for pair in player.get("records") or []:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            map_index, record_time = pair
            uid = index_to_uid.get(map_index)
            if uid in recovered and isinstance(record_time, int):
                recovered[uid][account_id] = record_time
    return recovered


def age_of(previous: dict) -> float | None:
    stamp = previous.get("updatedAt")
    if not stamp:
        return None
    try:
        parsed = time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return time.time() - calendar.timegm(parsed)


def is_real_time(value) -> bool:
    return isinstance(value, int) and 0 < value < HIDDEN_TIME


def game_mode_for(info: dict) -> str:
    map_type = info.get("mapType") or ""
    if map_type.endswith("TM_Stunt"):
        return "Stunt"
    if map_type.endswith("TM_Platform"):
        return "Platform"
    if info.get("hasClones"):
        return "TimeAttackClone"
    return "TimeAttack"


def medal_count(records: list[list[int]], maps: list[dict]) -> int:
    total = 0
    for index, record_time in records:
        if 0 <= index < len(maps) and is_real_time(record_time) and record_time <= maps[index]["cm"]:
            total += 1
    return total


def top_accounts(by_uid: dict[str, dict[str, int]], maps: list[dict]) -> list[str]:
    champion = {item["uid"]: item["cm"] for item in maps}
    counts: dict[str, int] = {}
    for uid, records in by_uid.items():
        cm_time = champion.get(uid)
        if cm_time is None:
            continue
        for account_id, record_time in records.items():
            if is_real_time(record_time) and record_time <= cm_time:
                counts[account_id] = counts.get(account_id, 0) + 1
    return sorted(counts, key=lambda account_id: (-counts[account_id], account_id))[:TOP_TRACKED]


def ensure_map_ids(client: Nadeo, maps: list[dict]) -> None:
    pending = [item for item in maps if not item.get("mapId") or not item.get("gameMode")]
    if not pending:
        print("Nadeo map ids already resolved.")
        return
    found = {item["uid"]: item for item in maps}
    uids = [item["uid"] for item in pending]
    for start in range(0, len(uids), 100):
        chunk = uids[start:start + 100]
        for info in client.map_info_by_uid(chunk):
            item = found.get(info.get("mapUid"))
            if not item or not info.get("mapId"):
                continue
            item["mapId"] = info["mapId"]
            item["gameMode"] = game_mode_for(info)
        print(f"Map ids {min(start + 100, len(uids))}/{len(uids)}", flush=True)
    payload = json.loads(MAPS_PATH.read_text(encoding="utf-8"))
    payload["maps"] = maps
    MAPS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    unresolved = [item["name"] for item in maps if not item.get("mapId")]
    if unresolved:
        print(f"No Nadeo id for {len(unresolved)} maps")


def fill_tracked_times(client: Nadeo, maps: list[dict], by_uid: dict[str, dict[str, int]],
                       carried: dict[str, dict[str, int]], tracked: list[str], errors: list[str]) -> int:
    print(f"Fetching personal bests for the top {len(tracked)}", flush=True)
    calls = 0
    for index, item in enumerate(maps, start=1):
        current = by_uid[item["uid"]]
        if not item.get("mapId"):
            errors.append(f"{item['name']}: no Nadeo map id")
            continue
        try:
            found = client.records_for_accounts(
                item["mapId"], tracked, item.get("gameMode") or "TimeAttack"
            )
            calls += 1
            slower = 0
            for account_id, record_time in found.items():
                existing = current.get(account_id)
                if existing is not None and existing <= record_time:
                    continue
                current[account_id] = record_time
                if record_time > item["cm"]:
                    slower += 1
            if index % 50 == 0 or index == len(maps):
                print(f"[pb {index}/{len(maps)}] {item['name']}  {slower} slower than the medal", flush=True)
        except Exception as exc:
            previous = carried.get(item["uid"], {})
            for account_id in tracked:
                if account_id not in current and is_real_time(previous.get(account_id)):
                    current[account_id] = previous[account_id]
            errors.append(f"{item['name']} personal bests: {exc}")
            print(f"[pb {index}/{len(maps)}] {item['name']} KEPT PREVIOUS ({exc})", flush=True)
    return calls


def publish(maps: list[dict], by_uid: dict[str, dict[str, int]], names: dict[str, str],
            updated_at: str | None, errors: list[str], tracked: set[str] | None = None) -> None:
    players_map: dict[str, list[list[int]]] = {}
    for index, item in enumerate(maps):
        for account_id, record_time in by_uid.get(item["uid"], {}).items():
            players_map.setdefault(account_id, []).append([index, record_time])

    tracked = tracked or set()
    players = []
    for account_id, records in players_map.items():
        records.sort()
        player = {
            "id": account_id,
            "name": names.get(account_id) or account_id,
            "records": records,
        }
        if account_id in tracked:
            player["tracked"] = True
        players.append(player)
    players.sort(key=lambda player: (-medal_count(player["records"], maps), player["name"].casefold(), player["id"]))

    payload = {
        "updatedAt": updated_at,
        "mapCount": len(maps),
        "errors": errors,
        "maps": [
            {"name": item["name"], "uid": item["uid"], "cm": item["cm"], "mx": item["mxId"]}
            for item in maps
        ],
        "players": players,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    temporary.replace(OUT_PATH)
    print(f"Wrote {OUT_PATH} ({len(players)} players, {len(maps)} maps)")
    update_history(players, maps, updated_at)


def downsample_history(points: list[list[int]], cutoff: int) -> list[list[int]]:
    recent = [point for point in points if point[0] >= cutoff]
    daily: dict[int, list[int]] = {}
    for stamp, count in points:
        if stamp >= cutoff:
            continue
        day = stamp // 86400
        current = daily.get(day)
        if current is None or stamp >= current[0]:
            daily[day] = [stamp, count]
    return [daily[day] for day in sorted(daily)] + recent


def update_history(players: list[dict], maps: list[dict], updated_at: str | None) -> None:
    if not updated_at:
        return
    stamp = int(calendar.timegm(time.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ")))
    history = {"names": {}, "series": {}}
    if HISTORY_PATH.exists():
        try:
            loaded = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded.get("names"), dict):
                history["names"] = loaded["names"]
            if isinstance(loaded.get("series"), dict):
                history["series"] = loaded["series"]
        except json.JSONDecodeError:
            pass
    for player in players[:HISTORY_TOP]:
        count = medal_count(player["records"], maps)
        history["names"][player["id"]] = player["name"]
        series = history["series"].setdefault(player["id"], [])
        if series and series[-1][0] == stamp:
            series[-1][1] = count
        elif not series or series[-1][0] < stamp:
            series.append([stamp, count])
    cutoff = stamp - HISTORY_DETAIL_SECONDS
    for account_id, series in list(history["series"].items()):
        cleaned = [point for point in series if isinstance(point, list) and len(point) == 2]
        cleaned.sort()
        history["series"][account_id] = downsample_history(cleaned, cutoff)
        if not history["series"][account_id]:
            history["series"].pop(account_id, None)
            history["names"].pop(account_id, None)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(history, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    temporary.replace(HISTORY_PATH)
    print(f"Wrote {HISTORY_PATH} ({len(history['series'])} players)")


def load_names() -> dict[str, str]:
    if not NAMES_PATH.exists():
        return {}
    try:
        payload = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_names(names: dict[str, str]) -> None:
    NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = NAMES_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(NAMES_PATH)


def refresh(force: bool) -> None:
    load_env()
    catalog = read_csv()
    maps = resolve_maps(catalog)
    previous = load_previous()
    age = age_of(previous)
    if not force and age is not None and age < MIN_AGE_SECONDS:
        minutes = int(age // 60)
        raise SystemExit(f"Last refresh was {minutes} min ago. The minimum gap is 30 min. Use --force to override.")

    require_credentials()
    client = Nadeo()
    carried = previous_records(previous, maps)
    by_uid = {item["uid"]: dict(carried.get(item["uid"], {})) for item in maps}
    errors = []
    requests_made = 0

    for index, item in enumerate(maps, start=1):
        try:
            records, pages = client.records_under(item["uid"], item["cm"])
            by_uid[item["uid"]] = {account_id: record_time for account_id, record_time in records}
            requests_made += pages
            print(f"[{index}/{len(maps)}] {item['name']}  {len(records)} medals  {pages} page(s)", flush=True)
        except Exception as exc:
            errors.append(f"{item['name']}: {exc}")
            print(f"[{index}/{len(maps)}] {item['name']} KEPT PREVIOUS DATA ({exc})", flush=True)

    tracked: list[str] = []
    pb_calls = 0
    try:
        ensure_map_ids(client, maps)
    except Exception as exc:
        errors.append(f"map ids: {exc}")
        print(f"Map ids failed: {exc}", flush=True)
    if any(item.get("mapId") for item in maps):
        tracked = top_accounts(by_uid, maps)
        pb_calls = fill_tracked_times(client, maps, by_uid, carried, tracked, errors)

    account_ids = set()
    for records in by_uid.values():
        account_ids.update(records)
    names = load_names()
    missing_ids = [account_id for account_id in account_ids if account_id not in names]
    print(f"Resolving {len(missing_ids)} new display names", flush=True)
    for start in range(0, len(missing_ids), 50):
        chunk = missing_ids[start:start + 50]
        try:
            names.update(client.display_names(chunk))
        except Exception as exc:
            errors.append(f"display names: {exc}")
            print(f"  name lookup failed: {exc}", flush=True)
            break
        time.sleep(0.3)
    save_names(names)

    map_errors = [item for item in errors if not item.startswith("display names")]
    if map_errors and len(map_errors) == len(maps):
        raise SystemExit("Every map request failed. The published file was left unchanged.")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    publish(maps, by_uid, names, stamp, errors, set(tracked))
    print(f"Live API pages: {requests_made}. Personal-best requests: {pb_calls}. Map errors: {len(map_errors)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the U10S champion medal leaderboard.")
    parser.add_argument("--resolve-only", action="store_true", help="Only match map names to Trackmania Exchange ids.")
    parser.add_argument("--force", action="store_true", help="Refresh even if the last run is under 30 minutes old.")
    args = parser.parse_args()
    load_env()
    catalog = read_csv()
    if args.resolve_only:
        maps = resolve_maps(catalog)
        previous = load_previous()
        by_uid = previous_records(previous, maps)
        publish(maps, by_uid, load_names(), previous.get("updatedAt"), previous.get("errors") or [], set())
        return
    refresh(force=args.force)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
