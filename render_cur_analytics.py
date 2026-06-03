# -*- coding: utf-8 -*-
"""
Страница аналитики ЦУР: динамика по дням, тренды критичных тем, источников,
зоны ответственности. Самодостаточный HTML с inline-SVG (без внешних зависимостей).
"""
import sys, json, html, argparse
from datetime import datetime

try:
    from metrics_cur import load_history, compare, verdict, LABELS, CRIT_KEYS
except Exception:
    from .metrics_cur import load_history, compare, verdict, LABELS, CRIT_KEYS

MONTHS_GEN = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# Ключи метрик, у которых рост = хуже (для цвета дельты в блоках периодов)
_BAD_UP = {"total", "problems", "urgent", "own_admin", "own_region",
           "crit_roads", "crit_garbage", "crit_territory", "crit_dip", "crit_hogweed"}


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def ru_date(date):
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        return f"{d.day} {MONTHS_GEN[d.month]} {d.year}"
    except Exception:
        return date


def sparkline(vals, w=260, h=46, color="#15507a"):
    vals = [v if v is not None else 0 for v in vals]
    if not vals:
        return '<div class="nodata">нет данных</div>'
    if len(vals) == 1:
        vals = vals * 2
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = round(i / (n - 1) * (w - 8) + 4, 1)
        y = round(h - 6 - (v - mn) / rng * (h - 14), 1)
        pts.append((x, y))
    poly = " ".join(f"{x},{y}" for x, y in pts)
    area = f"4,{h-2} " + poly + f" {w-4},{h-2}"
    lx, ly = pts[-1]
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="spark">'
            f'<polygon points="{area}" fill="{color}" opacity="0.08"/>'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx}" cy="{ly}" r="3" fill="{color}"/></svg>')


def trend_card(history, key, color="#15507a"):
    series = [r.get(key, 0) or 0 for r in history]
    if not any(series):
        # тема могла быть всегда нулевой — всё равно показываем (важна история)
        pass
    label = LABELS.get(key, key)
    last = series[-1] if series else 0
    prev = series[-2] if len(series) > 1 else None
    delta = (last - prev) if prev is not None else None
    dstr = ""
    if delta is not None:
        sign = "+" if delta > 0 else ""
        dcls = "d-up" if delta > 0 else ("d-down" if delta < 0 else "d-flat")
        dstr = f'<span class="tc-d {dcls}">{sign}{delta} к пред. дню</span>'
    mn = min(series) if series else 0
    mx = max(series) if series else 0
    return (f'<div class="tcard"><div class="tc-head"><span class="tc-l">{esc(label)}</span>'
            f'<span class="tc-v">{last}</span></div>'
            f'{sparkline(series, color=color)}'
            f'<div class="tc-foot">{dstr}<span class="tc-range">мин {mn} · макс {mx}</span></div></div>')


def _pdate(s):
    return ru_date(s)


def _metric_val(metrics, key):
    """Извлекает число по ключу из СУР-метрики (вывод parse_cur.aggregate)."""
    if key == "total":     return metrics.get("total", 0)
    if key == "problems":  return metrics.get("problems", 0)
    if key == "proposals": return metrics.get("proposals", 0)
    if key == "urgent":    return metrics.get("urgent", {}).get("count", 0)
    if key == "own_admin": return metrics.get("ownership", {}).get("admin", 0)
    if key == "own_region":return metrics.get("ownership", {}).get("region", 0)
    if key.startswith("crit_"):
        return metrics.get("critical", {}).get(key[5:], {}).get("count", 0)
    return 0


def _delta_cell(cur, prev, bad_up):
    """HTML-ячейка с абсолютной дельтой и % (цвет: рост проблем = красный)."""
    d = cur - prev
    if d == 0:
        return '<span class="muted">0</span>'
    worse = (d > 0) == bad_up
    cls = "d-bad" if worse else "d-good"
    sign = "+" if d > 0 else ""
    pct = ""
    if prev:
        pct = f" · {sign}{round(d / prev * 100)}%"
    arrow = "▲" if d > 0 else "▼"
    return f'<span class="{cls}">{arrow} {sign}{d}{pct}</span>'


PERIOD_ROWS = [
    ("total", "Всего обращений"),
    ("problems", "Проблемы"),
    ("proposals", "Предложения"),
    ("urgent", "Аварии и инциденты"),
    ("own_admin", "В администрацию округа"),
    ("own_region", "В областные/иные"),
    ("crit_roads", "Дороги"),
    ("crit_garbage", "Мусор и контейнеры"),
    ("crit_territory", "Содержание территории"),
    ("crit_dip", "Детские площадки (ДИП)"),
    ("crit_hogweed", "Борщевик"),
]


