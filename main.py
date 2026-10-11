import asyncio
import logging
import os
import random
import sqlite3
from collections import defaultdict, deque
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "").strip()
DEFAULT_CITY = os.getenv("CITY", "Bishkek").strip()
TIMEZONE = os.getenv("TIMEZONE", "Asia/Bishkek").strip()
MORNING_TIME = os.getenv("MORNING_TIME", "05:00").strip()
LUNCH_TIME = os.getenv("LUNCH_TIME", "13:00").strip()
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "data.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

if not BOT_TOKEN:
    raise SystemExit("Не задан BOT_TOKEN. Добавь его в .env или в Environment на Render.")

http: aiohttp.ClientSession | None = None
history: dict[int, deque] = defaultdict(lambda: deque(maxlen=20))

# ---------------------------------------------------------------- база данных


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, city TEXT)")
    return conn


def add_user(chat_id: int):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (chat_id, city) VALUES (?, ?)", (chat_id, DEFAULT_CITY))


def remove_user(chat_id: int):
    with db() as c:
        c.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))


def set_city(chat_id: int, city: str):
    with db() as c:
        c.execute(
            "INSERT INTO users (chat_id, city) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET city = excluded.city",
            (chat_id, city),
        )


def get_city(chat_id: int) -> str:
    with db() as c:
        row = c.execute("SELECT city FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    return row[0] if row and row[0] else DEFAULT_CITY


def all_recipients() -> dict[int, str]:
    with db() as c:
        rows = c.execute("SELECT chat_id, city FROM users").fetchall()
    result = {r[0]: r[1] or DEFAULT_CITY for r in rows}
    if OWNER_CHAT_ID.lstrip("-").isdigit():
        result.setdefault(int(OWNER_CHAT_ID), DEFAULT_CITY)
    return result


# ---------------------------------------------------------------- Gemini


async def gemini(contents: list, system: str | None = None, temperature: float = 0.9) -> str | None:
    if not GEMINI_API_KEY or http is None:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 2000},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    try:
        async with http.post(
            url,
            json=payload,
            headers={"x-goog-api-key": GEMINI_API_KEY},
            timeout=aiohttp.ClientTimeout(total=45),
        ) as r:
            data = await r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text or None
    except Exception as e:
        log.warning("Gemini error: %s", e)
        return None


# ---------------------------------------------------------------- погода

WMO = {
    0: "ясно ☀️", 1: "в основном ясно 🌤", 2: "переменная облачность ⛅", 3: "пасмурно ☁️",
    45: "туман 🌫", 48: "изморозь 🌫", 51: "лёгкая морось 🌦", 53: "морось 🌦", 55: "сильная морось 🌧",
    61: "небольшой дождь 🌦", 63: "дождь 🌧", 65: "сильный дождь 🌧", 66: "ледяной дождь 🌧",
    67: "сильный ледяной дождь 🌧", 71: "небольшой снег 🌨", 73: "снег 🌨", 75: "сильный снег ❄️",
    77: "снежные зёрна 🌨", 80: "ливни 🌦", 81: "сильные ливни 🌧", 82: "очень сильные ливни ⛈",
    85: "снегопад 🌨", 86: "сильный снегопад ❄️", 95: "гроза ⛈", 96: "гроза с градом ⛈", 99: "сильная гроза с градом ⛈",
}


async def get_weather(city: str) -> str:
    try:
        async with http.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "ru"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            geo = await r.json()
        place = geo["results"][0]
        async with http.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            w = await r.json()
        cur, day = w["current"], w["daily"]
        rain = day["precipitation_probability_max"][0]
        return (
            f"🌍 {place['name']}\n"
            f"Сейчас: {round(cur['temperature_2m'])}°C (ощущается как {round(cur['apparent_temperature'])}°C), "
            f"{WMO.get(cur['weather_code'], '')}\n"
            f"Днём: от {round(day['temperature_2m_min'][0])}° до {round(day['temperature_2m_max'][0])}°C\n"
            f"Ветер: {round(cur['wind_speed_10m'])} км/ч"
            + (f"\nВероятность осадков: {rain}%" if rain is not None else "")
        )
    except Exception as e:
        log.warning("Weather error: %s", e)
        return f"🌍 {city}: не удалось получить погоду, попробую позже."


# ---------------------------------------------------------------- тексты рассылок

FALLBACK_MOTIVATION = [
    "Маленький шаг сегодня лучше, чем идеальный план завтра. Начни с самого простого дела 💪",
    "Ты не обязан быть идеальным, ты обязан быть настойчивым. Сегодня твой день!",
    "Дисциплина — это когда делаешь, даже если не хочется. Ты справишься 🔥",
    "Каждое утро — чистый лист. Напиши на нём что-то, чем будешь гордиться.",
    "Пока другие спят, ты уже строишь своё будущее. Продолжай 🚀",
]

FALLBACK_SMM = [
    "Рубрика «Закулисье»: покажи, как создаётся твой продукт или контент за один день.",
    "Опрос в сторис: «А или Б?» по теме твоей ниши — вовлечение гарантировано.",
    "Карусель «5 ошибок новичков в [твоей теме]» — сохраняют и репостят.",
    "Reels «Было / стало» с короткой подписью и трендовым звуком.",
    "Пост-история клиента: проблема → решение → результат, с живой цитатой.",
]


async def build_morning(city: str) -> str:
    weather = await get_weather(city)
    quote = await gemini(
        [{"role": "user", "parts": [{"text": "Напиши короткое (2-3 предложения) тёплое мотивационное "
                                             "утреннее сообщение на русском. Без банальностей, "
                                             "с 1-2 эмодзи. Каждый раз новое."}]}],
        temperature=1.0,
    ) or random.choice(FALLBACK_MOTIVATION)
    return f"☀️ Доброе утро!\n\n{weather}\n\n💬 {quote}"


