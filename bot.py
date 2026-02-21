import sqlite3
import logging
from datetime import datetime, timedelta, timezone
import random
from typing import Optional, Tuple, List, Dict, Any
import time
import requests
import json
import os
import html
from difflib import SequenceMatcher
from collections import defaultdict, deque
import hashlib

from telegram import Update, User, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, ChatMemberHandler, CallbackQueryHandler
)

# === НАСТРОЙКИ ===
TOKEN = "8560378565:AAEHvQdBQteRZzaeGhmPas6bjOe4wk-tU-E"
DB_PATH = "bot.db"
RULES_FILE = "rules.json"
BAD_WORDS_FILE = "bad_words.json"
SHOP_ITEMS_FILE = "shop_items.json"
USER_INVENTORY_FILE = "user_inventory.json"
QUOTES_FILE = "quotes.json"
WEATHER_API_KEY = ""  # Можно добавить API ключ для погоды
MSK = timezone(timedelta(hours=3))
DEVELOPER_ID = 1678221039
WHITELIST = [DEVELOPER_ID, 777000]  # Неприкасаемые

# Настройки флуда
FLUD_WINDOW_SEC = 30
FLUD_MESSAGE_COUNT = 3
SIMILARITY_THRESHOLD = 0.7

# Настройки антирейда
RAID_WINDOW_SEC = 10
RAID_MENTION_COUNT = 5

# Настройки модерации
INITIAL_ADMIN_LEVEL = 5
FLOOD_MUTE_MINUTES = 10
BAD_WORDS_MUTE_MINUTES = 15

# === НАСТРОЙКА ЛОГГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ===
user_message_history = defaultdict(lambda: deque(maxlen=20))
raid_mode_active = defaultdict(bool)
raid_mention_counter = defaultdict(list)
game_sessions = {}  # Для хранения игр
duel_sessions = {}  # Для хранения дуэлей
marriage_proposals = {}  # Для предложений брака
daily_rep = defaultdict(set)  # Кто уже ставил репутацию сегодня

# === ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ БД ===
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        # Пользователи (глобальный список)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                rep INTEGER DEFAULT 0,
                marry_with INTEGER DEFAULT NULL,
                clan_id INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Проверяем и добавляем недостающие колонки
        try:
            conn.execute("ALTER TABLE users ADD COLUMN rep INTEGER DEFAULT 0")
            logger.info("✅ Добавлена колонка rep в таблицу users")
        except:
            pass  # Колонка уже существует
            
        try:
            conn.execute("ALTER TABLE users ADD COLUMN marry_with INTEGER DEFAULT NULL")
            logger.info("✅ Добавлена колонка marry_with в таблицу users")
        except:
            pass
            
        try:
            conn.execute("ALTER TABLE users ADD COLUMN clan_id INTEGER DEFAULT NULL")
            logger.info("✅ Добавлена колонка clan_id в таблицу users")
        except:
            pass
        
        # Чаты, в которых есть бот
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                invite_link TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Администраторы бота в конкретных чатах
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 6),
                is_frozen INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        
        # Правила чата
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_rules (
                chat_id INTEGER PRIMARY KEY,
                rules TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Логи модерации
        conn.execute("""
            CREATE TABLE IF NOT EXISTS moderation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Размеры "письки"
        conn.execute("""
            CREATE TABLE IF NOT EXISTS penis_sizes (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                size INTEGER DEFAULT 0,
                last_played DATE,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        
        # Очки пользователей
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                user_id INTEGER PRIMARY KEY,
                points INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Друзья
        conn.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                user_id INTEGER NOT NULL,
                friend_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, friend_id)
            )
        """)
        
        # Кланы
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clans (
                clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                owner_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                points INTEGER DEFAULT 0,
                members_count INTEGER DEFAULT 1
            )
        """)
        
        # Достижения
        conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER NOT NULL,
                ach_id TEXT NOT NULL,
                earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, ach_id)
            )
        """)
        
        # Предупреждения
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
    logger.info("✅ База данных инициализирована")

# === ФУНКЦИИ ДЛЯ ЭКРАНИРОВАНИЯ ТЕКСТА ===

def escape_markdown(text: str) -> str:
    """Экранирует специальные символы для Markdown"""
    if not text:
        return ""
    text = str(text)
    chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in chars:
        text = text.replace(char, '\\' + char)
    return text

def safe_markdown(text: str) -> str:
    """Безопасно форматирует текст для Markdown"""
    return escape_markdown(text)

# === ОСНОВНЫЕ ФУНКЦИИ РАБОТЫ С БД ===

def save_user(user: User):
    """Сохраняет пользователя в БД"""
    if not user or user.is_bot:
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        # Проверяем, есть ли уже пользователь
        existing = conn.execute(
            "SELECT rep, marry_with, clan_id FROM users WHERE user_id = ?",
            (user.id,)
        ).fetchone()
        
        if existing:
            # Сохраняем существующие данные
            conn.execute("""
                UPDATE users SET 
                username = ?, first_name = ?, last_name = ?
                WHERE user_id = ?
            """, (user.username, user.first_name, user.last_name, user.id))
        else:
            # Новый пользователь
            conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, rep)
                VALUES (?, ?, ?, ?, 0)
            """, (user.id, user.username, user.first_name, user.last_name))
        conn.commit()

def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Получает пользователя по ID"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT user_id, username, first_name, last_name, rep, marry_with, clan_id 
            FROM users WHERE user_id = ?
        """, (user_id,)).fetchone()
    
    if row:
        return {
            "user_id": row[0],
            "username": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "rep": row[4] if row[4] is not None else 0,
            "marry_with": row[5],
            "clan_id": row[6]
        }
    return None

def get_user_by_username(username: str) -> Optional[Dict]:
    """Получает пользователя по username"""
    username = username.lower().lstrip('@')
    
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT user_id, username, first_name, last_name, rep, marry_with, clan_id 
            FROM users WHERE LOWER(username) = ?
        """, (username,)).fetchone()
    
    if row:
        return {
            "user_id": row[0],
            "username": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "rep": row[4] if row[4] is not None else 0,
            "marry_with": row[5],
            "clan_id": row[6]
        }
    return None

def add_chat(chat_id: int, invite_link: str = None):
    """Добавляет чат в БД"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO chats (chat_id, invite_link, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (chat_id, invite_link))
        conn.commit()

# === ФУНКЦИИ ДЛЯ АДМИНОВ ===

def get_admin_level(chat_id: int, user_id: int) -> int:
    """Возвращает уровень администратора (0 - если не админ)"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT level FROM admins WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        ).fetchone()
    
    if row:
        return row[0]
    return 0

def is_admin_frozen(chat_id: int, user_id: int) -> bool:
    """Проверяет, заморожен ли админ"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT is_frozen FROM admins WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        ).fetchone()
    
    if row:
        return bool(row[0])
    return False

def set_admin_level(chat_id: int, user_id: int, level: int, moderator_id: int) -> Tuple[bool, str]:
    """Устанавливает уровень админа (0 - удалить) с проверкой прав"""
    
    # Разработчик может всё
    if moderator_id == DEVELOPER_ID:
        pass
    else:
        # Нельзя менять себя
        if moderator_id == user_id:
            return False, "❌ Нельзя изменять свой собственный уровень"
        
        # Проверяем уровень модератора
        mod_level = get_admin_level(chat_id, moderator_id)
        
        # Нельзя дать уровень выше своего
        if level > mod_level:
            return False, f"❌ Нельзя выдать уровень {level}, так как ваш уровень {mod_level}"
        
        # Нельзя дать уровень равный своему (кроме разработчика)
        if level == mod_level and moderator_id != DEVELOPER_ID:
            return False, f"❌ Нельзя выдать уровень {level} (равный вашему)"
        
        # Нельзя изменять пользователей с уровнем выше или равным своему
        target_level = get_admin_level(chat_id, user_id)
        if target_level >= mod_level and moderator_id != DEVELOPER_ID:
            return False, f"❌ Нельзя изменять администратора с уровнем {target_level} (ваш уровень {mod_level})"
    
    if user_id in WHITELIST and level == 0:
        return False, "❌ Нельзя удалить из белого списка"
    
    with sqlite3.connect(DB_PATH) as conn:
        if level == 0:
            cursor = conn.execute(
                "DELETE FROM admins WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            conn.commit()
            if cursor.rowcount > 0:
                return True, f"✅ Администратор удален"
            else:
                return False, "❌ Пользователь не является администратором"
        else:
            cursor = conn.execute("""
                INSERT OR REPLACE INTO admins 
                (chat_id, user_id, level, is_frozen, created_at, updated_at) 
                VALUES (?, ?, ?, 
                COALESCE((SELECT is_frozen FROM admins WHERE chat_id=? AND user_id=?), 0),
                COALESCE((SELECT created_at FROM admins WHERE chat_id=? AND user_id=?), CURRENT_TIMESTAMP),
                CURRENT_TIMESTAMP)
            """, (chat_id, user_id, level, chat_id, user_id, chat_id, user_id))
            conn.commit()
            if cursor.rowcount > 0:
                return True, f"✅ Администратор назначен с уровнем {level}"
            else:
                return False, "❌ Ошибка при назначении"

def freeze_admin(chat_id: int, user_id: int, moderator_id: int) -> Tuple[bool, str]:
    """Замораживает админа с проверкой прав"""
    
    if moderator_id == DEVELOPER_ID:
        pass
    else:
        if moderator_id == user_id:
            return False, "❌ Нельзя заморозить себя"
        
        mod_level = get_admin_level(chat_id, moderator_id)
        target_level = get_admin_level(chat_id, user_id)
        
        if target_level >= mod_level:
            return False, f"❌ Нельзя заморозить администратора с уровнем {target_level}"
    
    if user_id in WHITELIST:
        return False, "❌ Нельзя заморозить из белого списка"
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            UPDATE admins SET is_frozen = 1, updated_at = CURRENT_TIMESTAMP 
            WHERE chat_id = ? AND user_id = ?
        """, (chat_id, user_id))
        conn.commit()
        if cursor.rowcount > 0:
            return True, "✅ Администратор заморожен"
        return False, "❌ Пользователь не является администратором"

