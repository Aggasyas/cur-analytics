# -*- coding: utf-8 -*-
"""
Генератор HTML-сводки ЦУР из JSON (вывод parse_cur.py).
Самодостаточный HTML без внешних зависимостей.
Фокус: настроения жителей за вчера. Решённость НЕ анализируем.
"""
import sys, json, html, argparse
from datetime import datetime

try:
    from metrics_cur import (extract_metrics_cur, load_history, upsert_history,
                             compare, verdict, LABELS, CRIT_KEYS, SOURCE_KEYS)
except Exception:
    from .metrics_cur import (extract_metrics_cur, load_history, upsert_history,
                              compare, verdict, LABELS, CRIT_KEYS, SOURCE_KEYS)

MONTHS_GEN = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def ru_date(date):
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        return f"{d.day} {MONTHS_GEN[d.month]} {d.year}"
    except Exception:
        return date


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


# ---------- стрелка динамики ----------
def arrow(cmp_row):
    """Возвращает (html-стрелка, css-класс) для дельты к вчера."""
    if not cmp_row:
        return ("", "")
    d1 = cmp_row.get("delta1")
    if d1 is None:
        return ('<span class="dy dy-flat">—</span>', "")
    if d1 == 0:
        return ('<span class="dy dy-flat">→ 0</span>', "")
    worse = (d1 > 0) == cmp_row.get("bad_up", True)
    sign = "+" if d1 > 0 else ""
    ar = "▲" if d1 > 0 else "▼"
    cls = "dy-bad" if worse else "dy-good"
    return (f'<span class="dy {cls}">{ar} {sign}{d1}</span>', cls)


def vs_avg_text(cmp_row):
    """«к среднему за 7 дн.: +N» с цветом."""
    if not cmp_row:
        return ""
    v = cmp_row.get("vs_avg7")
    if v is None:
        return ""
    worse = (v > 0) == cmp_row.get("bad_up", True)
    sign = "+" if v > 0 else ""
    cls = "av-bad" if (v != 0 and worse) else ("av-good" if v != 0 else "av-flat")
    return f'<span class="avg {cls}">ср.7дн: {sign}{v}</span>'


# ---------- блок «что изменилось» ----------
def build_changes(cmp_all):
    """Автовыводы: направления/темы с заметным сдвигом к среднему за 7 дней."""
    if not cmp_all:
        return ""
    items = []
    watch = ["total", "problems", "proposals", "urgent",
             "crit_roads", "crit_garbage", "crit_territory", "crit_dip", "crit_hogweed",
             "own_admin", "own_region"]
    for k in watch:
        row = cmp_all.get(k)
        if not row:
            continue
        va = row.get("vs_avg7")
        a7 = row.get("avg7")
        if va is None or a7 in (None, 0):
            continue
        pct = va / a7 * 100 if a7 else 0
        # значимый сдвиг: >= 25% и абсолют >= 3
        if abs(pct) >= 25 and abs(va) >= 3:
            worse = (va > 0) == row.get("bad_up", True)
            ar = "↑" if va > 0 else "↓"
            sign = "+" if va > 0 else ""
            items.append((abs(pct), worse,
                          f'{ar} {esc(row["label"])} {sign}{va} ({sign}{round(pct)}% к норме)'))
    if not items:
        return ('<div class="changes"><div class="ch-h">Что изменилось</div>'
                '<div class="ch-empty">Существенных отклонений от среднего за 7 дней нет — '
                'фон обращений в пределах нормы.</div></div>')
    items.sort(key=lambda x: -x[0])
    rows = "".join(
        f'<li class="{"ch-bad" if w else "ch-good"}">{txt}</li>'
        for _p, w, txt in items[:8]
    )
    return (f'<div class="changes"><div class="ch-h">Что изменилось '
            f'<span class="ch-sub">(к среднему за 7 дней)</span></div>'
            f'<ul class="ch-list">{rows}</ul></div>')


