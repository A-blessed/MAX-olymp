"""
Парсер расписания олимпиад с olimpiada.ru
Читает activity_id из JSON-файла, парсит страницы расписания,
сохраняет результат в отдельный файл с этапами и датами.

Запуск: python olympiad_schedule_parser.py
"""

import json
import time
import re
import logging
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# ─── Настройки ────────────────────────────────────────────────────────────────

INPUT_FILE  = "olympiads_final_updated.json"   # ваш исходный файл
OUTPUT_FILE = "olympiads_schedule.json"         # результирующий файл

DELAY_BETWEEN_REQUESTS = 1.2   # секунды между запросами
REQUEST_TIMEOUT = 15           # таймаут запроса

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Словарь русских месяцев → номер ──────────────────────────────────────────

MONTHS_RU = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4,
    "май": 5, "мая": 5, "июн": 6, "июл": 7,
    "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}

# Паттерны дат:
#   «5 ноя...11 дек»  — диапазон с двумя разными месяцами
#   «4...17 дек»      — диапазон в рамках одного месяца
#   «до 22 окт»       — дедлайн
#   «22 окт»          — одна дата
_RE_RANGE_2M = re.compile(
    r"(\d{1,2})\s+([а-яё]{3,4})\s*[…\.]{2,3}\s*(\d{1,2})\s+([а-яё]{3,4})",
    re.IGNORECASE,
)
_RE_RANGE_1M = re.compile(
    r"(\d{1,2})\s*[…\.]{2,3}\s*(\d{1,2})\s+([а-яё]{3,4})",
    re.IGNORECASE,
)
_RE_SINGLE_UNTIL = re.compile(
    r"до\s+(\d{1,2})\s+([а-яё]{3,4})",
    re.IGNORECASE,
)
_RE_SINGLE = re.compile(
    r"(\d{1,2})\s+([а-яё]{3,4})",
    re.IGNORECASE,
)


def _guess_year(month: int, base_year: int) -> int:
    """Если месяц раньше текущего — скорее всего следующий год."""
    now = datetime.now()
    if month < now.month and base_year == now.year:
        return base_year + 1
    return base_year


def parse_date_text(raw: str) -> dict:
    """
    Разбирает строку даты из таблицы расписания и возвращает словарь:
      start_stage, end_stage  — строки "YYYY-MM-DD" или None
      date_precision          — "exact" | "until" | "range" | "unknown"
      source_text             — оригинальный текст
      parser_warning          — "date_parsed" | "date_not_parsed"
    """
    now = datetime.now()
    base_year = now.year

    text = raw.strip()
    low  = text.lower()

    result = {
        "start_stage":     None,
        "end_stage":       None,
        "date_precision":  "unknown",
        "source_text":     text,
        "parser_warning":  "date_not_parsed",
    }

    # Уточняется / TBD
    if re.search(r"уточн|tbd|определ|объявл", low):
        return result

    # «5 ноя...11 дек» — диапазон с двумя разными месяцами
    m = _RE_RANGE_2M.search(low)
    if m:
        d1, mo1, d2, mo2 = m.group(1), m.group(2), m.group(3), m.group(4)
        mo1_n = MONTHS_RU.get(mo1[:3])
        mo2_n = MONTHS_RU.get(mo2[:3])
        if mo1_n and mo2_n:
            y1 = _guess_year(mo1_n, base_year)
            y2 = _guess_year(mo2_n, base_year)
            result.update(
                start_stage    = f"{y1}-{mo1_n:02d}-{int(d1):02d}",
                end_stage      = f"{y2}-{mo2_n:02d}-{int(d2):02d}",
                date_precision = "range",
                parser_warning = "date_parsed",
            )
            return result

    # «4...17 дек» — диапазон в рамках одного месяца
    m = _RE_RANGE_1M.search(low)
    if m:
        d1, d2, mo = m.group(1), m.group(2), m.group(3)
        mo_n = MONTHS_RU.get(mo[:3])
        if mo_n:
            y = _guess_year(mo_n, base_year)
            result.update(
                start_stage    = f"{y}-{mo_n:02d}-{int(d1):02d}",
                end_stage      = f"{y}-{mo_n:02d}-{int(d2):02d}",
                date_precision = "range",
                parser_warning = "date_parsed",
            )
            return result

    # «до 22 окт» — дедлайн
    m = _RE_SINGLE_UNTIL.search(low)
    if m:
        d, mo = m.group(1), m.group(2)
        mo_n = MONTHS_RU.get(mo[:3])
        if mo_n:
            y = _guess_year(mo_n, base_year)
            result.update(
                end_stage      = f"{y}-{mo_n:02d}-{int(d):02d}",
                date_precision = "until",
                parser_warning = "date_parsed",
            )
            return result

    # «22 окт» — одна дата
    m = _RE_SINGLE.search(low)
    if m:
        d, mo = m.group(1), m.group(2)
        mo_n = MONTHS_RU.get(mo[:3])
        if mo_n:
            y = _guess_year(mo_n, base_year)
            result.update(
                start_stage    = f"{y}-{mo_n:02d}-{int(d):02d}",
                end_stage      = f"{y}-{mo_n:02d}-{int(d):02d}",
                date_precision = "exact",
                parser_warning = "date_parsed",
            )
            return result

    return result


