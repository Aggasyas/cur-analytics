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


def build(history, target_date=None):
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
footer.foot {{ margin-top:28px; font-size:12px; color:var(--muted); text-align:center; }}
@media (max-width:680px) {{ .trend-grid {{ grid-template-columns:1fr 1fr; }} }}
</style></head><body><div class="wrap">
<header class="doc">
  <div class="org">Центр управления регионом · г.о. Солнечногорск</div>
  <h1>Аналитика и динамика</h1>
  <div class="period">по состоянию на {esc(ru_date(target_date))} · дней в истории: {days}</div>
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
<section class="card"><h2>Сравнение ключевых показателей</h2>
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
