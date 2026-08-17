#!/usr/bin/env python3
r"""Build a research-oriented Chinese traditional screen image dataset.

The collector separates high-confidence core objects from items that still need
human review. It uses official collection APIs and IIIF services only; no
third-party gallery pages are scraped.

Examples (Windows portable Python included in this workspace during validation):
    .\.python-runtime\python.exe data.py
    .\.python-runtime\python.exe data.py --met-max-objects 250 --commons-max-files 120

Important: future train/validation/test splitting MUST be done by screen_id (Met)
or a completed object_group_manual (Commons), never by individual image.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import mimetypes
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


MET_API = "https://collectionapi.metmuseum.org/public/collection/v1"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
AIC_API = "https://api.artic.edu/api/v1"
AIC_IIIF = "https://www.artic.edu/iiif/2"
SMITHSONIAN_OBJECT_URL = (
    "https://asia.si.edu/explore-art-culture/collections/search/"
    "edanmdm%3Afsg_F1906.42a-l/"
)
def smithsonian_manifest(number: int) -> str:
    suffix = f"{number:03d}" if number <= 2 else f"{number:03d}x"
    return f"https://ids.si.edu/ids/manifest/FS-F1906.42a-l_{suffix}"
AIC_SCREEN_IDS = [15790, 28052]
RIJKS_SCREEN = {
    "record_id": "RIJKS_200364785",
    "source_object_id": "200364785",
    "title": "Folding Screen with Dutch ships",
    "date": "c. 1685 - c. 1700",
    "accession_no": "BK-1959-99",
    "image_url": "https://iiif.micr.io/poNLD/full/1200,/0/default.jpg",
    "source_url": "https://id.rijksmuseum.nl/200364785",
}
SEED_MET_IDS = [64084, 64085, 64086, 61665]
MET_QUERIES = [
    "Chinese folding screen",
    "Chinese lacquer screen",
    "Coromandel lacquer screen",
    "Ming dynasty folding screen",
    "Qing dynasty folding screen",
    "multi-panel Chinese screen",
    "Chinese traditional screen",
    "Chinese painted screen",
    "Chinese calligraphy screen",
    "Chinese map screen",
    "Chinese standing screen",
    "Chinese room screen",
    "Chinese decorative screen",
    "Chinese four-panel screen",
    "Chinese six-panel screen",
    "Chinese eight-panel screen",
    "Chinese twelve-panel screen",
]
COMMONS_CATEGORIES = [
    "Category:Chinese folding screens",
    "Category:Coromandel lacquer",
]
COMMONS_SEARCH_QUERIES = [
    '"Chinese folding screen"',
    '"Chinese lacquer screen"',
    '"Coromandel screen"',
    '"Coromandel lacquer" screen',
    '"Qing dynasty" "folding screen"',
    '"Ming dynasty" "folding screen"',
    '"Chinese standing screen" lacquer',
    '"Qing lacquer screen"',
    '"Screen with qilin" China Qing',
    '"Chinese screen" "Qianlong period" lacquer',
    '"paravent chinois" laque',
    'intitle:screen China Qing lacquer',
    'intitle:screen Chinese lacquer museum',
    'intitle:screen China Qianlong',
    'intitle:screen China Kangxi',
    'intitle:paravent chinois',
    'intitle:paravent Coromandel',
    'intitle:paravento Cina',
    'intitle:屏风 清',
    'intitle:屏風 清',
    '"standing screen with" China',
    '"screen with" China "Qing dynasty"',
    '"lacquered wooden screen" China',
    '"Chinese traditional screen"',
    '"Chinese painted screen"',
    '"Chinese calligraphy screen"',
    '"Chinese map screen"',
    '"Chinese multi-panel screen"',
    '"Chinese four-panel screen"',
    '"Chinese six-panel screen"',
    '"Chinese eight-panel screen"',
    '"Chinese twelve-panel screen"',
    '"Chinese decorative screen" museum',
    'intitle:漆屏',
    'intitle:立屏 中国',
    'intitle:围屏',
    'intitle:折屏',
    'intitle:款彩 屏风',
    '"paravento cinese"',
]
USER_AGENT = (
    "MingQingScreenResearchDataset/1.0 "
    "(academic cultural-heritage research; contact: local-research-user)"
)

FIELDS = [
    "screen_id", "record_id", "object_group_manual", "object_group_auto", "source",
    "source_object_id", "object_name", "title", "object_type", "dynasty",
    "period", "period_group", "date", "date_begin", "date_end", "culture", "country",
    "material", "surface_type", "dimensions", "panel_count_guess", "panel_count_manual",
    "height_cm_manual", "museum", "accession_no", "image_type", "license",
    "license_class", "source_url", "image_url", "thumbnail_url", "local_file",
    "sha256", "bytes", "pixel_width", "pixel_height", "mime",
    "candidate_score", "dataset_role", "needs_manual_review", "include_core", "is_floorstanding",
    "is_spatial_partition", "is_chinese_ming_qing", "image_quality", "notes",
    "download_status", "query_or_category", "artist", "credit",
    "datetime_original", "categories",
    "image_description",
]

OBJECT_FIELDS = [
    "screen_id", "record_id", "source_group_id", "source", "source_object_id",
    "source_record_ids", "title", "object_type", "period", "period_group", "date",
    "date_begin", "date_end", "culture", "country", "material", "surface_type",
    "dimensions", "panel_count_guess", "panel_count_manual", "museum", "accession_no",
    "license", "license_class", "source_url", "dataset_role", "needs_manual_review",
    "include_core", "candidate_score", "image_count", "notes",
]

IMAGE_FIELDS = [
    "image_id", "screen_id", "record_id", "source_group_id", "source", "source_object_id", "title",
    "image_type", "license", "license_class", "source_url", "image_url", "thumbnail_url",
    "local_file", "sha256", "bytes", "pixel_width", "pixel_height", "mime",
    "dataset_role", "needs_manual_review", "selected_for_training", "quality_manual", "notes",
]

REVIEW_FIELDS = ["screen_id", "keep", "training", "quality", "notes"]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v) for v in value if v not in (None, ""))
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
    return re.sub(r"\s+", " ", text).strip()


def truth(value: bool | str | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return ""


def safe_name(value: str, max_len: int = 110) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = re.sub(r"\s+", "_", value)
    return (value[:max_len].rstrip(" ._") or "unnamed")


def ext_for(url: str, mime: str = "") -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}:
        return ".jpg" if ext == ".jpeg" else ext
    guessed = mimetypes.guess_extension(mime.split(";")[0].strip()) if mime else None
    return guessed or ".jpg"


def actual_image_ext(path: Path, mime: str = "") -> str:
    mime_ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tif",
                "image/webp": ".webp"}.get(mime.split(";")[0].lower())
    if mime_ext:
        return mime_ext
    head = path.read_bytes()[:12]
    if head.startswith(b"\xff\xd8\xff"): return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return ".png"
    if head[:4] in (b"II*\x00", b"MM\x00*"): return ".tif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP": return ".webp"
    return path.suffix.lower()


def panel_count(text: str) -> str:
    """Return only an explicitly stated panel/leaf count; never infer visually."""
    words = {
        "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "sixteen": 16,
    }
    low = text.lower().replace("–", "-")
    match = re.search(r"\b(\d{1,2})\s*[- ]?(?:panel|fold|leaf)", low)
    if match:
        return match.group(1)
    match = re.search(
        r"\b(" + "|".join(words) + r")\s*[- ]?(?:panel|fold|leaf)", low
    )
    return str(words[match.group(1)]) if match else ""


def surface_type(text: str) -> str:
    low = text.lower()
    found: list[str] = []
    if any(t in low for t in ("lacquer", "coromandel", "lacca", "漆", "剔红", "款彩", "螺鈿", "螺钿")):
        found.append("lacquer")
    if any(t in low for t in ("calligraphy", "calligraphic", "書法", "书法", "ink inscription")):
        found.append("calligraphy")
    if any(t in low for t in ("map", "geographical", "地图", "地圖")):
        found.append("map")
    if any(t in low for t in ("painted", "painting", "ink and color", "colors on silk", "彩绘", "彩繪")):
        found.append("painting")
    if len(found) > 1:
        return "mixed"
    return found[0] if found else "unknown"


def commons_group_key(title: str, categories: str = "") -> str:
    """Conservatively group obvious Commons views of the same physical screen."""
    text = Path(title.removeprefix("File:")).stem.lower()
    # Cross-source matches supported directly by titles/Met image identifiers.
    if ("palace scene" in text or "宮苑圖" in text or "宫苑图" in text):
        return "MET_61665"
    if ("guo ziyi" in text or "郭子儀" in text or "郭子仪" in text):
        return "MET_64086"
    if ("map of china" in text or "中國地圖" in text or "中国地图" in text):
        return "MET_911983"
    if "women in a palace" in text or "仕女圖屏風" in text or "仕女图屏风" in text:
        return "COM_OBJECT_WOMEN_IN_PALACE_12_PANEL"
    if "eltham court" in text:
        return "COM_OBJECT_ELTHAM_COURT_COROMANDEL"
    if "miscellany in the villa ephrussi" in text:
        return "COM_OBJECT_VILLA_EPHRUSSI_COROMANDEL"
    if "musée d'histoire de nantes" in text or "musée dhistoire de nantes" in text or \
       "paravents en laque dite" in categories.lower():
        return "COM_OBJECT_NANTES_COROMANDEL"
    # Remove image/view identifiers, trailing sequence numbers, and punctuation.
    text = re.sub(r"\b(?:met\s+)?dp\d+\b", " ", text)
    text = re.sub(r"\b(?:dsc|img|image|photo)[-_ ]?\d+\b", " ", text)
    text = re.sub(r"\b(?:recto|verso|detail|détail|front|back)\b", " ", text)
    text = re.sub(r"\b\d{1,2}(?:\s+cavalli)?\b$", " ", text)
    text = re.sub(r"[_(),.;\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"COM_GROUP_{digest}"


def year_overlap(begin: Any, end: Any) -> bool | None:
    try:
        begin_i, end_i = int(begin), int(end)
    except (TypeError, ValueError):
        return None
    if begin_i == 0 and end_i == 0:
        return None
    return begin_i <= 1912 and end_i >= 1368


def classify_license(short: str, usage: str = "") -> str:
    text = f"{short} {usage}".lower()
    if "public domain" in text or re.search(r"\bpd\b", text):
        return "public_domain"
    if "cc0" in text:
        return "cc0"
    if "cc by-sa" in text or "cc-by-sa" in text:
        return "cc_by_sa_review"
    if "cc by" in text or "cc-by" in text:
        return "cc_by"
    return "unverified"


@dataclass
class FetchResult:
    data: bytes
    content_type: str
    status: int


class Collector:
    def __init__(self, root: Path, args: argparse.Namespace) -> None:
        self.root = root.resolve()
        self.args = args
        self.raw_met = self.root / "raw" / "met"
        self.raw_commons = self.root / "raw" / "commons"
        self.raw_open = self.root / "raw" / "open_museums"
        if (self.root / "raw").exists() and any(
            p.is_dir() and re.fullmatch(r"S\d{3,}", p.name) for p in (self.root / "raw").iterdir()
        ):
            self.raw_met = self.root / "staging" / "met"
            self.raw_commons = self.root / "staging" / "commons"
            self.raw_open = self.root / "staging" / "open_museums"
        self.metadata_dir = self.root / "metadata"
        self.logs_dir = self.root / "logs"
        for path in (self.raw_met, self.raw_commons, self.raw_open,
                     self.metadata_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)

        self.log = logging.getLogger("screen_dataset")
        self.log.setLevel(logging.INFO)
        self.log.handlers.clear()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(self.logs_dir / "crawler.log", encoding="utf-8")
        fh.setFormatter(formatter)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        self.log.addHandler(fh)
        self.log.addHandler(sh)

        self.objects: dict[str, dict[str, Any]] = {}
        self.images: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.rejected: dict[str, dict[str, Any]] = {}
        self.failures: list[dict[str, Any]] = []
        self.hashes: dict[str, str] = {}
        self.error_counts: Counter[str] = Counter()
        self.stats: Counter[str] = Counter()
        self.manual_values = self._load_manual_values()
        self.stable_screen_ids = {
            row.get("source_group_id") or row.get("record_id", ""): row.get("screen_id", "")
            for row in self._read_csv_rows("objects.csv")
            if re.fullmatch(r"S\d{3,}", row.get("screen_id", ""))
        }
        self.existing_group_counts: Counter[str] = Counter()
        self.context = ssl.create_default_context()
        self._load_other_source_for_incremental_run()

    def _read_csv_rows(self, filename: str) -> list[dict[str, str]]:
        path = self.metadata_dir / filename
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        except (OSError, csv.Error):
            return []

    def _load_other_source_for_incremental_run(self) -> None:
        """Preserve the unrefreshed source when --only is used."""
        refresh_sources = {
            "met": {"The Met"},
            "commons": {"Wikimedia Commons"},
            "open": {"Art Institute of Chicago", "Smithsonian National Museum of Asian Art"},
        }.get(self.args.only, set())
        load_all = self.args.only in {"metadata", "met", "commons", "open"}
        existing_images = self._read_csv_rows("images.csv")
        for row in existing_images:
            digest, local_file = row.get("sha256", ""), row.get("local_file", "")
            if digest and local_file and (self.root / local_file).exists():
                self.hashes.setdefault(digest, local_file)
            if row.get("dataset_role") in {"core_candidate", "auxiliary_candidate"}:
                key = (row.get("object_group_manual") or row.get("source_group_id") or
                       row.get("object_group_auto") or row.get("screen_id") or row.get("record_id"))
                self.existing_group_counts[str(key)] += 1
        if not refresh_sources and not load_all:
            return
        for row in self._read_csv_rows("objects.csv"):
            if (load_all or row.get("source") not in refresh_sources) and row.get("record_id"):
                self.objects[row["record_id"]] = row
                if row.get("dataset_role") in {"core_candidate", "auxiliary_candidate"} and \
                   row.get("source") != "Wikimedia Commons":
                    self.candidates[row["record_id"]] = row.copy()
        for row in existing_images:
            if (load_all or row.get("source") not in refresh_sources) and row.get("record_id"):
                self.images[row["record_id"]] = row
                if row.get("dataset_role") in {"core_candidate", "auxiliary_candidate"} and \
                   row.get("source") == "Wikimedia Commons":
                    self.candidates[row["record_id"]] = row.copy()
        for row in self._read_csv_rows("candidate_review.csv"):
            if (load_all or row.get("source") not in refresh_sources) and row.get("record_id"):
                self.candidates[row["record_id"]] = row
        for row in self._read_csv_rows("rejected_candidates.csv"):
            if (load_all or row.get("source") not in refresh_sources) and row.get("record_id"):
                self.rejected[row["record_id"]] = row
        for row in existing_images:
            if row.get("dataset_role") in {"core_candidate", "auxiliary_candidate"} and \
               row.get("source") == "Wikimedia Commons" and row.get("record_id"):
                self.candidates[row["record_id"]] = row.copy()

    @staticmethod
    def backfill_row(row: dict[str, Any]) -> dict[str, Any]:
        text = " ".join(str(row.get(k, "")) for k in
                        ("title", "material", "object_type", "period", "categories", "image_description"))
        if not row.get("surface_type"):
            row["surface_type"] = surface_type(text)
        role = row.get("dataset_role", "")
        if role == "core_candidate":
            row["period_group"] = row.get("period_group") or "traditional_core"
            row["include_core"] = "yes"
        elif role == "auxiliary_candidate":
            traditional = any(t in text.lower() for t in
                              ("traditional", "ming", "qing", "kangxi", "qianlong", "coromandel",
                               "17th century", "18th century", "19th century", "screen", "屏风", "屏風"))
            row["period_group"] = row.get("period_group") or (
                "traditional_auxiliary" if traditional else "unknown_review"
            )
            row["needs_manual_review"] = "yes"
        if row.get("source") == "Wikimedia Commons":
            row["object_group_auto"] = commons_group_key(str(row.get("title", "")),
                                                          str(row.get("categories", "")))
        return row

    @staticmethod
    def hard_error_from_saved_metadata(row: dict[str, Any]) -> str:
        text = " ".join(str(row.get(k, "")) for k in
                        ("title", "image_description", "categories")).lower()
        if any(t in text for t in ("屏风石", "屏風石", "screen-shaped rock")):
            return "object itself is not a screen (screen-shaped rock)"
        if any(t in text for t in ("screen ornament", "screen fragment", "detached panel",
                                   "table screen", "desk screen", "fire screen")):
            return "object itself is not an eligible full-size traditional screen"
        return ""

    def snapshot_metadata(self) -> None:
        csv_names = ("objects.csv", "images.csv", "review.csv", "candidate_review.csv", "core_candidates.csv",
                     "auxiliary_candidates.csv", "rejected_candidates.csv", "download_failures.csv",
                     "run_report.json")
        existing = [self.metadata_dir / name for name in csv_names if (self.metadata_dir / name).exists()]
        if not existing:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = self.metadata_dir / "history" / stamp
        target.mkdir(parents=True, exist_ok=True)
        for path in existing:
            shutil.copy2(path, target / path.name)

    def _load_manual_values(self) -> dict[str, dict[str, str]]:
        preserved: dict[str, dict[str, str]] = {}
        for filename in ("objects.csv", "images.csv", "candidate_review.csv"):
            path = self.metadata_dir / filename
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        key = row.get("record_id") or row.get("screen_id")
                        if key:
                            preserved[key] = {
                                name: row.get(name, "") for name in
                                ("object_group_manual", "panel_count_manual",
                                 "height_cm_manual", "image_quality", "notes")
                                if row.get(name, "")
                            }
            except (OSError, csv.Error):
                pass
        return preserved

    def _request(self, url: str, params: dict[str, Any] | None = None,
                 binary: bool = False) -> FetchResult:
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"
        last_error: Exception | None = None
        for attempt in range(self.args.retries + 1):
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            try:
                with urlopen(req, timeout=self.args.timeout, context=self.context) as resp:
                    data = resp.read()
                    return FetchResult(data, resp.headers.get("Content-Type", ""), resp.status)
            except HTTPError as exc:
                last_error = exc
                code = str(exc.code)
                self.error_counts[code] += 1
                if exc.code == 403 or exc.code == 404:
                    raise
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After", "")
                    # Wikimedia can return Retry-After: 600.  Waiting ten minutes per
                    # image is unsuitable for a batch job; cap it and record failure.
                    wait = float(retry_after) if retry_after.isdigit() else 2 ** attempt + random.random()
                elif 500 <= exc.code < 600:
                    wait = 2 ** attempt + random.random()
                else:
                    raise
            except (TimeoutError, URLError, ConnectionError) as exc:
                last_error = exc
                name = "timeout" if "timed out" in str(exc).lower() else "network"
                self.error_counts[name] += 1
                wait = 2 ** attempt + random.random()
            if attempt < self.args.retries:
                actual_wait = min(wait, self.args.max_retry_wait)
                self.log.warning("Retry %s/%s in %.1fs: %s", attempt + 1,
                                 self.args.retries, actual_wait, url)
                time.sleep(actual_wait)
        assert last_error is not None
        raise last_error

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self._request(url, params)
        if "json" not in result.content_type.lower() and not result.data.lstrip().startswith((b"{", b"[")):
            raise ValueError(f"Expected JSON, received {result.content_type}")
        return json.loads(result.data.decode("utf-8"))

    def _record_failure(self, source: str, record_id: str, url: str,
                        exc: Exception, image_type: str = "") -> None:
        status = str(exc.code) if isinstance(exc, HTTPError) else ""
        category = status or ("timeout" if "timed out" in str(exc).lower() else "other")
        self.failures.append({
            "source": source, "record_id": record_id, "image_type": image_type,
            "image_url": url, "http_status": status, "error_type": category,
            "error": clean_text(exc), "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })
        self.log.error("Download/API failure %s %s: %s", source, record_id, exc)

    def download(self, url: str, destination: Path, source: str,
                 record_id: str, image_type: str) -> tuple[str, int, str, str]:
        """Return sha256, bytes, status, content type."""
        if destination.exists() and destination.stat().st_size >= self.args.min_bytes:
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            self.hashes.setdefault(digest, str(destination.relative_to(self.root)))
            return digest, destination.stat().st_size, "existing", ""
        if source == "Wikimedia Commons" and self.args.commons_curl_first:
            result = self._download_with_curl(url, destination, record_id)
            if result is not None:
                return result
        try:
            result = self._request(url, binary=True)
            ctype = result.content_type.split(";")[0].strip().lower()
            if not ctype:
                head = result.data[:12]
                if head.startswith(b"\xff\xd8\xff"):
                    ctype = "image/jpeg"
                elif head.startswith(b"\x89PNG\r\n\x1a\n"):
                    ctype = "image/png"
                elif head[:4] in (b"II*\x00", b"MM\x00*"):
                    ctype = "image/tiff"
            if not ctype.startswith("image/"):
                raise ValueError(f"Non-image Content-Type {result.content_type!r}")
            if len(result.data) < self.args.min_bytes:
                raise ValueError(f"Image too small ({len(result.data)} bytes)")
            digest = hashlib.sha256(result.data).hexdigest()
            duplicate_of = self.hashes.get(digest)
            if duplicate_of:
                self.log.info("Exact duplicate %s matches %s", record_id, duplicate_of)
                return digest, len(result.data), f"duplicate:{duplicate_of}", ctype
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_suffix(destination.suffix + ".part")
            temp.write_bytes(result.data)
            os.replace(temp, destination)
            self.hashes[digest] = str(destination.relative_to(self.root))
            return digest, len(result.data), "downloaded", ctype
        except Exception as exc:
            # On some Windows/proxy combinations urllib is selectively throttled
            # by upload.wikimedia.org while curl succeeds through the same official
            # endpoint. Use a bounded, argument-list (no shell) fallback.
            result = self._download_with_curl(url, destination, record_id)
            if result is not None:
                return result
            self._record_failure(source, record_id, url, exc, image_type)
            return "", 0, "failed", ""

    def _download_with_curl(self, url: str, destination: Path,
                            record_id: str) -> tuple[str, int, str, str] | None:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            return None
        temp = destination.with_suffix(destination.suffix + ".curl.part")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run([
                curl, "-L", "--fail", "--silent", "--show-error",
                "--max-time", str(int(self.args.timeout)), "--retry", "1",
                "--user-agent", USER_AGENT, "--output", str(temp),
                "--write-out", "%{content_type}", url,
            ], capture_output=True, text=True, timeout=self.args.timeout + 10,
               check=False)
            ctype = proc.stdout.strip().split(";")[0].lower()
            if proc.returncode != 0:
                raise RuntimeError(f"curl exit {proc.returncode}: {proc.stderr.strip()}")
            data = temp.read_bytes()
            if not ctype:
                head = data[:12]
                if head.startswith(b"\xff\xd8\xff"):
                    ctype = "image/jpeg"
                elif head.startswith(b"\x89PNG\r\n\x1a\n"):
                    ctype = "image/png"
                elif head[:4] in (b"II*\x00", b"MM\x00*"):
                    ctype = "image/tiff"
            if not ctype.startswith("image/"):
                raise ValueError(f"curl returned non-image Content-Type {ctype!r}")
            if len(data) < self.args.min_bytes:
                raise ValueError(f"curl image too small ({len(data)} bytes)")
            digest = hashlib.sha256(data).hexdigest()
            duplicate_of = self.hashes.get(digest)
            if duplicate_of:
                temp.unlink(missing_ok=True)
                return digest, len(data), f"duplicate:{duplicate_of}", ctype
            os.replace(temp, destination)
            self.hashes[digest] = str(destination.relative_to(self.root))
            self.log.info("curl downloaded %s", record_id)
            return digest, len(data), "downloaded_curl", ctype
        except Exception as exc:
            temp.unlink(missing_ok=True)
            self.log.warning("curl download failed %s: %s", record_id, exc)
            return None

    def base_row(self, record_id: str) -> dict[str, Any]:
        row = {field: "" for field in FIELDS}
        row["record_id"] = record_id
        row.update(self.manual_values.get(record_id, {}))
        return row

    @staticmethod
    def met_assessment(obj: dict[str, Any]) -> tuple[int, str, str, str, str]:
        text = " ".join(clean_text(obj.get(k)) for k in
                        ("title", "objectName", "medium", "culture", "country",
                         "dynasty", "period", "objectDate", "tags")).lower()
        score, reasons = 0, []
        attribution = " ".join(clean_text(obj.get(k)) for k in
                               ("culture", "country", "dynasty", "period")).lower()
        chinese = any(t in attribution for t in ("china", "chinese", "qing", "ming"))
        object_is_screen = obj.get("objectName", "").strip().lower() in {
            "screen", "folding screen", "standing screen"
        }
        date_ok = year_overlap(obj.get("objectBeginDate"), obj.get("objectEndDate"))
        panels = panel_count(text)
        if object_is_screen: score += 5
        else: reasons.append("objectName is not Screen")
        if "folding screen" in text: score += 4
        elif " screen" in f" {text}": score += 1
        if chinese: score += 4
        else: reasons.append("no explicit Chinese attribution")
        if date_ok is True: score += 4
        elif date_ok is False: reasons.append("date outside 1368-1912")
        else: reasons.append("date unverified")
        if panels:
            score += 4 if int(panels) >= 4 else 1
            if int(panels) < 4: reasons.append("fewer than four explicit panels")
        else:
            reasons.append("panel count not stated")
        if any(t in text for t in ("lacquer", "wood", "coromandel", "carved")): score += 2
        if obj.get("isPublicDomain"): score += 3
        else: reasons.append("image not marked Public Domain")
        exclusion = ""
        for label, tokens, haystack in (
            ("Japanese screen", ("japan", "japanese", "byobu", "byōbu"), attribution),
            ("Korean screen", ("korea", "korean", "joseon"), attribution),
            ("European/Western screen", ("france", "french", "british", "england", "italian",
                                           "european", "american"), attribution),
            ("modern/contemporary screen", ("modern", "contemporary"), text),
            ("fire screen", ("fire screen", "firescreen"), text),
            ("table/desk/insertion/hanging screen", ("table screen", "desk screen", "insertion screen",
                                                       "hanging screen"), text),
        ):
            if any(token in haystack for token in tokens):
                exclusion = label
                score -= 20
                break
        if not object_is_screen and not exclusion:
            exclusion = "object itself is not a screen"
            score -= 20
        if not chinese and not exclusion:
            exclusion = "not explicitly a Chinese screen"
            score -= 20
        try:
            if int(obj.get("objectBeginDate") or 0) >= 1950 and not exclusion:
                exclusion = "modern/contemporary screen"
                score -= 20
        except (TypeError, ValueError):
            pass
        role = "rejected"
        if not exclusion:
            # Four or more explicitly stated panels plus a verified Ming/Qing date
            # earns high priority. Unknown/1/2/3 panels or uncertain dates remain
            # downloadable auxiliary candidates for manual review.
            role = ("core_candidate" if panels and int(panels) >= 4
                    else "auxiliary_candidate")
        return score, role, exclusion, panels, "; ".join(reasons)

    def collect_met(self) -> None:
        ids: list[int] = list(SEED_MET_IDS)
        sources: dict[int, set[str]] = {i: {"seed"} for i in ids}
        per_query = max(1, self.args.met_max_objects // len(MET_QUERIES))
        for query in MET_QUERIES:
            try:
                payload = self.get_json(f"{MET_API}/search", {"hasImages": "true", "q": query})
                found = payload.get("objectIDs") or []
                self.stats["met_search_hits"] += len(found)
                for object_id in found[:per_query]:
                    sources.setdefault(int(object_id), set()).add(query)
                    if int(object_id) not in ids:
                        ids.append(int(object_id))
            except Exception as exc:
                self._record_failure("The Met", f"search:{query}", "", exc)
        ids = ids[:max(self.args.met_max_objects, len(SEED_MET_IDS))]
        self.log.info("Met: inspecting %d unique objects from %d raw search hits",
                      len(ids), self.stats["met_search_hits"])

        selected: list[tuple[dict[str, Any], int, str, str, str, str]] = []
        for index, object_id in enumerate(ids, 1):
            try:
                obj = self.get_json(f"{MET_API}/objects/{object_id}")
                score, role, exclusion, panels, notes = self.met_assessment(obj)
                record_id = f"MET_{object_id}"
                row = self.base_row(record_id)
                row.update({
                    "screen_id": record_id, "source": "The Met",
                    "source_object_id": object_id, "object_name": clean_text(obj.get("objectName")),
                    "title": clean_text(obj.get("title")), "object_type": clean_text(obj.get("objectName")),
                    "dynasty": clean_text(obj.get("dynasty")), "period": clean_text(obj.get("period")),
                    "date": clean_text(obj.get("objectDate")), "date_begin": obj.get("objectBeginDate", ""),
                    "date_end": obj.get("objectEndDate", ""), "culture": clean_text(obj.get("culture")),
                    "country": clean_text(obj.get("country")), "material": clean_text(obj.get("medium")),
                    "dimensions": clean_text(obj.get("dimensions")), "panel_count_guess": panels,
                    "surface_type": surface_type(text := " ".join(clean_text(obj.get(k)) for k in
                                                       ("title", "medium", "objectName", "period"))),
                    "museum": "The Metropolitan Museum of Art",
                    "accession_no": clean_text(obj.get("accessionNumber")),
                    "license": "Public Domain" if obj.get("isPublicDomain") else "Unverified",
                    "license_class": "public_domain" if obj.get("isPublicDomain") else "unverified",
                    "source_url": clean_text(obj.get("objectURL")), "candidate_score": score,
                    "period_group": ("traditional_core" if role == "core_candidate" else
                                     "traditional_auxiliary" if role == "auxiliary_candidate" and
                                     year_overlap(obj.get("objectBeginDate"), obj.get("objectEndDate")) is True else
                                     "unknown_review" if role == "auxiliary_candidate" else ""),
                    "dataset_role": role, "needs_manual_review": truth(role == "auxiliary_candidate"),
                    "include_core": truth(role == "core_candidate"), "is_floorstanding": "",
                    "is_spatial_partition": "", "is_chinese_ming_qing": truth(
                        any(t in " ".join(map(str, (obj.get("culture"), obj.get("dynasty"), obj.get("period")))).lower()
                            for t in ("china", "chinese", "ming", "qing")) and
                        year_overlap(obj.get("objectBeginDate"), obj.get("objectEndDate")) is True
                    ), "notes": notes, "download_status": "metadata_only",
                    "query_or_category": "; ".join(sorted(sources.get(object_id, set()))),
                })
                self.objects[record_id] = row
                if exclusion:
                    row["notes"] = f"EXCLUDED: {exclusion}; {notes}".strip("; ")
                    self.rejected[record_id] = row.copy()
                    self.stats[f"excluded_{exclusion}"] += 1
                elif role in {"core_candidate", "auxiliary_candidate"}:
                    self.candidates[record_id] = row.copy()
                    # Automatic image download still requires the official Met
                    # Public Domain flag; otherwise retain metadata for review.
                    if obj.get("isPublicDomain") and (obj.get("primaryImage") or obj.get("additionalImages")):
                        selected.append((obj, score, role, panels, notes, record_id))
                    else:
                        row["needs_manual_review"] = "yes"
                        row["notes"] = f"{notes}; image not automatically downloadable under verified license".strip("; ")
                        self.candidates[record_id] = row.copy()
                else:
                    row["notes"] = f"REJECTED_LOW_SCORE; {notes}".strip("; ")
                    self.rejected[record_id] = row.copy()
                if index % 25 == 0:
                    self.log.info("Met metadata progress: %d/%d", index, len(ids))
                time.sleep(self.args.api_delay)
            except Exception as exc:
                self._record_failure("The Met", f"MET_{object_id}", f"{MET_API}/objects/{object_id}", exc)

        selected.sort(key=lambda item: (item[2] != "core_candidate", -item[1]))
        self.log.info("Met: %d candidate objects selected for image download", len(selected))
        for obj, score, role, panels, notes, record_id in selected:
            image_urls: list[tuple[str, str]] = []
            if obj.get("primaryImage"):
                image_urls.append(("full", obj["primaryImage"]))
            for n, url in enumerate(obj.get("additionalImages") or [], 1):
                if url and url not in [u for _, u in image_urls]:
                    image_urls.append((f"additional_{n:02d}", url))
            object_dir = self.raw_met / record_id
            success = 0
            for image_type, url in image_urls:
                image_id = f"{record_id}_{image_type}"
                existing_row = self.images.get(image_id)
                if existing_row and existing_row.get("local_file") and \
                   (self.root / str(existing_row["local_file"])).exists():
                    success += 1
                    continue
                if self.existing_group_counts[record_id] >= self.args.max_images_per_object:
                    self.stats["met_skipped_object_image_cap"] += 1
                    continue
                destination = object_dir / f"{image_id}{ext_for(url)}"
                digest, size, status, ctype = self.download(
                    url, destination, "The Met", image_id, image_type
                )
                image_row = self.objects[record_id].copy()
                image_row.update({
                    "record_id": image_id, "image_type": image_type, "image_url": url,
                    "local_file": str(destination.relative_to(self.root)) if status != "failed" else "",
                    "sha256": digest, "bytes": size, "mime": ctype,
                    "download_status": status,
                })
                self.images[image_id] = image_row
                if status != "failed" and not status.startswith("duplicate:"):
                    success += 1
                    self.existing_group_counts[record_id] += 1
            self.objects[record_id]["download_status"] = f"{success}/{len(image_urls)} images"
            self.candidates[record_id] = self.objects[record_id].copy()
            self.stats["met_images_downloaded"] += success

    def commons_members(self) -> dict[str, set[str]]:
        files: dict[str, set[str]] = {}
        queue = [(cat, 0) for cat in COMMONS_CATEGORIES]
        seen_categories: set[str] = set()
        while queue and len(files) < self.args.commons_max_files:
            category, depth = queue.pop(0)
            if category in seen_categories:
                continue
            seen_categories.add(category)
            cont = ""
            while len(files) < self.args.commons_max_files:
                params = {
                    "action": "query", "format": "json", "formatversion": "2",
                    "list": "categorymembers", "cmtitle": category,
                    "cmtype": "file|subcat", "cmlimit": "100",
                }
                if cont: params["cmcontinue"] = cont
                data = self.get_json(COMMONS_API, params)
                for member in data.get("query", {}).get("categorymembers", []):
                    if len(files) >= self.args.commons_max_files:
                        break
                    title = member.get("title", "")
                    if member.get("ns") == 6:
                        files.setdefault(title, set()).add(category)
                    elif member.get("ns") == 14 and depth < self.args.commons_depth:
                        queue.append((title, depth + 1))
                cont = data.get("continue", {}).get("cmcontinue", "")
                if not cont: break
            time.sleep(self.args.api_delay)
        # Complement category traversal with Commons' official search API. Search
        # is discovery only; every result still receives full metadata screening.
        for query in COMMONS_SEARCH_QUERIES:
            if len(files) >= self.args.commons_max_files:
                break
            cont = 0
            while len(files) < self.args.commons_max_files:
                try:
                    data = self.get_json(COMMONS_API, {
                        "action": "query", "format": "json", "formatversion": "2",
                        "list": "search", "srsearch": query, "srnamespace": "6",
                        "srlimit": "50", "sroffset": str(cont),
                    })
                except Exception as exc:
                    self._record_failure("Wikimedia Commons", f"search:{query}", COMMONS_API, exc)
                    break
                found = data.get("query", {}).get("search", [])
                if not found:
                    break
                for item in found:
                    files.setdefault(item.get("title", ""), set()).add(f"search:{query}")
                    if len(files) >= self.args.commons_max_files:
                        break
                cont += len(found)
                if len(found) < 50 or cont >= 200:
                    break
                time.sleep(self.args.api_delay)
        return files

    @staticmethod
    def commons_assessment(title: str, ext: dict[str, Any], categories: str,
                           license_class: str) -> tuple[int, str, str, str]:
        description = clean_text(ext.get("ImageDescription", {}).get("value"))
        date = clean_text(ext.get("DateTimeOriginal", {}).get("value"))
        text = f"{title} {description} {categories} {date}".lower()
        subject_text = f"{title} {description}".lower()
        score, reasons = 0, []
        explicit_screen = any(t in subject_text for t in
                              ("folding screen", "folding screens", "standing screen", "lacquer screen",
                               "paravent", "屏风", "屏風", "coromandel screen"))
        if explicit_screen: score += 5
        elif "screen" in subject_text: score += 2
        else: reasons.append("screen object not explicit in title/description")
        if any(t in text for t in ("chinese", "china", "cina", "qing", "ming", "coromandel")): score += 4
        else: reasons.append("Chinese origin not explicit")
        if any(t in text for t in ("qing", "ming", "17th century", "18th century", "19th century",
                                    "1700", "1800", "1720", "1750")): score += 3
        else: reasons.append("Ming/Qing date not explicit")
        panels = panel_count(text)
        if panels: score += 3 if int(panels) >= 4 else 1
        if any(t in text for t in ("lacquer", "coromandel", "wood", "lacca")): score += 2
        if license_class in {"public_domain", "cc0", "cc_by"}: score += 3
        elif license_class == "cc_by_sa_review": score += 1
        exclusion = ""
        rules = {
            "Japanese screen": ("japanese", "japan", "byobu", "byōbu"),
            "Korean screen": ("korean", "korea", "joseon"),
            "European/Western screen": ("french screen", "english screen", "european screen",
                                        "made in france", "made in england"),
            "modern/contemporary screen": ("modern screen", "contemporary screen", "modern reproduction",
                                           "contemporary folding screen"),
            "fire screen": ("fire screen", "firescreen"),
            "painting/print/photograph depicting screen": ("painting of", "portrait", "print", "engraving",
                                                          "poster", "photograph of"),
            "modern/interior/context photo": ("restaurant", "window screen", "auction preview", "hall of china"),
            "table/desk/insertion/hanging screen": ("table screen", "desk screen", "hanging screen",
                                                     "insertion screen"),
            "object itself is not a screen": ("screen ornament", "screen fragment", "design for a screen",
                                               "médailler", "medailler", "cabinet made from screen",
                                               "lacquer panel only"),
        }
        for label, tokens in rules.items():
            if any(t in text for t in tokens):
                exclusion = label
                score -= 20
                break
        if not explicit_screen and not exclusion:
            exclusion = "painting/print depicting screen" if any(
                t in subject_text for t in ("painting", "portrait", "artist", "oil on canvas")
            ) else "non-screen/context image"
            score -= 12
        panels = panel_count(text)
        chinese_explicit = any(t in text for t in
                               ("chinese", "china", "cina", "qing", "ming", "coromandel"))
        # Museum-object titles often use simply "Screen with ... China, Qing".
        # Treat that as an explicit screen object when Chinese attribution is also
        # present; context/computer/window/etc. photos are excluded by rules above.
        if not explicit_screen and chinese_explicit and re.search(r"\bscreen\b", subject_text):
            explicit_screen = True
        role = "rejected"
        if not exclusion and explicit_screen and chinese_explicit:
            role = ("core_candidate" if panels and int(panels) >= 4
                    else "auxiliary_candidate")
        elif not exclusion:
            exclusion = "object itself is not an explicitly Chinese screen"
        return score, role, exclusion, "; ".join(reasons)

    def collect_commons(self) -> None:
        try:
            files = self.commons_members()
        except Exception as exc:
            self._record_failure("Wikimedia Commons", "category-discovery", COMMONS_API, exc)
            return
        self.stats["commons_found"] = len(files)
        self.log.info("Commons: discovered %d category files", len(files))
        titles = list(files)
        for offset in range(0, len(titles), 20):
            batch = titles[offset:offset + 20]
            try:
                data = self.get_json(COMMONS_API, {
                    "action": "query", "format": "json", "formatversion": "2",
                    "prop": "imageinfo|categories", "titles": "|".join(batch),
                    "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(self.args.commons_image_width),
                    "cllimit": "max",
                })
            except Exception as exc:
                self._record_failure("Wikimedia Commons", f"batch-{offset}", COMMONS_API, exc)
                continue
            for page in data.get("query", {}).get("pages", []):
                title = page.get("title", "")
                info = (page.get("imageinfo") or [{}])[0]
                ext = info.get("extmetadata") or {}
                categories = "; ".join(c.get("title", "").removeprefix("Category:")
                                       for c in page.get("categories", []))
                lic = clean_text(ext.get("LicenseShortName", {}).get("value"))
                usage = clean_text(ext.get("UsageTerms", {}).get("value"))
                lic_class = classify_license(lic, usage)
                score, role, exclusion, notes = self.commons_assessment(
                    title, ext, categories, lic_class
                )
                page_id = page.get("pageid", hashlib.sha1(title.encode()).hexdigest()[:12])
                record_id = f"COM_{page_id}"
                existing_row = self.images.get(record_id)
                if existing_row and existing_row.get("local_file") and \
                   (self.root / str(existing_row["local_file"])).exists():
                    continue
                row = self.base_row(record_id)
                description = clean_text(ext.get("ImageDescription", {}).get("value"))
                row.update({
                    "screen_id": record_id, "object_group_auto": commons_group_key(title, categories),
                    "source": "Wikimedia Commons",
                    "source_object_id": page_id, "object_name": "", "title": title.removeprefix("File:"),
                    "object_type": "image-level candidate", "date": "",
                    "culture": "", "country": "", "material": "",
                    "panel_count_guess": panel_count(f"{title} {description} {categories}"),
                    "surface_type": surface_type(f"{title} {description} {categories}"),
                    "museum": "", "license": lic or usage, "license_class": lic_class,
                    "source_url": info.get("descriptionurl", ""), "image_url": info.get("url", ""),
                    "thumbnail_url": info.get("thumburl", ""), "pixel_width": info.get("width", ""),
                    "pixel_height": info.get("height", ""), "mime": info.get("mime", ""),
                    "candidate_score": score,
                    "period_group": ("traditional_core" if role == "core_candidate" else
                                     "traditional_auxiliary" if role == "auxiliary_candidate" and any(
                                         t in f"{title} {description} {categories}".lower() for t in
                                         ("traditional", "ming", "qing", "17th century", "18th century",
                                          "19th century", "kangxi", "qianlong", "coromandel")
                                     ) else "unknown_review" if role == "auxiliary_candidate" else ""),
                    "dataset_role": role,
                    "needs_manual_review": truth(role == "auxiliary_candidate"),
                    "include_core": truth(role == "core_candidate"),
                    "is_floorstanding": "", "is_spatial_partition": "",
                    "is_chinese_ming_qing": "", "notes": notes,
                    "download_status": "metadata_only",
                    "query_or_category": "; ".join(sorted(files.get(title, set()))),
                    "artist": clean_text(ext.get("Artist", {}).get("value")),
                    "credit": clean_text(ext.get("Credit", {}).get("value")),
                    "datetime_original": clean_text(ext.get("DateTimeOriginal", {}).get("value")),
                    "categories": categories, "image_description": description,
                })
                self.stats[f"commons_license_{lic_class}"] += 1
                if exclusion:
                    row["notes"] = f"EXCLUDED: {exclusion}; {notes}".strip("; ")
                    self.rejected[record_id] = row
                    self.stats[f"excluded_{exclusion}"] += 1
                    continue
                if role not in {"core_candidate", "auxiliary_candidate"}:
                    row["notes"] = f"EXCLUDED: {exclusion or 'not a candidate'}; {notes}".strip("; ")
                    self.rejected[record_id] = row
                    continue
                self.candidates[record_id] = row.copy()
                if lic_class == "unverified":
                    row["needs_manual_review"] = "yes"
                    row["notes"] = f"{notes}; license unverified: metadata only, image not downloaded".strip("; ")
                    self.candidates[record_id] = row.copy()
                    self.stats["candidate_license_unverified"] += 1
                    continue
                group_key = row.get("object_group_manual") or row.get("object_group_auto") or record_id
                if self.existing_group_counts[str(group_key)] >= self.args.max_images_per_object:
                    # The object is already represented sufficiently. Keep existing
                    # rows and direct bandwidth toward new physical screens.
                    if record_id not in self.images:
                        self.candidates.pop(record_id, None)
                    self.stats["commons_skipped_object_image_cap"] += 1
                    continue
                # Use Commons' official Special:Redirect/file endpoint for scaled
                # files. It handles the canonical thumbnail bucket and avoids stale
                # API-generated upload URLs. Preserve API original/thumbnail URLs.
                url = ("https://commons.wikimedia.org/wiki/Special:Redirect/file/" +
                       quote(title.removeprefix("File:"), safe="") +
                       f"?width={self.args.commons_image_width}")
                if not url:
                    self._record_failure("Wikimedia Commons", record_id, "", ValueError("missing original URL"))
                    continue
                destination = self.raw_commons / f"{record_id}_{safe_name(Path(title).stem, 70)}{ext_for(url, info.get('mime', ''))}"
                digest, size, status, ctype = self.download(url, destination,
                                                            "Wikimedia Commons", record_id,
                                                            f"scaled_{self.args.commons_image_width}px")
                if status != "failed" and destination.exists():
                    correct_ext = actual_image_ext(destination, ctype)
                    if correct_ext and destination.suffix.lower() != correct_ext:
                        corrected = destination.with_suffix(correct_ext)
                        os.replace(destination, corrected)
                        destination = corrected
                row.update({
                    "image_type": f"scaled_{self.args.commons_image_width}px", "local_file": str(destination.relative_to(self.root))
                    if status != "failed" else "", "sha256": digest, "bytes": size,
                    "mime": ctype or info.get("mime", ""), "download_status": status,
                })
                self.images[record_id] = row
                self.candidates[record_id] = row.copy()
                if status != "failed" and not status.startswith("duplicate:"):
                    self.stats["commons_images_downloaded"] += 1
                    self.existing_group_counts[str(group_key)] += 1
                time.sleep(self.args.commons_download_delay)
            time.sleep(self.args.api_delay)

    def collect_open_museums(self) -> None:
        """Collect a small, curator-verified set from official CC0 APIs/IIIF.

        Discovery is deliberately separate from inclusion: identifiers below
        were reviewed against the museum's object type, origin and dimensions.
        This prevents broad full-text searches from admitting desk screens,
        Japanese/Korean screens, prints, or depictions of screens.
        """
        try:
            payload = self.get_json(f"{AIC_API}/artworks", {
                "ids": ",".join(map(str, AIC_SCREEN_IDS)),
                "fields": ("id,title,date_display,place_of_origin,artwork_type_title,"
                           "department_title,artist_display,medium_display,dimensions,"
                           "credit_line,main_reference_number,image_id,alt_image_ids,"
                           "is_public_domain"),
            })
            for obj in payload.get("data", []):
                object_id = str(obj.get("id", ""))
                if not object_id or not obj.get("is_public_domain") or not obj.get("image_id"):
                    continue
                record_id = f"AIC_{object_id}"
                title = clean_text(obj.get("title"))
                text = " ".join(clean_text(obj.get(k)) for k in
                                ("title", "date_display", "place_of_origin",
                                 "artwork_type_title", "medium_display"))
                # These two official records are complete physical screens.
                panels = "4" if object_id == "28052" else "2"
                role = "core_candidate" if int(panels) >= 4 else "auxiliary_candidate"
                row = self.base_row(record_id)
                row.update({
                    "screen_id": record_id, "source_group_id": record_id,
                    "source": "Art Institute of Chicago", "source_object_id": object_id,
                    "title": title, "object_name": clean_text(obj.get("artwork_type_title")),
                    "object_type": clean_text(obj.get("artwork_type_title")),
                    "period": clean_text(obj.get("date_display")),
                    "period_group": ("traditional_core" if role == "core_candidate"
                                     else "traditional_auxiliary"),
                    "date": clean_text(obj.get("date_display")), "culture": "Chinese",
                    "country": clean_text(obj.get("place_of_origin")),
                    "material": clean_text(obj.get("medium_display")),
                    "surface_type": surface_type(text),
                    "dimensions": clean_text(obj.get("dimensions")),
                    "panel_count_guess": panels,
                    "museum": "Art Institute of Chicago",
                    "accession_no": clean_text(obj.get("main_reference_number")),
                    "license": "CC0", "license_class": "cc0",
                    "source_url": f"https://www.artic.edu/artworks/{object_id}",
                    "candidate_score": 22 if role == "core_candidate" else 18,
                    "dataset_role": role,
                    "needs_manual_review": truth(role == "auxiliary_candidate"),
                    "include_core": truth(role == "core_candidate"),
                    "notes": "Official object record reviewed: complete physical Chinese screen.",
                })
                self.objects[record_id] = row.copy()
                self.candidates[record_id] = row.copy()
                image_id = f"{record_id}_full"
                url = f"{AIC_IIIF}/{obj['image_id']}/full/843,/0/default.jpg"
                destination = self.raw_open / f"{image_id}.jpg"
                digest, size, status, ctype = self.download(
                    url, destination, "Art Institute of Chicago", image_id, "full"
                )
                if status != "failed":
                    image_row = row.copy()
                    image_row.update({
                        "record_id": image_id, "source_group_id": record_id,
                        "source_object_id": object_id, "image_type": "full",
                        "image_url": url, "thumbnail_url": url,
                        "local_file": str(destination.relative_to(self.root)),
                        "sha256": digest, "bytes": size, "mime": ctype or "image/jpeg",
                        "download_status": status,
                    })
                    self.images[image_id] = image_row
                time.sleep(max(1.0, self.args.api_delay))
        except Exception as exc:
            self._record_failure("Art Institute of Chicago", "discovery", AIC_API, exc)

        record_id = "SI_F1906_42A_L"
        title = "Twelve-panel screen depicting Spring Morning in the Han Palace"
        row = self.base_row(record_id)
        row.update({
            "screen_id": record_id, "source_group_id": record_id,
            "source": "Smithsonian National Museum of Asian Art",
            "source_object_id": "edanmdm:fsg_F1906.42a-l", "title": title,
            "object_name": "Furniture and Furnishing", "object_type": "Folding screen",
            "period": "Qing dynasty, Kangxi reign", "period_group": "traditional_core",
            "date": "May-June 1672", "date_begin": 1672, "date_end": 1672,
            "culture": "Chinese", "country": "China",
            "material": ("Black lacquer on prepared wooden core; carved recesses filled "
                         "with polychrome pigments and gold (kuancai)"),
            "surface_type": "lacquer", "dimensions": "216.5 x 50.1 x 606.5 cm",
            "panel_count_guess": "12", "museum": "National Museum of Asian Art",
            "accession_no": "F1906.42a-l", "license": "CC0", "license_class": "cc0",
            "source_url": SMITHSONIAN_OBJECT_URL, "candidate_score": 25,
            "dataset_role": "core_candidate", "needs_manual_review": "no",
            "include_core": "yes",
            "notes": "Official object page and IIIF manifest reviewed; complete 12-panel screen.",
        })
        self.objects[record_id] = row.copy()
        self.candidates[record_id] = row.copy()
        for number in range(1, min(self.args.max_images_per_object, 4) + 1):
            image_id = f"{record_id}_{number:03d}"
            try:
                manifest_url = smithsonian_manifest(number)
                manifest = self.get_json(manifest_url)
                canvas = manifest["sequences"][0]["canvases"][0]
                resource = canvas["images"][0]["resource"]
                service = resource.get("service", {}).get("@id", "")
                if not service:
                    raise ValueError("IIIF image service missing")
                url = f"{service}/full/1200,/0/default.jpg"
                image_type = "full" if number == 1 else f"additional_{number - 1:02d}"
                destination = self.raw_open / f"{image_id}.jpg"
                digest, size, status, ctype = self.download(
                    url, destination, "Smithsonian National Museum of Asian Art",
                    image_id, image_type
                )
                if status != "failed":
                    image_row = row.copy()
                    image_row.update({
                        "record_id": image_id, "source_group_id": record_id,
                        "image_type": image_type, "image_url": url,
                        "thumbnail_url": resource.get("@id", ""),
                        "local_file": str(destination.relative_to(self.root)),
                        "sha256": digest, "bytes": size,
                        "pixel_width": canvas.get("width", ""),
                        "pixel_height": canvas.get("height", ""),
                        "mime": ctype or "image/jpeg", "download_status": status,
                    })
                    self.images[image_id] = image_row
                time.sleep(max(1.0, self.args.api_delay))
            except Exception as exc:
                self._record_failure("Smithsonian National Museum of Asian Art",
                                     image_id, smithsonian_manifest(number), exc)

        obj = RIJKS_SCREEN
        record_id = obj["record_id"]
        row = self.base_row(record_id)
        row.update({
            "screen_id": record_id, "source_group_id": record_id,
            "source": "Rijksmuseum", "source_object_id": obj["source_object_id"],
            "title": obj["title"], "object_name": "kamerscherm",
            "object_type": "Folding screen; furniture", "period": "Qing dynasty",
            "period_group": "traditional_core", "date": obj["date"],
            "date_begin": 1685, "date_end": 1700, "culture": "Chinese",
            "country": "South China", "material": "Coromandel lacquer; bronze",
            "surface_type": "lacquer", "dimensions": "321 x 624 x 2 cm",
            "panel_count_guess": "12", "museum": "Rijksmuseum",
            "accession_no": obj["accession_no"], "license": "Public Domain",
            "license_class": "public_domain", "source_url": obj["source_url"],
            "candidate_score": 25, "dataset_role": "core_candidate",
            "needs_manual_review": "no", "include_core": "yes",
            "notes": ("Official object page and Linked Art record reviewed; complete "
                      "12-panel screen made in South China."),
        })
        self.objects[record_id] = row.copy()
        self.candidates[record_id] = row.copy()
        image_id = f"{record_id}_full"
        destination = self.raw_open / f"{image_id}.jpg"
        digest, size, status, ctype = self.download(
            obj["image_url"], destination, "Rijksmuseum", image_id, "full"
        )
        if status != "failed":
            image_row = row.copy()
            image_row.update({
                "record_id": image_id, "source_group_id": record_id,
                "image_type": "full", "image_url": obj["image_url"],
                "thumbnail_url": "https://iiif.micr.io/poNLD/full/400,/0/default.jpg",
                "local_file": str(destination.relative_to(self.root)),
                "sha256": digest, "bytes": size, "mime": ctype or "image/jpeg",
                "download_status": status,
            })
            self.images[image_id] = image_row

    @staticmethod
    def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fields})

    def assign_stable_screen_ids(self, object_rows: list[dict[str, Any]],
                                 image_rows: list[dict[str, Any]]) -> dict[str, str]:
        existing = dict(self.stable_screen_ids)
        used_numbers = [int(m.group(1)) for sid in existing.values()
                        if (m := re.fullmatch(r"S(\d+)", sid))]
        next_number = max(used_numbers, default=0) + 1
        group_to_sid: dict[str, str] = {}
        for row in object_rows:
            group = str(row.get("record_id", ""))
            sid = existing.get(group, "")
            if not sid:
                sid = f"S{next_number:03d}"
                next_number += 1
            group_to_sid[group] = sid
            row["source_group_id"] = group
            row["screen_id"] = sid
        for row in image_rows:
            group = str(row.get("object_group_manual") or row.get("source_group_id") or
                        row.get("object_group_auto") or row.get("screen_id") or row.get("record_id"))
            sid = group_to_sid.get(group) or existing.get(group)
            if sid:
                row["source_group_id"] = group
                row["screen_id"] = sid
                row["image_id"] = row.get("record_id", "")
        return group_to_sid

    @staticmethod
    def image_basename(row: dict[str, Any], sequence: int, used: set[str], suffix: str) -> str:
        kind = str(row.get("image_type", "")).lower()
        title = str(row.get("title", "")).lower()
        if "recto" in title or "front" in title or kind == "full":
            base = "full"
        elif "verso" in title or "reverse" in title or "back" in title:
            base = "reverse"
        elif "detail" in title or "détail" in title:
            base = "detail"
        elif kind.startswith("additional"):
            base = kind
        else:
            base = "full" if sequence == 1 else "additional"
        candidate = f"{base}{suffix}"
        n = 1
        while candidate.lower() in used:
            candidate = f"{base}_{n:02d}{suffix}"
            n += 1
        used.add(candidate.lower())
        return candidate

    def organize_object_directories(self, object_rows: list[dict[str, Any]],
                                    image_rows: list[dict[str, Any]]) -> None:
        raw_root = self.root / "raw"
        raw_root.mkdir(parents=True, exist_ok=True)
        by_screen: dict[str, list[dict[str, Any]]] = {}
        for row in image_rows:
            if row.get("screen_id") and row.get("local_file"):
                by_screen.setdefault(str(row["screen_id"]), []).append(row)
        for sid, rows in by_screen.items():
            target_dir = raw_root / sid
            target_dir.mkdir(parents=True, exist_ok=True)
            used: set[str] = {p.name.lower() for p in target_dir.iterdir() if p.is_file()}
            for sequence, row in enumerate(sorted(rows, key=lambda r: str(r.get("record_id", ""))), 1):
                source = self.root / str(row.get("local_file", ""))
                if not source.exists():
                    # Locate an already organized byte-identical image on rerun.
                    matches = [p for p in target_dir.iterdir() if p.is_file() and
                               hashlib.sha256(p.read_bytes()).hexdigest() == row.get("sha256")]
                    if matches:
                        row["local_file"] = str(matches[0].relative_to(self.root))
                        continue
                    self.log.warning("Cannot organize missing image %s", source)
                    continue
                if source.parent == target_dir:
                    row["local_file"] = str(source.relative_to(self.root))
                    continue
                suffix = actual_image_ext(source, str(row.get("mime", ""))) or source.suffix.lower()
                name = self.image_basename(row, sequence, used, suffix)
                target = target_dir / name
                shutil.copy2(source, target)
                if row.get("sha256") and hashlib.sha256(target.read_bytes()).hexdigest() != row["sha256"]:
                    target.unlink(missing_ok=True)
                    raise ValueError(f"SHA256 changed while organizing {row.get('record_id')}")
                row["local_file"] = str(target.relative_to(self.root))

        legacy_dirs = [raw_root / name for name in ("met", "commons", "open_museums")
                       if (raw_root / name).exists()]
        staging = self.root / "staging"
        if staging.exists():
            legacy_dirs.append(staging)
        if legacy_dirs:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive = self.root / "archive" / f"raw_legacy_{stamp}"
            archive.mkdir(parents=True, exist_ok=True)
            for path in legacy_dirs:
                target = archive / path.name
                if target.exists():
                    target = archive / f"{path.name}_{hashlib.sha1(str(path).encode()).hexdigest()[:6]}"
                shutil.move(str(path), str(target))

        valid_sids = {str(r.get("screen_id")) for r in object_rows}
        actual_sids = {p.name for p in raw_root.iterdir() if p.is_dir() and re.fullmatch(r"S\d{3,}", p.name)}
        if actual_sids != valid_sids:
            raise ValueError(f"Object folder mismatch: expected {len(valid_sids)}, got {len(actual_sids)}")

    def write_review(self, object_rows: list[dict[str, Any]]) -> None:
        existing = {r.get("screen_id", ""): r for r in self._read_csv_rows("review.csv")}
        rows = []
        for obj in object_rows:
            sid = str(obj.get("screen_id", ""))
            old = existing.get(sid, {})
            rows.append({"screen_id": sid, "keep": old.get("keep", ""),
                         "training": old.get("training", ""), "quality": old.get("quality", ""),
                         "notes": old.get("notes", "")})
        self.write_csv(self.metadata_dir / "review.csv", rows, REVIEW_FIELDS)

    def finish(self) -> dict[str, Any]:
        self.snapshot_metadata()
        # Re-audit persisted candidates so stricter hard-error rules can correct an
        # earlier broad run without deleting any successfully downloaded bytes.
        for record_id, row in list(self.candidates.items()):
            reason = self.hard_error_from_saved_metadata(row)
            if reason:
                row = row.copy()
                row.update({"dataset_role": "rejected", "include_core": "no",
                            "needs_manual_review": "no",
                            "notes": f"EXCLUDED: {reason}; {row.get('notes', '')}".strip("; ")})
                self.rejected[record_id] = row
                del self.candidates[record_id]
                if record_id in self.images:
                    self.images[record_id].update({"dataset_role": "rejected", "include_core": "no",
                                                   "needs_manual_review": "no", "notes": row["notes"]})
        # Keep image-level roles consistent with the authoritative candidate and
        # rejection maps, including corrections made in an earlier metadata run.
        for record_id, image_row in self.images.items():
            if record_id in self.rejected:
                image_row.update({"dataset_role": "rejected", "include_core": "no",
                                  "needs_manual_review": "no",
                                  "notes": self.rejected[record_id].get("notes", image_row.get("notes", ""))})
            elif record_id in self.candidates:
                image_row.update({key: self.candidates[record_id].get(key, image_row.get(key, ""))
                                  for key in ("dataset_role", "include_core", "needs_manual_review",
                                              "period_group", "surface_type", "object_group_auto")})
        all_image_rows = sorted((self.backfill_row(r) for r in self.images.values()),
                                key=lambda r: (r.get("source", ""), r["record_id"]))
        image_rows = [r for r in all_image_rows if r.get("dataset_role") in
                      {"core_candidate", "auxiliary_candidate"}]
        candidate_rows = sorted((self.backfill_row(r) for r in self.candidates.values()),
                                key=lambda r: (-int(r.get("candidate_score") or 0), r["record_id"]))
        rejected_rows = sorted((self.backfill_row(r) for r in self.rejected.values()),
                               key=lambda r: (r.get("notes", ""), r["record_id"]))
        core_rows = [r for r in candidate_rows if r.get("dataset_role") == "core_candidate"]
        auxiliary_rows = [r for r in candidate_rows if r.get("dataset_role") == "auxiliary_candidate"]
        # Build an object-level table. Official museum APIs are object-level;
        # Commons image records are conservatively grouped by normalized titles.
        direct_candidate_ids = {str(r.get("source_group_id") or r.get("record_id"))
                                for r in candidate_rows
                                if r.get("source") != "Wikimedia Commons"}
        direct_objects = [self.backfill_row(r) for r in self.objects.values()
                          if r.get("source") != "Wikimedia Commons" and
                          str(r.get("record_id")) in direct_candidate_ids]
        commons_groups: dict[str, list[dict[str, Any]]] = {}
        for row in candidate_rows:
            if row.get("source") == "Wikimedia Commons":
                key = (row.get("object_group_manual") or row.get("source_group_id") or
                       row.get("object_group_auto") or row["record_id"])
                commons_groups.setdefault(str(key), []).append(row)
        commons_objects: list[dict[str, Any]] = []
        direct_by_id = {r.get("record_id"): r for r in direct_objects}
        for key, rows in commons_groups.items():
            if key in direct_by_id:
                direct_by_id[key]["notes"] = (
                    f"{direct_by_id[key].get('notes', '')}; {len(rows)} linked Commons image records"
                ).strip("; ")
                continue
            representative = max(rows, key=lambda r: int(r.get("candidate_score") or 0)).copy()
            representative.update({"record_id": key, "screen_id": key, "image_type": "",
                                   "image_url": "", "local_file": "", "sha256": "", "bytes": "",
                                   "download_status": f"{len(rows)} image records",
                                   "notes": f"Auto-grouped Commons object; {representative.get('notes', '')}".strip("; ")})
            if any(r.get("dataset_role") == "core_candidate" for r in rows):
                representative.update({"dataset_role": "core_candidate", "include_core": "yes"})
            commons_objects.append(representative)
        object_rows = sorted(direct_objects + commons_objects,
                             key=lambda r: (-int(r.get("candidate_score") or 0), r["record_id"]))
        image_groups_present = {
            str(r.get("object_group_manual") or r.get("source_group_id") or
                r.get("object_group_auto") or r.get("screen_id") or r.get("record_id"))
            for r in image_rows if r.get("local_file")
        }
        object_rows = [r for r in object_rows if str(r.get("record_id", "")) in image_groups_present]
        for obj in object_rows:
            group = str(obj.get("record_id", ""))
            linked = [r for r in image_rows if str(r.get("object_group_manual") or
                      r.get("source_group_id") or r.get("object_group_auto") or
                      r.get("screen_id") or r.get("record_id")) == group]
            obj["source_group_id"] = group
            obj["source_record_ids"] = "; ".join(sorted({str(r.get("record_id", "")) for r in linked}))
            obj["image_count"] = len(linked)

        self.assign_stable_screen_ids(object_rows, image_rows)
        self.organize_object_directories(object_rows, image_rows)
        self.write_csv(self.metadata_dir / "objects.csv", object_rows, OBJECT_FIELDS)
        self.write_csv(self.metadata_dir / "images.csv", image_rows, IMAGE_FIELDS)
        self.write_review(object_rows)
        failure_fields = ["source", "record_id", "image_type", "image_url", "http_status",
                          "error_type", "error", "timestamp_utc"]
        self.write_csv(self.logs_dir / "download_failures.csv", self.failures, failure_fields)

        # The detailed development tables remain available in metadata/history.
        for name in ("candidate_review.csv", "core_candidates.csv", "auxiliary_candidates.csv",
                     "rejected_candidates.csv", "download_failures.csv", "run_report.json"):
            (self.metadata_dir / name).unlink(missing_ok=True)

        # Count usable local image rows, including byte-identical files reused
        # from an already organized Sxxx directory on an incremental rerun.
        downloaded = [r for r in image_rows if r.get("local_file") and
                      (self.root / str(r.get("local_file"))).exists()]
        candidate_downloaded = [r for r in downloaded if r.get("dataset_role") in
                                {"core_candidate", "auxiliary_candidate"}]
        downloaded_commons = [r for r in downloaded if r.get("source") == "Wikimedia Commons"]
        total_bytes = sum(int(r.get("bytes") or 0) for r in downloaded)
        images_by_object: Counter[str] = Counter()
        for row in candidate_downloaded:
            key = (row.get("object_group_manual") or row.get("source_group_id") or
                   row.get("object_group_auto") or row.get("screen_id") or row.get("record_id"))
            images_by_object[str(key)] += 1
        candidate_object_rows = [r for r in object_rows if r.get("dataset_role") in
                                 {"core_candidate", "auxiliary_candidate"}]
        source_objects = Counter(r.get("source", "") for r in candidate_object_rows)
        source_images = Counter(r.get("source", "") for r in candidate_downloaded)
        report = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_root": str(self.root),
            "met": {
                "raw_search_hits_with_overlap": self.stats["met_search_hits"],
                "objects_inspected": len(self.objects),
                "core_objects": sum(r.get("include_core") == "yes" for r in object_rows),
                "candidate_objects": sum(r.get("source") == "The Met" for r in candidate_rows),
                "images_downloaded": sum(r.get("source") == "The Met" for r in downloaded),
            },
            "commons": {
                "files_found": self.stats["commons_found"],
                "candidate_records": sum(r.get("source") == "Wikimedia Commons" for r in candidate_rows),
                "images_downloaded": len(downloaded_commons),
                "licenses_found": {k.removeprefix("commons_license_"): v for k, v in self.stats.items()
                             if k.startswith("commons_license_")},
                "licenses_downloaded": dict(Counter(r.get("license_class", "")
                                                     for r in downloaded_commons)),
            },
            "total": {"downloaded_images_all": len(downloaded),
                      "candidate_images": len(candidate_downloaded), "bytes": total_bytes,
                      "mib": round(total_bytes / 1048576, 2), "failures": len(self.failures),
                      "candidate_objects": len(candidate_object_rows),
                      "objects_with_one_image": sum(v == 1 for v in images_by_object.values())},
            "source_contributions": {
                source: {"candidate_objects": source_objects[source],
                         "candidate_images": source_images[source]}
                for source in sorted(set(source_objects) | set(source_images))
            },
            "dataset_roles": {
                "core_candidate_records": len(core_rows),
                "auxiliary_candidate_records": len(auxiliary_rows),
                "rejected": len(rejected_rows),
                "core_candidate_images": sum(r.get("dataset_role") == "core_candidate" for r in candidate_downloaded),
                "auxiliary_candidate_images": sum(r.get("dataset_role") == "auxiliary_candidate" for r in candidate_downloaded),
                "core_candidate_objects": sum(r.get("dataset_role") == "core_candidate" for r in object_rows),
                "auxiliary_candidate_objects": sum(r.get("dataset_role") == "auxiliary_candidate" for r in object_rows),
                "independent_candidate_objects": sum(r.get("dataset_role") in
                                                     {"core_candidate", "auxiliary_candidate"}
                                                     for r in object_rows),
            },
            "exclusions": {k.removeprefix("excluded_"): v for k, v in self.stats.items()
                           if k.startswith("excluded_")},
            "errors": dict(self.error_counts),
            "top_candidates": [{
                "record_id": r.get("record_id", ""), "title": r.get("title", ""),
                "date": r.get("date", ""), "source": r.get("source", ""),
                "panels_explicit": r.get("panel_count_guess", ""),
                "score": r.get("candidate_score", ""),
                "image_count": images_by_object.get(str(r.get("object_group_manual") or
                                                       r.get("object_group_auto") or
                                                       r.get("screen_id") or r.get("record_id")), 0),
            } for r in candidate_rows[:20]],
        }
        (self.logs_dir / "run_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.log.info("Complete: %d images, %.2f MiB, %d failures",
                      len(downloaded), total_bytes / 1048576, len(self.failures))
        return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("screen_dataset"))
    parser.add_argument("--met-max-objects", type=int, default=240,
                        help="maximum unique Met object records to inspect")
    parser.add_argument("--commons-max-files", type=int, default=120)
    parser.add_argument("--commons-depth", type=int, default=1)
    parser.add_argument("--commons-image-width", type=int, default=800,
                        help="official Commons scaled image width; original URL remains in metadata")
    parser.add_argument("--commons-download-delay", type=float, default=1.0)
    parser.add_argument("--max-images-per-object", type=int, default=4,
                        help="download cap per grouped object; existing images are never deleted")
    parser.add_argument("--commons-curl-first", action=argparse.BooleanOptionalAction,
                        default=(os.name == "nt"),
                        help="prefer curl for Commons file bytes (default on Windows)")
    parser.add_argument("--review-score", type=int, default=11)
    parser.add_argument("--commons-download-score", type=int, default=9)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-retry-wait", type=float, default=10.0)
    parser.add_argument("--min-bytes", type=int, default=10_000)
    parser.add_argument("--api-delay", type=float, default=0.25)
    parser.add_argument("--only", choices=("all", "met", "commons", "open", "metadata"), default="all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    collector = Collector(args.output, args)
    config = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "arguments": vars(args), "met_seed_ids": SEED_MET_IDS,
        "met_queries": MET_QUERIES, "commons_categories": COMMONS_CATEGORIES,
        "commons_search_queries": COMMONS_SEARCH_QUERIES,
        "selection_note": "Candidate scores rank review only; they do not replace human confirmation.",
        "split_rule": "Split train/validation/test by screen_id or completed object_group_manual, never by image.",
    }
    config["arguments"]["output"] = str(config["arguments"]["output"])
    collector.root.mkdir(parents=True, exist_ok=True)
    (collector.root / "run_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        if args.only in ("all", "met"):
            collector.collect_met()
        if args.only in ("all", "commons"):
            collector.collect_commons()
        if args.only in ("all", "open"):
            collector.collect_open_museums()
    finally:
        report = collector.finish()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
