#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Calibration Certificate Downloader (Qt6)

- Enter Equipment List URL + Cookie.
- (Optional) Follow pagination:
    * Follows normal "Next/1/2/…" links
    * Recognizes links containing 'sp='
    * If no links are found, synthesizes pages by iterating sp=offsets
      using the first page's item count (or 50) as the step.
- For each detail page:
    * Finds main certificate PDF
    * Finds secondary PDF under "Subcontracted Data" or "CISG as Found Data"
    * Downloads & merges (main first), saves as:
        VHM-COMXXXX due YYYY-MM-DD.pdf
"""

from __future__ import annotations

import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import (
    urljoin, urlparse, unquote, parse_qsl, urlencode, urlunparse
)

import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfMerger

from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QCheckBox, QPlainTextEdit, QProgressBar, QFileDialog
)

from PyQt6.QtGui import QIcon
import os, sys, ctypes
from pathlib import Path



def resource_path(rel_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller."""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return str(Path(base) / rel_path)

# Make Windows taskbar pinning use our app identity (for correct icon)
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VHM.CalibrationCertDownloader")
except Exception:
    pass


# ----------------------------- Config -----------------------------

APP_NAME = "Calibration Certificate Downloader (Qt6)"
OUTPUT_DIR = Path(__file__).resolve().parent / "downloads"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ----------------------------- Helpers -----------------------------

def parse_cookie_string(raw: str) -> dict:
    jar = {}
    for p in (raw or "").split(";"):
        p = p.strip()
        if not p or "=" not in p:
            continue
        k, v = p.split("=", 1)
        jar[k.strip()] = v.strip()
    return jar


def ensure_unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    stem, suffix = path.stem, path.suffix
    while True:
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "-", name).strip().strip(".")


def to_iso_date(s: str) -> Optional[str]:
    if not s:
        return None
    s = s.strip().replace("\xa0", " ")
    fmts = [
        "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"
    ]
    for fmt in fmts:
        try:
            from datetime import datetime as _dt
            dt = _dt.strptime(s, fmt)
            if dt.year < 100:
                dt = dt.replace(year=2000 + dt.year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def url_filename_from_response(resp: requests.Response, fallback_url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, flags=re.I)
    if m:
        return unquote(m.group(1).strip('"'))
    name = Path(unquote(urlparse(resp.url or fallback_url).path)).name
    return name or "download.pdf"


def normalize_label(s: str) -> str:
    return " ".join(s.replace("\xa0", " ").strip().lower().replace(":", "").split())


def set_query_param(url: str, **params) -> str:
    """Return url with given query param(s) set/replaced."""
    pu = urlparse(url)
    q = dict(parse_qsl(pu.query, keep_blank_values=True))
    for k, v in params.items():
        if v is None:
            q.pop(k, None)
        else:
            q[k] = str(v)
    new_query = urlencode(q, doseq=True)
    return urlunparse((pu.scheme, pu.netloc, pu.path, pu.params, new_query, pu.fragment))

# ------------------------- Parsing functions -------------------------

def extract_detail_urls_from_listing(html: str, base_url: str) -> List[str]:
    """Find all 'VIEW' links to itemzoom.aspx?item=..."""
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []

    def is_detail_href(href: str) -> bool:
        h = href.lower()
        return ("itemzoom" in h and "item=" in h) or ("itemzoom.aspx" in h)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text(" ", strip=True) or "").strip().lower()
        actual = href

        # Unwrap simple javascript: links pointing at itemzoom
        if actual.lower().startswith("javascript:"):
            m = re.search(r"(itemzoom[^'\"()]+)", actual, flags=re.I)
            if m:
                actual = m.group(1)

        if is_detail_href(actual) or (text.startswith("view") and "item=" in actual.lower()):
            abs_url = urljoin(base_url, actual)
            urls.append(abs_url)

    # De-duplicate while preserving order
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            unique.append(u)
            seen.add(u)
    return unique