def unfreeze_admin(chat_id: int, user_id: int, moderator_id: int) -> Tuple[bool, str]:
    """Размораживает админа с проверкой прав"""
    
    if moderator_id == DEVELOPER_ID:
        pass
    else:
        mod_level = get_admin_level(chat_id, moderator_id)
        target_level = get_admin_level(chat_id, user_id)
        
        if target_level >= mod_level:
            return False, f"❌ Нельзя разморозить администратора с уровнем {target_level}"
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            UPDATE admins SET is_frozen = 0, updated_at = CURRENT_TIMESTAMP 
            WHERE chat_id = ? AND user_id = ?
        """, (chat_id, user_id))
        conn.commit()
        if cursor.rowcount > 0:
            return True, "✅ Администратор разморожен"
        return False, "❌ Пользователь не заморожен"

def get_all_admins(chat_id: int) -> List[Tuple[int, int, bool]]:
    """Получает список всех админов чата с информацией о заморозке"""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT user_id, level, is_frozen FROM admins 
            WHERE chat_id = ? ORDER BY level DESC, is_frozen ASC
        """, (chat_id,)).fetchall()

def log_moderation(chat_id: int, action: str, target_id: int, moderator_id: int, reason: str = ""):
    """Логирует действие модерации"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO moderation_logs (chat_id, action, target_user_id, moderator_id, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, action, target_id, moderator_id, reason))
        conn.commit()

# === ФУНКЦИИ ДЛЯ ЭКОНОМИКИ ===

def get_user_points(user_id: int) -> int:
    """Получает количество очков пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT points FROM user_points WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    
    if row:
        return row[0]
    
    # Создаем запись если нет
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO user_points (user_id, points) VALUES (?, 0)",
            (user_id,)
        )
        conn.commit()
    return 0

def update_user_points(user_id: int, points: int):
    """Обновляет количество очков пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO user_points (user_id, points, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (user_id, points))
        conn.commit()

def add_points(user_id: int, amount: int) -> int:
    """Добавляет очки пользователю"""
    current = get_user_points(user_id)
    new_total = current + amount
    update_user_points(user_id, new_total)
    return new_total

def remove_points(user_id: int, amount: int) -> Tuple[bool, int]:
    """Списывает очки пользователя"""
    current = get_user_points(user_id)
    if current < amount:
        return False, current
    new_total = current - amount
    update_user_points(user_id, new_total)
    return True, new_total

# === ФУНКЦИИ ДЛЯ РЕПУТАЦИИ ===

def get_user_rep(user_id: int) -> int:
    """Получает репутацию пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT rep FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    
    if row and row[0] is not None:
        return row[0]
    return 0

def update_user_rep(user_id: int, change: int) -> int:
    """Обновляет репутацию пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        current = get_user_rep(user_id)
        new_rep = current + change
        conn.execute(
            "UPDATE users SET rep = ? WHERE user_id = ?",
            (new_rep, user_id)
        )
        conn.commit()
    return new_rep

def get_rep_top(limit: int = 10) -> List[Tuple[int, int]]:
    """Получает топ по репутации"""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT user_id, rep FROM users 
            WHERE rep > 0 ORDER BY rep DESC LIMIT ?
        """, (limit,)).fetchall()

# === ФУНКЦИИ ДЛЯ ДРУЗЕЙ ===

def add_friend(user_id: int, friend_id: int) -> bool:
    """Добавляет друга"""
    if user_id == friend_id:
        return False
    
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute(
                "INSERT INTO friends (user_id, friend_id) VALUES (?, ?)",
                (user_id, friend_id)
            )
            conn.commit()
            return True
        except:
            return False

def remove_friend(user_id: int, friend_id: int) -> bool:
    """Удаляет друга"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "DELETE FROM friends WHERE user_id = ? AND friend_id = ?",
            (user_id, friend_id)
        )
        conn.commit()
        return cursor.rowcount > 0

def get_friends(user_id: int) -> List[int]:
    """Получает список друзей"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT friend_id FROM friends WHERE user_id = ?",
            (user_id,)
        ).fetchall()
    return [row[0] for row in rows]

# === ФУНКЦИИ ДЛЯ БРАКА ===

def marry_users(user1_id: int, user2_id: int) -> bool:
    """Соединяет пользователей браком"""
    if user1_id == user2_id:
        return False
    
    with sqlite3.connect(DB_PATH) as conn:
        # Проверяем, не женаты ли уже
        u1 = conn.execute(
            "SELECT marry_with FROM users WHERE user_id = ?",
            (user1_id,)
        ).fetchone()
        
        u2 = conn.execute(
            "SELECT marry_with FROM users WHERE user_id = ?",
            (user2_id,)
        ).fetchone()
        
        if (u1 and u1[0]) or (u2 and u2[0]):
            return False
        
        conn.execute(
            "UPDATE users SET marry_with = ? WHERE user_id = ?",
            (user2_id, user1_id)
        )
        conn.execute(
            "UPDATE users SET marry_with = ? WHERE user_id = ?",
            (user1_id, user2_id)
        )
        conn.commit()
    return True

def divorce_user(user_id: int) -> bool:
    """Разводит пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        # Находим супруга
        row = conn.execute(
            "SELECT marry_with FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        
        if not row or not row[0]:
            return False
        
        spouse_id = row[0]
        
        # Разводим обоих
        conn.execute(
            "UPDATE users SET marry_with = NULL WHERE user_id IN (?, ?)",
            (user_id, spouse_id)
        )
        conn.commit()
    return True

# === ФУНКЦИИ ДЛЯ КЛАНОВ ===

def create_clan(name: str, owner_id: int) -> Tuple[bool, str, Optional[int]]:
    """Создает новый клан"""
    with sqlite3.connect(DB_PATH) as conn:
        # Проверяем, не состоит ли уже в клане
        user = conn.execute(
            "SELECT clan_id FROM users WHERE user_id = ?",
            (owner_id,)
        ).fetchone()
        
        if user and user[0]:
            return False, "❌ Вы уже состоите в клане", None
        
        # Проверяем, существует ли клан с таким именем
        existing = conn.execute(
            "SELECT clan_id FROM clans WHERE name = ?",
            (name,)
        ).fetchone()
        
        if existing:
            return False, "❌ Клан с таким названием уже существует", None
        
        # Создаем клан
        cursor = conn.execute("""
            INSERT INTO clans (name, owner_id, points)
            VALUES (?, ?, 0)
        """, (name, owner_id))
        
        clan_id = cursor.lastrowid
        
        # Обновляем пользователя
        conn.execute(
            "UPDATE users SET clan_id = ? WHERE user_id = ?",
            (clan_id, owner_id)
        )
        conn.commit()
        
        return True, f"✅ Клан '{name}' создан!", clan_id

def join_clan(user_id: int, clan_name: str) -> Tuple[bool, str]:
    """Вступает в клан"""
    with sqlite3.connect(DB_PATH) as conn:
        # Проверяем пользователя
        user = conn.execute(
            "SELECT clan_id FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        
        if user and user[0]:
            return False, "❌ Вы уже состоите в клане"
        
        # Ищем клан
        clan = conn.execute(
            "SELECT clan_id FROM clans WHERE name = ?",
            (clan_name,)
        ).fetchone()
        
        if not clan:
            return False, "❌ Клан не найден"
        
        clan_id = clan[0]
        
        # Вступаем
        conn.execute(
            "UPDATE users SET clan_id = ? WHERE user_id = ?",
            (clan_id, user_id)
        )
        
        # Обновляем счетчик
        conn.execute("""
            UPDATE clans SET members_count = members_count + 1 
            WHERE clan_id = ?
        """, (clan_id,))
        
        conn.commit()
        
        return True, f"✅ Вы вступили в клан '{clan_name}'"

def leave_clan(user_id: int) -> Tuple[bool, str]:
    """Покидает клан"""
    with sqlite3.connect(DB_PATH) as conn:
        # Получаем информацию о клане
        user = conn.execute(
            "SELECT clan_id FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        
        if not user or not user[0]:
            return False, "❌ Вы не состоите в клане"
        
        clan_id = user[0]
        
        # Проверяем, не владелец ли
        clan = conn.execute(
            "SELECT owner_id FROM clans WHERE clan_id = ?",
            (clan_id,)
        ).fetchone()
        
        if clan and clan[0] == user_id:
            return False, "❌ Владелец не может покинуть клан. Передайте права или распустите клан"
        
        # Покидаем клан
        conn.execute(
            "UPDATE users SET clan_id = NULL WHERE user_id = ?",
            (user_id,)
        )
        
        # Обновляем счетчик
        conn.execute("""
            UPDATE clans SET members_count = members_count - 1 
            WHERE clan_id = ?
        """, (clan_id,))
        
        conn.commit()
        
        return True, "✅ Вы покинули клан"

def get_clan_info(clan_id: int) -> Optional[Dict]:
    """Получает информацию о клане"""
    with sqlite3.connect(DB_PATH) as conn:
        clan = conn.execute("""
            SELECT clan_id, name, owner_id, created_at, points, members_count
            FROM clans WHERE clan_id = ?
        """, (clan_id,)).fetchone()
        
        if not clan:
            return None
        
        # Получаем участников
        members = conn.execute("""
            SELECT user_id, username, first_name FROM users 
            WHERE clan_id = ? ORDER BY rep DESC LIMIT 10
        """, (clan_id,)).fetchall()
        
        return {
            "id": clan[0],
            "name": clan[1],
            "owner_id": clan[2],
            "created_at": clan[3],
            "points": clan[4],
            "members_count": clan[5],
            "members": members
        }

def get_clan_top(limit: int = 10) -> List[Tuple]:
    """Получает топ кланов"""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT name, points, members_count FROM clans 
            ORDER BY points DESC LIMIT ?
        """, (limit,)).fetchall()

# === ФУНКЦИИ ДЛЯ ДОСТИЖЕНИЙ ===

