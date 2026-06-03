# Установка бота ЦУР — пошагово «за руку»

Бот ЦУР ставится **на тот же сервер (LXC), где уже работает бот ЕДДС**, но
полностью отдельно: своя папка `/opt/cur`, свой пользователь `cur`, своя служба
`cur-bot`, свой токен. Они никак не пересекаются и не мешают друг другу.

> Все команды выполняются в консоли вашего контейнера (LXC) под `root`
> (или через `sudo`). Где надо — я отдельно пишу, под кем выполнять.

---

## Шаг 0. Что нужно подготовить заранее

1. **Создать ОТДЕЛЬНОГО бота** в [@BotFather](https://t.me/BotFather):
   - команда `/newbot`;
   - имя, например, `Аналитика ЦУР Солнечногорск`;
   - username, например, `cur_solnechnogorsk_bot`;
   - BotFather пришлёт **токен** вида `123456789:AAabc...` — сохраните его.
   - ⚠️ Это должен быть **новый** бот, не тот же, что у ЕДДС.

2. **Отключить у бота режим приватности**, чтобы он видел файлы в группе:
   - в @BotFather: `/mybots` → выбрать бота → `Bot Settings` →
     `Group Privacy` → `Turn off`.

3. **Узнать Telegram-ID** — свой и руководителя ЦУР:
   - каждый пишет боту [@userinfobot](https://t.me/userinfobot), тот вернёт `Id: 111111111`.

4. **Создать чат ЦУР** в Telegram, добавить туда бота как участника
   (а позже — и в MAX, когда бота одобрят; движок тот же).

---

## Шаг 1. Создать пользователя и папку

```bash
# создаём отдельного системного пользователя cur
adduser --system --group --home /opt/cur cur

# на всякий случай — git и python должны быть установлены
apt update && apt install -y git python3 python3-venv python3-pip
```

---

## Шаг 2. Склонировать репозиторий

```bash
# клонируем публичный репозиторий в /opt/cur
sudo -u cur git clone https://github.com/Aggasyas/cur-analytics.git /opt/cur
```

Если папка `/opt/cur` уже существует и пустая — клонируйте во временную и
перенесите содержимое, либо удалите пустую папку и повторите.

---

## Шаг 3. Виртуальное окружение и зависимости

```bash
sudo -u cur python3 -m venv /opt/cur/venv
sudo -u cur /opt/cur/venv/bin/pip install --upgrade pip
sudo -u cur /opt/cur/venv/bin/pip install -r /opt/cur/bot/requirements.txt
```

---

## Шаг 4. Настроить доступ git для публикации (push)

Боту нужно уметь пушить обновлённый сайт обратно в GitHub. Самый простой
способ — **Personal Access Token** (как у бота ЕДДС):

1. На GitHub: `Settings` → `Developer settings` →
   `Personal access tokens` → `Fine-grained tokens` → `Generate new token`.
   - доступ к репозиторию `cur-analytics`;
   - права `Contents: Read and write`.
2. Прописать токен в git-адрес репозитория (под пользователем `cur`):

```bash
sudo -u cur git -C /opt/cur remote set-url origin \
  https://Aggasyas:ВАШ_ТОКЕН@github.com/Aggasyas/cur-analytics.git

# чтобы git не ругался на «владельца» папки и знал автора коммитов:
sudo -u cur git -C /opt/cur config user.name  "cur-bot"
sudo -u cur git -C /opt/cur config user.email "cur-bot@local"
```

> Можно переиспользовать тот же токен, что у бота ЕДДС, если у него есть
> доступ и к этому репозиторию. Но безопаснее — отдельный токен.

---

## Шаг 5. Файл настроек `.env`

```bash
sudo -u cur cp /opt/cur/bot/.env.example /opt/cur/bot/.env
sudo -u cur nano /opt/cur/bot/.env
```

Заполните значения (подробные комментарии — прямо в файле):

| Переменная | Что вписать |
|------------|-------------|
| `BOT_TOKEN` | токен нового бота от @BotFather |
| `PAGES_URL` | `https://aggasyas.github.io/cur-analytics` |
| `GIT_REPO_DIR` | `/opt/cur` |
| `SITE_DIR` | `/opt/cur/docs` |
| `HISTORY` | `/opt/cur/cur_history.jsonl` |
| `ALLOWED_IDS` | ваш id и id руководителя ЦУР через запятую |
| `ALLOWED_CHAT_IDS` | id чата ЦУР (отрицательное, `-100...`) |
| `REPORT_CHAT_ID` | обычно тот же id чата ЦУР |

> **Как узнать id чата ЦУР?** Добавьте бота в чат, отправьте туда любой файл —
> бот в логах (`journalctl`, см. шаг 7) напишет id чата. Либо временно поставьте
> `ALLOWED_CHAT_IDS=` пустым, отправьте файл в личку боту, чтобы проверить
> работу, а id группы добавите позже.

Сохранить в nano: `Ctrl+O`, `Enter`, выйти `Ctrl+X`.

---

## Шаг 6. Установить службу systemd

```bash
cp /opt/cur/bot/cur-bot.service /etc/systemd/system/cur-bot.service
systemctl daemon-reload
systemctl enable --now cur-bot
```

---

## Шаг 7. Проверить, что бот живой

```bash
systemctl status cur-bot
journalctl -u cur-bot -n 50 -f      # живой лог, выйти — Ctrl+C
```

Должно быть `active (running)` и строка `Бот ЦУР запущен...`.

Теперь в Telegram напишите боту `/start` — он ответит. Команды:

- `/start`, `/help` — справка;
- `/last` — короткая сводка цифр за последний день;
- `/svodka` — ссылка на сводку дня;
- `/analitika` — ссылка на страницу аналитики.

---

## Шаг 8. Боевой прогон

1. Выложите в чат ЦУР файл выгрузки тепловой карты (`*.xlsx`).
2. Бот скачает его, соберёт сайт, запушит в GitHub и пришлёт в чат ссылку
   на сводку и аналитику.
3. GitHub Pages обновляется ~1–2 минуты — если ссылка открылась со старыми
   данными, обновите страницу чуть позже.

---

## Если что-то пошло не так

- **Бот не отвечает** → `journalctl -u cur-bot -n 100` — смотрим ошибку.
  Чаще всего: неверный `BOT_TOKEN` или не заполнен `.env`.
- **Не принимает файл из группы** → проверьте, что отключён Group Privacy
  (Шаг 0.2) и что id группы есть в `ALLOWED_CHAT_IDS`.
- **Ошибка при push в GitHub** → проверьте токен в `remote set-url` (Шаг 4).
  Бот сам делает `git pull` и повторяет push при конфликте, но если токен
  без прав на запись — push не пройдёт.
- **После обновления кода** (если я пришлю новую версию скриптов):
  ```bash
  sudo -u cur git -C /opt/cur pull --no-rebase --no-edit origin main
  systemctl restart cur-bot
  ```
  и только потом заново скармливайте файл боту — иначе он пересоберёт сайт
  старым кодом и перезапишет GitHub.

---

## Важно про MAX

Сейчас основной чат планируется в MAX. Бот MAX уже создан, но **на модерации**:
Bot API мессенджера MAX (с августа 2025) требует верифицированное юрлицо/ИП,
физлицу бота не подтвердят. Как только бота одобрят — движок тот же, добавим
тонкую обёртку под MAX, переписывать аналитику не придётся. Пока работаем
в Telegram.