def discover_pagination_links(html: str, base_url: str) -> List[str]:
    """
    Find explicit pagination links on the listing page (same host).
    Now also recognizes anchors containing 'sp=' (your site's offset param).
    """
    soup = BeautifulSoup(html, "html.parser")
    pages: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text(" ", strip=True) or "").strip().lower()
        hlow = href.lower()
        if any(t in hlow for t in ["page=", "pagenum", "startrow", "start=", "sp="]) or \
           text in {"next", "prev", "previous", ">>", "<<"} or \
           text.isdigit():
            pages.append(urljoin(base_url, href))

    base_parsed = urlparse(base_url)
    filtered = []
    seen = set()
    for u in pages:
        pu = urlparse(u)
        if pu.netloc == base_parsed.netloc:
            key = (pu.scheme, pu.netloc, pu.path, pu.query)
            if key not in seen:
                seen.add(key)
                filtered.append(u)
    return filtered


def synthesize_sp_pages(session: requests.Session,
                        first_url: str,
                        first_html: str,
                        first_item_count: int,
                        log_cb,
                        max_pages: int = 200) -> List[str]:
    """
    If the listing uses 'sp=' offsets but the page doesn't expose explicit links,
    synthesize page URLs by incrementing sp in 'step' increments until no new items.
    Example: first page -> sp=0 (or absent), second page -> sp=50, third -> sp=100...
    """
    pages: List[str] = []

    # Determine step size: use count from first page or fallback to 50.
    step = first_item_count if first_item_count > 0 else 50
    if step <= 0:
        step = 50

    # Determine if 'sp' exists on the first URL; default to 0 if missing.
    pu = urlparse(first_url)
    q = dict(parse_qsl(pu.query, keep_blank_values=True))
    start_sp = int(q.get("sp", "0") or "0")

    # Iterate next pages: sp = start_sp + step, +2*step, ...
    for i in range(1, max_pages + 1):
        next_sp = start_sp + i * step
        next_url = set_query_param(first_url, sp=next_sp)
        try:
            r = session.get(next_url, headers={**DEFAULT_HEADERS, "Referer": first_url}, timeout=30)
            r.raise_for_status()
            html = r.text
        except requests.RequestException as e:
            log_cb(f"   ⚠️  Could not fetch synthesized page {next_url}: {e}")
            break

        # Extract detail URLs; stop when no items found
        items = extract_detail_urls_from_listing(html, base_url=next_url)
        log_cb(f"   Synthesized page {i+1}: sp={next_sp} -> {len(items)} item(s)")
        if not items:
            break

        pages.append(next_url)

        # Continue until a page returns fewer than step? We simply continue until 0.
        # Many sites return <step> on last page; we still try the next one which returns 0 and we stop.

    return pages


