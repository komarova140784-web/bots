import json
import logging
import sqlite3
import time
import requests
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "8222916294:AAEHC7gx4OhrFCmKz2XGXWqXTfQyiiXnkQs"
API_URL = f"https://api.telegram.org/bot{TOKEN}"
MAIN_ADMIN_ID = 1678221039  # Главный админ


# Инициализация БД
def init_db(recreate=False):
    conn = sqlite3.connect('messages.db')
    if recreate:
        conn.execute("DROP TABLE IF EXISTS users")
        conn.execute("DROP TABLE IF EXISTS messages")
        conn.execute("DROP TABLE IF EXISTS settings")
        conn.execute("DROP TABLE IF EXISTS user_states")
        conn.execute("DROP TABLE IF EXISTS admins")
        conn.execute("DROP TABLE IF EXISTS bots")
        conn.execute("DROP TABLE IF EXISTS developers")

    # Создаём таблицы
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        is_active BOOLEAN DEFAULT 1,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        message TEXT NOT NULL,
        response TEXT,
        status TEXT DEFAULT 'pending',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', 'off')")
    conn.execute('''CREATE TABLE IF NOT EXISTS user_states (
        user_id INTEGER PRIMARY KEY,
        state TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )''')
    conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (MAIN_ADMIN_ID,))
    conn.execute('''CREATE TABLE IF NOT EXISTS bots (
        username TEXT PRIMARY KEY,
        description TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS developers (
        name TEXT,
        role TEXT,
        contact TEXT
    )''')
    conn.commit()
    conn.close()

# Проверка, является ли пользователь админом
def is_admin(user_id):
    conn = sqlite3.connect('messages.db')
    cursor = conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Сохранение пользователя
