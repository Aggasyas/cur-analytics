#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полная сборка сайта аналитики ЦУР из ОДНОГО накопительного файла Excel
(выгрузка обращений с начала года). История на сервере не нужна — источник правды
сам файл.

Шаги:
  1. cur_periods.build_periods(xlsx)   -> читает файл, режет по дням и периодам
  2. строим дневную историю из файла   -> для стрелок/среднего и индекса
  3. render_cur.build (по каждому дню)  -> docs/cur-<date>.html (полный архив)
  4. render_cur_analytics.build (anchor)-> docs/analytics-<anchor>.html (с периодами)
  5. render_cur_index.build             -> docs/index.html (год→месяц→день)

Периоды на странице аналитики: вчера, ЦУР-неделя (чт→ср), месяц, квартал —
накопительно до последнего дня в файле, сравнение «день-в-день» с прошлым периодом.

Использование:
  python3 build_all_cur.py <накопительная_выгрузка.xlsx> [--site docs]
"""
import os, sys, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_cur
import metrics_cur
import cur_periods
import render_cur
import render_cur_analytics
import render_cur_index


def build_site(xlsx_path, site_dir="docs", history_path=None):
    """history_path игнорируется (оставлен для совместимости со старым ботом).
    Вся аналитика строится из самого накопительного файла."""
    os.makedirs(site_dir, exist_ok=True)

    res = cur_periods.build_periods(xlsx_path)
    by_day = res["by_day"]
    anchor = res["anchor"]               # «вчера» (сегодня − 1)
    source = res["source"]
    file = res["file"]

    # ВАЖНО: отчёт строим ТОЛЬКО по дням <= anchor (до вчера включительно).
    # Сегодняшние (или более поздние) записи из файла исключаем из
    # истории, архива и индекса — в файле они остаются, но не публикуются.
    days_pub = [d for d in res["days"] if cur_periods._d(d) <= anchor]

    # дневная история (для стрелок, среднего, индекса) — только дни <= anchor
    by_day_pub = {d: by_day[d] for d in days_pub}
    history = cur_periods.daily_history(by_day_pub, source, file)

    # --- страницы сводки дня для ВСЕХ опубликованных дней (до вчера) ---
    written_days = 0
    for dkey in days_pub:
        d = cur_periods._d(dkey)
        day_data = cur_periods.metrics_for_range(by_day, d, d, dkey, source, file)
        html = render_cur.build(day_data, history=history, analytics_date=anchor)
        with open(os.path.join(site_dir, f"cur-{dkey}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        written_days += 1

    # --- горячие точки: берём из самого широкого периода (квартал), иначе месяц/неделя ---
    periods = res["periods"]
    hotspots = None
    for pk in ("cur_quarter", "cur_month", "cur_week"):
        if pk in periods:
            hs = periods[pk]["cur"].get("hotspots")
            if hs and (hs.get("top") or hs.get("by_category")):
                hotspots = hs
                break

    # --- одна страница аналитики (для anchor-дня) с блоками периодов ---
    an_html = render_cur_analytics.build(
        history, target_date=anchor, periods=periods, hotspots=hotspots
    )
    an_file = os.path.join(site_dir, f"analytics-{anchor}.html")
    with open(an_file, "w", encoding="utf-8") as f:
        f.write(an_html)

    # --- индекс: все дни, ссылки «Аналитика» ведут на anchor-страницу ---
    idx_html = render_cur_index.build(history, analytics_date=anchor)
    with open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx_html)

    day_cur = res["day"]["cur"]
    return {
        "anchor": anchor,
        "total": day_cur.get("total", 0),
        "urgent": day_cur.get("urgent", {}).get("count", 0),
        "svodka": os.path.join(site_dir, f"cur-{anchor}.html"),
        "analytics": an_file,
        "index": os.path.join(site_dir, "index.html"),
        "days_written": written_days,
        "periods": {k: {
            "cur": p["cur"]["total"], "prev": p["prev"]["total"],
            "cur_range": p["def"]["cur_range"], "prev_range": p["def"]["prev_range"],
        } for k, p in res["periods"].items()},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--site", default="docs")
    ap.add_argument("--history", default=None, help="игнорируется (совместимость)")
    a = ap.parse_args()
    res = build_site(a.xlsx, a.site, a.history)
    print(json.dumps(res, ensure_ascii=False, indent=2))