def fetch_schedule(activity_id: int, session: requests.Session) -> dict:
    """
    Загружает страницу олимпиады и возвращает:
      academic_year  — строка "2025/26" (берём из обновлённой строки или текущий год)
      stages         — список этапов
      updated_text   — «Обновлено 26 августа» и т.п.
      parse_error    — None или сообщение об ошибке
    """
    url = f"https://olimpiada.ru/activity/{activity_id}"
    result = {
        "activity_id":  activity_id,
        "url":          url,
        "academic_year": None,
        "updated_text": None,
        "stages":       [],
        "parse_error":  None,
    }

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        result["parse_error"] = str(exc)
        return result

    soup = BeautifulSoup(resp.text, "lxml")

    # ── Найти блок расписания ──────────────────────────────────────────────────
    h2 = soup.find("h2", string=re.compile(r"Расписание", re.IGNORECASE))
    if not h2:
        # Попробовать класс
        h2 = soup.find("h2", class_=re.compile(r"timetable", re.IGNORECASE))
    if not h2:
        result["parse_error"] = "timetable_section_not_found"
        return result

    # Текст «Обновлено …»
    sib = h2.find_next_sibling(string=re.compile(r"Обновлено", re.IGNORECASE))
    if sib:
        result["updated_text"] = sib.strip()

    # Ссылка на расписание следующего года вида «Расписание 2025/2026 года →»
    year_link = h2.find_next(
        "a", string=re.compile(r"\d{4}/\d{2,4}", re.IGNORECASE)
    )
    if year_link:
        m = re.search(r"(\d{4})/(\d{2,4})", year_link.get_text())
        if m:
            y1, y2 = m.group(1), m.group(2)
            if len(y2) == 2:
                y2 = y1[:2] + y2
            result["academic_year"] = f"{y1}/{y2[2:]}"

    # Таблица расписания
    table = h2.find_next("table", class_=re.compile(r"events_for_activity"))
    if not table:
        # Попробовать ближайшую таблицу
        table = h2.find_next("table")

    if not table:
        result["parse_error"] = "schedule_table_not_found"
        return result

    rows = table.find_all("tr")
    stages = []
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        # Принимаем только строки с реальными этапами:
        # либо есть div.event_name, либо ссылка на /events/
        name_div = row.find("div", class_="event_name")
        has_event_link = bool(
            row.find("a", href=re.compile(r"/events/"))
        )
        if not name_div and not has_event_link:
            continue

        # Имя этапа
        if name_div:
            stage_name = name_div.get_text(strip=True)
        else:
            texts = [c.get_text(" ", strip=True) for c in cells]
            texts = [t for t in texts if t]
            if not texts:
                continue
            stage_name = texts[0]

        # Дата — последняя ячейка (Когда), чистим неразрывные пробелы
        date_raw = cells[-1].get_text(" ", strip=True)
        date_raw = date_raw.replace("\xa0", " ").replace("&nbsp;", " ").strip()

        parsed = parse_date_text(date_raw)

        stages.append({
            "name_stage":      stage_name,
            "start_stage":     parsed["start_stage"],
            "end_stage":       parsed["end_stage"],
            "date_precision":  parsed["date_precision"],
            "source_text":     parsed["source_text"],
            "parser_warning":  parsed["parser_warning"],
        })

    # Если год не удалось достать из ссылки — вычисляем из текущей даты
    if not result["academic_year"]:
        now = datetime.now()
        y = now.year if now.month >= 9 else now.year - 1
        result["academic_year"] = f"{y}/{str(y + 1)[2:]}"

    result["stages"] = stages
    return result