def extract_tool_and_due_from_soup(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    tool = None
    due_raw = None

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        label = normalize_label(tds[0].get_text(" ", strip=True))
        value = tds[1].get_text(" ", strip=True).strip()

        if ("tool #" in label) or label.startswith("tool #") or label == "tool #":
            tool = value or tool

        if ("calibration due date" in label) or ("calibration due date(s)" in label) or ("next calibration due date" in label):
            due_raw = value or due_raw

    if not tool:
        full_text = soup.get_text(" ", strip=True)
        m_tool = re.search(r"\bVHM-COM\d{3,6}\b", full_text, flags=re.I)
        if m_tool:
            tool = m_tool.group(0).upper()

    due_iso = to_iso_date(due_raw) if due_raw else None
    if tool:
        tool = tool.strip().upper().replace(" ", "")

    return tool, due_iso


def get_pdf_links_from_soup(soup: BeautifulSoup, base_url: str) -> Tuple[Optional[str], List[str]]:
    """
    Returns (main_pdf_url, extra_pdf_urls)
      - main: row labeled 'Certificate (PDF Format)'
      - extras: 'Subcontracted Data' or 'CISG as Found Data'
    """
    main_pdf = None
    extras: List[str] = []

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        label = normalize_label(tds[0].get_text(" ", strip=True))
        cell = tds[1]

        pdfs_here = []
        for a in cell.find_all("a", href=True):
            h = a["href"]
            if ".pdf" in h.lower():
                pdfs_here.append(urljoin(base_url, h))

        if not pdfs_here:
            continue

        if "certificate (pdf format" in label or label.startswith("certificate (pdf format"):
            main_pdf = pdfs_here[0]
            continue

        if ("subcontracted data" in label) or ("cisg as found data" in label) or ("cisg as found" in label):
            for p in pdfs_here:
                if p not in extras:
                    extras.append(p)

    if not main_pdf:
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if ".pdf" in h.lower():
                main_pdf = urljoin(base_url, h)
                break

    return main_pdf, extras


# -------------------------- Worker (thread) --------------------------

@dataclass
class JobParams:
    listing_url: str
    cookie_string: str
    follow_pagination: bool
    output_dir: Path


class DownloaderWorker(QObject):
    progress = pyqtSignal(int)          # 0..100
    status = pyqtSignal(str)            # status line text
    log = pyqtSignal(str)               # append to log
    finished = pyqtSignal()             # done
    enable_ui = pyqtSignal(bool)        # enable/disable UI

    def __init__(self, params: JobParams):
        super().__init__()
        self.params = params
        self._stop = False
        self.progress_value = 0

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self.enable_ui.emit(False)
            self.progress.emit(0)
            self.status.emit("Initializing session…")

            s = requests.Session()
            s.headers.update(DEFAULT_HEADERS)
            if self.params.cookie_string.strip():
                s.cookies.update(parse_cookie_string(self.params.cookie_string))

            listing_url = self.params.listing_url.strip()
            if not listing_url:
                self.log.emit("❗ Listing URL is empty.")
                self.status.emit("Idle")
                self.progress.emit(0)
                return

            # 1) Load first listing page
            self.status.emit("Fetching listing page…")
            self.log.emit(f"GET {listing_url}")
            try:
                r = s.get(listing_url, headers=DEFAULT_HEADERS, timeout=30)
                r.raise_for_status()
                first_html = r.text
            except requests.RequestException as e:
                self.log.emit(f"❌ Cannot load listing page: {e}")
                self.status.emit("Error")
                return

            detail_urls = extract_detail_urls_from_listing(first_html, base_url=listing_url)
            first_count = len(detail_urls)
            self.log.emit(f"Found {first_count} detail URL(s) on the first page.")

            # 2) Pagination
            if self.params.follow_pagination:
                # 2a) Try explicit links (including ones with sp=)
                links = discover_pagination_links(first_html, base_url=listing_url)
                visited_pages = set([listing_url])
                for p in links:
                    if self._stop: break
                    if p in visited_pages: continue
                    visited_pages.add(p)
                    self.status.emit(f"Following pagination link…")
                    self.log.emit(f"GET {p}")
                    try:
                        rp = s.get(p, headers=DEFAULT_HEADERS, timeout=30)
                        rp.raise_for_status()
                        html = rp.text
                    except requests.RequestException as e:
                        self.log.emit(f"   ⚠️  Could not fetch {p}: {e}")
                        continue
                    items = extract_detail_urls_from_listing(html, base_url=p)
                    self.log.emit(f"   -> {len(items)} item(s)")
                    detail_urls.extend(items)

                # 2b) If no links found, synthesize pages by sp=offsets
                if len(links) == 0:
                    self.log.emit("No explicit pagination links; trying sp= offsets…")
                    sp_pages = synthesize_sp_pages(
                        session=s,
                        first_url=listing_url,
                        first_html=first_html,
                        first_item_count=first_count,
                        log_cb=self.log.emit,
                        max_pages=200,
                    )
                    for p in sp_pages:
                        if self._stop: break
                        self.log.emit(f"GET {p}")
                        try:
                            rp = s.get(p, headers=DEFAULT_HEADERS, timeout=30)
                            rp.raise_for_status()
                            html = rp.text
                        except requests.RequestException as e:
                            self.log.emit(f"   ⚠️  Could not fetch {p}: {e}")
                            continue
                        items = extract_detail_urls_from_listing(html, base_url=p)
                        self.log.emit(f"   -> {len(items)} item(s)")
                        detail_urls.extend(items)

            # Deduplicate preserve order
            seen = set()
            detail_urls = [u for u in detail_urls if not (u in seen or seen.add(u))]
            if not detail_urls:
                self.log.emit("No detail URLs found. Check the listing URL/filters.")
                self.status.emit("Nothing to do")
                self.progress.emit(0)
                return

            total_items = len(detail_urls)
            self.log.emit(f"Total unique detail URLs: {total_items}")

            # 3) Process each detail URL
            for idx, url in enumerate(detail_urls, start=1):
                if self._stop:
                    break
                prefix = f"[{idx}/{total_items}]"
                self.status.emit(f"{prefix} Fetching details page…")
                self.log.emit(f"{prefix} GET {url}")

                try:
                    r = s.get(url, headers={**DEFAULT_HEADERS, "Referer": url}, timeout=30)
                    r.raise_for_status()
                    html = r.text
                except requests.RequestException as e:
                    self.log.emit(f"{prefix} ❌ Cannot load details page: {e}")
                    self._update_progress(idx, total_items)
                    continue

                soup = BeautifulSoup(html, "html.parser")

                tool, due_iso = extract_tool_and_due_from_soup(soup)
                main_pdf, extras = get_pdf_links_from_soup(soup, url)

                if not main_pdf:
                    self.log.emit(f"{prefix} ❗ No certificate PDF found on page.")
                    self._update_progress(idx, total_items)
                    continue

                # Desired output filename
                if tool and due_iso:
                    desired_name = f"{tool} due {due_iso}.pdf"
                elif tool:
                    desired_name = f"{tool}.pdf"
                elif due_iso:
                    desired_name = f"certificate due {due_iso}.pdf"
                else:
                    desired_name = "certificate.pdf"

                desired_path = ensure_unique(self.params.output_dir / safe_filename(desired_name))

                # Download & merge
                self.status.emit(f"{prefix} Downloading PDF(s)…")
                with tempfile.TemporaryDirectory() as td:
                    tdir = Path(td)
                    parts: List[Path] = []

                    mp = self._download_to_temp(s, main_pdf, tdir, f"{prefix} main")
                    if mp:
                        parts.append(mp)
                    else:
                        self._update_progress(idx, total_items)
                        continue

                    for extra in extras:
                        if self._stop:
                            break
                        ep = self._download_to_temp(s, extra, tdir, f"{prefix} extra")
                        if ep:
                            parts.append(ep)

                    try:
                        if len(parts) == 1:
                            desired_path.write_bytes(parts[0].read_bytes())
                            self.log.emit(f"{prefix} Saved: {desired_path.name}")
                        else:
                            self.status.emit(f"{prefix} Merging {len(parts)} files…")
                            merger = PdfMerger()
                            for p in parts:
                                merger.append(str(p))
                            with open(desired_path, "wb") as f:
                                merger.write(f)
                            merger.close()
                            self.log.emit(f"{prefix} Saved (merged {len(parts)}): {desired_path.name}")
                    except Exception as e:
                        self.log.emit(f"{prefix} ❌ Merge/save error: {e}")

                self._update_progress(idx, total_items)

            self.status.emit("Done")
            self.progress.emit(100 if not self._stop else self.progress_value)

        finally:
            self.enable_ui.emit(True)
            self.finished.emit()

    # ----- internal helpers -----

    progress_value: int = 0

    def _update_progress(self, item_idx: int, total_items: int):
        pct = int(round((item_idx / max(total_items, 1)) * 100))
        self.progress_value = max(self.progress_value, min(100, pct))
        self.progress.emit(self.progress_value)

    def _download_to_temp(self, session: requests.Session, url: str, tdir: Path, label: str) -> Optional[Path]:
        try:
            r = session.get(url, stream=True, allow_redirects=True, timeout=60)
            r.raise_for_status()
            fname = url_filename_from_response(r, url)
            out = tdir / (fname if fname.lower().endswith(".pdf") else f"{fname}.pdf")
            with open(out, "wb") as f:
                for chunk in r.iter_content(64 * 1024):
                    if chunk:
                        f.write(chunk)
            return out
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "HTTP"
            self.log.emit(f"{label}: HTTP error {code} for {url}")
        except requests.RequestException as e:
            self.log.emit(f"{label}: Network error for {url}: {e}")
        except Exception as e:
            self.log.emit(f"{label}: Error downloading {url}: {e}")
        return None


# ------------------------------ GUI ------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(860)

        # Widgets
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Equipment List URL (with your filters applied)")

        self.cookie_edit = QLineEdit()
        self.cookie_edit.setPlaceholderText("Cookie header (paste from DevTools → Network)")

        self.follow_cb = QCheckBox("Follow pagination")
        self.follow_cb.setChecked(True)  # enable by default, since your site uses sp=

        self.output_dir_label = QLabel(str(OUTPUT_DIR))
        self.browse_btn = QPushButton("Browse…")
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.status_line = QLabel("Idle")
        self.status_line.setStyleSheet("color: #666;")

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(2000)

        # Layouts
        container = QWidget()
        v = QVBoxLayout(container)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Listing URL:"))
        row1.addWidget(self.url_edit)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Cookie:"))
        row2.addWidget(self.cookie_edit)

        row3 = QHBoxLayout()
        row3.addWidget(self.follow_cb)
        row3.addStretch()
        row3.addWidget(QLabel("Output:"))
        row3.addWidget(self.output_dir_label)
        row3.addWidget(self.browse_btn)

        row4 = QHBoxLayout()
        row4.addWidget(self.start_btn)
        row4.addWidget(self.stop_btn)
        row4.addStretch()

        v.addLayout(row1)
        v.addLayout(row2)
        v.addLayout(row3)
        v.addLayout(row4)
        v.addWidget(self.progress)
        v.addWidget(self.status_line)
        v.addWidget(QLabel("Log:"))
        v.addWidget(self.log_box)

        self.setCentralWidget(container)

        # Signals
        self.browse_btn.clicked.connect(self.choose_output_dir)
        self.start_btn.clicked.connect(self.start_job)
        self.stop_btn.clicked.connect(self.stop_job)

        self.thread: Optional[QThread] = None
        self.worker: Optional[DownloaderWorker] = None

    def choose_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Download Folder", str(OUTPUT_DIR))
        if path:
            self.output_dir_label.setText(path)

    def start_job(self):
        listing_url = self.url_edit.text().strip()
        cookie_str = self.cookie_edit.text().strip()
        follow = self.follow_cb.isChecked()
        out_dir = Path(self.output_dir_label.text().strip() or str(OUTPUT_DIR))
        out_dir.mkdir(parents=True, exist_ok=True)

        params = JobParams(
            listing_url=listing_url,
            cookie_string=cookie_str,
            follow_pagination=follow,
            output_dir=out_dir,
        )

        self.thread = QThread()
        self.worker = DownloaderWorker(params)
        self.worker.moveToThread(self.thread)

        # Wire signals
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self.status_line.setText)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.enable_ui.connect(self.set_ui_enabled)

        self.set_ui_enabled(False)
        self.thread.start()
        self.thread.finished.connect(lambda: self.set_ui_enabled(True))

    def stop_job(self):
        if self.worker:
            self.worker.stop()
            self.append_log("⏹️ Stop requested…")

    def set_ui_enabled(self, enabled: bool):
        self.start_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(not enabled)
        self.url_edit.setEnabled(enabled)
        self.cookie_edit.setEnabled(enabled)
        self.follow_cb.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)

    def append_log(self, text: str):
        self.log_box.appendPlainText(text)


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()