def save_user(user_id, username):
    conn = sqlite3.connect('messages.db')
    conn.execute('INSERT OR REPLACE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()
    conn.close()

# Сохранение сообщения
def save_message(user_id, username, message):
    conn = sqlite3.connect('messages.db')
    conn.execute('INSERT INTO messages (user_id, username, message) VALUES (?, ?, ?)', (user_id, username, message))
    conn.commit()
    conn.close()

# Получение ID пользователя по ID или @username
def get_user_by_id_or_username(identifier):
    conn = sqlite3.connect('messages.db')
    if str(identifier).startswith('@'):
        cursor = conn.execute('SELECT user_id FROM users WHERE username = ? LIMIT 1', (identifier,))
    else:
        cursor = conn.execute('SELECT user_id FROM users WHERE user_id = ? LIMIT 1', (int(identifier),))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


# Сохранение ответа админа
def save_response(user_id, response):
    conn = sqlite3.connect('messages.db')
    conn.execute(
        '''UPDATE messages
           SET response = ?, status = 'replied'
           WHERE user_id = ? AND status = 'pending'
           ORDER BY id DESC LIMIT 1''',
        (response, user_id)
    )
    conn.commit()
    conn.close()

# Установка режима техработ
def set_maintenance(status):
    conn = sqlite3.connect('messages.db')
    conn.execute("UPDATE settings SET value = ? WHERE key = 'maintenance'", (status,))
    conn.commit()
    conn.close()

# Проверка режима техработ
def is_maintenance():
    conn = sqlite3.connect('messages.db')
    cursor = conn.execute("SELECT value FROM settings WHERE key = 'maintenance'")
    result = cursor.fetchone()
    conn.close()
    return result[0] == 'on' if result else False


# Получение списка админов
def get_admins():
    conn = sqlite3.connect('messages.db')
    cursor = conn.execute("SELECT user_id FROM admins")
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return result

# Удаление админа
def remove_admin(admin_id):
    conn = sqlite3.connect('messages.db')
    conn.execute("DELETE FROM admins WHERE user_id = ?", (admin_id,))
    conn.commit()
    conn.close()

# Клавиатура для пользователей
def get_keyboard(user_id):
    if is_admin(user_id):
        return {
            "keyboard": [
                ["Связаться с администратором"],
                ["Помощь"],
                ["Список ботов"],
                ["Список разработчиков"],
                ["Меню администратора"]
            ],
            "resize_keyboard": True
        }
    else:
        return USER_KEYBOARD

USER_KEYBOARD = {
    "keyboard": [
        ["Связаться с администратором"],
        ["Помощь"],
        ["Список ботов"],
        ["Список разработчиков"]
    ],
    "resize_keyboard": True
}

# Отправка сообщения
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    if parse_mode:
        data["parse_mode"] = parse_mode

    try:
        response = requests.post(f"{API_URL}/sendMessage", data=data)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return None

# Получение состояния пользователя из БД
def get_user_state(user_id):
    conn = sqlite3.connect('messages.db')
    cursor = conn.execute("SELECT state FROM user_states WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


# Установка состояния пользователя в БД
def set_user_state(user_id, state):
    conn = sqlite3.connect('messages.db')
    conn.execute(
        "INSERT OR REPLACE INTO user_states (user_id, state) VALUES (?, ?)",
        (user_id, state)
    )
    conn.commit()
    conn.close()

# Удаление состояния пользователя
def clear_user_state(user_id):
    conn = sqlite3.connect('messages.db')
    conn.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Получение списка ботов из БД
def get_bots():
    conn = sqlite3.connect('messages.db')
    cursor = conn.execute("SELECT username, description FROM bots")
    result = cursor.fetchall()
    conn.close()
    return result


# Получение списка разработчиков из БД
def get_developers():
    conn = sqlite3.connect('messages.db')
    cursor = conn.execute("SELECT name, role, contact FROM developers")
    result = cursor.fetchall()
    conn.close()
    return result

# Обработчики команд
def handle_start(user_id, username):
    save_user(user_id, f"@{username}" if username else "N/A")
    if is_maintenance() and not is_admin(user_id):
        send_message(user_id, "🛠️ Сейчас проводятся технические работы. Скоро вернёмся!")
        return
    keyboard = get_keyboard(user_id)
    send_message(user_id, "👋 Добро пожаловать! Выберите действие:", keyboard)

def handle_admin_menu(user_id):
    if not is_admin(user_id):
        send_message(user_id, "У вас нет прав для просмотра этого меню.")
        return

    admin_commands = (
        "<b>🔐 Меню администратора</b>\n\n"
        "Доступные команды:\n"
        "/maintenance on — включить техработы\n"
        "/maintenance off — выключить техработы\n"
        "/add_bot @botname «Описание» — добавить бота\n"
        "/add_dev Имя «Роль» @contact — добавить разработчика\n"
        "/add_admin ID — добавить админа\n"
        "/reply ID_или_@username Текст — ответить пользователю\n"
    )

    if user_id == MAIN_ADMIN_ID:
        admin_commands += (
            "\n<b>🔹 Команды главного админа:</b>\n"
            "/reload_db — перезагрузить БД (пересоздать таблицы)\n"
            "/remove_admin ID — удалить админа\n"
            "/admin_list — список всех админов"
        )

    send_message(user_id, admin_commands, parse_mode="HTML")

def handle_feedback(user_id):
    send_message(user_id, "Напишите ваше сообщение:")
    set_user_state(user_id, "awaiting_feedback")

def handle_help(user_id):
    help_text = (
        "❓ <b>Помощь</b>\n\n"
        "1. /start — главное меню.\n"
        "2. /feedback — связаться с администратором.\n"
        "3. Администратор ответит через /reply &lt;ID или @username&gt; &lt;текст&gt;."
    )
    send_message(user_id, help_text, parse_mode="HTML")

def handle_bot_list(user_id):
    bots = get_bots()
    if not bots:
        send_message(user_id, "Список ботов пока пуст.")
        return
    bot_text = "<b>🤖 Список ботов:</b>\n\n"
    for username, desc in bots:
        bot_text += f"🔹 <code>{username}</code> — {desc}\n"
    send_message(user_id, bot_text, parse_mode="HTML")

def handle_dev_list(user_id):
    devs = get_developers()
    if not devs:
        send_message(user_id, "Список разработчиков пока пуст.")
        return
    dev_text = "<b>👥 Список разработчиков:</b>\n\n"
    for name, role, contact in devs:
        dev_text += f"<b>{name}</b>\nРоль: {role}\nКонтакт: {contact}\n\n"
    send_message(user_id, dev_text, parse_mode="HTML")

def handle_admin_commands(user_id, text):
    if not is_admin(user_id):
        return False

    if text == '/maintenance on':
        set_maintenance('on')
        send_message(user_id, "🛠️ Режим технических работ включён.")
        return True

    elif text == '/maintenance off':
        set_maintenance('off')
        send_message(user_id, "✅ Режим технических работ выключен.")
        return True

    elif text.startswith('/add_bot'):
        parts = text.split(' ', 2)
        if len(parts) < 3:
            send_message(user_id, "Формат: /add_bot &lt;@username&gt; &lt;описание&gt;")
            return True
        username, desc = parts[1], parts[2]
        try:
            conn = sqlite3.connect('messages.db')
            conn.execute("INSERT OR REPLACE INTO bots (username, description) VALUES (?, ?)", (username, desc))
            conn.commit()
            conn.close()
            send_message(user_id, f"Бот {username} добавлен в список.")
        except Exception as e:
            send_message(user_id, f"Ошибка при добавлении бота: {e}")
        return True

    elif text.startswith('/add_dev'):
        parts = text.split(' ', 3)
        if len(parts) < 4:
            send_message(user_id, "Формат: /add_dev &lt;имя&gt; &lt;роль&gt; &lt;контакт&gt;")
            return True
        name, role, contact = parts[1], parts[2], parts[3]
        try:
            conn = sqlite3.connect('messages.db')
            conn.execute("INSERT INTO developers (name, role, contact) VALUES (?, ?, ?)", (name, role, contact))
            conn.commit()
            conn.close()
            send_message(user_id, f"Разработчик {name} добавлен.")
        except Exception as e:
            send_message(user_id, f"Ошибка при добавлении разработчика: {e}")
        return True

    elif text.startswith('/add_admin'):
        try:
            new_id = int(text.split(' ')[1])
            conn = sqlite3.connect('messages.db')
            conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
            conn.commit()
            conn.close()
            send_message(user_id, f"Пользователь {new_id} добавлен как администратор.")
        except:
            send_message(user_id, "Укажите корректный ID пользователя.")
        return True

    elif text.startswith('/reply'):
        parts = text.split(' ', 2)
        if len(parts) < 3:
            send_message(user_id, "Формат: /reply &lt;ID или @username&gt; &lt;текст&gt;")
            return True
        identifier, response_text = parts[1], parts[2]
        target_id = get_user_by_id_or_username(identifier)

        if not target_id:
            send_message(user_id, "Пользователь не найден в базе.")
            return True

        result = send_message(target_id, f"<b>Ответ от администратора:</b>\n\n{response_text}", parse_mode="HTML")
        if result and result.get("ok"):
            send_message(user_id, f"Ответ отправлен пользователю {identifier}.")
            save_response(target_id, response_text)
        else:
            send_message(user_id, "Не удалось отправить сообщение.")
        return True

    # Команды только для главного админа
    elif user_id == MAIN_ADMIN_ID:
        if text == '/reload_db':
            try:
                init_db(recreate=True)
                send_message(user_id, "✅ База данных перезагружена (таблицы пересозданы).")
            except Exception as e:
                send_message(user_id, f"Ошибка при перезагрузке БД: {e}")
            return True

        elif text.startswith('/remove_admin'):
            try:
                target_id = int(text.split(' ')[1])
                if target_id == MAIN_ADMIN_ID:
                    send_message(user_id, "Нельзя удалить главного админа!")
                    return True
                remove_admin(target_id)
                send_message(user_id, f"Администратор {target_id} удалён.")
            except:
                send_message(user_id, "Укажите корректный ID админа.")
            return True

        elif text == '/admin_list':
            admins = get_admins()
            if admins:
                admin_list = "\n".join([f"• {aid}" for aid in admins])
                send_message(user_id, f"<b>Список админов:</b>\n{admin_list}", parse_mode="HTML")
            else:
                send_message(user_id, "Список админов пуст.")
            return True

    return False  # Команда не распознана или не для админов

# Основной обработчик текстовых сообщений
def handle_text_message(user_id, username, text):
    # Проверка режима техработ (кроме админов)
    if not is_admin(user_id) and is_maintenance():
        send_message(user_id, "🛠️ Сейчас проводятся технические работы. Скоро вернёмся!")
        return

    # Обрабатываем команды админов
    if handle_admin_commands(user_id, text):
        return

    current_state = get_user_state(user_id)

    if text.strip().lower() == 'связаться с администратором':
        handle_feedback(user_id)
        return

    elif text.strip().lower() == 'помощь':
        handle_help(user_id)
        return

    elif text.strip().lower() == 'список ботов':
        handle_bot_list(user_id)
        return

    elif text.strip().lower() == 'список разработчиков':
        handle_dev_list(user_id)
        return

    elif text.strip().lower() == 'меню администратора':
        handle_admin_menu(user_id)
        return

    # Если пользователь в состоянии ожидания сообщения
    elif current_state == "awaiting_feedback":
        if text.strip():
            save_message(user_id, f"@{username}" if username else "N/A", text)

            admin_msg = (
                f"✉️ Новое сообщение!\n"
                f"ID: {user_id}\n"
                f"Username: @{username}\n"
                f"Текст: {text}\n"
                f"\nЧтобы ответить: /reply {user_id} <ваш текст>"
            )
            # Отправляем всем админам
            conn = sqlite3.connect('messages.db')
            cursor = conn.execute("SELECT user_id FROM admins")
            admin_ids = [row[0] for row in cursor.fetchall()]
            conn.close()
            for admin_id in admin_ids:
                send_message(admin_id, admin_msg, parse_mode="HTML")

            send_message(user_id, "✅ Ваше сообщение отправлено!")
        else:
            send_message(user_id, "Пожалуйста, напишите сообщение.")

        # Сбрасываем состояние
        clear_user_state(user_id)
        return

    # Всё остальное — напоминание о меню
    keyboard = get_keyboard(user_id)
    send_message(user_id, "Используйте кнопки ниже 👇", keyboard)

# Основной цикл опроса Telegram API
def main():
    init_db()  # Инициализируем БД при запуске
    offset = None  # Для предотвращения повторной обработки сообщений

    logger.info("Бот запущен. Ожидание сообщений...")

    while True:
        try:
            # Получаем обновления
            data = {
                "offset": offset,
                "limit": 100,
                "timeout": 60
            }
            response = requests.post(f"{API_URL}/getUpdates", data=data)
            result = response.json()

            if not result.get("result"):
                continue  # Нет новых сообщений

            for item in result["result"]:
                update_id = item["update_id"]
                message = item.get("message")

                if not message:
                    continue

                # Обновляем offset
                offset = update_id + 1

                chat_id = message["chat"]["id"]
                user_id = message["from"]["id"]
                username = message["from"].get("username")
                text = message.get("text", "")

                logger.info(f"Получено сообщение от {user_id}: {text}")

                # Обрабатываем команду /start
                if text == "/start":
                    handle_start(user_id, username)
                    continue

                # Для всех остальных сообщений
                handle_text_message(user_id, username, text)


        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети при получении обновлений: {e}")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Неожиданная ошибка в основном цикле: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()