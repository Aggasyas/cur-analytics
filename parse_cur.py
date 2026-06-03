# -*- coding: utf-8 -*-
"""
Парсер выгрузки тепловой карты ЦУР (Excel) -> JSON.
Фокус: настроения жителей за вчера. Решённость/закрытость НЕ анализируем.
Разрезы: направления, синт.группы, подтемы, источники, тип (проблема/предложение),
зона ответственности (администрация округа / областные-иные), критичные темы, аварии/инциденты.
"""
import sys, os, json, re
from collections import Counter, OrderedDict

import openpyxl


# ---- Критичные темы (всегда показываем, даже если 0) ----
# Каждая тема = ключ -> (заголовок, иконка, regex по направлению+группе+подтеме)
CRITICAL = OrderedDict([
    ("roads",     ("Дороги",                  "\U0001F6A7", r"дорог|ям[аы]|покрыт|асфальт|обочин|знак|разметк|ИДН|мост")),
    ("garbage",   ("Мусор и контейнеры",      "\U0001F5D1", r"контейнер|мусор|ТКО|свал|навал|отход|вывоз")),
    ("territory", ("Содержание территории",   "\U0001F333", r"содержание территор|благоустр|покос|трав|озелен|урн")),
    ("dip",       ("Детские площадки (ДИП)",  "\U0001F6DD", r"детск|игров|ДИП|площадк")),
    ("hogweed",   ("Борщевик",                "\U0001F331", r"борщевик")),
])

# Зона ответственности
ADM_PREFIX = "Администрация г. о. Солнечногорск"
NO_OWNER = {"none", "без управления", ""}

# Аварии/инциденты — срочное
INCIDENT_STATUS = {"инцидент"}
INCIDENT_SOURCE = {"инцидент"}
EMERGENCY_RE = re.compile(r"авари", re.I)

# Исполнение — группировка статусов в крупные классы
DEFERRED_RE = re.compile(r"отлож", re.I)
CLOSED_RE = re.compile(r"^(закрыт|готово|архивирован)", re.I)
RETURNED_RE = re.compile(r"возврат", re.I)
INWORK_RE = re.compile(r"исполнен|в работе|согласован|модерац|уточнен|редактирован|внешн|реакц", re.I)


def _exec_class(status):
    """Класс исполнения по статусу. Отложенные считаем отдельно (они также закрыты)."""
    s = status.strip().lower()
    if not s or s == "none":
        return "none"
    if RETURNED_RE.search(s):
        return "returned"
    if CLOSED_RE.search(s):
        return "closed"
    return "in_work"


# --- Разбор адреса для «горячих точек» ---
_ADDR_NOISE = {
    "россия", "московская область", "солнечногорск", "го солнечногорск",
    "г.о. солнечногорск", "городской округ солнечногорск", "городской округ",
}
_ADDR_STREET = ("улица", "ул.", "проспект", "шоссе", "переулок", "проезд",
                "бульвар", "набережная", "площадь", "аллея", "тупик")
_ADDR_NP = ("посёлок", "поселок", "деревня", "село", "пгт", "микрорайон",
            "снт", "пос.", "квартал")
_ROAD_RE = re.compile(r"\d+[КкНнАаHK]-?\s?\d+", re.I)


def _addr_key(addr):
    """Возвращает «горячую точку»: улица / дорожный код / населённый пункт.
    Если ничего не распознано — None (попадёт в «Без уточнения»)."""
    if not addr:
        return None
    parts = [p.strip() for p in str(addr).split(",") if p.strip()]
    clean = [p for p in parts if p.lower() not in _ADDR_NOISE]
    street = np = road = None
    for p in clean:
        pl = p.lower()
        if street is None and any(w in pl for w in _ADDR_STREET):
            street = p
        if np is None and any(w in pl for w in _ADDR_NP):
            np = p
        if road is None and _ROAD_RE.search(p):
            road = p
    return street or road or np or (clean[0] if clean else None)


def _norm(v):
    return "" if v is None else str(v).strip()


def _is_admin(executor):
    return executor.startswith(ADM_PREFIX)


def _ownership(executor):
    e = executor.strip()
    if e.lower() in NO_OWNER:
        return "none"
    if _is_admin(e):
        return "admin"
    return "region"


