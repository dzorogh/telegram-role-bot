import sqlite3
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ChatType, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
import logging
import re
import os

# Получение API_TOKEN из переменных окружения (Docker)
API_TOKEN = os.environ['API_TOKEN']

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- Инициализация базы данных ---
conn = sqlite3.connect("/app/data/roles.db")
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        name TEXT,
        UNIQUE(chat_id, name)
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS role_users (
        role_id INTEGER,
        user_id INTEGER,
        username TEXT,
        UNIQUE(role_id, user_id)
    )
''')
conn.commit()

# --- Хелперы ---
def get_role_id(chat_id, role_name):
    cursor.execute("SELECT id FROM roles WHERE chat_id = ? AND name = ?", (chat_id, role_name))
    row = cursor.fetchone()
    return row[0] if row else None

# --- Команды ---
@dp.message_handler(commands=['start', 'help'])
async def show_help(message: types.Message):
    help_text = (
        "📚 <b>Доступные команды:</b>\n"
        "/add_role &quot;роль&quot; — создать новую роль\n"
        "/roles — список всех ролей в чате\n"
        "/join &quot;роль&quot; — вступить в роль\n"
        "/leave &quot;роль&quot; — выйти из роли\n"
        "/list_role &quot;роль&quot; — кто в роли\n"
        "/notify &quot;роль&quot; сообщение — оповестить участников роли\n"
        "/my_roles — мои роли"
    )
    await message.reply(help_text, parse_mode="HTML")

@dp.message_handler(commands=['add_role'])
async def add_role(message: types.Message):
    role = message.get_args().strip()
    if not role:
        return await message.reply("⚠️ Укажи название роли: /add_role дизайнеры")

    try:
        cursor.execute("INSERT INTO roles (chat_id, name) VALUES (?, ?)", (message.chat.id, role))
        conn.commit()
        await message.reply(f"✅ Роль '{role}' создана.")
    except sqlite3.IntegrityError:
        await message.reply("⚠️ Такая роль уже существует в этом чате.")

@dp.message_handler(commands=['roles'])
async def list_roles(message: types.Message):
    chat_id = message.chat.id
    cursor.execute("SELECT name FROM roles WHERE chat_id = ? ORDER BY name", (chat_id,))
    roles = cursor.fetchall()
    if not roles:
        return await message.reply("📭 В этом чате ещё нет ролей.")

    keyboard = InlineKeyboardMarkup(row_width=2)
    for (role_name,) in roles:
        keyboard.add(
            InlineKeyboardButton(f"✅ Вступить: {role_name}", callback_data=f"join:{role_name}"),
            InlineKeyboardButton(f"🚪 Выйти: {role_name}", callback_data=f"leave:{role_name}")
        )

    await message.reply("📃 Список ролей в этом чате:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith("join:") or c.data.startswith("leave:"))
async def handle_role_buttons(callback_query: types.CallbackQuery):
    action, role = callback_query.data.split(":", 1)
    chat_id = callback_query.message.chat.id
    user = callback_query.from_user
    role_id = get_role_id(chat_id, role)

    if not role_id:
        return await callback_query.answer("Такой роли не существует", show_alert=True)

    if action == "join":
        cursor.execute("INSERT OR IGNORE INTO role_users (role_id, user_id, username) VALUES (?, ?, ?)",
                       (role_id, user.id, user.username or ""))
        conn.commit()
        await callback_query.answer(f"Ты вступил в роль '{role}' ✅")
    elif action == "leave":
        cursor.execute("DELETE FROM role_users WHERE role_id = ? AND user_id = ?", (role_id, user.id))
        conn.commit()
        await callback_query.answer(f"Ты покинул роль '{role}' 🚪")

@dp.message_handler(commands=['join'])
async def join_role(message: types.Message):
    role = message.get_args().strip()
    if not role:
        return await message.reply("⚠️ Укажи название роли: /join дизайнеры")

    role_id = get_role_id(message.chat.id, role)
    if not role_id:
        return await message.reply("⚠️ Такой роли не существует в этом чате.")

    user = message.from_user
    cursor.execute("INSERT OR IGNORE INTO role_users (role_id, user_id, username) VALUES (?, ?, ?)",
                   (role_id, user.id, user.username or ""))
    conn.commit()
    await message.reply(f"✅ Ты добавлен в роль '{role}'.")

@dp.message_handler(commands=['leave'])
async def leave_role(message: types.Message):
    role = message.get_args().strip()
    if not role:
        return await message.reply("⚠️ Укажи название роли: /leave дизайнеры")

    role_id = get_role_id(message.chat.id, role)
    if not role_id:
        return await message.reply("⚠️ Такой роли не существует в этом чате.")

    cursor.execute("DELETE FROM role_users WHERE role_id = ? AND user_id = ?", (role_id, message.from_user.id))
    conn.commit()
    await message.reply(f"🚪 Ты покинул роль '{role}'.")

@dp.message_handler(commands=['list_role'])
async def list_role(message: types.Message):
    role = message.get_args().strip()
    role_id = get_role_id(message.chat.id, role)
    if not role_id:
        return await message.reply("⚠️ Такой роли не существует в этом чате.")

    cursor.execute("SELECT username FROM role_users WHERE role_id = ?", (role_id,))
    users = cursor.fetchall()
    if not users:
        return await message.reply(f"📭 В роли '{role}' пока никого нет.")

    user_list = ', '.join([f"@{u[0]}" for u in users if u[0]])
    await message.reply(f"👥 В роли '{role}': {user_list}")

@dp.message_handler(commands=['notify'])
async def notify(message: types.Message):
    args = message.get_args()
    if not args:
        return await message.reply("⚠️ Пример: /notify дизайнеры Собрание в 18:00")

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("⚠️ Укажи роль и текст уведомления: /notify роль сообщение")

    role, text = parts
    role_id = get_role_id(message.chat.id, role)
    if not role_id:
        return await message.reply("⚠️ Такой роли не существует в этом чате.")

    cursor.execute("SELECT username FROM role_users WHERE role_id = ?", (role_id,))
    users = cursor.fetchall()
    if not users:
        return await message.reply("📭 В этой роли пока нет пользователей.")

    mentions = ' '.join([f"@{u[0]}" for u in users if u[0]])
    await message.reply(f"📢 {text}\n\n{mentions}")

@dp.message_handler(commands=['my_roles'])
async def my_roles(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    cursor.execute('''
        SELECT roles.name FROM roles
        JOIN role_users ON roles.id = role_users.role_id
        WHERE role_users.user_id = ? AND roles.chat_id = ?
    ''', (user_id, chat_id))
    roles = cursor.fetchall()
    if not roles:
        await message.reply("🤷 Ты пока не состоишь ни в одной роли.")
    else:
        role_list = ', '.join([r[0] for r in roles])
        await message.reply(f"🎭 Ты в ролях: {role_list}")

# --- Установка меню команд ---
async def on_startup(dp):
    await bot.set_my_commands([
        BotCommand("help", "Показать справку"),
        BotCommand("add_role", "Создать новую роль"),
        BotCommand("roles", "Список ролей"),
        BotCommand("join", "Вступить в роль"),
        BotCommand("leave", "Выйти из роли"),
        BotCommand("list_role", "Кто в роли"),
        BotCommand("notify", "Оповестить участников роли"),
        BotCommand("my_roles", "Мои роли")
    ])

# --- Запуск ---
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
