import asyncio
import logging
import json
import os
from datetime import datetime, date, timedelta, time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

# ================= КОНФІГУРАЦІЯ =================
TOKEN = "8464185840:AAHxo7jES7pwjI35zj05pQNiOrfi_3lnfIE"
ADMIN_IDS = [693141451]  # Ваш ID
GROUP_CHAT_ID = 8280781426  # ID групи

TIMEZONE = timezone("Europe/Kyiv")
DB_FILE = "schedule.json"

# ================= БАЗА ДАНИХ =================
def load_schedule():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        return {datetime.strptime(k, "%Y-%m-%d").date(): v for k, v in data.items()}

def save_schedule(schedule_data):
    data = {k.strftime("%Y-%m-%d"): v for k, v in schedule_data.items()}
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

SCHEDULE = load_schedule()
USER_BINDINGS = {}

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ================= РОЗУМНА МАТЕМАТИКА ЧАСУ =================
def calculate_smart_shifts(d: date, people: list):
    if not people:
        return [], False

    count = len(people)

    # < 6 людей -> 2 рази, >= 6 людей -> 1 раз
    if count < 6:
        shifts_count = count * 2
        is_double = True
    else:
        shifts_count = count
        is_double = False

    TOTAL_MINUTES = 1440 
    shifts = []
    start_dt = TIMEZONE.localize(datetime.combine(d, time(9, 0)))

    for i in range(shifts_count):
        start_offset = int((TOTAL_MINUTES * i) / shifts_count)
        end_offset = int((TOTAL_MINUTES * (i + 1)) / shifts_count)

        current_start = start_dt + timedelta(minutes=start_offset)
        current_end = start_dt + timedelta(minutes=end_offset)

        person = people[i % count]

        shifts.append({
            "start": current_start.strftime("%H:%M"),
            "end": current_end.strftime("%H:%M"),
            "person": person,
            "duration_min": end_offset - start_offset,
            "start_dt": current_start
        })

    return shifts, is_double

def format_day_text(d: date):
    people = SCHEDULE.get(d)
    text = f"📅 *{d.strftime('%d.%m.%Y')}*\n"

    if not people:
        text += "❌ Графік не встановлено.\n"
        return text

    shifts, is_double = calculate_smart_shifts(d, people)

    dur = shifts[0]['duration_min']
    h = dur // 60
    m = dur % 60

    mode_text = "2 рази на добу" if is_double else "1 раз на добу"

    text += f"👥 Людей: {len(people)}. Режим: {mode_text}.\n"
    text += f"⏱ Вахта по: **{h} год {m:02d} хв**.\n"
    text += "-------------------\n"

    for s in shifts:
        hour = int(s['start'].split(':')[0])
        icon = "🌙" if (hour >= 21 or hour < 6) else "☀️"
        text += f"{icon} `{s['start']} - {s['end']}` : *{s['person']}*\n"

    return text

# ================= АДМІНКА =================

@dp.message(Command("set"))
async def set_schedule_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        args = msg.text.split()
        if len(args) < 3: raise ValueError
        day_str = args[1]
        date_obj = datetime.strptime(f"{day_str}.{datetime.now().year}", "%d.%m.%Y").date()
        names = args[2:]
        SCHEDULE[date_obj] = names
        save_schedule(SCHEDULE)
        await msg.answer(f"✅ Графік на {date_obj.strftime('%d.%m')} збережено!")
        await msg.answer(format_day_text(date_obj), parse_mode="Markdown")
    except:
        await msg.answer("❗ Помилка. Пишіть так:\n`/set 15.02 Прізвище1 Прізвище2 ...`", parse_mode="Markdown")

@dp.message(Command("clear"))
async def clear_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try:
        day_str = msg.text.split()[1]
        date_obj = datetime.strptime(f"{day_str}.{datetime.now().year}", "%d.%m.%Y").date()
        if date_obj in SCHEDULE:
            del SCHEDULE[date_obj]
            save_schedule(SCHEDULE)
            await msg.answer("🗑 Видалено.")
    except: pass

# ================= КОРИСТУВАЧ =================

@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer(
        "⚓ **Бот Вахти**\n\n"
        "/today — графік сьогодні\n"
        "/tomorrow — графік завтра\n"
        "/grafik 15 — графік на число\n"
        "/me — коли мені заступати\n"
        "/bind Прізвище — підписатися\n\n"
        "**Адміну:**\n"
        "`/set 15.02 Прізвище1...`",
        parse_mode="Markdown"
    )

@dp.message(Command("bind"))
async def bind(msg: types.Message):
    try:
        surname = msg.text.split()[1]
        USER_BINDINGS[msg.from_user.id] = surname
        await msg.answer(f"✅ Ви: **{surname}**", parse_mode="Markdown")
    except:
        await msg.answer("❗ `/bind Гогулов`", parse_mode="Markdown")

