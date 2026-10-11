# 🤖 Telegram-бот: утро, обед и ИИ друг

**Что умеет**
- ⏰ 05:00 — погода + мотивация (Gemini пишет каждый раз новую)
- 🍽 13:00 — 5 идей контента для SMM
- 🤝 ИИ друг — просто пиши боту любой текст
- Команды: /weather /morning /lunch /city /reset /stop /id

Время и город меняются в переменных (`MORNING_TIME`, `LUNCH_TIME`, `TIMEZONE`, `CITY`).

---

## Шаг 1. Токен бота
1. В Telegram открой @BotFather → `/newbot` → придумай имя.
2. Скопируй токен → это `BOT_TOKEN`.

## Шаг 2. Ключ Gemini (бесплатно)
1. Зайди на https://aistudio.google.com/apikey → Create API key.
2. Скопируй → это `GEMINI_API_KEY`.

## Шаг 3. Проверка на компьютере (по желанию)
```
python -m venv venv
venv\Scripts\activate          (Windows)   или   source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         (и впиши токен и ключ)
python main.py
```
Напиши боту /start. Свой ID узнай командой /id и впиши в `OWNER_CHAT_ID`.

## Шаг 4. GitHub
Залей папку в **приватный** репозиторий (файл `.env` не попадёт — он в `.gitignore`).
```
git init
git add .
git commit -m "tg bot"
git branch -M main
git remote add origin https://github.com/ТВОЙ_НИК/ИМЯ_РЕПО.git
git push -u origin main
```

## Шаг 5. Render
1. https://render.com → **New +** → **Web Service** → подключи репозиторий.
2. Настройки:
   - Runtime: **Python 3**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python main.py`
   - Plan: Free
3. **Environment** → добавь переменные:

| Ключ | Значение |
|---|---|
| `BOT_TOKEN` | токен от BotFather |
| `GEMINI_API_KEY` | ключ Gemini |
| `OWNER_CHAT_ID` | твой ID из /id |
| `CITY` | Bishkek (или твой город) |
| `TIMEZONE` | Asia/Bishkek |
| `PYTHON_VERSION` | 3.12.3 |

4. Deploy. Когда в логах появится «Веб-сервер запущен» — бот работает.

> Можно и через `render.yaml` (New + → Blueprint), он уже настроен.

## Шаг 6. Мониторинг 24/7 (чтобы Render не усыплял)
Бесплатный Render засыпает через 15 минут без запросов. Чтобы этого не было:
1. Зарегистрируйся на https://uptimerobot.com (бесплатно).
2. **Add New Monitor** → тип **HTTP(s)**.
3. URL: `https://ИМЯ-ТВОЕГО-СЕРВИСА.onrender.com/health`
4. Интервал: **5 минут** → Create.

Готово: сервис получает запрос каждые 5 минут и не засыпает, а в 05:00 по Бишкеку приходит рассылка.

---

## Важно знать
- На бесплатном Render диск **временный**: при перезапуске список подписчиков (`data.db`) сбрасывается. Поэтому впиши свой ID в `OWNER_CHAT_ID` — тебе рассылка придёт всегда. Остальным придётся снова нажать /start. Для постоянной базы нужен платный диск Render или внешняя БД.
- Если бот молчит: Render → Logs. Частые причины — неверный токен или не задан `GEMINI_API_KEY`.
- Запускай **только один** экземпляр бота с этим токеном (не держи его одновременно на компьютере и на Render, иначе будет ошибка Conflict).
- Токен и ключи никогда не публикуй. Если токен утёк — BotFather → `/revoke`.
- Время рассылки меняется переменными `MORNING_TIME` и `LUNCH_TIME` (формат `ЧЧ:ММ`).