def period_card(pkey, p):
    """Карточка периода: текущий отрезок vs тот же отрезок предыдущего периода."""
    d = p["def"]
    cur, prev = p["cur"], p["prev"]
    cr = d["cur_range"]; pr = d["prev_range"]
    cur_lbl = f'{_pdate(cr[0])} — {_pdate(cr[1])}' if cr[0] != cr[1] else _pdate(cr[0])
    prev_lbl = f'{_pdate(pr[0])} — {_pdate(pr[1])}' if pr[0] != pr[1] else _pdate(pr[0])
    rows = []
    for key, label in PERIOD_ROWS:
        cv = _metric_val(cur, key)
        pv = _metric_val(prev, key)
        rows.append(
            f'<tr><td>{esc(label)}</td>'
            f'<td class="num strong">{cv}</td>'
            f'<td class="num">{_delta_cell(cv, pv, key in _BAD_UP)}</td>'
            f'<td class="num muted">{pv}</td></tr>'
        )
    return (
        f'<section class="card pcard">'
        f'<div class="pc-head"><h2>{esc(d["title"])}</h2>'
        f'<span class="pc-sub">{esc(d["subtitle"])} · {d["cur_days"]} '
        f'{plural(d["cur_days"], "день", "дня", "дней")}</span></div>'
        f'<div class="pc-ranges"><span class="pc-cur">Текущий: {esc(cur_lbl)}</span>'
        f'<span class="pc-prev">Предыдущий: {esc(prev_lbl)}</span></div>'
        f'<table class="cmp"><thead><tr><th>Показатель</th><th>Текущий</th>'
        f'<th>Динамика</th><th>Предыд.</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></section>'
    )


def plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


EXEC_ROWS = [
    ("exec_closed", "Закрыто / готово", False),
    ("exec_in_work", "В работе / на согласовании", True),
    ("exec_returned", "Возврат модератору", True),
    ("exec_deferred", "Отложенные", True),
]


def _exec_val(metrics, key):
    return metrics.get("execution", {}).get(key.replace("exec_", ""), 0)


def execution_section(periods):
    """Блок «Исполнение»: структура статусов и отложенные с динамикой по периодам."""
    order = [("cur_week", "Неделя"), ("cur_month", "Месяц"), ("cur_quarter", "Квартал")]
    cards = []
    for pkey, plabel in order:
        if pkey not in periods:
            continue
        p = periods[pkey]
        cur, prev = p["cur"], p["prev"]
        ecur = cur.get("execution", {}); eprev = prev.get("execution", {})
        cshare_c = ecur.get("closed_share", 0); cshare_p = eprev.get("closed_share", 0)
        rows = []
        for key, label, bad_up in EXEC_ROWS:
            sk = key.replace("exec_", "")
            cv = ecur.get(sk, 0); pv = eprev.get(sk, 0)
            rows.append(
                f'<tr><td>{esc(label)}</td>'
                f'<td class="num strong">{cv}</td>'
                f'<td class="num">{_delta_cell(cv, pv, bad_up)}</td>'
                f'<td class="num muted">{pv}</td></tr>'
            )
        share_delta = _delta_cell(cshare_c, cshare_p, bad_up=False)
        cards.append(
            f'<section class="card pcard">'
            f'<div class="pc-head"><h2>{esc(plabel)}</h2>'
            f'<span class="pc-sub">доля закрытых: <b>{cshare_c}%</b> {share_delta}</span></div>'
            f'<table class="cmp"><thead><tr><th>Статус</th><th>Текущий</th>'
            f'<th>Динамика</th><th>Предыд.</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></section>'
        )
    if not cards:
        return ""
    intro = (
        '<section class="card pintro"><h2>Исполнение</h2>'
        '<div class="sub">Структура статусов и отложенные обращения по периодам. '
        '«Доля закрытых» — от обработанных (имеющих статус). Рост в работе/возвратов/отложенных — хуже. '
        'Срок «в срок/просрочено» не считается — в выгрузке нет даты закрытия.</div></section>'
    )
    return intro + "".join(cards)