ACHIEVEMENTS = {
    "first_message": {"name": "👋 Первый шаг", "desc": "Отправить первое сообщение", "points": 5},
    "rep_10": {"name": "⭐ Популярный", "desc": "Достичь репутации 10", "points": 10},
    "rep_50": {"name": "🌟🌟 Известный", "desc": "Достичь репутации 50", "points": 25},
    "rep_100": {"name": "👑 Легенда", "desc": "Достичь репутации 100", "points": 50},
    "points_100": {"name": "💰 Богач", "desc": "Накопить 100 очков", "points": 10},
    "points_500": {"name": "💎 Магнат", "desc": "Накопить 500 очков", "points": 25},
    "points_1000": {"name": "🦍 Миллиардер", "desc": "Накопить 1000 очков", "points": 50},
    "friends_5": {"name": "🤝 Дружелюбный", "desc": "Завести 5 друзей", "points": 15},
    "friends_10": {"name": "👥 Душа компании", "desc": "Завести 10 друзей", "points": 30},
    "marry": {"name": "💍 Женат/Замужем", "desc": "Вступить в брак", "points": 20},
    "clan": {"name": "⚔️ Клановый", "desc": "Вступить в клан", "points": 15},
    "create_clan": {"name": "👑 Лидер", "desc": "Создать клан", "points": 30},
    "dick_10": {"name": "📏 Среднячок", "desc": "Достичь 10 см", "points": 5},
    "dick_20": {"name": "🍆 Гигант", "desc": "Достичь 20 см", "points": 15},
}

def add_achievement(user_id: int, ach_id: str) -> bool:
    """Добавляет достижение пользователю"""
    if ach_id not in ACHIEVEMENTS:
        return False
    
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute("""
                INSERT INTO achievements (user_id, ach_id)
                VALUES (?, ?)
            """, (user_id, ach_id))
            conn.commit()
            
            # Начисляем бонусные очки
            bonus = ACHIEVEMENTS[ach_id]["points"]
            add_points(user_id, bonus)
            
            return True
        except:
            return False

def get_user_achievements(user_id: int) -> List[str]:
    """Получает список достижений пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT ach_id FROM achievements WHERE user_id = ?
        """, (user_id,)).fetchall()
    return [row[0] for row in rows]

def check_achievements(user_id: int) -> List[str]:
    """Проверяет и начисляет достижения"""
    user = get_user_by_id(user_id)
    if not user:
        return []
    
    user_achs = set(get_user_achievements(user_id))
    new_achs = []
    
    # Проверяем репутацию
    rep = user["rep"]
    if rep >= 100 and "rep_100" not in user_achs:
        if add_achievement(user_id, "rep_100"):
            new_achs.append("rep_100")
    elif rep >= 50 and "rep_50" not in user_achs:
        if add_achievement(user_id, "rep_50"):
            new_achs.append("rep_50")
    elif rep >= 10 and "rep_10" not in user_achs:
        if add_achievement(user_id, "rep_10"):
            new_achs.append("rep_10")
    
    # Проверяем очки
    points = get_user_points(user_id)
    if points >= 1000 and "points_1000" not in user_achs:
        if add_achievement(user_id, "points_1000"):
            new_achs.append("points_1000")
    elif points >= 500 and "points_500" not in user_achs:
        if add_achievement(user_id, "points_500"):
            new_achs.append("points_500")
    elif points >= 100 and "points_100" not in user_achs:
        if add_achievement(user_id, "points_100"):
            new_achs.append("points_100")
    
    # Проверяем брак
    if user["marry_with"] and "marry" not in user_achs:
        if add_achievement(user_id, "marry"):
            new_achs.append("marry")
    
    # Проверяем клан
    if user["clan_id"]:
        if "clan" not in user_achs:
            if add_achievement(user_id, "clan"):
                new_achs.append("clan")
        
        # Проверяем, владелец ли
        with sqlite3.connect(DB_PATH) as conn:
            clan = conn.execute(
                "SELECT owner_id FROM clans WHERE clan_id = ?",
                (user["clan_id"],)
            ).fetchone()
            if clan and clan[0] == user_id and "create_clan" not in user_achs:
                if add_achievement(user_id, "create_clan"):
                    new_achs.append("create_clan")
    
    # Проверяем друзей
    friends = get_friends(user_id)
    if len(friends) >= 10 and "friends_10" not in user_achs:
        if add_achievement(user_id, "friends_10"):
            new_achs.append("friends_10")
    elif len(friends) >= 5 and "friends_5" not in user_achs:
        if add_achievement(user_id, "friends_5"):
            new_achs.append("friends_5")
    
    return new_achs

# === ФУНКЦИИ ДЛЯ ПРЕДУПРЕЖДЕНИЙ ===

def add_warn(chat_id: int, user_id: int, moderator_id: int, reason: str = "") -> int:
    """Добавляет предупреждение пользователю"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO user_warns (chat_id, user_id, moderator_id, reason)
            VALUES (?, ?, ?, ?)
        """, (chat_id, user_id, moderator_id, reason))
        conn.commit()
    
    return get_warn_count(chat_id, user_id)

def get_warn_count(chat_id: int, user_id: int) -> int:
    """Получает количество предупреждений пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT COUNT(*) FROM user_warns 
            WHERE chat_id = ? AND user_id = ?
        """, (chat_id, user_id)).fetchone()
    
    return row[0] if row else 0

def get_user_warns(chat_id: int, user_id: int) -> List[Dict]:
    """Получает список предупреждений пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT id, moderator_id, reason, timestamp FROM user_warns 
            WHERE chat_id = ? AND user_id = ?
            ORDER BY timestamp DESC
        """, (chat_id, user_id)).fetchall()
    
    warns = []
    for row in rows:
        warns.append({
            "id": row[0],
            "moderator_id": row[1],
            "reason": row[2] or "",
            "timestamp": row[3]
        })
    
    return warns

def clear_warns(chat_id: int, user_id: int):
    """Очищает все предупреждения пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            DELETE FROM user_warns WHERE chat_id = ? AND user_id = ?
        """, (chat_id, user_id))
        conn.commit()

# === ФУНКЦИИ ДЛЯ ИГРЫ В ПИСЬКУ ===

def get_penis_size(chat_id: int, user_id: int) -> Tuple[int, Optional[str]]:
    """Получает размер письки и дату последней игры"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT size, last_played FROM penis_sizes WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        ).fetchone()
    
    if row:
        return row[0], row[1]
    return 0, None

def update_penis_size(chat_id: int, user_id: int, size: int, last_played: str):
    """Обновляет размер письки"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO penis_sizes (chat_id, user_id, size, last_played)
            VALUES (?, ?, ?, ?)
        """, (chat_id, user_id, size, last_played))
        conn.commit()

def get_penis_top(chat_id: int) -> List[Tuple[int, int]]:
    """Получает топ-10 размеров в чате"""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT user_id, size FROM penis_sizes 
            WHERE chat_id = ? ORDER BY size DESC LIMIT 10
        """, (chat_id,)).fetchall()

def get_penis_position(chat_id: int, user_id: int) -> int:
    """Получает позицию пользователя в топе"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT user_id FROM penis_sizes 
            WHERE chat_id = ? ORDER BY size DESC
        """, (chat_id,)).fetchall()
    
    for i, (uid,) in enumerate(rows, 1):
        if uid == user_id:
            return i
    return len(rows) + 1

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def parse_duration(duration: str) -> Optional[int]:
    """Парсит длительность (10m, 2h, 1d) в секунды"""
    if not duration:
        return None
    
    duration = duration.lower().strip()
    
    if duration.endswith('m'):
        try:
            minutes = int(duration[:-1])
            if 1 <= minutes <= 43200:
                return minutes * 60
        except:
            pass
    
    elif duration.endswith('h'):
        try:
            hours = int(duration[:-1])
            if 1 <= hours <= 720:
                return hours * 3600
        except:
            pass
    
    elif duration.endswith('d'):
        try:
            days = int(duration[:-1])
            if 1 <= days <= 365:
                return days * 86400
        except:
            pass
    
    return None

def check_admin_access(update: Update, required_level: int, chat_id: int) -> Tuple[bool, str]:
    """Проверяет права администратора"""
    user_id = update.effective_user.id
    
    # Разработчик имеет полный доступ
    if user_id == DEVELOPER_ID:
        return True, "ok"
    
    # Проверяем белый список
    if user_id in WHITELIST:
        return True, "ok"
    
    # Проверяем заморозку
    if is_admin_frozen(chat_id, user_id):
        return False, "❌ Ваши права заморожены"
    
    # Проверяем уровень
    level = get_admin_level(chat_id, user_id)
    if level >= required_level:
        return True, "ok"
    
    return False, f"❌ Требуется уровень {required_level}+"

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]) -> Tuple[Optional[int], Optional[str]]:
    """
    Получает цель для наказания:
    1. Ответ на сообщение
    2. ID пользователя
    3. Username
    """
    message = update.message
    
    # 1. Ответ на сообщение
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        if user.is_bot:
            await message.reply_text("❌ Нельзя наказать бота")
            return None, None
        
        if user.id in WHITELIST:
            await message.reply_text("❌ Нельзя наказать этого пользователя")
            return None, None
        
        save_user(user)
        display_name = user.username or user.first_name or str(user.id)
        return user.id, display_name
    
    # 2. Нет аргументов
    if not args:
        return None, None
    
    # 3. ID
    if args[0].isdigit():
        user_id = int(args[0])
        
        if user_id in WHITELIST:
            await message.reply_text("❌ Нельзя наказать этого пользователя")
            return None, None
        
        user_data = get_user_by_id(user_id)
        if user_data:
            display_name = user_data['username'] or user_data['first_name'] or str(user_id)
        else:
            display_name = str(user_id)
        
        return user_id, display_name
    
    # 4. Username
    username = args[0].lstrip('@')
    user_data = get_user_by_username(username)
    
    if user_data:
        if user_data['user_id'] in WHITELIST:
            await message.reply_text("❌ Нельзя наказать этого пользователя")
            return None, None
        return user_data['user_id'], user_data['username'] or user_data['first_name'] or username
    
    await message.reply_text(f"❌ Пользователь @{username} не найден в базе")
    return None, None