# ---------- бар топ-направлений ----------
def build_directions_bar(data):
    dirs = data.get("directions", [])[:8]
    if not dirs:
        return ""
    mx = max((d["count"] for d in dirs), default=1) or 1
    rows = []
    for d in dirs:
        w = round(d["count"] / mx * 100)
        rows.append(
            f'<div class="bar-row"><div class="bar-name">{esc(d["name"])}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{w}%"></div></div>'
            f'<div class="bar-val">{d["count"]}</div></div>'
        )
    return ('<section class="card"><h2>Топ направлений за день</h2>'
            '<div class="bars">' + "".join(rows) + '</div></section>')


# ---------- источники ----------
def build_sources(data, cmp_all):
    srcs = data.get("sources", [])
    if not srcs:
        return ""
    total = sum(s["count"] for s in srcs) or 1
    # порядок: как в SOURCE_KEYS, плюс прочие
    name_by_key = {k: disp for k, disp, _ in SOURCE_KEYS}
    rows = []
    for key, disp, needles in SOURCE_KEYS:
        val = sum(s["count"] for s in srcs
                  if any(nd in s["name"].lower() for nd in needles))
        cmp_row = cmp_all.get(f"src_{key}") if cmp_all else None
        ar, _ = arrow(cmp_row)
        pct = round(val / total * 100)
        rows.append(
            f'<div class="src-row"><span class="src-name">{esc(disp)}</span>'
            f'<span class="src-bar"><span class="src-fill" style="width:{pct}%"></span></span>'
            f'<span class="src-val">{val} <span class="src-pct">· {pct}%</span> {ar}</span></div>'
        )
    return ('<section class="card"><h2>Источники поступления</h2>'
            '<div class="src-list">' + "".join(rows) + '</div>'
            '<div class="src-note">Откуда пришли обращения жителей за сутки.</div></section>')


# ---------- зона ответственности ----------
def build_ownership(data, cmp_all):
    own = data.get("ownership", {})
    adm = own.get("admin", 0)
    reg = own.get("region", 0)
    non = own.get("none", 0)
    tot = adm + reg + non or 1
    a_pct = round(adm / tot * 100)
    r_pct = round(reg / tot * 100)
    detail = own.get("region_detail", [])[:6]
    det_rows = "".join(
        f'<li><span>{esc(x["name"])}</span><b>{x["count"]}</b></li>' for x in detail
    )
    det_block = (
        f'<details class="det"><summary><span class="det-caret"></span>'
        f'Областные/иные структуры — детально ({len(detail)})</summary>'
        f'<ul class="own-det">{det_rows}</ul></details>'
    ) if detail else ""
    ar_adm, _ = arrow((cmp_all or {}).get("own_admin"))
    ar_reg, _ = arrow((cmp_all or {}).get("own_region"))
    return (
        '<section class="card"><h2>Зона ответственности</h2>'
        '<div class="own-bar">'
        f'<div class="own-seg own-adm" style="width:{a_pct}%" title="Администрация округа">{a_pct}%</div>'
        f'<div class="own-seg own-reg" style="width:{r_pct}%" title="Область/иные">{r_pct}%</div>'
        '</div>'
        '<div class="own-legend">'
        f'<div class="own-li"><span class="dot adm"></span>Администрация округа — <b>{adm}</b> {ar_adm}</div>'
        f'<div class="own-li"><span class="dot reg"></span>Областные/иные структуры — <b>{reg}</b> {ar_reg}</div>'
        + (f'<div class="own-li"><span class="dot non"></span>Без управления — <b>{non}</b></div>' if non else "")
        + '</div>'
        + det_block +
        '<div class="src-note">Куда направлены обращения для исполнения.</div></section>'
    )


