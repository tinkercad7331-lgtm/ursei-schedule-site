#!/usr/bin/env python3
"""Conservative source probe and schedule extractor.

This starter intentionally does not guess the official site's schema. It only
publishes data if it can find table rows with recognizable schedule columns.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SCHEDULE_PATH = DOCS / "data" / "schedule.json"
REPORT_PATH = ROOT / "probe-report.json"

SOURCES = [
    "https://ursei.su/asu/ssched.php",
    "https://ursei.su/Services/StudSched",
    "https://ursei.su/Services/SchedTeacher",
]
GROUPS = {"РПД-101", "РПД-102", "РПД-103"}
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
HEADERS = {
    "User-Agent": "UrSEI-Schedule-Independent-Project/0.1 (+manual educational use)"
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "ursei.su":
        return {"url": url, "ok": False, "error": "URL outside allowlisted HTTPS host"}
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        content_type = response.headers.get("content-type", "")
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        text = " ".join(soup.stripped_strings)
        return {
            "url": url,
            "ok": response.ok,
            "status_code": response.status_code,
            "final_url": response.url,
            "content_type": content_type,
            "title": soup.title.get_text(" ", strip=True) if soup.title else None,
            "html_bytes": len(response.content),
            "table_count": len(tables),
            "form_count": len(soup.find_all("form")),
            "script_count": len(soup.find_all("script")),
            "selects": [
                {
                    "name": el.get("name"),
                    "id": el.get("id"),
                    "options": [o.get_text(" ", strip=True) for o in el.find_all("option")[:30]],
                }
                for el in soup.find_all("select")
            ],
            "sample_text": text[:1800],
            "_html": response.text,
        }
    except requests.RequestException as exc:
        return {"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def serializable_probe(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "_html"}


def normalize_time(value: str) -> str | None:
    match = TIME_RE.search(value or "")
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def extract_from_tables(html: str) -> list[dict]:
    """Only recognizes clear headers; intentionally fails closed on unknown layout."""
    soup = BeautifulSoup(html, "html.parser")
    extracted = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        grid = [[cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])] for row in rows]
        grid = [row for row in grid if row]
        if len(grid) < 2:
            continue
        header = [re.sub(r"\s+", " ", cell).strip().lower() for cell in grid[0]]
        def find_col(patterns):
            for i, h in enumerate(header):
                if any(p in h for p in patterns):
                    return i
            return None
        time_col = find_col(["время", "time", "начало"])
        subject_col = find_col(["предмет", "дисциплина", "занятие"])
        teacher_col = find_col(["преподаватель", "teacher", "педагог"])
        room_col = find_col(["аудитория", "кабинет", "ауд.", "room"])
        group_col = find_col(["группа", "group"])
        date_col = find_col(["дата", "date"])
        # A row is usable only if headers explicitly identify subject and either time/date.
        if subject_col is None or (time_col is None and date_col is None):
            continue
        for row in grid[1:]:
            def at(index):
                return row[index].strip() if index is not None and index < len(row) else ""
            subject = at(subject_col)
            if not subject:
                continue
            group = at(group_col)
            if group and group not in GROUPS:
                continue
            raw_time = at(time_col)
            times = TIME_RE.findall(raw_time)
            start = f"{int(times[0][0]):02d}:{times[0][1]}" if times else normalize_time(raw_time)
            end = f"{int(times[1][0]):02d}:{times[1][1]}" if len(times) > 1 else None
            date_text = at(date_col)
            # Do not infer date formats unless an explicit ISO date exists.
            iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", date_text)
            if not iso_match:
                continue
            extracted.append({
                "group": group,
                "date": iso_match.group(1),
                "start": start,
                "end": end,
                "subject": subject,
                "teacher": at(teacher_col) or None,
                "room": at(room_col) or None,
            })
    return extracted


def load_existing() -> dict:
    try:
        return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schemaVersion": 1,
            "source": SOURCES[0],
            "lastSuccessfulSync": None,
            "status": "not_connected",
            "message": "Источник расписания ещё не подключён.",
            "groups": {},
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true", help="Inspect source pages and write a diagnostic report")
    mode.add_argument("--update", action="store_true", help="Attempt a conservative extraction and update JSON only on success")
    args = parser.parse_args()

    results = [fetch(url) for url in SOURCES]
    REPORT_PATH.write_text(
        json.dumps({
            "checkedAt": utc_now(),
            "results": [serializable_probe(r) for r in results],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for item in results:
        print(f"[{'OK' if item.get('ok') else 'FAIL'}] {item['url']} — "
              f"HTTP {item.get('status_code', 'n/a')}; tables={item.get('table_count', 0)}; "
              f"forms={item.get('form_count', 0)}; scripts={item.get('script_count', 0)}")
        if item.get("error"):
            print("  ", item["error"])
        if item.get("selects"):
            print("  select controls:", json.dumps(item["selects"], ensure_ascii=False))

    if args.probe:
        print(f"\nДиагностика записана в {REPORT_PATH}")
        print("Проверь sample_text, таблицы и формы перед настройкой извлечения.")
        return 0 if any(x.get("ok") for x in results) else 1

    all_rows = []
    for item in results:
        if item.get("ok") and item.get("_html"):
            all_rows.extend(extract_from_tables(item["_html"]))

    # Fail closed: no fabricated rows, no overwrite if schema is not recognized.
    if not all_rows:
        print("\nНе удалось уверенно извлечь расписание из распознанных таблиц.")
        print("Существующий schedule.json оставлен без изменений. Исследуй probe-report.json.")
        return 2

    grouped: dict[str, dict[str, list[dict]]] = {}
    for row in all_rows:
        group = row.get("group")
        date = row.get("date")
        if group not in GROUPS or not date:
            continue
        grouped.setdefault(group, {}).setdefault(date, []).append({
            "start": row.get("start"),
            "end": row.get("end"),
            "subject": row["subject"],
            "teacher": row.get("teacher"),
            "room": row.get("room"),
        })
    if not grouped:
        print("Данные найдены, но группы не определены надёжно. JSON не обновлён.")
        return 2

    for dates in grouped.values():
        for lessons in dates.values():
            lessons.sort(key=lambda lesson: lesson.get("start") or "99:99")

    payload = {
        "schemaVersion": 1,
        "source": "https://ursei.su/asu/ssched.php",
        "lastSuccessfulSync": utc_now(),
        "status": "ok",
        "message": "Расписание получено из распознанных таблиц официального источника.",
        "groups": grouped,
    }
    SCHEDULE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Расписание обновлено: {sum(len(ds) for ds in grouped.values())} дат.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