async def scan_chat_members(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Сканирует всех участников чата"""
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        for admin in admins:
            save_user(admin.user)
        
        logger.info(f"📋 Чат {chat_id}: сохранено {len(admins)} администраторов")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сканирования чата {chat_id}: {e}")

# === ОБРАБОТЧИК СООБЩЕНИЙ ===

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все сообщения"""
    if update.effective_user and not update.effective_user.is_bot:
        save_user(update.effective_user)
    
    if not update.message or not update.message.text or update.message.text.startswith('/'):
        return
    
    await check_flood(update, context)
    await check_bad_words(update, context)

# === АНТИФЛУД ===

async def check_flood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет на флуд"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if get_admin_level(chat_id, user_id) >= 1 or user_id in WHITELIST:
        return
    
    current_time = time.time()
    message_text = update.message.text.lower().strip()
    
    key = f"{chat_id}:{user_id}"
    user_message_history[key].append({
        'text': message_text,
        'time': current_time
    })
    
    recent = [msg for msg in user_message_history[key] 
              if current_time - msg['time'] <= FLUD_WINDOW_SEC]
    
    if len(recent) < FLUD_MESSAGE_COUNT:
        return
    
    texts = [msg['text'] for msg in recent[-FLUD_MESSAGE_COUNT:]]
    similar = 0
    
    for i in range(len(texts) - 1):
        if SequenceMatcher(None, texts[i], texts[i+1]).ratio() >= SIMILARITY_THRESHOLD:
            similar += 1
    
    if similar >= 2:
        until = int(time.time() + (FLOOD_MUTE_MINUTES * 60))
        
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_other_messages=False,
            can_send_polls=False,
            can_add_web_page_previews=False
        )
        
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                until_date=until
            )
            
            await update.message.reply_text(
                f"🔇 Пользователь замучен на {FLOOD_MUTE_MINUTES} минут за флуд"
            )
            
            user_message_history[key].clear()
            log_moderation(chat_id, "flood_mute", user_id, context.bot.id, "Автоматически за флуд")
            
        except Exception as e:
            logger.error(f"Ошибка при муте за флуд: {e}")

# === АНТИМАТ ===

async def check_bad_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет на мат"""
    if not os.path.exists(BAD_WORDS_FILE):
        # Создаем файл с примерами
        default_words = ["дебил", "тупой", "идиот", "дурак", "лох", "сволочь", "гад"]
        with open(BAD_WORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_words, f, ensure_ascii=False, indent=2)
    
    try:
        with open(BAD_WORDS_FILE, 'r', encoding='utf-8') as f:
            bad_words = json.load(f)
    except:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if get_admin_level(chat_id, user_id) >= 1 or user_id in WHITELIST:
        return
    
    text = update.message.text.lower()
    
    for word in bad_words:
        if word.lower() in text:
            until = int(time.time() + (BAD_WORDS_MUTE_MINUTES * 60))
            
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_other_messages=False,
                can_send_polls=False,
                can_add_web_page_previews=False
            )
            
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=permissions,
                    until_date=until
                )
                
                await update.message.reply_text(
                    f"🔇 Пользователь замучен на {BAD_WORDS_MUTE_MINUTES} минут за использование запрещенных слов"
                )
                
                try:
                    await update.message.delete()
                except:
                    pass
                    
                log_moderation(chat_id, "bad_words_mute", user_id, context.bot.id, "Автоматически за мат")
                
            except Exception as e:
                logger.error(f"Ошибка при муте за мат: {e}")
            
            break

# === КОМАНДЫ МОДЕРАЦИИ ===

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mute - замутить пользователя"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 2, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /mute 10m причина\n"
            "• /mute @username 10m причина\n"
            "• /mute 123456789 10m причина"
        )
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Укажите время и причину\n"
            "Пример: /mute @user 10m Спам"
        )
        return
    
    duration_sec = parse_duration(args[1])
    if not duration_sec:
        await update.message.reply_text("❌ Неверный формат времени. Пример: 10m, 2h, 1d")
        return
    
    reason = " ".join(args[2:]) if len(args) > 2 else "не указана"
    until = int(time.time() + duration_sec)
    
    permissions = ChatPermissions(
        can_send_messages=False,
        can_send_other_messages=False,
        can_send_polls=False,
        can_add_web_page_previews=False
    )
    
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            permissions=permissions,
            until_date=until
        )
        
        end_time = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        
        await update.message.reply_text(
            f"🔇 {display_name} замучен\n"
            f"⏱ Длительность: {args[1]}\n"
            f"📅 До: {end_time}\n"
            f"📝 Причина: {reason}"
        )
        
        log_moderation(chat_id, "mute", target_id, update.effective_user.id, reason)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unmute - размутить пользователя"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 2, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /unmute\n"
            "• /unmute @username\n"
            "• /unmute 123456789"
        )
        return
    
    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_other_messages=True,
        can_send_polls=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False
    )
    
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            permissions=permissions
        )
        
        await update.message.reply_text(f"✅ {display_name} размучен")
        log_moderation(chat_id, "unmute", target_id, update.effective_user.id, "")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ban - забанить пользователя"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 3, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /ban 1h причина\n"
            "• /ban @username 1h причина\n"
            "• /ban 123456789 1h причина"
        )
        return
    
    args = context.args
    
    if len(args) >= 2 and parse_duration(args[1]):
        duration_sec = parse_duration(args[1])
        until = int(time.time() + duration_sec)
        reason = " ".join(args[2:]) if len(args) > 2 else "не указана"
        
        try:
            await context.bot.ban_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                until_date=until
            )
            
            end_time = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
            
            await update.message.reply_text(
                f"🚫 {display_name} забанен\n"
                f"⏱ Длительность: {args[1]}\n"
                f"📅 До: {end_time}\n"
                f"📝 Причина: {reason}"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    else:
        reason = " ".join(args[1:]) if len(args) > 1 else "не указана"
        
        try:
            await context.bot.ban_chat_member(
                chat_id=chat_id,
                user_id=target_id
            )
            
            await update.message.reply_text(
                f"🚫 {display_name} забанен навсегда\n"
                f"📝 Причина: {reason}"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    log_moderation(chat_id, "ban", target_id, update.effective_user.id, reason)

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unban - разбанить пользователя"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 3, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /unban\n"
            "• /unban @username\n"
            "• /unban 123456789"
        )
        return
    
    try:
        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            only_if_banned=True
        )
        
        await update.message.reply_text(f"✅ {display_name} разбанен")
        log_moderation(chat_id, "unban", target_id, update.effective_user.id, "")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kick - выгнать пользователя"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 2, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /kick причина\n"
            "• /kick @username причина\n"
            "• /kick 123456789 причина"
        )
        return
    
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "не указана"
    
    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=target_id)
        
        await update.message.reply_text(
            f"👋 {display_name} выгнан из чата\n"
            f"📝 Причина: {reason}"
        )
        
        log_moderation(chat_id, "kick", target_id, update.effective_user.id, reason)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def setadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setadmin - назначить/снять админа"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 4, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /setadmin 4 причина\n"
            "• /setadmin @username 4 причина"
        )
        return
    
    args = context.args
    if len(args) < 2 or not args[1].isdigit():
        await update.message.reply_text(
            "❌ Укажите уровень (0-5)\n"
            "0 - снять админку\n"
            "1-5 - назначить с уровнем"
        )
        return
    
    level = int(args[1])
    reason = " ".join(args[2:]) if len(args) > 2 else "не указана"
    
    if level < 0 or level > 5:
        await update.message.reply_text("❌ Уровень должен быть от 0 до 5")
        return
    
    if target_id == DEVELOPER_ID:
        await update.message.reply_text("❌ Нельзя изменить права разработчика")
        return
    
    success, message = set_admin_level(chat_id, target_id, level, update.effective_user.id)
    
    if success:
        if level == 0:
            await update.message.reply_text(
                f"📋 {display_name} снят с должности администратора\n"
                f"📝 Причина: {reason}"
            )
            log_moderation(chat_id, "remove_admin", target_id, update.effective_user.id, reason)
        else:
            level_names = {
                1: "Кандидат",
                2: "Младший модератор",
                3: "Старший модератор",
                4: "Зам. руководителя",
                5: "Руководитель"
            }
            level_name = level_names.get(level, f"Уровень {level}")
            
            await update.message.reply_text(
                f"🛡 {display_name} назначен администратором\n"
                f"📊 Уровень: {level_name} ({level})\n"
                f"📝 Причина: {reason}"
            )
            log_moderation(chat_id, "set_admin", target_id, update.effective_user.id, f"level={level}, {reason}")
    else:
        await update.message.reply_text(message)

async def freeze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/freeze - заморозить админа"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 4, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /freeze причина\n"
            "• /freeze @username причина"
        )
        return
    
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "не указана"
    
    success, message = freeze_admin(chat_id, target_id, update.effective_user.id)
    
    if success:
        await update.message.reply_text(
            f"❄️ {display_name} заморожен\n"
            f"📝 Причина: {reason}"
        )
        log_moderation(chat_id, "freeze", target_id, update.effective_user.id, reason)
    else:
        await update.message.reply_text(message)

async def unfreeze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unfreeze - разморозить админа"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 4, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /unfreeze\n"
            "• /unfreeze @username"
        )
        return
    
    success, message = unfreeze_admin(chat_id, target_id, update.effective_user.id)
    
    if success:
        await update.message.reply_text(f"🔥 {display_name} разморожен")
        log_moderation(chat_id, "unfreeze", target_id, update.effective_user.id, "")
    else:
        await update.message.reply_text(message)

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/warn - выдать предупреждение"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 1, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /warn причина\n"
            "• /warn @username причина"
        )
        return
    
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "не указана"
    
    warn_count = add_warn(chat_id, target_id, update.effective_user.id, reason)
    
    await update.message.reply_text(
        f"⚠️ {display_name} получил предупреждение\n"
        f"📝 Причина: {reason}\n"
        f"📊 Всего предупреждений: {warn_count}"
    )
    
    log_moderation(chat_id, "warn", target_id, update.effective_user.id, reason)
    
    # Автоматический мут при 3 предупреждениях
    if warn_count >= 3:
        until = int(time.time() + 3600)  # 1 час
        
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_other_messages=False,
            can_send_polls=False,
            can_add_web_page_previews=False
        )
        
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=permissions,
                until_date=until
            )
            
            await update.message.reply_text(
                f"🔇 {display_name} замучен на 1 час (3/3 предупреждений)"
            )
            
            clear_warns(chat_id, target_id)
            log_moderation(chat_id, "auto_mute", target_id, context.bot.id, "3 предупреждения")
            
        except Exception as e:
            logger.error(f"Ошибка при автоматическом муте: {e}")

async def warns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/warns - показать предупреждения"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 1, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /warns\n"
            "• /warns @username"
        )
        return
    
    warns = get_user_warns(chat_id, target_id)
    
    if not warns:
        await update.message.reply_text(f"✅ У {display_name} нет предупреждений")
        return
    
    text = f"⚠️ Предупреждения {display_name}:\n\n"
    for i, warn in enumerate(warns, 1):
        mod = get_user_by_id(warn["moderator_id"])
        mod_name = mod["username"] or mod["first_name"] if mod else "Неизвестно"
        time_str = warn["timestamp"][:16] if warn["timestamp"] else "Неизвестно"
        text += f"{i}. {warn['reason']}\n"
        text += f"   От: {mod_name}, {time_str}\n"
    
    await update.message.reply_text(text)

async def clearwarns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/clearwarns - очистить предупреждения"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 3, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /clearwarns\n"
            "• /clearwarns @username"
        )
        return
    
    clear_warns(chat_id, target_id)
    await update.message.reply_text(f"✅ Предупреждения {display_name} очищены")
    log_moderation(chat_id, "clear_warns", target_id, update.effective_user.id, "")

# === НОВЫЕ РАЗВЛЕКАТЕЛЬНЫЕ КОМАНДЫ ===

async def love_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/love - узнать совместимость с пользователем"""
    target_id, display_name = await get_target_user(update, context, context.args)
    
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /love\n"
            "• /love @username"
        )
        return
    
    user1 = update.effective_user
    user2_id = target_id
    
    if user1.id == user2_id:
        await update.message.reply_text("❌ Нельзя проверить совместимость с самим собой")
        return
    
    # Генерируем "совместимость" на основе ID
    seed = user1.id + user2_id
    random.seed(seed)
    compatibility = random.randint(0, 100)
    random.seed()
    
    hearts = "❤️" * (compatibility // 10) + "🖤" * (10 - compatibility // 10)
    
    user2 = get_user_by_id(user2_id)
    name2 = user2["username"] or user2["first_name"] if user2 else display_name
    
    await update.message.reply_text(
        f"💘 Совместимость {user1.first_name} и {name2}\n\n"
        f"{hearts}\n"
        f"Результат: {compatibility}%\n"
        f"{'Идеальная пара! 💑' if compatibility > 80 else 'Неплохо! 💕' if compatibility > 50 else 'Может быть друзьями? 💔'}"
    )

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/coin - подбросить монетку"""
    result = random.choice(["Орёл", "Решка"])
    await update.message.reply_text(f"🪙 Монетка показывает: {result}!")

async def cube_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cube - бросить кубик"""
    result = random.randint(1, 6)
    dice = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][result-1]
    await update.message.reply_text(f"🎲 {dice} {result}")

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dice - бросить два кубика"""
    d1 = random.randint(1, 6)
    d2 = random.randint(1, 6)
    total = d1 + d2
    await update.message.reply_text(f"🎲 {d1} + {d2} = {total}")

async def rps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rps - камень-ножницы-бумага"""
    choices = ["камень", "ножницы", "бумага"]
    
    if context.args and context.args[0].lower() in choices:
        user_choice = context.args[0].lower()
    else:
        await update.message.reply_text(
            "❌ Выберите: камень, ножницы или бумага\n"
            "Пример: /rps камень"
        )
        return
    
    bot_choice = random.choice(choices)
    
    # Определяем победителя
    if user_choice == bot_choice:
        result = "Ничья! 🤝"
    elif (
        (user_choice == "камень" and bot_choice == "ножницы") or
        (user_choice == "ножницы" and bot_choice == "бумага") or
        (user_choice == "бумага" and bot_choice == "камень")
    ):
        result = "Ты выиграл! 🎉"
        points = add_points(update.effective_user.id, 5)
        result += f"\n💰 +5 очков! Баланс: {points}"
    else:
        result = "Я выиграл! 🤖"
    
    await update.message.reply_text(
        f"Ты выбрал: {user_choice}\n"
        f"Я выбрал: {bot_choice}\n\n"
        f"{result}"
    )