def hotspots_section(hot):
    """Блок «Горячие точки»: общий топ + по категориям."""
    if not hot:
        return ""
    top = hot.get("top", [])
    cats = hot.get("by_category", [])
    if not top and not cats:
        return ""
    maxv = top[0]["count"] if top else 1
    top_rows = "".join(
        f'<div class="hs-row"><span class="hs-name">{esc(t["name"])}</span>'
        f'<span class="hs-bar"><i style="width:{round(t["count"]/maxv*100)}%"></i></span>'
        f'<span class="hs-num">{t["count"]}</span></div>'
        for t in top[:12]
    )
    cat_cards = []
    for c in cats:
        pts = c.get("points", [])
        if not pts:
            continue
        mx = pts[0]["count"]
        rows = "".join(
            f'<div class="hs-row sm"><span class="hs-name">{esc(p["name"])}</span>'
            f'<span class="hs-bar"><i style="width:{round(p["count"]/mx*100)}%"></i></span>'
            f'<span class="hs-num">{p["count"]}</span></div>'
            for p in pts[:6]
        )
        cat_cards.append(
            f'<div class="hs-cat"><h3>{esc(c["napr"])}</h3>{rows}</div>'
        )
    return (
        '<section class="card"><h2>Горячие точки</h2>'
        '<div class="sub">Адреса и улицы с наибольшим числом обращений за период. '
        'Адреса без уточнения (только округ) не учитываются.</div>'
        f'<div class="hs-top">{top_rows}</div>'
        '<h3 class="hs-h">По категориям</h3>'
        f'<div class="hs-cats">{"".join(cat_cards)}</div>'
        '</section>'
    )