@dp.message(Command("today"))
async def today(msg: types.Message):
    d = datetime.now(TIMEZONE).date()
    await msg.answer(format_day_text(d), parse_mode="Markdown")

@dp.message(Command("tomorrow"))
async def tomorrow(msg: types.Message):
    d = datetime.now(TIMEZONE).date() + timedelta(days=1)
    await msg.answer(format_day_text(d), parse_mode="Markdown")

# НОВЕ: Обробка команди /grafik
@dp.message(Command("grafik"))
async def grafik_cmd(msg: types.Message):
    try:
        args = msg.text.split()
        if len(args) < 2:
            await msg.answer("❗ Введіть число: `/grafik 15`", parse_mode="Markdown")
            return

        raw = args[1]
        now = datetime.now(TIMEZONE)

        # Якщо ввели повну дату 15.02
        if "." in raw:
             d = datetime.strptime(f"{raw}.{now.year}", "%d.%m.%Y").date()
        # Якщо ввели просто число 15
        else:
             d = date(now.year, now.month, int(raw))

        await msg.answer(format_day_text(d), parse_mode="Markdown")
    except Exception as e:
        await msg.answer("❗ Некоректна дата. Спробуйте: `/grafik 15`", parse_mode="Markdown")

@dp.message(Command("me"))
async def me(msg: types.Message):
    surname = USER_BINDINGS.get(msg.from_user.id)
    if not surname:
        await msg.answer("❗ `/bind Прізвище`", parse_mode="Markdown")
        return
    d = datetime.now(TIMEZONE).date()
    people = SCHEDULE.get(d)
    if not people:
        await msg.answer("💤 Графіку немає.")
        return
    shifts, _ = calculate_smart_shifts(d, people)
    my_shifts = [s for s in shifts if s['person'].lower() == surname.lower()]
    if not my_shifts:
        await msg.answer(f"👤 **{surname}**\nСьогодні вихідний.", parse_mode="Markdown")
        return
    text = f"👤 **{surname}** ({d.strftime('%d.%m')}):\n"
    for s in my_shifts:
        text += f"⏰ `{s['start']} - {s['end']}`\n"
    await msg.answer(text, parse_mode="Markdown")

# НОВЕ: Обробка простого числа (наприклад пишеш "15" і отримуєш графік)
@dp.message(F.text.regexp(r"^\d{1,2}$"))
async def simple_number_handler(msg: types.Message):
    try:
        day = int(msg.text)
        now = datetime.now(TIMEZONE)
        d = date(now.year, now.month, day)
        await msg.answer(format_day_text(d), parse_mode="Markdown")
    except:
        pass

# ================= СПОВІЩЕННЯ =================
async def send_flag_raise():
    try: await bot.send_message(GROUP_CHAT_ID, "🇺🇦 **Підняття Прапора!**", parse_mode="Markdown")
    except: pass

async def send_silence_minute():
    try: await bot.send_message(GROUP_CHAT_ID, "🕯 **Хвилина мовчання.**", parse_mode="Markdown")
    except: pass

sent_reminders = set()
async def check_personal_reminders():
    now = datetime.now(TIMEZONE)
    d = now.date()
    shifts = []
    if d in SCHEDULE:
        s, _ = calculate_smart_shifts(d, SCHEDULE[d])
        shifts.extend(s)
    d_next = d + timedelta(days=1)
    if d_next in SCHEDULE:
        s_next, _ = calculate_smart_shifts(d_next, SCHEDULE[d_next])
        shifts.extend(s_next)

    for s in shifts:
        start_dt = s['start_dt']
        diff = (start_dt - now).total_seconds()
        key = (start_dt.date(), s["start"], s["person"])
        if 60 < diff <= 1800 and key not in sent_reminders:
            for uid, uname in USER_BINDINGS.items():
                if uname.lower() == s["person"].lower():
                    try:
                        await bot.send_message(uid, f"🔔 **Вахта через 30 хв!**\n⏰ `{s['start']} - {s['end']}`", parse_mode="Markdown")
                        sent_reminders.add(key)
                    except: pass

async def daily_cleanup():
    sent_reminders.clear()

async def main():
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(check_personal_reminders, "interval", minutes=1)
    scheduler.add_job(daily_cleanup, "cron", hour=0, minute=1)
    scheduler.add_job(send_flag_raise, "cron", day_of_week='mon-fri', hour=8, minute=0)
    scheduler.add_job(send_flag_raise, "cron", day_of_week='sat,sun', hour=9, minute=0)
    scheduler.add_job(send_silence_minute, "cron", hour=9, minute=0)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