# ---------- критичные карточки ----------
def build_critical(data, cmp_all):
    crit = data.get("critical", {})
    cards = []
    for key in CRIT_KEYS:
        c = crit.get(key)
        if not c:
            continue
        cmp_row = (cmp_all or {}).get(f"crit_{key}")
        ar, arcls = arrow(cmp_row)
        avg = vs_avg_text(cmp_row)
        # цвет рамки: рост = тревожнее
        tone = "crit-up" if arcls == "dy-bad" else ("crit-down" if arcls == "dy-good" else "crit-flat")
        subs = c.get("subtopics", [])[:4]
        sub_html = ""
        if subs:
            sub_html = ('<div class="crit-subs">' + " · ".join(
                f'{esc(s["name"])} <b>{s["count"]}</b>' for s in subs) + '</div>')
        cards.append(
            f'<div class="crit-card {tone}">'
            f'<div class="crit-top"><span class="crit-ic">{c["icon"]}</span>'
            f'<span class="crit-title">{esc(c["title"])}</span></div>'
            f'<div class="crit-num">{c["count"]} {ar}</div>'
            f'<div class="crit-avg">{avg}</div>'
            f'{sub_html}</div>'
        )
    return ('<section class="card"><h2>Критичные темы</h2>'
            '<div class="crit-grid">' + "".join(cards) + '</div>'
            '<div class="src-note">Темы под особым контролем. Показываются всегда, '
            'даже при нулевых значениях.</div></section>')


# ---------- плашка аварий/инцидентов ----------
def build_urgent(data):
    u = data.get("urgent", {})
    cnt = u.get("count", 0)
    if not cnt:
        return ""
    by = u.get("by_direction", [])[:8]
    chips = "".join(
        f'<span class="ug-chip">{esc(x["name"])} <b>{x["count"]}</b></span>' for x in by
    )
    word = plural(cnt, "авария/инцидент", "аварии/инцидента", "аварий/инцидентов")
    return (
        '<div class="urgent-alert">'
        '<div class="ug-top"><span class="ug-ic">!</span>'
        '<span class="ug-h">Срочное: аварии и инциденты</span>'
        f'<span class="ug-badge">{cnt} {word}</span></div>'
        f'<div class="ug-chips">{chips}</div>'
        '<div class="ug-note">Аварийные ситуации, инциденты и обращения, '
        'требующие немедленной реакции.</div></div>'
    )


# ---------- KPI-шапка ----------
def build_kpi(data, cmp_all):
    total = data.get("total", 0)
    prob = data.get("problems", 0)
    prop = data.get("proposals", 0)
    urg = data.get("urgent", {}).get("count", 0)
    ar_total, _ = arrow((cmp_all or {}).get("total"))
    avg_total = vs_avg_text((cmp_all or {}).get("total"))
    return f"""
<div class="metrics">
  <div class="metric blue"><div class="v">{total} {ar_total}</div><div class="l">Всего обращений за сутки</div><div class="m-sub">{avg_total}</div></div>
  <div class="metric amber"><div class="v">{prob}</div><div class="l">Проблемы</div></div>
  <div class="metric green"><div class="v">{prop}</div><div class="l">Предложения</div></div>
  <div class="metric red"><div class="v">{urg}</div><div class="l">Аварии и инциденты</div></div>
</div>"""