def build(history, target_date=None, periods=None, hotspots=None):
    history = sorted(history, key=lambda r: r.get("date", ""))
    if not history:
        return "<html><body><p>Нет данных истории.</p></body></html>"
    if target_date is None:
        target_date = history[-1]["date"]
    cmp_all = compare(history, target_date)
    last = next((r for r in history if r["date"] == target_date), history[-1])

    # вердикт по объёму обращений
    v_total = verdict(cmp_all.get("total", {})) if cmp_all else ("n/a", "")
    vmap = {"better": ("verdict-good", "Спокойнее обычного"),
            "worse": ("verdict-bad", "Напряжённее обычного"),
            "same": ("verdict-flat", "Как вчера"),
            "n/a": ("verdict-flat", "Первый день наблюдений")}
    vcls, vword = vmap.get(v_total[0], ("verdict-flat", ""))

    days = len(history)

    # --- таблица сравнения ключевых метрик ---
    table_keys = ["total", "problems", "proposals", "urgent",
                  "own_admin", "own_region",
                  "crit_roads", "crit_garbage", "crit_territory", "crit_dip", "crit_hogweed"]
    rows = []
    for k in table_keys:
        c = cmp_all.get(k)
        if not c:
            continue
        d1 = c.get("delta1")
        a7 = c.get("avg7")
        va = c.get("vs_avg7")
        def fmt(x, signed=False):
            if x is None:
                return '<span class="muted">—</span>'
            s = ("+" if (signed and x > 0) else "") + str(x)
            return s
        # цвет дельты
        dcell = '<span class="muted">—</span>'
        if d1 is not None:
            worse = (d1 > 0) == c.get("bad_up", True)
            cls = "d-bad" if d1 != 0 and worse else ("d-good" if d1 != 0 else "muted")
            dcell = f'<span class="{cls}">{fmt(d1, True)}</span>'
        vcell = '<span class="muted">—</span>'
        if va is not None:
            worse = (va > 0) == c.get("bad_up", True)
            cls = "d-bad" if va != 0 and worse else ("d-good" if va != 0 else "muted")
            vcell = f'<span class="{cls}">{fmt(va, True)}</span>'
        rows.append(
            f'<tr><td>{esc(c["label"])}</td><td class="num">{c["value"]}</td>'
            f'<td class="num">{dcell}</td>'
            f'<td class="num">{fmt(a7)}</td><td class="num">{vcell}</td></tr>'
        )
    table = ('<table class="cmp"><thead><tr><th>Показатель</th><th>Вчера</th>'
             '<th>Δ к позавч.</th><th>Ср.7дн</th><th>Δ к норме</th></tr></thead>'
             '<tbody>' + "".join(rows) + '</tbody></table>')

    # --- тренды ---
    main_trends = "".join([
        trend_card(history, "total", "#15507a"),
        trend_card(history, "problems", "#c77700"),
        trend_card(history, "urgent", "#c0392b"),
    ])
    crit_colors = {"roads": "#15507a", "garbage": "#1f7a4d", "territory": "#1f7a4d",
                   "dip": "#8e44ad", "hogweed": "#1f7a4d"}
    crit_trends = "".join(
        trend_card(history, f"crit_{k}", crit_colors.get(k, "#15507a")) for k in CRIT_KEYS
    )
    own_trends = "".join([
        trend_card(history, "own_admin", "#15507a"),
        trend_card(history, "own_region", "#8e44ad"),
    ])
    src_keys = ["src_dobrodel", "src_incident", "src_pos", "src_ppmo", "src_msed", "src_onf"]
    src_trends = "".join(trend_card(history, k, "#15507a") for k in src_keys)

    note = ("Тренды строятся по всем дням истории. Для коротких рядов график "
            "ориентировочен и наполнится по мере накопления данных.") if days < 7 else \
           "Тренды по дням истории. Точка справа — последний день."

    # --- блоки периодов (неделя/месяц/квартал) ---
    periods_html = ""
    if periods:
        order = ["cur_week", "cur_month", "cur_quarter"]
        cards = "".join(period_card(k, periods[k]) for k in order if k in periods)
        periods_html = (
            '<section class="card pintro"><h2>Сравнение по периодам</h2>'
            '<div class="sub">Текущий период — накопительно до последнего дня в файле; '
            'сравнение — с равным по длине началом предыдущего периода («день-в-день»). '
            'Рост обращений трактуется как ухудшение.</div></section>'
            + cards
        )

    execution_html = execution_section(periods) if periods else ""
    hotspots_html = hotspots_section(hotspots) if hotspots else ""

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Аналитика ЦУР · динамика</title>
<style>
:root {{ --bg:#f4f6f9; --card:#fff; --ink:#1a2230; --muted:#6b7686; --line:#e3e8ef;
  --brand:#15507a; --red:#c0392b; --amber:#c77700; --green:#1f7a4d; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif; font-size:15px; line-height:1.55; }}
.wrap {{ max-width:980px; margin:0 auto; padding:20px 16px 64px; }}
header.doc {{ background:linear-gradient(135deg,#15507a,#1d6ea3); color:#fff;
  border-radius:14px; padding:22px 26px; box-shadow:0 6px 20px rgba(21,80,122,.2); }}
header.doc .org {{ font-size:13px; opacity:.92; }}
header.doc h1 {{ margin:8px 0 4px; font-size:22px; }}
header.doc .period {{ font-size:14px; opacity:.95; }}
nav.page-tabs {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 2px; }}
nav.page-tabs a {{ font-size:13.5px; font-weight:600; text-decoration:none;
  padding:8px 16px; border-radius:10px; border:1px solid var(--line);
  background:var(--card); color:var(--brand); }}
nav.page-tabs a.active {{ background:var(--brand); color:#fff; border-color:var(--brand); }}
nav.page-tabs a:hover {{ background:#dbe7f7; }}
.verdict {{ margin-top:16px; border-radius:14px; padding:18px 22px; color:#fff; font-weight:700; }}
.verdict .vh {{ font-size:13px; font-weight:600; opacity:.9; }}
.verdict .vw {{ font-size:22px; margin-top:4px; }}
.verdict .vd {{ font-size:13.5px; font-weight:500; opacity:.95; margin-top:6px; }}
.verdict-good {{ background:linear-gradient(135deg,#1f7a4d,#2e9d68); }}
.verdict-bad {{ background:linear-gradient(135deg,#c0392b,#d65a4c); }}
.verdict-flat {{ background:linear-gradient(135deg,#5a6675,#7a8696); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:18px 20px; margin-top:16px; }}
.card h2 {{ margin:0 0 6px; font-size:17px; color:var(--brand); }}
.card .sub {{ font-size:12.5px; color:var(--muted); margin-bottom:12px; }}
.trend-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
.tcard {{ border:1px solid var(--line); border-radius:11px; padding:12px 13px; background:#fbfcfe; }}
.tc-head {{ display:flex; justify-content:space-between; align-items:baseline; }}
.tc-l {{ font-size:13px; font-weight:600; }}
.tc-v {{ font-size:20px; font-weight:800; color:var(--brand); }}
.spark {{ width:100%; height:46px; display:block; margin:6px 0 4px; }}
.tc-foot {{ display:flex; justify-content:space-between; align-items:center; font-size:11.5px; }}
.tc-d.d-up {{ color:var(--red); font-weight:700; }}
.tc-d.d-down {{ color:var(--green); font-weight:700; }}
.tc-d.d-flat {{ color:var(--muted); }}
.tc-range {{ color:var(--muted); }}
.nodata {{ font-size:12px; color:var(--muted); padding:14px 0; text-align:center; }}
table.cmp {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
table.cmp th {{ text-align:left; color:var(--muted); font-weight:600; font-size:12px;
  padding:6px 8px; border-bottom:2px solid var(--line); }}
table.cmp td {{ padding:7px 8px; border-bottom:1px solid var(--line); }}
table.cmp td.num {{ text-align:center; }}
.d-bad {{ color:var(--red); font-weight:700; }}
.d-good {{ color:var(--green); font-weight:700; }}
.muted {{ color:var(--muted); }}
table.cmp td.strong {{ font-weight:800; color:var(--ink); }}
.pintro {{ background:linear-gradient(135deg,#eef4fb,#e3edf7); border-color:#d4e2f0; }}
.pcard .pc-head {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
.pcard .pc-head h2 {{ margin:0; }}
.pcard .pc-sub {{ font-size:12.5px; color:var(--muted); }}
.pc-ranges {{ display:flex; flex-wrap:wrap; gap:8px 18px; margin:8px 0 12px; font-size:12.5px; }}
.pc-cur {{ color:var(--brand); font-weight:600; }}
.pc-prev {{ color:var(--muted); }}
.hs-top {{ margin:6px 0 4px; }}
.hs-row {{ display:grid; grid-template-columns:200px 1fr 48px; align-items:center; gap:10px; padding:3px 0; font-size:13.5px; }}
.hs-row.sm {{ grid-template-columns:150px 1fr 40px; font-size:12.5px; }}
.hs-name {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.hs-bar {{ background:#eef2f6; border-radius:5px; height:12px; overflow:hidden; }}
.hs-bar i {{ display:block; height:100%; background:linear-gradient(90deg,#2f7ec4,#15507a); }}
.hs-num {{ text-align:right; font-weight:700; color:var(--ink); }}
.hs-h {{ margin:18px 0 8px; font-size:15px; }}
.hs-cats {{ display:grid; grid-template-columns:1fr 1fr; gap:14px 22px; }}
.hs-cat h3 {{ margin:0 0 6px; font-size:13.5px; color:var(--brand); }}
@media (max-width:680px) {{ .hs-cats {{ grid-template-columns:1fr; }} .hs-row {{ grid-template-columns:130px 1fr 40px; }} }}
footer.foot {{ margin-top:28px; font-size:12px; color:var(--muted); text-align:center; }}
@media (max-width:680px) {{ .trend-grid {{ grid-template-columns:1fr 1fr; }} }}
</style></head><body><div class="wrap">
<header class="doc">
  <div class="org">Центр управления регионом · г.о. Солнечногорск</div>
  <h1>Аналитика и динамика</h1>
  <div class="period">отчётный день: {esc(ru_date(target_date))} · дней в истории: {days}</div>
</header>
<nav class="page-tabs">
  <a href="index.html">🗂 Все сводки</a>
  <a href="cur-{esc(target_date)}.html">📄 Сводка за день</a>
  <a class="active" href="analytics-{esc(target_date)}.html">📊 Аналитика и динамика</a>
</nav>
<div class="verdict {vcls}">
  <div class="vh">Общая оценка дня по объёму обращений</div>
  <div class="vw">{esc(vword)}</div>
  <div class="vd">Всего обращений: {last.get('total',0)} · {esc(v_total[1])}</div>
</div>
{periods_html}
{execution_html}
{hotspots_html}
<section class="card"><h2>Сравнение ключевых показателей (день)</h2>
  <div class="sub">Δ — изменение к предыдущему дню; «к норме» — отклонение от среднего за 7 дней. Рост обращений трактуется как ухудшение.</div>
  {table}
</section>
<section class="card"><h2>Динамика: объём и характер</h2>
  <div class="sub">{note}</div>
  <div class="trend-grid">{main_trends}</div>
</section>
<section class="card"><h2>Критичные темы — тренды</h2>
  <div class="sub">Дороги · Мусор · Содержание территории · ДИП · Борщевик.</div>
  <div class="trend-grid">{crit_trends}</div>
</section>
<section class="card"><h2>Зона ответственности — тренды</h2>
  <div class="trend-grid">{own_trends}</div>
</section>
<section class="card"><h2>Источники поступления — тренды</h2>
  <div class="trend-grid">{src_trends}</div>
</section>
<footer class="foot">Сформировано автоматически · аналитика обращений ЦУР г.о. Солнечногорск</footer>
</div></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("history")
    ap.add_argument("--date", default=None)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    hist = load_history(a.history)
    out = build(hist, a.date)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(out)
        print("written", a.out)
    else:
        sys.stdout.write(out)
