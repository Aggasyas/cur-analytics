# -*- coding: utf-8 -*-
"""
Движок периодов ЦУР поверх ОДНОГО накопительного файла (выгрузка с начала года).
Источник правды — сам файл; история на сервере не нужна.

Группировка обращения по «Дате (первого взятия в работу)» (поле row['day']).

Периоды (все — НЕЗАВЕРШЁННЫЕ, накопительно до последнего дня в файле «anchor»):
  • day        : вчера (= последний день в файле) vs позавчера
  • cur_week   : текущая ЦУР-неделя (чт→ср) до anchor   vs тот же отрезок прошлой недели
  • cur_month  : текущий календарный месяц до anchor    vs тот же отрезок прошлого месяца
  • cur_quarter: текущий квартал до anchor               vs тот же отрезок прошлого квартала

Сравнение «день-в-день»: текущий незавершённый период сравнивается с РАВНЫМ по длине
началом предыдущего периода (например, если в текущем месяце прошло 3 дня — берём
первые 3 дня прошлого месяца). Так цифры сопоставимы.
"""
import datetime as dt
from collections import defaultdict

import parse_cur as P


# ---------- даты периодов ----------

def _d(s):
    return dt.date.fromisoformat(s)


def cur_week_start(day):
    """Начало ЦУР-недели (четверг). weekday(): Пн=0..Вс=6, Чт=3."""
    offset = (day.weekday() - 3) % 7   # сколько дней назад был ближайший чт (вкл. сегодня)
    return day - dt.timedelta(days=offset)


def month_start(day):
    return day.replace(day=1)