# ─── Основная логика ──────────────────────────────────────────────────────────

def load_existing_output(path: Path) -> dict:
    """Загружает уже сохранённый файл результатов (для инкрементального обновления)."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_output(data: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Сохранено → %s", path)


def main():
    input_path  = Path(INPUT_FILE)
    output_path = Path(OUTPUT_FILE)

    if not input_path.exists():
        log.error("Входной файл не найден: %s", input_path)
        return

    with open(input_path, encoding="utf-8") as f:
        source = json.load(f)

    subjects = source.get("subjects", [])

    # Собрать все олимпиады с activity_id
    all_olympiads = []
    for subject in subjects:
        for olym in subject.get("olympiads", []):
            aid = olym.get("activity_id")
            if aid:
                all_olympiads.append({
                    "subject":     subject["name"],
                    "name":        olym.get("name", ""),
                    "activity_id": aid,
                    "level":       olym.get("level", ""),
                    "grades":      olym.get("grades", ""),
                })

    log.info("Всего олимпиад с activity_id: %d", len(all_olympiads))

    # Загрузить уже готовые результаты (чтобы не парсить заново)
    existing: dict = load_existing_output(output_path)
    results = existing.get("schedules", {})

    session = requests.Session()
    session.headers.update(HEADERS)

    updated_count = 0
    error_count   = 0

    for i, olym in enumerate(all_olympiads, 1):
        aid = str(olym["activity_id"])

        log.info(
            "[%d/%d] %s — %s (id=%s)",
            i, len(all_olympiads), olym["subject"], olym["name"], aid,
        )

        schedule = fetch_schedule(int(aid), session)

        results[aid] = {
            "subject":      olym["subject"],
            "name":         olym["name"],
            "level":        olym["level"],
            "grades":       olym["grades"],
            "activity_id":  int(aid),
            "url":          schedule["url"],
            "academic_year": schedule["academic_year"],
            "updated_text": schedule["updated_text"],
            "stages":       schedule["stages"],
            "parse_error":  schedule["parse_error"],
            "fetched_at":   datetime.now().isoformat(timespec="seconds"),
        }

        if schedule["parse_error"]:
            error_count += 1
            log.warning("  ⚠  Ошибка: %s", schedule["parse_error"])
        else:
            updated_count += 1
            log.info(
                "  ✓  %d этапов  |  год: %s",
                len(schedule["stages"]),
                schedule["academic_year"],
            )

        # Сохраняем после каждого запроса — не потеряем данные при обрыве
        save_output(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "total":        len(results),
                "schedules":    results,
            },
            output_path,
        )

        time.sleep(DELAY_BETWEEN_REQUESTS)

    log.info(
        "Готово. Успешно: %d  |  Ошибок: %d  |  Файл: %s",
        updated_count, error_count, output_path,
    )


if __name__ == "__main__":
    main()