async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/quote - случайная цитата"""
    quotes = [
        "Жизнь - это то, что с тобой происходит, пока ты строишь планы. — Джон Леннон",
        "Будь тем изменением, которое хочешь увидеть в мире. — Махатма Ганди",
        "Счастье не в том, чтобы делать всегда, что хочешь, а в том, чтобы всегда хотеть того, что делаешь. — Лев Толстой",
        "Единственный способ сделать великую работу - любить то, что ты делаешь. — Стив Джобс",
        "Всё, что нас не убивает, делает нас сильнее. — Фридрих Ницше",
        "Живи так, как будто умрёшь завтра. Учись так, как будто будешь жить вечно. — Махатма Ганди",
        "Самая важная вещь в жизни - это сама жизнь. — Теодор Драйзер",
        "Сложнее всего начать действовать, все остальное зависит только от упорства. — Амелия Эрхарт",
        "Успех - это способность идти от неудачи к неудаче, не теряя энтузиазма. — Уинстон Черчилль",
        "Неважно, как медленно ты идешь, пока ты не останавливаешься. — Конфуций"
    ]
    
    await update.message.reply_text(f"💭 {random.choice(quotes)}")

async def anecdote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/anecdote - случайный анекдот"""
    anecdotes = [
        "Встречаются два программиста:\n- Знаешь, я вчера полдня мучился, никак не мог понять, почему программа не работает.\n- А потом?\n- А потом оказалось, что я просто забыл компьютер включить.",
        
        "Приходит мужик к врачу:\n- Доктор, у меня галлюцинации!\n- А с чего вы взяли?\n- Как с чего? Я же постоянно вижу розовых слонов!\n- А вы пробовали не пить?\n- А при чем тут пить? Я их уже третий день вижу!\n- ???\n- Я же программист, у меня дедлайн горит!",
        
        "Сидят два кота на крыше. Один говорит:\n- Мяу.\nВторой:\n- Гав.\nПервый:\n- Ты чего, с ума сошел? Ты же кот!\nВторой:\n- А я учу иностранные языки.",
        
        "Приходит Штирлиц к Мюллеру и видит - тот сидит и плачет.\n- Что случилось, Мюллер?\n- Да понимаешь, Штирлиц, дочка у меня не разговаривает.\n- А сколько ей?\n- Два года.\n- Так она же еще маленькая!\n- В том-то и дело, что маленькая, а уже молчит как партизан!",
        
        "Учительница спрашивает Вовочку:\n- Вовочка, почему ты опоздал в школу?\n- Я видел сон, что путешествую по разным странам, а потом захотел вернуться домой, но никак не мог найти Россию на карте.\n- И что же ты сделал?\n- Проснулся!"
    ]
    
    await update.message.reply_text(f"😄 {random.choice(anecdotes)}")

async def fact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/fact - случайный факт"""
    facts = [
        "🐝 Пчелы могут узнавать человеческие лица.",
        "🦒 У жирафа такое же количество шейных позвонков, как и у человека - 7.",
        "🐙 У осьминога три сердца.",
        "🦋 Бабочки чувствуют вкус своими лапками.",
        "🐧 Императорские пингвины могут нырять на глубину до 500 метров.",
        "🐫 Верблюды не хранят воду в горбах, там находится жир.",
        "🦉 Совы не могут вращать глазами, зато могут повернуть голову на 270 градусов.",
        "🐶 Собаки понимают до 250 слов и жестов.",
        "🐱 Кошки проводят 70% своей жизни во сне.",
        "🦔 Ежики рождаются слепыми и с мягкими иголками, которые твердеют через несколько часов."
    ]
    
    await update.message.reply_text(f"ℹ️ {random.choice(facts)}")

# === КОМАНДЫ ДЛЯ СОЦИАЛЬНЫХ ВЗАИМОДЕЙСТВИЙ ===

async def rep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rep - повысить репутацию"""
    user_id = update.effective_user.id
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /rep\n"
            "• /rep @username"
        )
        return
    
    if user_id == target_id:
        await update.message.reply_text("❌ Нельзя повысить репутацию себе")
        return
    
    # Проверяем, не ставил ли уже сегодня
    today = datetime.now().strftime("%Y%m%d")
    key = f"{user_id}:{today}"
    
    if key in daily_rep:
        await update.message.reply_text("❌ Сегодня вы уже ставили репутацию")
        return
    
    # Повышаем репутацию
    new_rep = update_user_rep(target_id, 1)
    daily_rep.add(key)
    
    # Проверяем достижения
    new_achs = check_achievements(target_id)
    
    await update.message.reply_text(
        f"👍 Репутация {display_name} повышена!\n"
        f"📊 Теперь у него {new_rep} очков репутации"
    )

async def unrep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unrep - понизить репутацию"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 3, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /unrep\n"
            "• /unrep @username"
        )
        return
    
    # Понижаем репутацию
    new_rep = update_user_rep(target_id, -1)
    
    await update.message.reply_text(
        f"👎 Репутация {display_name} понижена!\n"
        f"📊 Теперь у него {new_rep} очков репутации"
    )

async def repstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/repstats - топ репутации"""
    top = get_rep_top(10)
    
    if not top:
        await update.message.reply_text("📊 Пока нет пользователей с репутацией")
        return
    
    text = "🏆 Топ пользователей по репутации:\n\n"
    
    for i, (user_id, rep) in enumerate(top, 1):
        user = get_user_by_id(user_id)
        name = user["username"] or user["first_name"] if user else f"ID {user_id}"
        text += f"{i}. {name} — {rep} ⭐\n"
    
    await update.message.reply_text(text)

async def friend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/friend - добавить в друзья"""
    user_id = update.effective_user.id
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /friend\n"
            "• /friend @username"
        )
        return
    
    if user_id == target_id:
        await update.message.reply_text("❌ Нельзя добавить в друзья себя")
        return
    
    if add_friend(user_id, target_id):
        friends = get_friends(user_id)
        await update.message.reply_text(
            f"✅ {display_name} добавлен в друзья!\n"
            f"👥 Теперь у вас {len(friends)} друзей"
        )
        
        # Проверяем достижения
        check_achievements(user_id)
    else:
        await update.message.reply_text("❌ Этот пользователь уже у вас в друзьях")

