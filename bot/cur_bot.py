#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот аналитики ЦУР г.о. Солнечногорск.

Что делает:
  • Принимает .xlsx (выгрузка тепловой карты ЦУР за сутки) как документ в чат.
  • Прогоняет конвейер build_all_cur.build_site():
        парсинг → метрики → история → HTML (сводка дня, аналитика, индекс).
  • Публикует папку docs/ на GitHub Pages (git push).
  • Отвечает ссылкой на свежую сводку + краткой динамикой.

Команды:
  /start, /help            — справка.
  /last                    — ссылки на последнюю сводку + аналитику + динамика.
  /svodka YYYY-MM-DD       — ссылка на сводку за конкретный день.
  /analitika               — ссылка на аналитику за последний день.

Доступ: только Telegram-ID из ALLOWED_IDS (вы + руководитель ЦУР).

Работа в группе (чат ЦУР):
  • Бот можно добавить в рабочий чат ЦУР — он сам увидит присланный .xlsx
    и обработает его (нужно отключить privacy mode у @BotFather).
  • В группе бот реагирует ТОЛЬКО на файлы по NAME_FILTER (по умолчанию любой .xlsx).
  • Разрешённые группы — в ALLOWED_CHAT_IDS (id чатов, отрицательные).
  • Результат уходит в тот же чат (на страницах ПДн нет — только агрегаты),
    либо в REPORT_CHAT_ID, если он задан.