def _topn(counter, n=None):
    items = counter.most_common(n)
    return [{"name": k, "count": v} for k, v in items]


def read_rows(xlsx_path):
    """Читает Excel-выгрузку и возвращает (rows, date_period).
    rows — список нормализованных словарей, у каждого есть поле 'day' (YYYY-MM-DD)
    по дате первого взятия в работу. Поддерживает дневную и накопительную выгрузки.
    Чтение потоковое (read_only) — выдерживает десятки тысяч строк.
    """
    import warnings
    warnings.simplefilter("ignore")
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    header = next(it)
    H = {}
    for idx, name in enumerate(header):
        nm = _norm(name)
        if nm:
            H[nm] = idx

    def col(*cands):
        for cand in cands:
            for k in H:
                if k.lower() == cand.lower():
                    return H[k]
        for cand in cands:
            for k in H:
                if cand.lower() in k.lower():
                    return H[k]
        return None

    I_NAPR = col("Направление")
    I_SYNT = col("Синт. группа", "Синт группа")
    I_POD = col("Подтема")
    I_STAT = col("Статус")
    I_EXEC = col("Исполнитель")
    I_SRC = col("Источник")
    I_TYPE = col("Тип сообщения - 0 проблемы, 1 - предложения", "Тип сообщения")
    I_SPAM = col("Спам (да/нет)", "Спам")
    I_DATE = col("Дата (первого взятия в работу)", "Дата")
    I_ADDR = col("Адрес (формат)", "Адрес")

    def cell(row, i):
        return _norm(row[i]) if (i is not None and i < len(row)) else ""

    def to_day(row, i):
        if i is None or i >= len(row):
            return ""
        v = row[i]
        if v is None:
            return ""
        import datetime as _dt
        if isinstance(v, _dt.datetime):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, _dt.date):
            return v.strftime("%Y-%m-%d")
        s = str(v).strip()
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return m.group(0)
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s)
        if m:
            d, mo, y = m.groups()
            return f"{y}-{mo}-{d}"
        return ""

    rows = []
    for row in it:
        if row is None:
            continue
        napr = cell(row, I_NAPR)
        synt = cell(row, I_SYNT)
        pod = cell(row, I_POD)
        if not (napr or synt or pod):
            continue
        rows.append({
            "napr": napr,
            "synt": synt,
            "pod": pod,
            "status": cell(row, I_STAT),
            "exec": cell(row, I_EXEC),
            "src": cell(row, I_SRC),
            "type": cell(row, I_TYPE),
            "spam": cell(row, I_SPAM),
            "day": to_day(row, I_DATE),
            "addr": cell(row, I_ADDR),
        })
    wb.close()

    date = _extract_date_from_name(xlsx_path)
    if not date and rows:
        days = Counter(x["day"] for x in rows if x["day"])
        if days:
            date = max(days)  # последний день в файле
    return rows, date