async def unfriend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unfriend - удалить из друзей"""
    user_id = update.effective_user.id
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /unfriend\n"
            "• /unfriend @username"
        )
        return
    
    if remove_friend(user_id, target_id):
        await update.message.reply_text(f"✅ {display_name} удален из друзей")
    else:
        await update.message.reply_text("❌ Этот пользователь не у вас в друзьях")

async def friends_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/friends - список друзей"""
    user_id = update.effective_user.id
    
    friends_ids = get_friends(user_id)
    
    if not friends_ids:
        await update.message.reply_text("👥 У вас пока нет друзей")
        return
    
    text = "👥 Ваши друзья:\n\n"
    
    for i, friend_id in enumerate(friends_ids[:10], 1):
        friend = get_user_by_id(friend_id)
        if friend:
            name = friend["username"] or friend["first_name"] or f"ID {friend_id}"
            text += f"{i}. {name}\n"
    
    if len(friends_ids) > 10:
        text += f"\n...и еще {len(friends_ids) - 10}"
    
    await update.message.reply_text(text)

async def marry_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/marry - предложить брак"""
    user_id = update.effective_user.id
    
    target_id, display_name = await get_target_user(update, context, context.args)
    if not target_id:
        await update.message.reply_text(
            "❌ Укажите пользователя:\n"
            "• Ответ на сообщение + /marry\n"
            "• /marry @username"
        )
        return
    
    if user_id == target_id:
        await update.message.reply_text("❌ Нельзя жениться на себе")
        return
    
    # Проверяем, не женаты ли уже
    user = get_user_by_id(user_id)
    if user and user["marry_with"]:
        await update.message.reply_text("❌ Вы уже состоите в браке")
        return
    
    target = get_user_by_id(target_id)
    if target and target["marry_with"]:
        await update.message.reply_text("❌ Этот пользователь уже состоит в браке")
        return
    
    # Создаем предложение
    proposal_id = f"{user_id}:{target_id}"
    marriage_proposals[proposal_id] = {
        "from": user_id,
        "to": target_id,
        "time": time.time()
    }
    
    # Создаем клавиатуру
    keyboard = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"marry_accept_{user_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"marry_decline_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"💍 {display_name}, {update.effective_user.first_name} предлагает вам руку и сердце!\n"
        f"У вас есть 5 минут, чтобы ответить.",
        reply_markup=reply_markup
    )

async def divorce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/divorce - развестись"""
    user_id = update.effective_user.id
    
    if divorce_user(user_id):
        await update.message.reply_text("💔 Вы развелись. Брак расторгнут.")
    else:
        await update.message.reply_text("❌ Вы не состоите в браке")

async def clan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/clan - управление кланом"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📚 Команды клана:\n\n"
            "/clan create Название - создать клан (200 очков)\n"
            "/clan join Название - вступить в клан\n"
            "/clan leave - покинуть клан\n"
            "/clan info - информация о клане\n"
            "/clan top - топ кланов"
        )
        return
    
    cmd = context.args[0].lower()
    
    if cmd == "create":
        if len(context.args) < 2:
            await update.message.reply_text("❌ Укажите название клана: /clan create Название")
            return
        
        # Проверяем очки
        success, result = remove_points(user_id, 200)
        if not success:
            await update.message.reply_text(f"❌ Недостаточно очков. Нужно 200, у вас {result}")
            return
        
        name = " ".join(context.args[1:])
        success, message, clan_id = create_clan(name, user_id)
        
        if success:
            await update.message.reply_text(message)
            # Проверяем достижения
            check_achievements(user_id)
        else:
            # Возвращаем очки
            add_points(user_id, 200)
            await update.message.reply_text(message)
    
    elif cmd == "join":
        if len(context.args) < 2:
            await update.message.reply_text("❌ Укажите название клана: /clan join Название")
            return
        
        name = " ".join(context.args[1:])
        success, message = join_clan(user_id, name)
        await update.message.reply_text(message)
        
        if success:
            check_achievements(user_id)
    
    elif cmd == "leave":
        success, message = leave_clan(user_id)
        await update.message.reply_text(message)
    
    elif cmd == "info":
        user = get_user_by_id(user_id)
        if not user or not user["clan_id"]:
            await update.message.reply_text("❌ Вы не состоите в клане")
            return
        
        clan = get_clan_info(user["clan_id"])
        if not clan:
            await update.message.reply_text("❌ Клан не найден")
            return
        
        owner = get_user_by_id(clan["owner_id"])
        owner_name = owner["username"] or owner["first_name"] if owner else "Неизвестно"
        
        text = (
            f"🏰 Информация о клане '{clan['name']}'\n\n"
            f"👑 Владелец: {owner_name}\n"
            f"📅 Создан: {clan['created_at'][:16]}\n"
            f"💰 Очков клана: {clan['points']}\n"
            f"👥 Участников: {clan['members_count']}\n\n"
            f"Участники:\n"
        )
        
        for member in clan["members"][:5]:
            name = member[1] or member[2] or f"ID {member[0]}"
            text += f"• {name}\n"
        
        await update.message.reply_text(text)
    
    elif cmd == "top":
        top = get_clan_top(10)
        
        if not top:
            await update.message.reply_text("📊 Пока нет кланов")
            return
        
        text = "🏆 Топ кланов:\n\n"
        for i, (name, points, members) in enumerate(top, 1):
            text += f"{i}. {name} — {points}💰 ({members} 👥)\n"
        
        await update.message.reply_text(text)

async def achievements_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/achievements - достижения"""
    user_id = update.effective_user.id
    
    if context.args and context.args[0] == "top":
        # Топ по достижениям
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT user_id, COUNT(*) as count FROM achievements
                GROUP BY user_id ORDER BY count DESC LIMIT 10
            """).fetchall()
        
        if not rows:
            await update.message.reply_text("📊 Пока нет достижений")
            return
        
        text = "🏆 Топ по достижениям:\n\n"
        for i, (uid, count) in enumerate(rows, 1):
            user = get_user_by_id(uid)
            name = user["username"] or user["first_name"] or f"ID {uid}"
            text += f"{i}. {name} — {count} 🏅\n"
        
        await update.message.reply_text(text)
        return
    
    # Свои достижения
    user_achs = get_user_achievements(user_id)
    
    if not user_achs:
        await update.message.reply_text("🏅 У вас пока нет достижений")
        return
    
    text = f"🏅 Достижения {update.effective_user.first_name}:\n\n"
    
    for ach_id in user_achs:
        if ach_id in ACHIEVEMENTS:
            ach = ACHIEVEMENTS[ach_id]
            text += f"{ach['name']}: {ach['desc']}\n"
    
    await update.message.reply_text(text)