Запускается как systemd-сервис. Настройки — через переменные окружения
(см. .env.example и INSTRUKCIYA.md).
"""
import os
import re
import sys
import asyncio
import logging
import subprocess
import tempfile
from datetime import datetime

# --- путь к пайплайну (build_all_cur.py и render_*.py на уровень выше) ---
PIPELINE_DIR = os.environ.get(
    "PIPELINE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import build_all_cur          # noqa: E402
import metrics_cur as M       # noqa: E402

from aiogram import Bot, Dispatcher, F             # noqa: E402
from aiogram.filters import Command, CommandStart  # noqa: E402
from aiogram.types import Message                   # noqa: E402

# ------------------------- КОНФИГ -------------------------
BOT_TOKEN   = os.environ["BOT_TOKEN"]                        # от @BotFather
SITE_DIR    = os.environ.get("SITE_DIR",    os.path.join(PIPELINE_DIR, "docs"))
HISTORY     = os.environ.get("HISTORY",     os.path.join(PIPELINE_DIR, "cur_history.jsonl"))
PAGES_URL   = os.environ.get("PAGES_URL",   "").rstrip("/")  # https://aggasyas.github.io/cur-analytics
GIT_REPO    = os.environ.get("GIT_REPO_DIR", PIPELINE_DIR)   # корень git-репозитория

ALLOWED_IDS = {
    int(x) for x in os.environ.get("ALLOWED_IDS", "").replace(" ", "").split(",") if x
}
ALLOWED_CHAT_IDS = {
    int(x) for x in os.environ.get("ALLOWED_CHAT_IDS", "").replace(" ", "").split(",") if x
}
_report = os.environ.get("REPORT_CHAT_ID", "").strip()
REPORT_CHAT_ID = int(_report) if _report.lstrip("-").isdigit() else None

# В группе реагируем на файлы по этому шаблону (регистронезависимо).
# По умолчанию — любой .xlsx (выгрузка тепловой карты называется по-разному).
NAME_FILTER = re.compile(os.environ.get("NAME_FILTER", r".*\.xlsx$"), re.IGNORECASE)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cur_bot")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# ------------------------- ВСПОМОГАТЕЛЬНОЕ -------------------------
def allowed(msg: Message) -> bool:
    if not ALLOWED_IDS:
        return True
    return msg.from_user and msg.from_user.id in ALLOWED_IDS


def url_svodka(date: str) -> str:
    return f"{PAGES_URL}/cur-{date}.html" if PAGES_URL else f"cur-{date}.html"


def url_analytics(date: str) -> str:
    return f"{PAGES_URL}/analytics-{date}.html" if PAGES_URL else f"analytics-{date}.html"


def url_index() -> str:
    return f"{PAGES_URL}/" if PAGES_URL else "index.html"


def last_date():
    hist = M.load_history(HISTORY)
    dates = sorted(r["date"] for r in hist if r.get("date"))
    return dates[-1] if dates else None


def dynamics_text(date: str) -> str:
    """Короткая динамика по ключевым показателям ЦУР."""
    hist = M.load_history(HISTORY)
    keys = ["total", "problems", "urgent", "own_admin", "own_region"]
    cmp = M.compare(hist, date, keys=keys)
    if not cmp:
        return ""
    lines = []
    for k in keys:
        row = cmp.get(k)
        if not row:
            continue
        _, txt = M.verdict(row)
        d1 = row.get("delta1")
        arrow = "•"
        if d1 is not None:
            arrow = "▲" if d1 > 0 else ("▼" if d1 < 0 else "▪")
        lines.append(f"{arrow} {row['label']}: {row['value']} ({txt})")
    return "\n".join(lines)


def crit_text(date: str) -> str:
    """Критичные темы за день одной строкой."""
    hist = M.load_history(HISTORY)
    rec = next((r for r in hist if r.get("date") == date), None)
    if not rec:
        return ""
    parts = []
    for k, lbl in [("crit_roads", "Дороги"), ("crit_garbage", "Мусор/КП"),
                   ("crit_territory", "Территория"), ("crit_dip", "ДИП"),
                   ("crit_hogweed", "Борщевик")]:
        parts.append(f"{lbl} {rec.get(k, 0)}")
    return " · ".join(parts)


def git_publish(commit_msg: str):
    """Коммитим docs/ + историю и пушим. (успех, текст)."""
    try:
        site_rel = os.path.relpath(SITE_DIR, GIT_REPO)
        hist_rel = os.path.relpath(HISTORY, GIT_REPO)
        subprocess.run(["git", "-C", GIT_REPO, "add", site_rel, hist_rel],
                       check=True, capture_output=True, text=True)
        diff = subprocess.run(["git", "-C", GIT_REPO, "diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            return True, "изменений нет (уже опубликовано)"
        subprocess.run(["git", "-C", GIT_REPO, "commit", "-m", commit_msg],
                       check=True, capture_output=True, text=True)

        def _try_push():
            return subprocess.run(["git", "-C", GIT_REPO, "push", "origin", "HEAD"],
                                  capture_output=True, text=True)
        push = _try_push()
        if push.returncode != 0:
            subprocess.run(["git", "-C", GIT_REPO, "pull", "--no-rebase",
                            "--no-edit", "origin", "HEAD"],
                           check=True, capture_output=True, text=True)
            push = _try_push()
        if push.returncode != 0:
            return False, (push.stderr or push.stdout or "push failed")[-500:]
        return True, "опубликовано"
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e))[-500:]


# ------------------------- ХЕНДЛЕРЫ -------------------------
@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_help(msg: Message):
    if not allowed(msg):
        await msg.answer("⛔ Доступ запрещён. Обратитесь к администратору.")
        return
    await msg.answer(
        "🟢 <b>Бот аналитики ЦУР</b>\n\n"
        "Пришлите мне выгрузку <b>.xlsx</b> из тепловой карты ЦУР за сутки — "
        "я соберу аналитику настроений жителей, обновлю динамику и опубликую "
        "в интернете, а в ответ дам ссылку.\n\n"
        "<b>Команды:</b>\n"
        "/last — последняя сводка + аналитика + динамика\n"
        "/svodka ГГГГ-ММ-ДД — сводка за конкретный день\n"
        "/analitika — аналитика за последний день\n",
        parse_mode="HTML",
    )


@dp.message(Command("last"))
async def cmd_last(msg: Message):
    if not allowed(msg):
        return
    d = last_date()
    if not d:
        await msg.answer("Истории пока нет — пришлите первую выгрузку .xlsx.")
        return
    dyn = dynamics_text(d)
    crit = crit_text(d)
    await msg.answer(
        f"📄 <b>Последняя сводка ЦУР за {d}</b>\n"
        f"{url_svodka(d)}\n\n"
        f"📊 Аналитика: {url_analytics(d)}\n"
        f"🗂 Все сводки: {url_index()}\n\n"
        + (f"<b>Критичные темы:</b>\n{crit}\n\n" if crit else "")
        + (f"<b>Динамика к вчера:</b>\n{dyn}" if dyn else ""),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@dp.message(Command("svodka"))
async def cmd_svodka(msg: Message):
    if not allowed(msg):
        return
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer("Укажите дату: <code>/svodka 2026-06-02</code>", parse_mode="HTML")
        return
    date = parts[1].strip()
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await msg.answer("Формат: ГГГГ-ММ-ДД, например <code>/svodka 2026-06-02</code>", parse_mode="HTML")
        return
    hist = M.load_history(HISTORY)
    if not any(r.get("date") == date for r in hist):
        await msg.answer(f"За {date} сводки в истории нет.")
        return
    await msg.answer(
        f"📄 Сводка ЦУР за {date}:\n{url_svodka(date)}\n"
        f"📊 Аналитика: {url_analytics(date)}",
        disable_web_page_preview=True,
    )


@dp.message(Command("analitika"))
async def cmd_analitika(msg: Message):
    if not allowed(msg):
        return
    d = last_date()
    if not d:
        await msg.answer("Истории пока нет.")
        return
    await msg.answer(f"📊 Аналитика ЦУР за {d}:\n{url_analytics(d)}",
                     disable_web_page_preview=True)


def is_private(msg: Message) -> bool:
    return msg.chat and msg.chat.type == "private"


def group_allowed(msg: Message) -> bool:
    if not ALLOWED_CHAT_IDS:
        return False
    return msg.chat and msg.chat.id in ALLOWED_CHAT_IDS


@dp.message(F.document)
async def on_document(msg: Message):
    doc = msg.document
    name = (doc.file_name or "")
    private = is_private(msg)

    if private:
        if not allowed(msg):
            await msg.answer("⛔ Доступ запрещён.")
            return
        if not name.lower().endswith(".xlsx"):
            await msg.answer("Нужна выгрузка <b>.xlsx</b> из тепловой карты ЦУР.", parse_mode="HTML")
            return
    else:
        if not group_allowed(msg):
            return
        if not (name.lower().endswith(".xlsx") and NAME_FILTER.search(name)):
            return

    report_to = msg.chat.id if private else (REPORT_CHAT_ID or msg.chat.id)

    async def report(text: str):
        await bot.send_message(report_to, text, parse_mode="HTML",
                               disable_web_page_preview=True)

    if private:
        status = await msg.answer("⏳ Принял выгрузку, собираю аналитику ЦУР…")
    else:
        await report(f"⏳ Принял выгрузку ЦУР из чата «{esc_chat(msg)}», собираю…")
        status = None

    # 1. скачиваем во временный файл
    tmpdir = tempfile.mkdtemp(prefix="cur_")
    local_path = os.path.join(tmpdir, doc.file_name)
    try:
        tg_file = await bot.get_file(doc.file_id)
        await bot.download_file(tg_file.file_path, destination=local_path)
    except Exception as e:
        await _set(status, report, f"❌ Не смог скачать файл: {e}")
        return

    # 2. конвейер сборки (в отдельном потоке)
    try:
        res = await asyncio.to_thread(
            build_all_cur.build_site, local_path, SITE_DIR, HISTORY
        )
    except Exception as e:
        log.exception("build_site failed")
        await _set(status, report, f"❌ Ошибка сборки: {e}")
        return

    date = res["date"]

    # 3. публикация
    await _set(status, report, f"✅ Собрал аналитику за {date}. Публикую…")
    ok, pub = await asyncio.to_thread(git_publish, f"Аналитика ЦУР за {date}")

    # 4. ответ
    dyn = dynamics_text(date)
    crit = crit_text(date)
    head = "🟢 Опубликовано" if ok else "⚠️ Собрано, но публикация не удалась"
    body = (
        f"{head} — аналитика ЦУР за <b>{date}</b>\n"
        f"📄 {url_svodka(date)}\n"
        f"📊 {url_analytics(date)}\n"
        f"🗂 {url_index()}\n"
        f"📚 Дней в истории: {res['days_in_history']}\n"
    )
    if crit:
        body += f"\n<b>Критичные темы:</b>\n{crit}\n"
    if dyn:
        body += f"\n<b>Динамика к вчера:</b>\n{dyn}"
    if not ok:
        body += f"\n\n<code>{pub}</code>"

    await _set(status, report, body)


def esc_chat(msg: Message) -> str:
    t = getattr(msg.chat, "title", None) or getattr(msg.chat, "full_name", None) or str(msg.chat.id)
    return (t or "").replace("<", "&lt;").replace(">", "&gt;")


async def _set(status, report, text: str):
    if status is not None:
        await status.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await report(text)


async def main():
    log.info("Бот ЦУР запускается. Pages: %s | site: %s | history: %s",
             PAGES_URL or "(не задан)", SITE_DIR, HISTORY)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
