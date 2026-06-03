# Запуск MAX-бота аналитики ЦУР — пошагово «за руку»

Этот бот работает в мессенджере **MAX** параллельно с Telegram-ботом, на том же
движке и том же сервере. Получает накопительную выгрузку `.xlsx`, собирает сайт
аналитики и публикует на GitHub Pages, в ответ присылает кнопки со ссылками.

Telegram-бот при этом продолжает работать как раньше — ничего отключать не нужно.

---

## Что понадобится

- Сервер, где уже крутится Telegram-бот ЦУР (папка `/opt/cur-analytics`, пользователь `cur`).
- Токен MAX-бота `mcursolnregbot` (business.max.ru → бот → **Интеграция** → **Получить токен**).
- 10 минут.

> Если папка/пользователь у вас называются иначе — просто подставляйте свои имена
> в командах ниже. Дальше предполагаю стандартные `/opt/cur-analytics` и `cur`.

---

## Шаг 1. Обновить код на сервере

```bash
sudo -u cur git -C /opt/cur-analytics pull --no-rebase --no-edit origin main
```

Должны подтянуться новые файлы: `bot/max_core.py`, `bot/cur_max_bot.py`,
`bot/cur-max-bot.service`, `bot/.env.max.example`.

---

## Шаг 2. Доустановить зависимость `requests`

MAX-обёртка работает на чистом `requests` (без aiogram). Ставим в тот же venv:

```bash
sudo -u cur /opt/cur-analytics/venv/bin/pip install requests
```

(остальное — `openpyxl` — уже стоит для движка).

---

## Шаг 3. Создать файл настроек `.env.max`

```bash
sudo -u cur cp /opt/cur-analytics/bot/.env.max.example /opt/cur-analytics/bot/.env.max
sudo -u cur nano /opt/cur-analytics/bot/.env.max
```

Заполните минимум две строки:

```
MAX_BOT_TOKEN=сюда_токен_из_business.max.ru
PAGES_URL=https://aggasyas.github.io/cur-analytics
```

Остальное можно оставить пустым (тогда бот отвечает всем в личке).
Сохранить в nano: `Ctrl+O`, `Enter`, выйти: `Ctrl+X`.

> Закройте права на файл, в нём токен:
> ```bash
> sudo chmod 600 /opt/cur-analytics/bot/.env.max
> sudo chown cur:cur /opt/cur-analytics/bot/.env.max
> ```

---

## Шаг 4. Установить systemd-сервис

```bash
sudo cp /opt/cur-analytics/bot/cur-max-bot.service /etc/systemd/system/cur-max-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now cur-max-bot
```

Проверить, что запустился:

```bash
sudo systemctl status cur-max-bot --no-pager
journalctl -u cur-max-bot -n 30 --no-pager
```

В логах должна быть строка вида:
`MAX-бот ЦУР запущен: @mcursolnregbot (id …) | Pages: …`

---

## Шаг 5. Боевой прогон

1. Найдите бота в MAX по имени **@mcursolnregbot** и напишите ему `/start`.
2. Пришлите боту **в личку** накопительную выгрузку `.xlsx`
   (имя вида `nr-01.01.26-03.06.2026.xlsx`).
3. Бот ответит: «Принял… Собрал… Опубликовано» и пришлёт три кнопки:
   **Сводка дня**, **Аналитика**, **Все сводки**.
4. GitHub Pages обновляется 1–2 минуты — если открылись старые данные, обновите
   страницу чуть позже.

---

## Работа в групповом чате ЦУР (необязательно)

Чтобы бот сам ловил файлы прямо в рабочем чате:

1. Добавьте бота в чат и **сделайте его администратором** — иначе MAX не отдаёт
   боту сообщения группы.
2. Узнайте id чата: пришлите в чат любой файл, посмотрите `journalctl -u cur-max-bot -f`
   — там будет `chat_id`. Впишите его в `.env.max`:
   ```
   ALLOWED_CHAT_IDS=-123456789
   # по желанию — фильтр только на нужные файлы:
   NAME_FILTER=nr.*\.xlsx$
   ```
3. Перезапустите: `sudo systemctl restart cur-max-bot`.

---

## Частые вопросы

- **Оба бота (Telegram + MAX) шлют один и тот же сайт?** Да. Они пишут в одну папку
  `docs/` и пушат в один репозиторий. Какой бы вы ни прислали файл — сайт один.
- **Можно слать файл в оба сразу?** Лучше в один за раз: оба пушат в git,
  второй просто увидит «изменений нет».
- **Бот молчит в группе.** Почти всегда — бот не админ группы. Сделайте админом.
- **Логи:** `journalctl -u cur-max-bot -f`.
- **Перезапуск после правок кода:**
  `sudo -u cur git -C /opt/cur-analytics pull --no-rebase --no-edit origin main && sudo systemctl restart cur-max-bot`.

---

## Безопасность

Токен бота — как пароль. Если он где-то «засветился» (например, в переписке),
перевыпустите его в business.max.ru и обновите `MAX_BOT_TOKEN` в `.env.max`,
затем `sudo systemctl restart cur-max-bot`.