CSS = """
:root {
  --bg:#f4f6f9; --card:#ffffff; --ink:#1a2230; --muted:#6b7686;
  --line:#e3e8ef; --brand:#15507a; --brand-soft:#e8f1f8;
  --red:#c0392b; --amber:#c77700; --green:#1f7a4d; --blue:#15507a;
  --reg:#8e44ad;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;
  font-size:15px; line-height:1.55; }
.wrap { max-width:980px; margin:0 auto; padding:20px 16px 64px; }
header.doc { background:linear-gradient(135deg,#15507a,#1d6ea3); color:#fff;
  border-radius:14px; padding:22px 26px; box-shadow:0 6px 20px rgba(21,80,122,.2); }
header.doc .org { font-size:13px; opacity:.92; }
header.doc h1 { margin:8px 0 4px; font-size:23px; }
header.doc .period { font-size:15px; opacity:.95; }
header.doc .asof { font-size:13px; opacity:.85; margin-top:4px; }
nav.page-tabs { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 2px; }
nav.page-tabs a { font-size:13.5px; font-weight:600; text-decoration:none;
  padding:8px 16px; border-radius:10px; border:1px solid var(--line);
  background:var(--card); color:var(--brand); }
nav.page-tabs a.active { background:var(--brand); color:#fff; border-color:var(--brand); }
nav.page-tabs a:hover { background:#dbe7f7; }
nav.page-tabs a.active:hover { background:var(--brand); }
.metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:18px 0 6px; }
.metric { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
.metric .v { font-size:26px; font-weight:700; line-height:1.1; }
.metric .l { font-size:12.5px; color:var(--muted); margin-top:6px; }
.metric .m-sub { font-size:11.5px; margin-top:3px; }
.metric.red .v { color:var(--red); } .metric.blue .v { color:var(--blue); }
.metric.green .v { color:var(--green); } .metric.amber .v { color:var(--amber); }
.dy { font-size:14px; font-weight:700; }
.dy-bad { color:var(--red); } .dy-good { color:var(--green); } .dy-flat { color:var(--muted); }
.avg { font-size:11.5px; font-weight:600; }
.av-bad { color:var(--red); } .av-good { color:var(--green); } .av-flat { color:var(--muted); }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:18px 20px; margin-top:16px; }
.card h2 { margin:0 0 14px; font-size:17px; color:var(--brand); }
.src-note { font-size:12px; color:var(--muted); margin-top:12px; font-style:italic; }
/* источники */
.src-list { display:flex; flex-direction:column; gap:9px; }
.src-row { display:grid; grid-template-columns:120px 1fr auto; align-items:center; gap:12px; }
.src-name { font-weight:600; font-size:14px; }
.src-bar { height:9px; background:#eef2f7; border-radius:6px; overflow:hidden; }
.src-fill { display:block; height:100%; background:var(--brand); border-radius:6px; }
.src-val { font-size:14px; font-weight:700; white-space:nowrap; }
.src-pct { color:var(--muted); font-weight:600; font-size:12.5px; }
/* зона ответственности */
.own-bar { display:flex; height:30px; border-radius:9px; overflow:hidden; margin-bottom:14px; }
.own-seg { display:flex; align-items:center; justify-content:center; color:#fff;
  font-weight:700; font-size:13px; min-width:34px; }
.own-adm { background:var(--brand); } .own-reg { background:var(--reg); }
.own-legend { display:flex; flex-direction:column; gap:7px; }
.own-li { font-size:14px; } .own-li b { font-size:15px; }
.dot { display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:7px; vertical-align:baseline; }
.dot.adm { background:var(--brand); } .dot.reg { background:var(--reg); } .dot.non { background:var(--muted); }
.own-det { list-style:none; padding:6px 0 0; margin:0; }
.own-det li { display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--line); font-size:13.5px; }
.own-det li b { color:var(--brand); }
/* критичные */
.crit-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
.crit-card { border:1px solid var(--line); border-left:5px solid var(--muted);
  border-radius:11px; padding:13px 15px; background:#fbfcfe; }
.crit-card.crit-up { border-left-color:var(--red); }
.crit-card.crit-down { border-left-color:var(--green); }
.crit-card.crit-flat { border-left-color:var(--muted); }
.crit-top { display:flex; align-items:center; gap:8px; }
.crit-ic { font-size:18px; }
.crit-title { font-weight:600; font-size:13.5px; }
.crit-num { font-size:26px; font-weight:800; margin-top:6px; }
.crit-avg { min-height:15px; margin-top:2px; }
.crit-subs { font-size:11.5px; color:var(--muted); margin-top:8px; line-height:1.5; }
.crit-subs b { color:var(--ink); }
/* топ-бары */
.bars { display:flex; flex-direction:column; gap:9px; }
.bar-row { display:grid; grid-template-columns:190px 1fr auto; align-items:center; gap:12px; }
.bar-name { font-size:13.5px; font-weight:600; }
.bar-track { height:12px; background:#eef2f7; border-radius:7px; overflow:hidden; }
.bar-fill { height:100%; background:linear-gradient(90deg,#1d6ea3,#15507a); border-radius:7px; }
.bar-val { font-weight:700; font-size:14px; }
/* что изменилось */
.changes { background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:16px 20px; margin-top:16px; }
.ch-h { font-weight:700; color:var(--brand); font-size:16px; margin-bottom:8px; }
.ch-sub { font-size:12px; color:var(--muted); font-weight:500; }
.ch-list { margin:0; padding-left:2px; list-style:none; }
.ch-list li { font-size:14px; padding:5px 0; border-bottom:1px dashed var(--line); }
.ch-bad { color:var(--red); font-weight:600; }
.ch-good { color:var(--green); font-weight:600; }
.ch-empty { font-size:13.5px; color:var(--muted); }
/* срочное */
.urgent-alert { background:#fdecea; border:1px solid #f0b6ae; border-left:6px solid var(--red);
  border-radius:13px; padding:14px 18px; margin-top:16px; }
.ug-top { display:flex; align-items:center; gap:10px; }
.ug-ic { flex:0 0 auto; width:24px; height:24px; background:var(--red); color:#fff;
  border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; }
.ug-h { font-weight:800; font-size:15.5px; color:var(--red); }
.ug-badge { margin-left:auto; background:var(--red); color:#fff; font-weight:700;
  font-size:12.5px; padding:3px 11px; border-radius:20px; }
.ug-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:11px; }
.ug-chip { background:#fff; border:1px solid #f0b6ae; border-radius:8px; padding:4px 10px; font-size:13px; }
.ug-chip b { color:var(--red); }
.ug-note { font-size:12px; color:#9a5249; margin-top:10px; font-style:italic; }
/* caret */
.det { margin-top:8px; }
.det > summary { cursor:pointer; list-style:none; font-weight:600; font-size:13.5px;
  color:var(--brand); display:flex; align-items:center; gap:8px; padding:4px 0; }
.det > summary::-webkit-details-marker { display:none; }
.det-caret { display:inline-block; flex:0 0 auto; width:8px; height:8px;
  border-right:2px solid var(--brand); border-bottom:2px solid var(--brand);
  transform:rotate(-45deg); transition:transform .15s; margin-top:-3px; }
details.det[open] > summary .det-caret { transform:rotate(45deg); margin-top:-4px; }
footer.foot { margin-top:28px; font-size:12px; color:var(--muted); text-align:center; }
@media (max-width:680px) {
  .metrics { grid-template-columns:repeat(2,1fr); }
  .crit-grid { grid-template-columns:1fr 1fr; }
  .bar-row { grid-template-columns:120px 1fr auto; }
  .src-row { grid-template-columns:90px 1fr auto; }
}
"""