def quarter_start(day):
    qm = ((day.month - 1) // 3) * 3 + 1
    return day.replace(month=qm, day=1)


def prev_month_start(day):
    ms = month_start(day)
    return (ms - dt.timedelta(days=1)).replace(day=1)


def prev_quarter_start(day):
    qs = quarter_start(day)
    return quarter_start(qs - dt.timedelta(days=1))


def period_defs(anchor):
    """Возвращает OrderedDict period_key -> dict с границами текущего и предыдущего отрезка.
    anchor — последний день в файле (он же «вчера» в нашей терминологии)."""
    a = anchor
    defs = {}

    # --- ЦУР-неделя ---
    ws = cur_week_start(a)
    span = (a - ws).days                         # сколько полных дней прошло после старта
    pws = ws - dt.timedelta(days=7)
    defs["cur_week"] = {
        "title": "ЦУР-неделя",
        "subtitle": "четверг → среда",
        "cur": (ws, a),
        "prev": (pws, pws + dt.timedelta(days=span)),
    }

    # --- календарный месяц ---
    ms = month_start(a)
    days_in = (a - ms).days
    pms = prev_month_start(a)
    # тот же отрезок прошлого месяца, но не вылезаем за его границу
    p_end_candidate = pms + dt.timedelta(days=days_in)
    this_ms = ms  # граница текущего месяца
    p_end = min(p_end_candidate, this_ms - dt.timedelta(days=1))
    defs["cur_month"] = {
        "title": "Месяц",
        "subtitle": "календарный",
        "cur": (ms, a),
        "prev": (pms, p_end),
    }

    # --- квартал ---
    qs = quarter_start(a)
    qdays_in = (a - qs).days
    pqs = prev_quarter_start(a)
    pq_end_candidate = pqs + dt.timedelta(days=qdays_in)
    pq_end = min(pq_end_candidate, qs - dt.timedelta(days=1))
    defs["cur_quarter"] = {
        "title": "Квартал",
        "subtitle": "календарный",
        "cur": (qs, a),
        "prev": (pqs, pq_end),
    }
    return defs


# ---------- агрегация ----------

def index_by_day(rows):
    by = defaultdict(list)
    for r in rows:
        if r["day"]:
            by[r["day"]].append(r)
    return by


def rows_in_range(by_day, start, end):
    """Все строки с днём в [start, end] включительно."""
    out = []
    cur = start
    while cur <= end:
        key = cur.isoformat()
        if key in by_day:
            out.extend(by_day[key])
        cur += dt.timedelta(days=1)
    return out


def metrics_for_range(by_day, start, end, date_label, source, file):
    rows = rows_in_range(by_day, start, end)
    return P.aggregate(rows, date_label, source=source, file=file)


def daily_history(by_day, source, file, last_n=None):
    """Строит список плоских метрик по дням (как cur_history.jsonl, но из накопит. файла).
    Используется для сравнения день-к-дню и среднего за 7/30 дней на сводке дня
    и для трендов/индекса. last_n — ограничить последними N днями (None = все)."""
    import metrics_cur as M
    days = sorted(by_day.keys())
    if last_n:
        days = days[-last_n:]
    hist = []
    for dkey in days:
        d = _d(dkey)
        data = metrics_for_range(by_day, d, d, dkey, source, file)
        hist.append(M.extract_metrics_cur(data))
    return hist


def build_periods(xlsx_path):
    """Читает накопительный файл и возвращает всё для рендера:
    {
      'anchor': 'YYYY-MM-DD',   # вчера
      'prev_day': 'YYYY-MM-DD', # позавчера
      'days': [...все даты с данными, по возрастанию...],
      'day': {'cur': metrics, 'prev': metrics},
      'periods': {
          'cur_week':   {'def':..., 'cur': metrics, 'prev': metrics},
          'cur_month':  {...},
          'cur_quarter':{...},
      },
      'by_day': by_day,         # для индекса/трендов
      'file': basename,
    }
    """
    rows, _ = P.read_rows(xlsx_path)
    by_day = index_by_day(rows)
    if not by_day:
        raise ValueError("В файле не найдено обращений с распознанной датой.")
    days = sorted(by_day.keys())
    anchor = _d(days[-1])
    file = __import__("os").path.basename(xlsx_path)
    source = "Тепловая карта ЦУР (накопительная выгрузка)"

    # вчера / позавчера
    prev_day = anchor - dt.timedelta(days=1)
    day_cur = metrics_for_range(by_day, anchor, anchor, anchor.isoformat(), source, file)
    day_prev = metrics_for_range(by_day, prev_day, prev_day, prev_day.isoformat(), source, file)

    # периоды
    defs = period_defs(anchor)
    periods = {}
    for key, d in defs.items():
        cs, ce = d["cur"]
        ps, pe = d["prev"]
        periods[key] = {
            "def": {
                "title": d["title"],
                "subtitle": d["subtitle"],
                "cur_range": (cs.isoformat(), ce.isoformat()),
                "prev_range": (ps.isoformat(), pe.isoformat()),
                "cur_days": (ce - cs).days + 1,
                "prev_days": (pe - ps).days + 1,
            },
            "cur": metrics_for_range(by_day, cs, ce, ce.isoformat(), source, file),
            "prev": metrics_for_range(by_day, ps, pe, pe.isoformat(), source, file),
        }

    return {
        "anchor": anchor.isoformat(),
        "prev_day": prev_day.isoformat(),
        "days": days,
        "day": {"cur": day_cur, "prev": day_prev},
        "periods": periods,
        "by_day": by_day,
        "file": file,
        "source": source,
    }


if __name__ == "__main__":
    import sys, json
    res = build_periods(sys.argv[1])
    out = {
        "anchor": res["anchor"], "prev_day": res["prev_day"],
        "n_days": len(res["days"]),
        "day_cur_total": res["day"]["cur"]["total"],
        "day_prev_total": res["day"]["prev"]["total"],
    }
    for k, p in res["periods"].items():
        out[k] = {
            "cur_range": p["def"]["cur_range"], "cur_total": p["cur"]["total"],
            "prev_range": p["def"]["prev_range"], "prev_total": p["prev"]["total"],
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))