# === КОМАНДЫ ДЛЯ ВСЕХ ===

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help - показать справку"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if chat_id > 0:  # Личный чат
        await update.message.reply_text(
            "🤖 **Помощь по боту**\n\n"
            "Добавьте меня в группу и выдайте права администратора!\n\n"
            "**Основные команды:**\n"
            "/help - эта справка\n"
            "/profile - мой профиль\n"
            "/dick - сыграть в письку\n"
            "/top - топ размеров\n"
            "/balance - мои очки\n"
            "/game - угадай число\n"
            "/casino - казино\n"
            "/shop - магазин\n"
            "/inventory - инвентарь\n"
            "/staff - админы чата\n"
            "/id - мой ID\n\n"
            "**Развлечения:**\n"
            "/love @user - совместимость\n"
            "/coin - монетка\n"
            "/cube - кубик\n"
            "/dice - два кубика\n"
            "/rps камень - камень-ножницы-бумага\n"
            "/quote - цитата\n"
            "/anecdote - анекдот\n"
            "/fact - факт\n\n"
            "**Социальное:**\n"
            "/rep @user - репутация\n"
            "/repstats - топ репутации\n"
            "/friend @user - добавить в друзья\n"
            "/friends - список друзей\n"
            "/marry @user - предложение\n"
            "/divorce - развод\n"
            "/clan - кланы\n"
            "/achievements - достижения\n\n"
            "👑 **Для администраторов** - команды открываются по уровню доступа"
        )
        return
    
    # В групповом чате
    level = get_admin_level(chat_id, user_id)
    if user_id == DEVELOPER_ID:
        level = 6
    
    help_text = "📚 **Доступные команды**\n\n"
    help_text += "👤 **Для всех:**\n"
    help_text += "• /help - эта справка\n"
    help_text += "• /profile - мой профиль\n"
    help_text += "• /dick - сыграть в письку\n"
    help_text += "• /top - топ размеров\n"
    help_text += "• /balance - мои очки\n"
    help_text += "• /game - угадай число\n"
    help_text += "• /casino - казино\n"
    help_text += "• /shop - магазин\n"
    help_text += "• /inventory - инвентарь\n"
    help_text += "• /staff - админы чата\n"
    help_text += "• /id - ID пользователя\n"
    help_text += "• /love @user - совместимость\n"
    help_text += "• /coin - монетка\n"
    help_text += "• /cube - кубик\n"
    help_text += "• /dice - два кубика\n"
    help_text += "• /rps - камень-ножницы-бумага\n"
    help_text += "• /quote - цитата\n"
    help_text += "• /anecdote - анекдот\n"
    help_text += "• /fact - факт\n"
    help_text += "• /rep @user - репутация\n"
    help_text += "• /repstats - топ репутации\n"
    help_text += "• /friend @user - добавить в друзья\n"
    help_text += "• /friends - список друзей\n"
    help_text += "• /marry @user - предложение\n"
    help_text += "• /divorce - развод\n"
    help_text += "• /clan - кланы\n"
    help_text += "• /achievements - достижения\n\n"
    
    if level >= 1:
        help_text += "🛡 **Уровень 1+:**\n"
        help_text += "• /warn @user причина - предупреждение\n"
        help_text += "• /warns @user - список предупреждений\n\n"
    
    if level >= 2:
        help_text += "🔨 **Уровень 2+:**\n"
        help_text += "• /mute @user 10m причина - замутить\n"
        help_text += "• /unmute @user - размутить\n"
        help_text += "• /kick @user причина - выгнать\n\n"
    
    if level >= 3:
        help_text += "⛔️ **Уровень 3+:**\n"
        help_text += "• /ban @user время причина - забанить\n"
        help_text += "• /unban @user - разбанить\n"
        help_text += "• /clearwarns @user - очистить предупреждения\n"
        help_text += "• /unrep @user - понизить репутацию\n\n"
    
    if level >= 4:
        help_text += "⚡️ **Уровень 4+:**\n"
        help_text += "• /setadmin @user уровень - назначить админа\n"
        help_text += "• /freeze @user причина - заморозить админа\n"
        help_text += "• /unfreeze @user - разморозить\n"
        help_text += "• /rules set текст - установить правила\n"
        help_text += "• /antiraid - режим антирейд\n\n"
    
    if level >= 5:
        help_text += "👑 **Уровень 5+:**\n"
        help_text += "• /rules - показать правила\n\n"
    
    if level == 6 or user_id == DEVELOPER_ID:
        help_text += "🔧 **Разработчик:**\n"
        help_text += "• /getowner - получить права владельца\n"
    
    help_text += "\n💡 **Как использовать:**\n"
    help_text += "• Ответ на сообщение + команда\n"
    help_text += "• /команда @username\n"
    help_text += "• /команда ID"
    help_text += "Так же если у вас есть какие то предложение или вопросы обратитесь к @q_shimokuroda2"
    help_text += "Т.К разработчики являются Unity Devs"
    
    await update.message.reply_text(help_text)

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/profile - профиль пользователя"""
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Получаем данные
    user_data = get_user_by_id(user_id)
    points = get_user_points(user_id)
    rep = get_user_rep(user_id)
    friends = get_friends(user_id)
    user_achs = get_user_achievements(user_id)
    
    with sqlite3.connect(DB_PATH) as conn:
        # Статистика наказаний
        warns = conn.execute(
            "SELECT COUNT(*) FROM moderation_logs WHERE target_user_id = ? AND action = 'warn'",
            (user_id,)
        ).fetchone()[0]
        
        mutes = conn.execute(
            "SELECT COUNT(*) FROM moderation_logs WHERE target_user_id = ? AND action LIKE '%mute%'",
            (user_id,)
        ).fetchone()[0]
    
    profile_text = (
        f"👤 **Профиль пользователя**\n\n"
        f"• **ID:** {user_id}\n"
        f"• **Имя:** {user.first_name}\n"
    )
    
    if user.username:
        profile_text += f"• **Username:** @{user.username}\n"
    
    if user_data and user_data["marry_with"]:
        spouse = get_user_by_id(user_data["marry_with"])
        if spouse:
            spouse_name = spouse["username"] or spouse["first_name"] or f"ID {spouse['user_id']}"
            profile_text += f"• **💍 Супруг(а):** {spouse_name}\n"
    
    if user_data and user_data["clan_id"]:
        clan = get_clan_info(user_data["clan_id"])
        if clan:
            profile_text += f"• **🏰 Клан:** {clan['name']}\n"
    
    profile_text += (
        f"\n📊 **Статистика**\n"
        f"• 🪙 Очки: {points}\n"
        f"• ⭐ Репутация: {rep}\n"
        f"• 👥 Друзья: {len(friends)}\n"
        f"• 🏅 Достижения: {len(user_achs)}\n"
        f"• ⚠️ Предупреждения: {warns}\n"
        f"• 🔇 Муты: {mutes}\n"
    )
    
    await update.message.reply_text(profile_text)

async def dick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dick - игра в письку"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.first_name or f"Пользователь {user_id}"
    
    current_size, last_played = get_penis_size(chat_id, user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    if last_played == today:
        await update.message.reply_text(
            f"{username}, сегодня ты уже играл!\n"
            "Попробуй снова завтра."
        )
        return
    
    change = random.randint(-5, 10)
    new_size = max(0, current_size + change)
    
    update_penis_size(chat_id, user_id, new_size, today)
    position = get_penis_position(chat_id, user_id)
    
    if change > 0:
        verb = f"вырос на {change} см"
    elif change < 0:
        verb = f"уменьшился на {-change} см"
    else:
        verb = "не изменился"
    
    await update.message.reply_text(
        f"{username}, твой писюн {verb} 📏\n"
        f"Теперь он {new_size} см\n"
        f"Ты занимаешь {position} место в топе\n"
        "Приходи завтра!"
    )

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/top - топ размеров"""
    chat_id = update.effective_chat.id
    
    rows = get_penis_top(chat_id)
    
    if not rows:
        await update.message.reply_text("📊 В этом чате еще никто не играл в письку")
        return
    
    text = "🏆 **Топ-10 размеров**\n\n"
    
    for i, (user_id, size) in enumerate(rows, 1):
        user_data = get_user_by_id(user_id)
        if user_data and user_data['username']:
            name = f"@{user_data['username']}"
        elif user_data and user_data['first_name']:
            name = user_data['first_name']
        else:
            name = f"ID {user_id}"
        
        text += f"{i}. {name} — {size} см\n"
    
    await update.message.reply_text(text)

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/balance - баланс очков"""
    user_id = update.effective_user.id
    points = get_user_points(user_id)
    
    await update.message.reply_text(f"💰 Ваш баланс: {points} очков")

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/game - угадай число"""
    user_id = update.effective_user.id
    
    number = random.randint(1, 10)
    game_sessions[user_id] = {
        'number': number,
        'active': True,
        'time': time.time()
    }
    
    await update.message.reply_text(
        "🎮 **Угадай число от 1 до 10**\n"
        "Напиши свой ответ в чат"
    )

async def casino_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/casino - казино"""
    user_id = update.effective_user.id
    
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "❌ Укажите ставку\n"
            "Пример: /casino 50"
        )
        return
    
    bet = int(args[0])
    if bet < 1 or bet > 1000:
        await update.message.reply_text("❌ Ставка от 1 до 1000 очков")
        return
    
    current_points = get_user_points(user_id)
    
    if current_points < bet:
        await update.message.reply_text(f"❌ Недостаточно очков. У вас {current_points}")
        return
    
    win = random.random() < 0.4
    
    if win:
        new_points = current_points + bet
        result = f"🎉 **Вы выиграли!** +{bet} очков"
    else:
        new_points = current_points - bet
        result = f"😢 **Вы проиграли!** -{bet} очков"
    
    update_user_points(user_id, new_points)
    
    await update.message.reply_text(
        f"{result}\n"
        f"💰 Текущий баланс: {new_points}"
    )

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/shop - магазин"""
    if not os.path.exists(SHOP_ITEMS_FILE):
        default_items = {
            "1": {"name": "🍬 Конфетка", "price": 10, "description": "Просто конфетка"},
            "2": {"name": "🎫 Лотерейный билет", "price": 50, "description": "Шанс выиграть приз"},
            "3": {"name": "👑 VIP статус", "price": 200, "description": "Особый статус на 1 день"},
            "4": {"name": "🌈 Цветное имя", "price": 500, "description": "Ваше имя будет разноцветным"},
            "5": {"name": "⚡️ Ускоритель", "price": 100, "description": "+10% к опыту на 1 час"},
            "6": {"name": "🛡 Защита", "price": 300, "description": "Защита от одного наказания"},
            "7": {"name": "🎁 Секретный подарок", "price": 1000, "description": "Что-то очень интересное!"}
        }
        with open(SHOP_ITEMS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_items, f, ensure_ascii=False, indent=2)
    
    try:
        with open(SHOP_ITEMS_FILE, 'r', encoding='utf-8') as f:
            items = json.load(f)
    except:
        await update.message.reply_text("❌ Ошибка загрузки магазина")
        return
    
    shop_text = "🏪 **Магазин**\n\n"
    shop_text += "Купить: /buy [номер]\n\n"
    
    for item_id, item in items.items():
        shop_text += f"{item_id}. {item['name']} - {item['price']}💰\n"
        shop_text += f"   _{item['description']}_\n\n"
    
    await update.message.reply_text(shop_text)

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/buy - купить товар"""
    user_id = update.effective_user.id
    
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ Укажите номер товара: /buy 1")
        return
    
    item_id = args[0]
    
    try:
        with open(SHOP_ITEMS_FILE, 'r', encoding='utf-8') as f:
            items = json.load(f)
    except:
        await update.message.reply_text("❌ Ошибка загрузки магазина")
        return
    
    if item_id not in items:
        await update.message.reply_text("❌ Товар не найден")
        return
    
    item = items[item_id]
    current_points = get_user_points(user_id)
    
    if current_points < item['price']:
        await update.message.reply_text(f"❌ Недостаточно очков. Нужно {item['price']}")
        return
    
    new_points = current_points - item['price']
    update_user_points(user_id, new_points)
    
    # Сохраняем в инвентарь
    inventory = {}
    if os.path.exists(USER_INVENTORY_FILE):
        try:
            with open(USER_INVENTORY_FILE, 'r', encoding='utf-8') as f:
                inventory = json.load(f)
        except:
            pass
    
    str_user_id = str(user_id)
    if str_user_id not in inventory:
        inventory[str_user_id] = []
    
    inventory[str_user_id].append({
        "item_id": item_id,
        "name": item['name'],
        "purchased": datetime.now().isoformat()
    })
    
    with open(USER_INVENTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
    
    await update.message.reply_text(
        f"✅ Вы купили {item['name']}\n"
        f"💰 Осталось очков: {new_points}"
    )

async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/inventory - инвентарь"""
    user_id = update.effective_user.id
    
    if not os.path.exists(USER_INVENTORY_FILE):
        await update.message.reply_text("📦 Ваш инвентарь пуст")
        return
    
    try:
        with open(USER_INVENTORY_FILE, 'r', encoding='utf-8') as f:
            inventory = json.load(f)
    except:
        await update.message.reply_text("❌ Ошибка загрузки инвентаря")
        return
    
    str_user_id = str(user_id)
    if str_user_id not in inventory or not inventory[str_user_id]:
        await update.message.reply_text("📦 Ваш инвентарь пуст")
        return
    
    items = inventory[str_user_id]
    
    inv_text = "📦 **Ваш инвентарь**\n\n"
    for i, item in enumerate(items[-10:], 1):
        inv_text += f"{i}. {item['name']}\n"
    
    await update.message.reply_text(inv_text)

