"""ZooPicker's website login and paginated, authenticated observations.

These are the requests made by ZooPicker's own frontend, not a public API.
Cookies and Firebase tokens stay in memory and are never written to disk.
"""

import datetime as dt
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent
JST = ZoneInfo("Asia/Tokyo")
TIMEOUT = (10, 30)
SITE = "https://zoopicker.com"
PAGE_SIZE = 100
AD_MARKERS = (
    "さらに野鳥の場所情報を見る", "短い広告を見る", "広告の視聴が必要",
    "watch a short ad", "ad_required", "rewarded_ad_required",
)


class ZoopickerError(RuntimeError):
    """A safe, user-facing error; never include response bodies or credentials."""


class AuthenticationError(ZoopickerError):
    pass


class AdRequiredError(ZoopickerError):
    pass


def check_ad_gate(text):
    if any(marker in text.lower() for marker in AD_MARKERS):
        raise AdRequiredError("需要观看广告才能访问；广告尚未解锁，数据不完整。")


@dataclass(frozen=True)
class Observation:
    date: dt.date
    observed_jp: str
    scientific: str


@dataclass
class PlaceResult:
    records: list = field(default_factory=list)
    pages: int = 0
    fetched_count: int = 0
    warning: str = ""


def load_locations(csv_file):
    import csv

    locations = []
    # utf-8-sig also accepts ordinary UTF-8; the supplied CSV has a BOM.
    with open(csv_file, newline="", encoding="utf-8-sig") as stream:
        for row in csv.reader(stream):
            if not row or not row[0].strip().isdigit():
                continue
            pid = int(row[0].strip())
            locations.append({
                "id": pid,
                "url": f"{SITE}/places/{pid}/observations",
                "place_url": f"{SITE}/places/{pid}",
                "location": row[1].strip() if len(row) > 1 else str(pid),
            })
    return locations


def parse_records_jp(html, target_date_mapping):
    """Compatibility HTML parser, scoped to observation cards, never ads/sidebar."""
    soup = BeautifulSoup(html, "html.parser")
    check_ad_gate(soup.get_text(" ", strip=True))
    if "未ログインのため観察記録の表示が制限" in soup.get_text():
        raise AuthenticationError("未登录，页面只显示部分观测记录。")
    records = {}
    for date_node in soup.select(".watched-date"):
        date_text = date_node.get_text(strip=True)
        if date_text not in target_date_mapping:
            continue
        card = date_node.find_parent(class_="list-item")
        if card is None:
            raise ZoopickerError("观测卡片结构变化，无法解析。")
        name = card.select_one("span")
        scientific = next((node.get_text(" ", strip=True).split("/", 1)[1].strip()
                           for node in card.select(".font-size-xs")
                           if "/" in node.get_text()), "")
        if name is None or not scientific:
            raise ZoopickerError("观测卡片缺少鸟名或学名，无法确认数据完整性。")
        records.setdefault(date_text, []).append({
            "observed_jp": name.get_text(strip=True), "scientific": scientific,
        })
    if not soup.select(".watched-date"):
        if "観察記録がまだありません" not in soup.get_text():
            raise ZoopickerError("页面未包含可识别的观测列表，无法确认数据完整性。")
    return records


