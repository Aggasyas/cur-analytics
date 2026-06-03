# -*- coding: utf-8 -*-
"""
Метрики ЦУР из вывода parse_cur.py + история/сравнение.
Движок истории и сравнения (load_history/upsert_history/compare/verdict)
переиспользуется из общего metrics.py. Здесь только extract_metrics_cur,
свои подписи и набор «рост = хуже».
Фокус: настроения жителей. Решённость НЕ анализируем.
"""
import os, sys, json, statistics
from datetime import datetime, timedelta

# --- метрики ЦУР: какие критичные темы выносим в плоский вид ---
CRIT_KEYS = ["roads", "garbage", "territory", "dip", "hogweed"]

# Источники поступления (нормализованный ключ -> отображаемое имя).
# Совпадение по подстроке (без учёта регистра) с полем "Источник".
# Распознаём по списку подстрок (любая из них = совпадение).
SOURCE_KEYS = [
    ("dobrodel", "Добродел", ["добродел"]),
    ("incident", "Инцидент", ["инцидент"]),
    ("onf",      "ОНФ",      ["онф", "народный фронт", "народного фронта"]),
    ("pos",      "ПОС",      ["пос"]),
    ("ppmo",     "ППМО",     ["ппмо"]),
    ("msed",     "МСЭД",     ["мсэд"]),
    ("eds",      "ЕДС",      ["едс"]),
]

# Рост = хуже (для стрелок). Для ЦУР почти все обращения = рост недовольства = хуже.
BAD_UP = {
    "total", "problems", "urgent",
    "crit_roads", "crit_garbage", "crit_territory", "crit_dip", "crit_hogweed",
    "own_admin", "own_region",
}

# proposals (предложения) — нейтрально/скорее хорошо, не входит в BAD_UP.

LABELS = {
    "total": "Всего обращений",
    "problems": "Проблемы",
    "proposals": "Предложения",
    "urgent": "Аварии и инциденты",
    "own_admin": "В администрацию округа",
    "own_region": "В областные/иные структуры",
    "own_none": "Без управления",
    "crit_roads": "Дороги",
    "crit_garbage": "Мусор и контейнеры",
    "crit_territory": "Содержание территории",
    "crit_dip": "Детские площадки (ДИП)",
    "crit_hogweed": "Борщевик",
    "src_dobrodel": "Добродел",
    "src_incident": "Инцидент",
    "src_pos": "ПОС",
    "src_ppmo": "ППМО",
    "src_msed": "МСЭД",
    "src_eds": "ЕДС",
    "src_onf": "ОНФ",
    "src_other": "Иные источники",
}


def extract_metrics_cur(data):
    """Плоский dict числовых метрик ЦУР за день."""
    m = {"date": data.get("meta", {}).get("date", "")}
    m["total"] = data.get("total", 0)
    m["problems"] = data.get("problems", 0)
    m["proposals"] = data.get("proposals", 0)
    m["urgent"] = data.get("urgent", {}).get("count", 0)
    own = data.get("ownership", {})
    m["own_admin"] = own.get("admin", 0)
    m["own_region"] = own.get("region", 0)
    m["own_none"] = own.get("none", 0)
    crit = data.get("critical", {})
    for k in CRIT_KEYS:
        m[f"crit_{k}"] = crit.get(k, {}).get("count", 0)
    # --- источники поступления ---
    src_counts = {x["name"]: x["count"] for x in data.get("sources", [])}
    matched_total = 0
    for key, _disp, needles in SOURCE_KEYS:
        c = sum(v for name, v in src_counts.items()
                if any(nd in name.lower() for nd in needles))
        m[f"src_{key}"] = c
        matched_total += c
    total_src = sum(src_counts.values())
    m["src_other"] = max(0, total_src - matched_total)
    # --- исполнение ---
    ex = data.get("execution", {})
    m["exec_closed"] = ex.get("closed", 0)
    m["exec_in_work"] = ex.get("in_work", 0)
    m["exec_returned"] = ex.get("returned", 0)
    m["exec_deferred"] = ex.get("deferred", 0)
    m["exec_closed_share"] = ex.get("closed_share", 0)
    return m


# ---------- История / сравнение (переиспользуем общий движок) ----------
# Чтобы модуль работал автономно на сервере ЦУРа без зависимости от
# ЕДДС-репозитория, дублируем здесь компактные функции истории/сравнения.

def load_history(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def upsert_history(path, metrics):
    rows = load_history(path)
    date = metrics.get("date")
    rows = [r for r in rows if r.get("date") != date]
    rows.append(metrics)
    rows.sort(key=lambda r: r.get("date", ""))
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.mean(vals), 1) if vals else None


def compare(history, date, keys=None):
    by_date = {r["date"]: r for r in history if r.get("date")}
    cur = by_date.get(date)
    if not cur:
        return {}
    d = datetime.strptime(date, "%Y-%m-%d")
    prev1 = by_date.get((d - timedelta(days=1)).strftime("%Y-%m-%d"))
    prev2 = by_date.get((d - timedelta(days=2)).strftime("%Y-%m-%d"))
    prior = [r for r in history if r.get("date", "") < date]
    win7 = prior[-7:]
    win30 = prior[-30:]
    if keys is None:
        keys = [k for k in cur.keys() if k != "date"]
    out = {}
    for k in keys:
        v = cur.get(k, 0) or 0
        y = (prev1 or {}).get(k)
        yy = (prev2 or {}).get(k)
        a7 = _avg([r.get(k, 0) for r in win7]) if win7 else None
        a30 = _avg([r.get(k, 0) for r in win30]) if win30 else None
        out[k] = {
            "label": LABELS.get(k, k),
            "value": v,
            "prev1": y, "delta1": (v - y) if y is not None else None,
            "prev2": yy, "delta2": (v - yy) if yy is not None else None,
            "avg7": a7, "vs_avg7": (round(v - a7, 1) if a7 is not None else None),
            "avg30": a30, "vs_avg30": (round(v - a30, 1) if a30 is not None else None),
            "bad_up": k in BAD_UP,
        }
    return out


def verdict(cmp_row):
    """Оценка к вчерашнему дню: лучше/хуже/как вчера."""
    d1 = cmp_row.get("delta1")
    if d1 is None:
        return ("n/a", "нет данных за вчера")
    if d1 == 0:
        return ("same", "как вчера")
    worse = (d1 > 0) == cmp_row["bad_up"]
    word = "хуже" if worse else "лучше"
    sign = "+" if d1 > 0 else ""
    return ("worse" if worse else "better", f"{word} (вчера {sign}{d1})")


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    print(json.dumps(extract_metrics_cur(data), ensure_ascii=False, indent=2))
