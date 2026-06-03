#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полная сборка сайта аналитики ЦУР из одной выгрузки Excel.

Шаги:
  1. parse_cur.parse(xlsx)              -> структурированный JSON
  2. metrics_cur.extract_metrics_cur    -> плоские метрики дня
  3. metrics_cur.upsert_history         -> добавляем/обновляем день (идемпотентно по дате)
  4. render_cur.build                   -> site/cur-<date>.html
  5. render_cur_analytics.build         -> site/analytics-<date>.html
  6. render_cur_index.build             -> site/index.html

Идемпотентно по дате: повторная сборка того же дня перезаписывает файлы и строку истории.

Использование:
  python3 build_all_cur.py <выгрузка.xlsx> [--site docs] [--history cur_history.jsonl]
"""
import os, sys, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_cur
import metrics_cur
import render_cur
import render_cur_analytics
import render_cur_index


def build_site(xlsx_path, site_dir="docs", history_path="cur_history.jsonl"):
    os.makedirs(site_dir, exist_ok=True)

    data = parse_cur.parse(xlsx_path)
    date = data.get("meta", {}).get("date", "")
    if not date:
        raise ValueError("Не удалось определить дату из выгрузки ЦУР.")

    m = metrics_cur.extract_metrics_cur(data)
    history = metrics_cur.upsert_history(history_path, m)

    svodka_html = render_cur.build(data, history=history)
    svodka_file = os.path.join(site_dir, f"cur-{date}.html")
    with open(svodka_file, "w", encoding="utf-8") as f:
        f.write(svodka_html)

    an_html = render_cur_analytics.build(history, target_date=date)
    an_file = os.path.join(site_dir, f"analytics-{date}.html")
    with open(an_file, "w", encoding="utf-8") as f:
        f.write(an_html)

    idx_html = render_cur_index.build(history)
    idx_file = os.path.join(site_dir, "index.html")
    with open(idx_file, "w", encoding="utf-8") as f:
        f.write(idx_html)

    return {
        "date": date,
        "total": m.get("total", 0),
        "urgent": m.get("urgent", 0),
        "svodka": svodka_file,
        "analytics": an_file,
        "index": idx_file,
        "days_in_history": len(history),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--site", default="docs")
    ap.add_argument("--history", default="cur_history.jsonl")
    a = ap.parse_args()
    res = build_site(a.xlsx, a.site, a.history)
    print(json.dumps(res, ensure_ascii=False, indent=2))
