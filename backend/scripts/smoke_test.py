"""Сквозная проверка пользовательского сценария на живом API.

    docker compose run --rm backend python -m scripts.smoke_test

Проходит механику целиком от лица тестового пользователя: «Буду писать»,
план в календаре, лимит трёх олимпиад в день, ответы «прошёл / не
прошёл» с блокировкой следующих этапов, новости, настройки, удаление.

Этапы и олимпиады подбираются по свойствам данных, а не по жёстким id,
поэтому скрипт переживает повторный импорт каталога. Если нужных данных
нет — например, закончились этапы с окном на ближайшие дни, — проверка
помечается как пропущенная, а не проваленная.

Тестовый пользователь отдельный, его данные удаляются в начале и в конце.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.clock import today as app_today
from app.config import get_settings
from app.security.testing import build_signed_launch_data

# Отдельный id, чтобы не задеть данные настоящих пользователей.
TEST_USER_ID = 999_000_001


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def check(self, title: str, condition: bool, details: str = "") -> bool:
        if condition:
            self.passed += 1
            print(f"  ✓ {title}")
        else:
            self.failed += 1
            print(f"  ✗ {title}")
            if details:
                print(f"      {details}")
        return condition

    def skip(self, title: str, reason: str) -> None:
        self.skipped += 1
        print(f"  – {title} (пропущено: {reason})")


def detail_code(response: httpx.Response) -> Optional[str]:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    return detail.get("code") if isinstance(detail, dict) else None


def find_stage(olympiad: Dict[str, Any], predicate: Callable[[Dict[str, Any]], bool]):
    return next((s for s in olympiad["stages"] if predicate(s)), None)


def contains_day(stage: Dict[str, Any], day: date) -> bool:
    """Окно этапа с точными датами покрывает день."""
    if not stage["plannable"] or stage["start_precision"] != "day":
        return False
    start = date.fromisoformat(stage["starts_on"])
    if stage["ends_on"] and stage["end_precision"] == "day":
        end = date.fromisoformat(stage["ends_on"])
    else:
        end = start
    return start <= day <= end


def main() -> int:
    parser = argparse.ArgumentParser(description="Сквозная проверка API")
    parser.add_argument("--base-url", default="http://backend:8000")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.bot_token:
        print("BOT_TOKEN не задан — нечем подписать данные запуска.")
        return 1

    launch = build_signed_launch_data(
        settings.bot_token, user_id=TEST_USER_ID, first_name="Смоук", last_name="Тест"
    )
    client = httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": f"tma {launch}"},
        timeout=30,
    )
    report = Report()
    today = app_today()
    target_day = today + timedelta(days=2)

    def cleanup() -> None:
        mine = client.get("/api/me/olympiads")
        if mine.status_code == 200:
            for item in mine.json()["items"]:
                client.delete(f"/api/me/olympiads/{item['id']}")

    print(f"API: {args.base_url} | сегодня: {today} | день для лимита: {target_day}\n")

    # --- Авторизация и настройки ---------------------------------------
    print("Авторизация и настройки")
    me = client.get("/api/me")
    if not report.check("GET /api/me — подпись принята", me.status_code == 200, me.text[:200]):
        print("\nДальше проверять бессмысленно: авторизация не работает.")
        return 1
    cleanup()

    client.patch("/api/me/settings", json={"grade": None, "colorblind_mode": False,
                                           "notifications_enabled": True})
    defaults = client.get("/api/me/settings").json()
    report.check(
        "настройки по умолчанию: уведомления включены, режим для дальтоников выключен",
        defaults["notifications_enabled"] is True and defaults["colorblind_mode"] is False,
        str(defaults),
    )
    patched = client.patch("/api/me/settings", json={"grade": 10, "colorblind_mode": True}).json()
    report.check(
        "PATCH меняет только переданные поля",
        patched["grade"] == 10 and patched["colorblind_mode"] is True
        and patched["notifications_enabled"] is True,
        str(patched),
    )
    bad_grade = client.patch("/api/me/settings", json={"grade": 12})
    report.check("класс 12 отклоняется", bad_grade.status_code == 422, bad_grade.text[:200])

    # --- Подбор данных --------------------------------------------------
    catalog = client.get("/api/catalog/olympiads", params={"limit": 200}).json()["items"]
    details = [client.get(f"/api/catalog/olympiads/{o['id']}").json() for o in catalog]

    # Олимпиады, у которых есть этап с точным окном на target_day и за ним
    # ещё хотя бы один этап — на них проверяются лимит и блокировка.
    candidates = []
    for olympiad in details:
        first = find_stage(olympiad, lambda s: contains_day(s, target_day))
        if first is None:
            continue
        later = [s for s in olympiad["stages"] if s["id"] != first["id"]
                 and s["status"] == "upcoming" and s["plannable"]]
        candidates.append((olympiad, first, later))

    month_only = next(
        (o for o in details if o["stages"] and all(not s["plannable"] for s in o["stages"])), None
    )
    with_finished = next(
        (o for o in details
         if find_stage(o, lambda s: s["status"] == "finished" and s["kind"] != "registration")),
        None,
    )

    # --- «Буду писать» --------------------------------------------------
    print("\n«Буду писать»")
    if not candidates:
        report.skip("основной сценарий", f"нет этапов с точным окном на {target_day}")
        cleanup()
        return summary(report)

    olympiad_a, first_a, later_a = candidates[0]
    created = client.post(f"/api/me/olympiads/{olympiad_a['id']}")
    report.check("первое добавление — 201", created.status_code == 201, created.text[:200])
    repeated = client.post(f"/api/me/olympiads/{olympiad_a['id']}")
    report.check("повторное добавление — 200, без дубля", repeated.status_code == 200)
    flagged = client.get(f"/api/catalog/olympiads/{olympiad_a['id']}").json()
    report.check("в каталоге появился флаг saved", flagged["saved"] is True)
    missing = client.post("/api/me/olympiads/99999999")
    report.check("несуществующая олимпиада — 404", missing.status_code == 404)

    # --- Календарь ------------------------------------------------------
    print("\nКалендарь")
    if later_a:
        second_a = later_a[0]
        second_day = date.fromisoformat(second_a["starts_on"])
        planned_later = client.put(f"/api/me/stages/{second_a['id']}/plan",
                                   json={"planned_on": second_day.isoformat()})
        report.check("план на следующий этап", planned_later.status_code == 200,
                     planned_later.text[:200])
    else:
        second_a = None
        report.skip("план на следующий этап", "у олимпиады нет будущего этапа с точной датой")

    plan = client.put(f"/api/me/stages/{first_a['id']}/plan",
                      json={"planned_on": target_day.isoformat()})
    ok = plan.status_code == 200 and find_stage(
        plan.json(), lambda s: s["id"] == first_a["id"])["planned_on"] == target_day.isoformat()
    report.check("план на день внутри окна этапа — «Запланировано на …»", ok, plan.text[:200])

    same = client.put(f"/api/me/stages/{first_a['id']}/plan",
                      json={"planned_on": target_day.isoformat()})
    report.check("тот же план повторно — не ошибка", same.status_code == 200)

    other = client.put(f"/api/me/stages/{first_a['id']}/plan",
                       json={"planned_on": (target_day + timedelta(days=1)).isoformat()})
    report.check("этот этап на другой день — 409 already_planned_other_day",
                 other.status_code == 409 and detail_code(other) == "already_planned_other_day",
                 other.text[:200])

    outside = client.put(f"/api/me/stages/{first_a['id']}/plan",
                         json={"planned_on": (target_day + timedelta(days=400)).isoformat()})
    report.check("день вне окна этапа — 422 date_outside_stage",
                 outside.status_code == 422 and detail_code(outside) == "date_outside_stage",
                 outside.text[:200])

    if month_only is not None:
        client.post(f"/api/me/olympiads/{month_only['id']}")
        stage = month_only["stages"][0]
        rough = client.put(f"/api/me/stages/{stage['id']}/plan",
                           json={"planned_on": target_day.isoformat()})
        report.check("этап без точной даты — 422 not_plannable",
                     rough.status_code == 422 and detail_code(rough) == "not_plannable",
                     rough.text[:200])
    else:
        report.skip("этап без точной даты", "в каталоге нет олимпиады только с месячными датами")

    if len(candidates) >= 4:
        for olympiad, first, _ in candidates[1:3]:
            client.post(f"/api/me/olympiads/{olympiad['id']}")
            client.put(f"/api/me/stages/{first['id']}/plan",
                       json={"planned_on": target_day.isoformat()})
        fourth_olympiad, fourth_stage, _ = candidates[3]
        client.post(f"/api/me/olympiads/{fourth_olympiad['id']}")
        over = client.put(f"/api/me/stages/{fourth_stage['id']}/plan",
                          json={"planned_on": target_day.isoformat()})
        report.check("четвёртая олимпиада на один день — 409 day_limit_reached",
                     over.status_code == 409 and detail_code(over) == "day_limit_reached",
                     over.text[:200])

        day_view = client.get(f"/api/me/calendar/{target_day.isoformat()}").json()
        blocked = next((o for o in day_view["options"] if o["stage_id"] == fourth_stage["id"]), None)
        report.check("окно дня: выбрано 3 из 3", day_view["selected_count"] == 3, str(day_view)[:200])
        report.check("окно дня: четвёртая олимпиада недоступна для выбора",
                     blocked is not None and blocked["selectable"] is False, str(blocked))
    else:
        report.skip("лимит три в день", f"нужно 4 олимпиады с окном на {target_day}, "
                                         f"есть {len(candidates)}")

    calendar = client.get("/api/me/calendar", params={
        "date_from": target_day.isoformat(),
        "date_to": (target_day + timedelta(days=60)).isoformat(),
    }).json()
    report.check("календарь за период отдаёт полосы этапов",
                 any(e["stage_id"] == first_a["id"] for e in calendar["entries"]))

    # --- Прошёл / не прошёл ---------------------------------------------
    print("\nПрошёл / не прошёл")
    if second_a is not None:
        early = client.put(f"/api/me/stages/{second_a['id']}/result", json={"result": "passed"})
        report.check("ответ на ещё не начавшийся этап — 422 stage_not_started",
                     early.status_code == 422 and detail_code(early) == "stage_not_started",
                     early.text[:200])

    failed = client.put(f"/api/me/stages/{first_a['id']}/result", json={"result": "failed"})
    state = failed.json() if failed.status_code == 200 else {}
    report.check("«не прошёл» принят", failed.status_code == 200, failed.text[:200])
    if state:
        report.check("олимпиада помечена eliminated", state["eliminated"] is True)
        # Этапы приходят в порядке проведения — всё после отвеченного.
        ids = [s["id"] for s in state["stages"]]
        after = state["stages"][ids.index(first_a["id"]) + 1:]
        report.check("все следующие этапы заблокированы",
                     bool(after) and all(s["locked"] for s in after), str([s["locked"] for s in after]))
        report.check("планы следующих этапов сняты с календаря",
                     all(s["planned_on"] is None for s in after))

    if second_a is not None:
        locked = client.put(f"/api/me/stages/{second_a['id']}/plan",
                            json={"planned_on": date.fromisoformat(second_a["starts_on"]).isoformat()})
        report.check("план на заблокированный этап — 409 stage_locked",
                     locked.status_code == 409 and detail_code(locked) == "stage_locked",
                     locked.text[:200])

    mine = client.get("/api/me/olympiads").json()["items"]
    report.check("выбывшая олимпиада внизу списка",
                 mine and mine[-1]["id"] == olympiad_a["id"], [m["name"][:30] for m in mine])

    undo = client.delete(f"/api/me/stages/{first_a['id']}/result")
    report.check("отмена ответа снимает блокировку",
                 undo.status_code == 200 and undo.json()["eliminated"] is False
                 and not any(s["locked"] for s in undo.json()["stages"]),
                 undo.text[:200])

    if with_finished is not None:
        client.post(f"/api/me/olympiads/{with_finished['id']}")
        done = find_stage(with_finished,
                          lambda s: s["status"] == "finished" and s["kind"] != "registration")
        news = client.get("/api/me/news").json()
        report.check("завершённый этап без ответа — в «Ожидает ответа от тебя»",
                     any(n["stage_id"] == done["id"] for n in news["awaiting_answer"]))
        passed = client.put(f"/api/me/stages/{done['id']}/result", json={"result": "passed"})
        report.check("«прошёл» на завершённый этап принят", passed.status_code == 200,
                     passed.text[:200])
        news = client.get("/api/me/news").json()
        moved = next((n for n in news["finished"] if n["stage_id"] == done["id"]), None)
        report.check("после ответа этап переехал в «Завершено»",
                     moved is not None and moved["result"] == "passed", str(moved))
    else:
        report.skip("«Ожидает ответа»", "в каталоге нет завершённых этапов")

    # --- Новости --------------------------------------------------------
    print("\nНовости")
    news = client.get("/api/me/news")
    body = news.json() if news.status_code == 200 else {}
    report.check("лента отдаёт все пять категорий",
                 set(body) == {"urgent", "soon", "later", "awaiting_answer", "finished"},
                 str(list(body)))
    everything = [n for bucket in body.values() for n in bucket]
    report.check("у каждой новости есть текст", everything and all(n["message"] for n in everything))

    # --- Удаление -------------------------------------------------------
    print("\nУдаление")
    removed = client.delete(f"/api/me/olympiads/{olympiad_a['id']}")
    report.check("удаление из моих — 204", removed.status_code == 204)
    gone = client.get(f"/api/me/olympiads/{olympiad_a['id']}")
    report.check("после удаления — 404 not_saved",
                 gone.status_code == 404 and detail_code(gone) == "not_saved")
    orphan = client.put(f"/api/me/stages/{first_a['id']}/plan",
                        json={"planned_on": target_day.isoformat()})
    report.check("план по удалённой олимпиаде — 409 not_saved",
                 orphan.status_code == 409 and detail_code(orphan) == "not_saved",
                 orphan.text[:200])

    cleanup()
    client.patch("/api/me/settings", json={"grade": None, "colorblind_mode": False})
    return summary(report)


def summary(report: Report) -> int:
    print(f"\nИтого: пройдено {report.passed}, провалено {report.failed}, "
          f"пропущено {report.skipped}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