def aggregate(rows, date, source="Тепловая карта ЦУР", file=""):
    """Собирает метрику-словарь из набора нормализованных строк."""
    total = len(rows)

    # тип: проблемы / предложения.
    # Разные выгрузки кодируют по-разному: дневная — 0/1, годовая — текстом
    # «Проблемы»/«Предложения». Поддерживаем оба.
    def _is_problem(t):
        t = t.strip().lower()
        return t in ("0", "0.0") or t.startswith("проблем")
    def _is_proposal(t):
        t = t.strip().lower()
        return t in ("1", "1.0") or t.startswith("предлож")
    problems = sum(1 for x in rows if _is_problem(x["type"]))
    proposals = sum(1 for x in rows if _is_proposal(x["type"]))

    # направления
    napr_counter = Counter(x["napr"] for x in rows if x["napr"])
    synt_counter = Counter(x["synt"] for x in rows if x["synt"])
    pod_counter = Counter(x["pod"] for x in rows if x["pod"])

    # зона ответственности
    own = Counter(_ownership(x["exec"]) for x in rows)
    region_detail = Counter(
        x["exec"] for x in rows if _ownership(x["exec"]) == "region"
    )

    # источники
    src_counter = Counter(x["src"] for x in rows if x["src"])

    # критичные темы
    critical = OrderedDict()
    for key, (title, icon, pat) in CRITICAL.items():
        rx = re.compile(pat, re.I)
        cnt = sum(
            1 for x in rows
            if rx.search(" ".join([x["napr"], x["synt"], x["pod"]]))
        )
        # подтемы внутри критичной темы
        sub = Counter(
            x["pod"] for x in rows
            if x["pod"] and rx.search(" ".join([x["napr"], x["synt"], x["pod"]]))
        )
        critical[key] = {
            "title": title, "icon": icon,
            "count": cnt,
            "subtopics": _topn(sub, 6),
        }

    # аварии / инциденты (срочное)
    urgent = []
    seen = set()
    for x in rows:
        is_inc = (
            x["status"].lower() in INCIDENT_STATUS
            or x["src"].lower() in INCIDENT_SOURCE
            or EMERGENCY_RE.search(" ".join([x["synt"], x["pod"]]))
        )
        if is_inc:
            label = x["pod"] or x["synt"] or x["napr"]
            key = (x["napr"], label)
            urgent.append({"napr": x["napr"], "label": label})
            seen.add(key)
    urgent_count = len(urgent)
    urgent_by_napr = Counter(u["napr"] for u in urgent if u["napr"])

    # --- исполнение (структура статусов) ---
    exec_cls = Counter(_exec_class(x["status"]) for x in rows)
    deferred = sum(1 for x in rows if DEFERRED_RE.search(x["status"]))
    deferred_by_napr = Counter(
        x["napr"] for x in rows if DEFERRED_RE.search(x["status"]) and x["napr"]
    )
    closed = exec_cls.get("closed", 0)
    in_work = exec_cls.get("in_work", 0)
    returned = exec_cls.get("returned", 0)
    none_st = exec_cls.get("none", 0)
    processed = total - none_st  # обработанные (имеют статус)
    closed_share = round(closed / processed * 100) if processed else 0

    # --- горячие точки (рейтинг адресов/улиц) ---
    hot_all = Counter()
    hot_by_napr = {}  # направление -> Counter(адрес)
    for x in rows:
        key = _addr_key(x.get("addr", ""))
        if not key:
            continue
        hot_all[key] += 1
        nk = x["napr"] or "Прочее"
        hot_by_napr.setdefault(nk, Counter())[key] += 1
    # топ-категории для горячих точек — по числу обращений в направлении
    hot_categories = []
    for napr, _c in napr_counter.most_common(6):
        c = hot_by_napr.get(napr)
        if not c:
            continue
        hot_categories.append({
            "napr": napr,
            "points": _topn(c, 8),
        })

    data = {
        "meta": {
            "date": date,
            "source": source,
            "file": file,
        },
        "total": total,
        "problems": problems,
        "proposals": proposals,
        "ownership": {
            "admin": own.get("admin", 0),
            "region": own.get("region", 0),
            "none": own.get("none", 0),
            "region_detail": _topn(region_detail),
        },
        "directions": _topn(napr_counter),
        "synt_groups": _topn(synt_counter),
        "subtopics": _topn(pod_counter),
        "sources": _topn(src_counter),
        "critical": critical,
        "urgent": {
            "count": urgent_count,
            "by_direction": _topn(urgent_by_napr),
        },
        "execution": {
            "closed": closed,
            "in_work": in_work,
            "returned": returned,
            "none": none_st,
            "processed": processed,
            "closed_share": closed_share,
            "deferred": deferred,
            "deferred_by_direction": _topn(deferred_by_napr, 8),
        },
        "hotspots": {
            "top": _topn(hot_all, 12),
            "by_category": hot_categories,
        },
    }
    return data


def _extract_date_from_name(path):
    """Конечная дата периода из имени файла: ...01.01.2026-02.06.2026.xlsx -> 2026-06-02."""
    base = os.path.basename(path)
    dates = re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", base)
    if dates:
        d, m, y = dates[-1]
        return f"{y}-{m}-{d}"
    return ""


def parse(xlsx_path):
    """Совместимость: разобрать файл целиком в одну метрику-сводку."""
    rows, date = read_rows(xlsx_path)
    return aggregate(rows, date, file=os.path.basename(xlsx_path))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 parse_cur.py <xlsx>", file=sys.stderr)
        sys.exit(1)
    d = parse(sys.argv[1])
    print(json.dumps(d, ensure_ascii=False, indent=2))