async def staff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/staff - список админов"""
    chat_id = update.effective_chat.id
    
    admins = get_all_admins(chat_id)
    
    if not admins:
        await update.message.reply_text("👥 В этом чате нет администраторов бота")
        return
    
    level_names = {
        6: "👑 Владелец",
        5: "⚜️ Руководитель",
        4: "🔰 Зам. руководителя",
        3: "🛡 Старший модератор",
        2: "🔨 Младший модератор",
        1: "📋 Кандидат"
    }
    
    text = "👥 **Администраторы чата**\n\n"
    
    for admin_id, level, frozen in admins:
        user_data = get_user_by_id(admin_id)
        
        if user_data and user_data['username']:
            name = f"@{user_data['username']}"
        elif user_data and user_data['first_name']:
            name = user_data['first_name']
        else:
            name = f"ID {admin_id}"
        
        frozen_icon = "❄️" if frozen else ""
        level_name = level_names.get(level, f"Уровень {level}")
        
        text += f"• {level_name} {frozen_icon}: {name}\n"
    
    await update.message.reply_text(text)

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rules - управление правилами"""
    chat_id = str(update.effective_chat.id)
    
    if not os.path.exists(RULES_FILE):
        rules = {}
    else:
        try:
            with open(RULES_FILE, 'r', encoding='utf-8') as f:
                rules = json.load(f)
        except:
            rules = {}
    
    args = context.args
    
    if not args:
        if chat_id in rules:
            await update.message.reply_text(
                f"📜 **Правила чата**\n\n{rules[chat_id]}"
            )
        else:
            await update.message.reply_text("📜 В этом чате еще нет правил")
        return
    
    has_access, msg = check_admin_access(update, 4, int(chat_id))
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    cmd = args[0].lower()
    
    if cmd == "set" and len(args) >= 2:
        new_rules = " ".join(args[1:])
        rules[chat_id] = new_rules
        
        try:
            with open(RULES_FILE, 'w', encoding='utf-8') as f:
                json.dump(rules, f, ensure_ascii=False, indent=2)
            await update.message.reply_text("✅ Правила сохранены")
        except:
            await update.message.reply_text("❌ Ошибка сохранения")
    
    elif cmd == "del":
        if chat_id in rules:
            del rules[chat_id]
            try:
                with open(RULES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(rules, f, ensure_ascii=False, indent=2)
                await update.message.reply_text("✅ Правила удалены")
            except:
                await update.message.reply_text("❌ Ошибка удаления")
        else:
            await update.message.reply_text("❌ Правил нет")
    
    else:
        await update.message.reply_text(
            "Использование:\n"
            "/rules - показать правила\n"
            "/rules set текст - установить правила\n"
            "/rules del - удалить правила"
        )

async def antiraid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/antiraid - режим антирейд"""
    chat_id = update.effective_chat.id
    
    has_access, msg = check_admin_access(update, 4, chat_id)
    if not has_access:
        await update.message.reply_text(msg)
        return
    
    raid_mode_active[chat_id] = not raid_mode_active[chat_id]
    
    if raid_mode_active[chat_id]:
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_other_messages=False,
            can_send_polls=False,
            can_add_web_page_previews=False
        )
        
        try:
            await context.bot.set_chat_permissions(chat_id, permissions)
            await update.message.reply_text(
                "🛡 **Режим антирейд включен!**\n"
                "Чат переведен в режим только для админов"
            )
        except:
            await update.message.reply_text("❌ Ошибка: нет прав на изменение прав чата")
    else:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_other_messages=True,
            can_send_polls=True,
            can_add_web_page_previews=True
        )
        
        try:
            await context.bot.set_chat_permissions(chat_id, permissions)
            await update.message.reply_text("✅ Режим антирейд выключен")
        except:
            await update.message.reply_text("❌ Ошибка: нет прав на изменение прав чата")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/id - показать ID"""
    if context.args or update.message.reply_to_message:
        target_id, display_name = await get_target_user(update, context, context.args)
        if target_id:
            await update.message.reply_text(f"🔢 ID пользователя: {target_id}")
            return
    
    await update.message.reply_text(
        f"🔢 Ваш ID: {update.effective_user.id}\n"
        f"📢 ID чата: {update.effective_chat.id}"
    )

async def getowner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/getowner - получить права владельца (для разработчика)"""
    user_id = update.effective_user.id
    
    if user_id != DEVELOPER_ID:
        await update.message.reply_text("❌ Эта команда только для разработчика")
        return
    
    chat_id = update.effective_chat.id
    
    success, message = set_admin_level(chat_id, user_id, 6, user_id)
    
    if success:
        await update.message.reply_text("👑 Вы получили уровень 6 (Владелец бота)")
        log_moderation(chat_id, "set_owner", user_id, user_id, "getowner command")
    else:
        await update.message.reply_text(f"❌ {message}")

# === ОБРАБОТЧИКИ СОБЫТИЙ ===

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик добавления бота в чат"""
    chat_member = update.my_chat_member
    if not chat_member:
        return
    
    old = chat_member.old_chat_member.status if chat_member.old_chat_member else None
    new = chat_member.new_chat_member.status if chat_member.new_chat_member else None
    
    if new == "member" and old != "member":
        chat_id = chat_member.chat.id
        
        try:
            invite_link = await context.bot.export_chat_invite_link(chat_id)
            add_chat(chat_id, invite_link)
        except:
            add_chat(chat_id, None)
        
        welcome = (
            "🤖 **Бот добавлен в чат!**\n\n"
            "📌 **Важные действия:**\n"
            "1. Выдайте мне права администратора\n"
            "2. Я автоматически сохраняю всех участников\n\n"
            "🔍 **Сканирование участников...**"
        )
        
        await context.bot.send_message(chat_id=chat_id, text=welcome)
        await scan_chat_members(chat_id, context)
        
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            creator = None
            for admin in admins:
                if admin.status == "creator":
                    creator = admin.user
                    break
            
            if creator:
                set_admin_level(chat_id, creator.id, INITIAL_ADMIN_LEVEL, creator.id)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"👑 {creator.first_name}, вы получили уровень {INITIAL_ADMIN_LEVEL} как создатель чата!"
                )
        except:
            pass
        
        logger.info(f"✅ Бот добавлен в чат {chat_id}")

async def on_user_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик входа нового пользователя"""
    if not update.chat_member or not update.chat_member.new_chat_member:
        return
    
    user = update.chat_member.new_chat_member.user
    
    if user and not user.is_bot:
        save_user(user)
        logger.info(f"👤 Новый пользователь в чате: {user.id} (@{user.username})")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("marry_accept"):
        from_id = int(data.split("_")[2])
        to_id = query.from_user.id
        
        proposal_id = f"{from_id}:{to_id}"
        
        if proposal_id not in marriage_proposals:
            await query.edit_message_text("❌ Предложение устарело или не найдено")
            return
        
        if time.time() - marriage_proposals[proposal_id]["time"] > 300:  # 5 минут
            await query.edit_message_text("❌ Время предложения истекло")
            del marriage_proposals[proposal_id]
            return
        
        if marry_users(from_id, to_id):
            from_user = get_user_by_id(from_id)
            from_name = from_user["username"] or from_user["first_name"] if from_user else f"ID {from_id}"
            
            await query.edit_message_text(
                f"💍 Поздравляем! {from_name} и {query.from_user.first_name} теперь муж и жена!"
            )
            
            # Проверяем достижения
            add_achievement(from_id, "marry")
            add_achievement(to_id, "marry")
        else:
            await query.edit_message_text("❌ Не удалось заключить брак. Возможно, кто-то уже женат")
        
        del marriage_proposals[proposal_id]
    
    elif data.startswith("marry_decline"):
        from_id = int(data.split("_")[2])
        to_id = query.from_user.id
        
        proposal_id = f"{from_id}:{to_id}"
        
        if proposal_id in marriage_proposals:
            del marriage_proposals[proposal_id]
        
        await query.edit_message_text("💔 Предложение отклонено")

# === ОСНОВНАЯ ФУНКЦИЯ ===

def main():
    """Запуск бота"""
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    # Обработчик всех сообщений
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    
    # Команды для всех
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("start", help_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("dick", dick_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("game", game_command))
    application.add_handler(CommandHandler("casino", casino_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("inventory", inventory_command))
    application.add_handler(CommandHandler("staff", staff_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CommandHandler("id", id_command))
    
    # Развлекательные команды
    application.add_handler(CommandHandler("love", love_command))
    application.add_handler(CommandHandler("coin", coin_command))
    application.add_handler(CommandHandler("cube", cube_command))
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("rps", rps_command))
    application.add_handler(CommandHandler("quote", quote_command))
    application.add_handler(CommandHandler("anecdote", anecdote_command))
    application.add_handler(CommandHandler("fact", fact_command))
    
    # Социальные команды
    application.add_handler(CommandHandler("rep", rep_command))
    application.add_handler(CommandHandler("unrep", unrep_command))
    application.add_handler(CommandHandler("repstats", repstats_command))
    application.add_handler(CommandHandler("friend", friend_command))
    application.add_handler(CommandHandler("unfriend", unfriend_command))
    application.add_handler(CommandHandler("friends", friends_command))
    application.add_handler(CommandHandler("marry", marry_command))
    application.add_handler(CommandHandler("divorce", divorce_command))
    application.add_handler(CommandHandler("clan", clan_command))
    application.add_handler(CommandHandler("achievements", achievements_command))
    
    # Команды модерации
    application.add_handler(CommandHandler("mute", mute_command))
    application.add_handler(CommandHandler("unmute", unmute_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("kick", kick_command))
    application.add_handler(CommandHandler("warn", warn_command))
    application.add_handler(CommandHandler("warns", warns_command))
    application.add_handler(CommandHandler("clearwarns", clearwarns_command))
    application.add_handler(CommandHandler("setadmin", setadmin_command))
    application.add_handler(CommandHandler("freeze", freeze_command))
    application.add_handler(CommandHandler("unfreeze", unfreeze_command))
    application.add_handler(CommandHandler("antiraid", antiraid_command))
    
    # Команды для разработчика
    application.add_handler(CommandHandler("getowner", getowner_command))
    
    # Обработчики событий
    application.add_handler(ChatMemberHandler(on_bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(on_user_join, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("🚀 Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()