async def build_lunch() -> str:
    ideas = await gemini(
        [{"role": "user", "parts": [{"text": "Дай 5 свежих идей контента для SMM-специалиста (Instagram, "
                                             "TikTok, Telegram) на русском: формат + тема + короткий хук. "
                                             "Пронумеруй, без вступлений, коротко, с эмодзи."}]}],
        temperature=1.0,
    )
    if not ideas:
        ideas = "\n".join(f"{i}. {t}" for i, t in enumerate(random.sample(FALLBACK_SMM, 3), 1))
    return f"🍽 Обеденные идеи для контента:\n\n{ideas}"


# ---------------------------------------------------------------- рассылка


async def broadcast(kind: str):
    log.info("Рассылка: %s", kind)
    recipients = all_recipients()
    lunch_text = await build_lunch() if kind == "lunch" else None
    for chat_id, city in recipients.items():
        try:
            text = lunch_text if kind == "lunch" else await build_morning(city)
            await bot.send_message(chat_id, text)
        except Exception as e:
            log.warning("Не отправлено %s: %s", chat_id, e)
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------- бот

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

HELP = (
    "Команды:\n"
    "/weather — погода сейчас\n"
    "/morning — утреннее сообщение прямо сейчас\n"
    "/lunch — идеи для контента сейчас\n"
    "/city Название — сменить город\n"
    "/reset — забыть наш разговор\n"
    "/stop — отписаться от рассылки\n"
    "/id — узнать свой Telegram ID\n\n"
    "А ещё просто пиши мне что угодно — я твой ИИ друг 🤝"
)

FRIEND_PROMPT = (
    "Ты — добрый, остроумный ИИ друг в Telegram. Общайся на «ты», по-человечески, тепло, "
    "с юмором, без канцелярита. Отвечай на языке собеседника, коротко (обычно 1-4 предложения), "
    "иногда задавай встречный вопрос. Поддерживай, но говори честно. Эмодзи — в меру."
)


@dp.message(CommandStart())
async def cmd_start(m: Message):
    add_user(m.chat.id)
    await m.answer(
        f"Привет, {m.from_user.first_name}! 👋\n\n"
        f"Каждый день в {MORNING_TIME} пришлю погоду и мотивацию, "
        f"а в {LUNCH_TIME} — идеи для контента.\n\n{HELP}"
    )


@dp.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(HELP)


@dp.message(Command("id"))
async def cmd_id(m: Message):
    await m.answer(f"Твой chat ID: {m.chat.id}")


@dp.message(Command("stop"))
async def cmd_stop(m: Message):
    remove_user(m.chat.id)
    await m.answer("Отписал от рассылки. Вернуться — /start 🙌")


@dp.message(Command("reset"))
async def cmd_reset(m: Message):
    history.pop(m.chat.id, None)
    await m.answer("Окей, начинаем с чистого листа ✨")


@dp.message(Command("weather"))
async def cmd_weather(m: Message):
    await m.answer(await get_weather(get_city(m.chat.id)))


@dp.message(Command("morning"))
async def cmd_morning(m: Message):
    await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    await m.answer(await build_morning(get_city(m.chat.id)))


@dp.message(Command("lunch"))
async def cmd_lunch(m: Message):
    await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    await m.answer(await build_lunch())


@dp.message(Command("city"))
async def cmd_city(m: Message):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.answer("Напиши так: /city Москва")
        return
    city = parts[1].strip()
    text = await get_weather(city)
    if "не удалось" in text:
        await m.answer("Не нашёл такой город 🤔 Попробуй написать по-другому.")
        return
    set_city(m.chat.id, city)
    await m.answer(f"Город обновлён ✅\n\n{text}")


@dp.message(F.text & ~F.text.startswith("/"))
async def friend(m: Message):
    if not GEMINI_API_KEY:
        await m.answer("ИИ друг пока спит: не задан GEMINI_API_KEY 😴")
        return
    await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    hist = history[m.chat.id]
    contents = list(hist) + [{"role": "user", "parts": [{"text": m.text}]}]
    reply = await gemini(contents, system=FRIEND_PROMPT, temperature=0.9)
    if not reply:
        await m.answer("Что-то я задумался и завис 😅 Попробуй ещё раз через минутку.")
        return
    hist.append({"role": "user", "parts": [{"text": m.text}]})
    hist.append({"role": "model", "parts": [{"text": reply}]})
    await m.answer(reply)


# ---------------------------------------------------------------- веб-сервер для Render / мониторинга


async def start_web():
    async def ok(_):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", ok)
    app.router.add_get("/health", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Веб-сервер запущен на порту %s", PORT)


def parse_time(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


async def main():
    global http
    http = aiohttp.ClientSession()
    await start_web()

    tz = ZoneInfo(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)
    mh, mm = parse_time(MORNING_TIME)
    lh, lm = parse_time(LUNCH_TIME)
    scheduler.add_job(broadcast, CronTrigger(hour=mh, minute=mm, timezone=tz), args=["morning"],
                      misfire_grace_time=3600, id="morning")
    scheduler.add_job(broadcast, CronTrigger(hour=lh, minute=lm, timezone=tz), args=["lunch"],
                      misfire_grace_time=3600, id="lunch")
    scheduler.start()
    log.info("Расписание: утро %s, обед %s (%s)", MORNING_TIME, LUNCH_TIME, TIMEZONE)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await http.close()


if __name__ == "__main__":
    asyncio.run(main())