class ZoopickerClient:
    def __init__(self, email, password, *, session=None, delay=1.0, max_pages=99):
        if not email or not password:
            raise AuthenticationError("请配置 ZOOPICKER_EMAIL 和 ZOOPICKER_PASSWORD。")
        self._email = email
        self._password = password
        self.session = session or requests.Session()
        self.delay = delay
        self.max_pages = max_pages
        self.authenticated = False
        self._last_get = None
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; birdalert personal bird alerts)",
            "Origin": SITE, "Referer": f"{SITE}/",
            "Accept-Language": "ja",
        })
        # Only idempotent GETs are retried. Never retry password submissions.
        retry = Retry(total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET"}), raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    @classmethod
    def from_env(cls, **kwargs):
        return cls(os.getenv("ZOOPICKER_EMAIL", ""), os.getenv("ZOOPICKER_PASSWORD", ""), **kwargs)

    def __enter__(self):
        try:
            self.login()
        except ZoopickerError:
            self.close()
            raise
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.session.close()
        self.authenticated = False

    def _request(self, method, url, **kwargs):
        if method == "GET":
            if self._last_get is not None:
                time.sleep(max(0, self.delay - (time.monotonic() - self._last_get)))
            self._last_get = time.monotonic()
        try:
            return self.session.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException:
            # Requests errors may include URLs/query strings. Do not propagate them.
            raise ZoopickerError("网络请求失败或超时。") from None

    @staticmethod
    def _json(response):
        check_ad_gate(response.text)
        if response.status_code == 401:
            raise AuthenticationError("登录已失效或未被网站认可。")
        if response.status_code == 403:
            raise ZoopickerError("访问被拒绝，可能需要广告解锁或其他访问权限；数据不完整。")
        if response.status_code != 200:
            raise ZoopickerError(f"网站请求失败（HTTP {response.status_code}）。")
        try:
            data = response.json()
        except ValueError:
            raise ZoopickerError("网站未返回预期的 JSON 数据，可能受到登录或页面限制。") from None
        if not isinstance(data, dict):
            raise ZoopickerError("网站数据结构变化，无法确认数据完整性。")
        return data

    def login(self):
        self.authenticated = False
        page = self._request("GET", f"{SITE}/")
        check_ad_gate(page.text)
        if page.status_code != 200:
            raise AuthenticationError(f"无法读取登录配置（HTTP {page.status_code}）。")
        match = re.search(r'firebaseApiKey\s*:\s*["\']([^"\']+)["\']', page.text)
        if not match:
            raise AuthenticationError("网站登录配置已变化，无法取得 Firebase 配置。")
        response = self._request(
            "POST", "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
            params={"key": match.group(1)},
            json={"email": self._email, "password": self._password, "returnSecureToken": True},
        )
        if response.status_code != 200:
            raise AuthenticationError("邮箱密码认证失败，请检查配置或在网站确认账号状态。")
        data = self._json(response)
        if not data.get("idToken"):
            raise AuthenticationError("认证未返回登录令牌。")
        response = self._request("POST", f"{SITE}/api/v1/accounts/firebase_signin",
                                 json={"id_token": data["idToken"]})
        self._json(response)
        # Verify server-side login instead of assuming a 200 response means success.
        me = self._json(self._request("GET", f"{SITE}/api/v1/accounts/me"))
        if not me.get("id"):
            raise AuthenticationError("网站未建立有效登录会话。")
        self.authenticated = True

    def _observations_page(self, place_id, page):
        for attempt in range(2):
            response = self._request("GET", f"{SITE}/api/v1/watcheds/search",
                                     params={"place_id": place_id, "page": page})
            try:
                return self._json(response)
            except AuthenticationError:
                self.authenticated = False
                if attempt:
                    raise
                self.login()

    @staticmethod
    def _normalize(item, place_id):
        if not isinstance(item, dict):
            raise ZoopickerError("观测记录结构变化。")
        bird = item.get("animal_page")
        if bird is None:  # The website labels these as removed data.
            return None
        went = item.get("went")
        if not isinstance(bird, dict) or not isinstance(went, dict):
            raise ZoopickerError("观测记录缺少物种或日期信息。")
        # Anonymous records lack this field; never accept an anonymous preview.
        place = went.get("place")
        if not isinstance(place, dict):
            raise ZoopickerError("观测地点信息受限，可能需要重新登录或广告解锁；数据不完整。")
        if place.get("id") is not None and str(place["id"]) != str(place_id):
            raise ZoopickerError("网站返回了其他地点的记录。")
        scientific = bird.get("scientific_name")
        title = bird.get("title")
        if not isinstance(scientific, str) or not scientific.strip() or not isinstance(title, str):
            raise ZoopickerError("观测记录缺少有效鸟名或学名。")
        try:
            date = dt.date.fromisoformat(went["date"])
        except (KeyError, TypeError, ValueError):
            raise ZoopickerError("观测日期缺失或格式变化。") from None
        return Observation(date, title, scientific.strip())

    def fetch_place(self, place_id, target_dates):
        """Fetch the full date window, preserving partial results with a warning."""
        result = PlaceResult()
        if not target_dates:
            return result
        cutoff = min(target_dates)
        fingerprints = set()
        previous_date = None
        descending = True
        try:
            if not self.authenticated:
                self.login()
            for page in range(1, self.max_pages + 1):
                data = self._observations_page(place_id, page)
                rows = data.get("watcheds")
                meta = data.get("meta")
                if not isinstance(rows, list) or not isinstance(meta, dict):
                    raise ZoopickerError("网站观测列表结构变化。")
                if meta.get("current_page") != page:
                    raise ZoopickerError("网站没有返回所请求的分页，数据不完整。")
                fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).digest()
                if rows and fingerprint in fingerprints:
                    raise ZoopickerError("网站重复返回同一页，已停止抓取；数据不完整。")
                fingerprints.add(fingerprint)
                normalized = [self._normalize(row, place_id) for row in rows]
                normalized = [record for record in normalized if record is not None]
                result.pages += 1
                result.fetched_count += len(rows)
                for record in normalized:
                    if previous_date is not None and record.date > previous_date:
                        descending = False
                    previous_date = record.date
                    if record.date in target_dates:
                        # No record IDs are provided. Same-species/date rows can
                        # be independent observations; do not collapse them.
                        result.records.append(record)
                if len(rows) < PAGE_SIZE:
                    return result
                if descending and normalized and normalized[-1].date < cutoff:
                    return result
                last_page = meta.get("last_page")
                if isinstance(last_page, int) and page >= last_page:
                    return result
            raise ZoopickerError(f"已达到 {self.max_pages} 页上限，尚未覆盖完整日期范围。")
        except ZoopickerError as error:
            result.warning = str(error)
            return result