def build(data, history=None):
    date = data.get("meta", {}).get("date", "")
    # метрики + сравнение
    cmp_all = {}
    if history:
        cmp_all = compare(history, date)

    parts = [f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Сводка ЦУР · {esc(ru_date(date))}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="doc">
  <div class="org">Центр управления регионом · г.о. Солнечногорск</div>
  <h1>Аналитика обращений ЦУР</h1>
  <div class="period">Настроения жителей за {esc(ru_date(date))}</div>
  <div class="asof">Источник: тепловая карта ЦУР</div>
</header>
<nav class="page-tabs">
  <a href="index.html">🗂 Все сводки</a>
  <a class="active" href="cur-{esc(date)}.html">📄 Сводка за день</a>
  <a href="analytics-{esc(date)}.html">📊 Аналитика и динамика</a>
</nav>
"""]
    parts.append(build_kpi(data, cmp_all))
    parts.append(build_urgent(data))
    parts.append(build_critical(data, cmp_all))
    parts.append(build_changes(cmp_all))
    parts.append(build_directions_bar(data))
    parts.append(build_sources(data, cmp_all))
    parts.append(build_ownership(data, cmp_all))
    parts.append(
        f'<footer class="foot">Сформировано автоматически из выгрузки тепловой карты ЦУР '
        f'· {esc(data.get("meta",{}).get("file",""))}<br>'
        f'Персональные данные заявителей не публикуются.</footer>'
    )
    parts.append("</div></body></html>")
    return "".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--history", default=None)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    with open(a.json, encoding="utf-8") as f:
        data = json.load(f)
    hist = load_history(a.history) if a.history else None
    out = build(data, hist)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(out)
        print("written", a.out)
    else:
        sys.stdout.write(out)
