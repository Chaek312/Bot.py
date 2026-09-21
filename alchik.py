import telebot
from telebot import types
import random
from random import shuffle
import asyncio
import logging
import time
import threading
import io
import re
import csv
from datetime import datetime, timedelta
from telebot.apihelper import ApiTelegramException
import concurrent.futures
from collections import defaultdict
import hashlib
from telebot.types import LabeledPrice
import zipfile
import sqlite3
import json
import os
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

notification_timers = {}

logging.basicConfig(level=logging.INFO)

bot = telebot.TeleBot("7605504614:AAF_8F_O3uQsQ7MVOWS2PjL0lqsp3_KGroM")

chat_list = {}
game_tasks = {}
registration_timers = {}
game_start_timers = {}
user_game_registration = {}
vote_timestamps = {}
next_players = {}
registration_lock = threading.Lock()
game_timers = {}
update_timers = {}
lock = threading.Lock()
ALLOWED_CHAT_ID = [-1002145074948, -1002398622601, -1002279830772]
OFFICIAL_CHAT_LINK = "https://t.me/CityMafiaSupportBot"
ADMIN_ID = 6265990443
CHANNEL_ID = -1002598471111
SETTINGS_CHANNEL_ID = -1002687818190
OWNER_ID = 6265990443
AD_CHANNEL_ID = -1002501442029
current_ad_message = None
last_top_usage = {}
sent_messages = {}

# ================== SQLITE-ПОСТОЯННОЕ ХРАНИЛИЩЕ ==================
# Профили, настройки чатов и очки НЕ хранятся в больших RAM-словарях.
# SQLite является единственным источником истины для постоянных данных.
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
PROFILE_DB_PATH = os.path.join(BASE_DIR, "city_mafia.db")
_db_lock = threading.RLock()


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def init_profile_database():
    with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_profiles (
                user_id INTEGER PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                settings_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_scores (
                user_id INTEGER PRIMARY KEY,
                score INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


class SQLiteProfile(dict):
    """Профиль игрока. Сам профиль загружается только при обращении.
    Любое изменение поля сразу записывается в SQLite."""

    def __init__(self, user_id, data):
        super().__init__(data)
        self._user_id = int(user_id)

    def _save(self):
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute(
                    """INSERT INTO player_profiles (user_id, profile_json, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id) DO UPDATE SET
                           profile_json=excluded.profile_json,
                           updated_at=CURRENT_TIMESTAMP""",
                    (self._user_id, _json_dumps(dict(self)))
                )
                conn.commit()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._save()

    def setdefault(self, key, default=None):
        if key not in self:
            super().__setitem__(key, default)
            self._save()
        return super().get(key)

    def pop(self, key, *args):
        value = super().pop(key, *args)
        self._save()
        return value

    def clear(self):
        super().clear()
        self._save()


class SQLiteProfiles:
    """DB-backed mapping без хранения всех профилей в RAM."""

    def _load(self, user_id):
        user_id = int(user_id)
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                row = conn.execute(
                    "SELECT profile_json FROM player_profiles WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        if not isinstance(data, dict):
            return None
        data.setdefault('id', user_id)
        return SQLiteProfile(user_id, data)

    def get(self, user_id, default=None):
        profile = self._load(user_id)
        return default if profile is None else profile

    def __getitem__(self, user_id):
        profile = self._load(user_id)
        if profile is None:
            raise KeyError(user_id)
        return profile

    def __setitem__(self, user_id, profile):
        if not isinstance(profile, dict):
            raise TypeError("Профиль должен быть dict")
        data = dict(profile)
        data.setdefault('id', int(user_id))
        SQLiteProfile(user_id, data)._save()

    def __delitem__(self, user_id):
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute("DELETE FROM player_profiles WHERE user_id = ?", (int(user_id),))
                conn.commit()

    def __contains__(self, user_id):
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                return conn.execute(
                    "SELECT 1 FROM player_profiles WHERE user_id = ? LIMIT 1", (int(user_id),)
                ).fetchone() is not None

    def __len__(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM player_profiles").fetchone()[0])

    def __iter__(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            rows = conn.execute("SELECT user_id FROM player_profiles ORDER BY user_id").fetchall()
        return iter(row[0] for row in rows)

    def keys(self):
        return self.__iter__()

    def items(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            rows = conn.execute("SELECT user_id, profile_json FROM player_profiles ORDER BY user_id").fetchall()
        for user_id, raw in rows:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    data.setdefault('id', int(user_id))
                    yield int(user_id), SQLiteProfile(user_id, data)
            except Exception as e:
                logging.error(f"SQLite: ошибка чтения профиля {user_id}: {e}")

    def values(self):
        for _, profile in self.items():
            yield profile


class SQLiteJsonMapping:
    """Простое DB-backed хранилище JSON по integer key.
    Используется для настроек чатов без глобального словаря в RAM."""

    def __init__(self, table_name, key_name, value_column):
        self.table_name = table_name
        self.key_name = key_name
        self.value_column = value_column

    def get(self, key, default=None):
        try:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                row = conn.execute(
                    f"SELECT {self.value_column} FROM {self.table_name} WHERE {self.key_name} = ?",
                    (int(key),)
                ).fetchone()
            if not row:
                return default
            value = json.loads(row[0])
            return value if isinstance(value, dict) else default
        except Exception as e:
            logging.error(f"SQLite: ошибка чтения {self.table_name}/{key}: {e}")
            return default

    def __getitem__(self, key):
        value = self.get(key, None)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        if not isinstance(value, dict):
            raise TypeError("Значение должно быть dict")
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute(
                    f"""INSERT INTO {self.table_name} ({self.key_name}, {self.value_column}, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT({self.key_name}) DO UPDATE SET
                            {self.value_column}=excluded.{self.value_column},
                            updated_at=CURRENT_TIMESTAMP""",
                    (int(key), _json_dumps(value))
                )
                conn.commit()

    def __delitem__(self, key):
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute(f"DELETE FROM {self.table_name} WHERE {self.key_name} = ?", (int(key),))
                conn.commit()

    def __contains__(self, key):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            return conn.execute(
                f"SELECT 1 FROM {self.table_name} WHERE {self.key_name} = ? LIMIT 1", (int(key),)
            ).fetchone() is not None

    def __len__(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0])

    def items(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            rows = conn.execute(
                f"SELECT {self.key_name}, {self.value_column} FROM {self.table_name} ORDER BY {self.key_name}"
            ).fetchall()
        for key, raw in rows:
            try:
                value = json.loads(raw)
                if isinstance(value, dict):
                    yield int(key), value
            except Exception as e:
                logging.error(f"SQLite: ошибка чтения {self.table_name}/{key}: {e}")

    def keys(self):
        return (key for key, _ in self.items())


class SQLiteSettingsDict(dict):
    """Настройки одного чата. Вложенные изменения тоже сохраняются в SQLite."""
    def __init__(self, chat_id, data):
        super().__init__(data)
        self._chat_id = int(chat_id)

    def _save(self):
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute(
                    """INSERT INTO chat_settings (chat_id, settings_json, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(chat_id) DO UPDATE SET
                           settings_json=excluded.settings_json,
                           updated_at=CURRENT_TIMESTAMP""",
                    (self._chat_id, _json_dumps(dict(self)))
                )
                conn.commit()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._save()


class SQLiteSettings(SQLiteJsonMapping):
    """DB-backed настройки чатов без глобального RAM-словаря."""
    def __init__(self):
        super().__init__('chat_settings', 'chat_id', 'settings_json')

    def get(self, key, default=None):
        try:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                row = conn.execute(
                    "SELECT settings_json FROM chat_settings WHERE chat_id = ?",
                    (int(key),)
                ).fetchone()
            if not row:
                return default
            value = json.loads(row[0])
            return SQLiteSettingsDict(key, value) if isinstance(value, dict) else default
        except Exception as e:
            logging.error(f"SQLite: ошибка чтения настроек чата {key}: {e}")
            return default

    def __setitem__(self, key, value):
        if not isinstance(value, dict):
            raise TypeError("Настройки должны быть dict")
        SQLiteSettingsDict(key, dict(value))._save()

    def items(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            rows = conn.execute("SELECT chat_id, settings_json FROM chat_settings ORDER BY chat_id").fetchall()
        for chat_id, raw in rows:
            try:
                value = json.loads(raw)
                if isinstance(value, dict):
                    yield int(chat_id), SQLiteSettingsDict(chat_id, value)
            except Exception as e:
                logging.error(f"SQLite: ошибка чтения настроек чата {chat_id}: {e}")


class SQLiteScores:
    """Очки игроков хранятся в SQLite, а не в player_scores = {}."""

    def get(self, user_id, default=0):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            row = conn.execute("SELECT score FROM player_scores WHERE user_id = ?", (int(user_id),)).fetchone()
        return int(row[0]) if row else default

    def __getitem__(self, user_id):
        return self.get(user_id, 0)

    def __setitem__(self, user_id, score):
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute(
                    """INSERT INTO player_scores (user_id, score, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id) DO UPDATE SET score=excluded.score, updated_at=CURRENT_TIMESTAMP""",
                    (int(user_id), int(score))
                )
                conn.commit()

    def __contains__(self, user_id):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            return conn.execute("SELECT 1 FROM player_scores WHERE user_id = ?", (int(user_id),)).fetchone() is not None

    def __len__(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM player_scores").fetchone()[0])

    def items(self):
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            rows = conn.execute("SELECT user_id, score FROM player_scores ORDER BY user_id").fetchall()
        for user_id, score in rows:
            yield int(user_id), int(score)

    def clear(self):
        with _db_lock:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute("DELETE FROM player_scores")
                conn.commit()

    def keys(self):
        return (user_id for user_id, _ in self.items())


init_profile_database()
player_profiles = SQLiteProfiles()
chat_settings = SQLiteSettings()
player_scores = SQLiteScores()
# ================== ГЛОБАЛЬНЫЙ СЛОВАРЬ ТЕКСТОВ ==================
# ================== ЛОКАЛИЗАЦИЯ ==================
# Тексты вынесены в отдельные JSON-файлы для работы через Crowdin.
LOCALES_DIR = os.path.join(BASE_DIR, "locales")
DEFAULT_LANGUAGE = "ru"
SUPPORTED_LANGUAGES = ("ru", "kz", "uz", "en")


def _load_locales():
    result = {}
    for lang in SUPPORTED_LANGUAGES:
        path = os.path.join(LOCALES_DIR, f"{lang}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                result[lang] = json.load(f)
        except FileNotFoundError:
            result[lang] = {}
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка JSON локализации {path}: {e}")
            result[lang] = {}

    if not result.get(DEFAULT_LANGUAGE):
        raise RuntimeError(
            f"Не удалось загрузить основную локализацию "
            f"{os.path.join(LOCALES_DIR, 'ru.json')}"
        )
    return result


TEXTS = _load_locales()


# Функция для получения текста по ключу и языку чата

# Функция для получения текста по языку пользователя
def get_user_text(user_id, key, **kwargs):
    """Получает локализованный текст с fallback на русский."""
    profile = player_profiles.get(user_id, {})
    lang = profile.get('language', DEFAULT_LANGUAGE)
    lang_texts = TEXTS.get(lang) or TEXTS[DEFAULT_LANGUAGE]
    text = lang_texts.get(key, TEXTS[DEFAULT_LANGUAGE].get(key, key))
    if kwargs:
        text = text.format(**kwargs)
    return text

# Функция для перевода роли (полное описание)
def translate_role(role, lang):
    """Переводит роль с fallback на русский."""
    lang_texts = TEXTS.get(lang) or TEXTS[DEFAULT_LANGUAGE]
    return lang_texts.get('role_texts', {}).get(
        role,
        TEXTS[DEFAULT_LANGUAGE].get('role_texts', {}).get(role, role)
    )

# Функция для получения короткого названия роли
def get_short_role(role, chat_id=None):
    """Возвращает короткое название роли для вывода в результатах игры"""
    if chat_id:
        lang = chat_settings.get(chat_id, {}).get("language", "ru")
    else:
        lang = "ru"
    
    short_roles_map = {
        '🤵🏻‍♂️ Дон': 'short_role_don',
        '🤵🏻 Мафия': 'short_role_mafia',
        '👨🏼‍⚕️ Дәрігер': 'short_role_doctor',
        '🤦🏼 Самоубийца': 'short_role_suicide',
        '🧙‍♂️ Қаңғыбас': 'short_role_hobo',
        '🕵🏼 Комиссар': 'short_role_sheriff',
        '🤞 Жолы болғыш': 'short_role_lucky',
        '💣 Камикадзе': 'short_role_kamikaze',
        '💃🏼 Көңілдес': 'short_role_lover',
        '👨🏼‍💼 Қорғаушы': 'short_role_lawyer',
        '👮🏼 Сержант': 'short_role_sergeant',
        '🔪 Жауыз': 'short_role_maniac',
        '👨🏼 Тату тұрғын': 'short_role_citizen'
    }
    
    key = short_roles_map.get(role, 'short_role_citizen')
    lang_texts = TEXTS.get(lang) or TEXTS[DEFAULT_LANGUAGE]
    return lang_texts.get(key, TEXTS[DEFAULT_LANGUAGE].get(key, role))

# Функция для получения полного имени игрока
def get_full_name(player):
    first_name = player.get('name', '')
    last_name = player.get('last_name', '')
    return f"{first_name} {last_name}".strip()

# ================== КЛАСС GAME ==================
class Game:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = {}
        self.dead_last_words = {}
        self.dead = None
        self.sheriff_check = None
        self.sheriff_shoot = None
        self.sheriff_id = None
        self.sergeant_id = None
        self.doc_target = None
        self.vote_counts = {}
        self.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
        self.game_running = False
        self.button_id = None
        self.dList_id = None
        self.shList_id = None
        self.docList_id = None
        self.mafia_votes = {}
        self.mafia_voting_message_id = None
        self.don_id = None
        self.lucky_id = None
        self.vote_message_id = None
        self.hobo_id = None
        self.hobo_target = None
        self.hobo_visitors = []
        self.suicide_bomber_id = None
        self.suicide_hanged = False
        self.all_dead_players = []
        self.lover_id = None
        self.lover_target_id = None
        self.previous_lover_target_id = None
        self.last_sheriff_menu_id = None
        self.lawyer_id = None
        self.lawyer_target = None
        self.maniac_id = None
        self.maniac_target = None
        self.voting_finished = False
        self.is_night = False
        self.is_voting_time = False
        self.kamikaze_choice_message_id = None
        self.kamikaze_choice_active = False
        self.kamikaze_victim = None
        self.kamikaze_kill = None
        self.suicide_lynched_ids = []  # ← ДОБАВИТЬ ЭТУ СТРОКУ

    def update_player_list(self):
        players_list = ", ".join([f"{player['name']} {player.get('last_name', '')}" for player in self.players.values()])
        return players_list

    def remove_player(self, player_id, killed_by=None):
        if player_id in self.players:
           dead_player = self.players.pop(player_id)
        
        # Сохраняем как умер
           dead_player['killed_by'] = killed_by
        
        # Если это линчевание, отмечаем статус
        if killed_by == 'lynch':
            dead_player['status'] = 'lynched'
            # Дополнительно сохраняем в отдельный список для надёжности
            if dead_player['role'] == '🤦🏼 Самоубийца':
                if not hasattr(self, 'suicide_lynched_ids'):
                    self.suicide_lynched_ids = []
                self.suicide_lynched_ids.append(player_id)
        else:
            dead_player['status'] = 'dead'

        if player_id in user_game_registration and user_game_registration[player_id] == self.chat_id:
            del user_game_registration[player_id]

        lang = chat_settings.get(self.chat_id, {}).get("language", "kz")
        role = get_short_role(dead_player['role'], self.chat_id)
        full_name = f"{dead_player['name']} {dead_player.get('last_name', '')}".strip()
        clickable_name = f"[{full_name}](tg://user?id={player_id})"

        # Сохраняем в all_dead_players с полной информацией
        dead_copy = dead_player.copy()
        dead_copy['user_id'] = player_id
        dead_copy['killed_by'] = killed_by
        self.all_dead_players.append(dead_copy)

        if killed_by == 'night':
            try:
                send_message(player_id, get_text(self.chat_id, 'death_night_message'), parse_mode='Markdown')
                self.dead_last_words[player_id] = full_name
            except Exception as e:
                print(f"Не удалось отправить сообщение игроку {full_name}: {e}")


def start_kamikaze_choice(chat, kamikaze_id):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    
    kamikaze_player = chat.players.get(kamikaze_id)
    if not kamikaze_player:
        return
    
    markup = types.InlineKeyboardMarkup()
    alive_players = []
    
    for player_id, player in chat.players.items():
        if player['role'] != 'dead' and player_id != kamikaze_id:
            alive_players.append(player_id)
            player_name = f"{player['name']} {player.get('last_name', '')}"
            markup.add(types.InlineKeyboardButton(player_name, callback_data=f'kamikaze_choice_{player_id}'))
    
    if not alive_players:
        return
    
    message_text = get_text(chat.chat_id, 'kamikaze_question')
    
    try:
        msg = send_message(kamikaze_id, message_text, reply_markup=markup)
        chat.kamikaze_choice_message_id = msg.message_id
        chat.kamikaze_choice_active = True
        
        timer = threading.Timer(30.0, lambda: end_kamikaze_choice(chat, kamikaze_id))
        timer.start()
        
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение камикадзе {kamikaze_id}: {e}")


def handle_kamikaze_choice(chat, kamikaze_id, chosen_player_id):
    if not chat.kamikaze_choice_active:
        return
    
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    
    chosen_player = chat.players.get(chosen_player_id)
    if not chosen_player or chosen_player['role'] == 'dead':
        send_message(kamikaze_id, get_text(chat.chat_id, 'kamikaze_no_target'))
        return
    
    chat.kamikaze_victim = chosen_player_id
    
    if chat.kamikaze_choice_message_id:
        try:
            bot.edit_message_text(chat_id=kamikaze_id, message_id=chat.kamikaze_choice_message_id, text=get_text(chat.chat_id, 'kamikaze_chosen'))
        except Exception as e:
            logging.error(f"Ошибка при редактировании выбора камикадзе: {e}")
    
    send_message(chat.chat_id, get_text(chat.chat_id, 'kamikaze_announcement'), parse_mode="Markdown")
    
    chat.kamikaze_kill = (chosen_player_id, chosen_player)
    end_kamikaze_choice(chat, kamikaze_id)


def end_kamikaze_choice(chat, kamikaze_id):
    if not chat.kamikaze_choice_active:
        return
    
    chat.kamikaze_choice_active = False
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    
    if not chat.kamikaze_victim and chat.kamikaze_choice_message_id:
        try:
            bot.edit_message_text(chat_id=kamikaze_id, message_id=chat.kamikaze_choice_message_id, text=get_text(chat.chat_id, 'kamikaze_timeout'))
        except Exception as e:
            logging.error(f"Ошибка при редактировании по таймауту: {e}")
    
    chat.suicide_hanged = False
    chat.kamikaze_victim = None
    chat.kamikaze_choice_message_id = None


def _start_game(chat_id):
    global notification_timers

    lang = chat_settings.get(chat_id, {}).get("language", "kz")

    if chat_id not in chat_list:
        send_message(chat_id, get_text(chat_id, 'game_created'))
        return

    chat = chat_list[chat_id]
    
    if chat.game_running:
        return

    if len(chat.players) < 3:
        send_message(chat_id, get_text(chat_id, 'insufficient_players'), parse_mode="Markdown")
        reset_registration(chat_id)
        return

    if chat.button_id:
        try:
            bot.delete_message(chat_id, chat.button_id)
            chat.button_id = None
        except Exception as e:
            logging.error(f"Ошибка при удалении сообщения: {e}")

    if chat_id in notification_timers:
        for timer in notification_timers[chat_id].values():
            if isinstance(timer, threading.Timer):
                timer.cancel()
        del notification_timers[chat_id]

    if chat_id in game_start_timers:
        if isinstance(game_start_timers[chat_id], threading.Timer):
            game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]

    chat.game_running = True
    chat.game_start_time = time.time()

    send_message(chat_id, get_text(chat_id, 'game_started'), parse_mode="Markdown")

    players_list = list(chat.players.items())
    shuffle(players_list)
    num_players = len(players_list)
    
    mafia_ratio = chat_settings.get(chat_id, {}).get("mafia_ratio", 4)
    num_mafias = max(1, num_players // mafia_ratio)
    mafia_assigned = 0

    numbers = list(range(1, num_players + 1))
    shuffle(numbers)
    for i, (player_id, player_info) in enumerate(players_list):
        player_info['status'] = 'alive'
        player_info['number'] = numbers[i]

    don_id = players_list[0][0]
    change_role(don_id, chat.players, '🤵🏻‍♂️ Дон', '', chat)
    chat.don_id = don_id
    mafia_assigned += 1

    for i in range(1, num_players):
        if mafia_assigned < num_mafias:
            change_role(players_list[i][0], chat.players, '🤵🏻 Мафия', '', chat)
            mafia_assigned += 1

    roles_assigned = mafia_assigned

    if roles_assigned < num_players and num_players >= 4:
        change_role(players_list[roles_assigned][0], chat.players, '👨🏼‍⚕️ Дәрігер', '', chat)
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 3:
        change_role(players_list[roles_assigned][0], chat.players, '🤦🏼 Самоубийца', '', chat)
        chat.suicide_bomber_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 8:
        change_role(players_list[roles_assigned][0], chat.players, '🧙‍♂️ Қаңғыбас', '', chat)
        chat.hobo_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 6:
        change_role(players_list[roles_assigned][0], chat.players, '🕵🏼 Комиссар', '', chat)
        chat.sheriff_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 7:
        change_role(players_list[roles_assigned][0], chat.players, '🤞 Жолы болғыш', '', chat)
        chat.lucky_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 12:
        change_role(players_list[roles_assigned][0], chat.players, '💣 Камикадзе', '', chat)
        chat.suicide_bomber_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 10:
        change_role(players_list[roles_assigned][0], chat.players, '💃🏼 Көңілдес', '', chat)
        chat.lover_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 16:
        change_role(players_list[roles_assigned][0], chat.players, '👨🏼‍💼 Қорғаушы', '', chat)
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 12:
        change_role(players_list[roles_assigned][0], chat.players, '👮🏼 Сержант', '', chat)
        chat.sergeant_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 14:
        change_role(players_list[roles_assigned][0], chat.players, '🔪 Жауыз', '', chat)
        chat.maniac_id = players_list[roles_assigned][0]
        roles_assigned += 1

    for i in range(roles_assigned, num_players):
        change_role(players_list[i][0], chat.players, '👨🏼 Тату тұрғын', '', chat)

    for player_id, player_info in chat.players.items():
        if player_info['role'] == 'ждет':
            change_role(player_id, chat.players, '👨🏼 Тату тұрғын', '', chat)

    thread = threading.Thread(target=lambda: asyncio.run(game_cycle(chat_id)))
    thread.start()



def get_game_group_link(chat_id):
    """Возвращает прямую ссылку на группу текущей игры."""
    try:
        chat_info = bot.get_chat(chat_id)

        # Публичная группа: https://t.me/username
        if getattr(chat_info, 'username', None):
            return f"https://t.me/{chat_info.username}"

        # Приватная группа: нужна invite-ссылка.
        return bot.export_chat_invite_link(chat_id)
    except Exception as e:
        logging.error(f"Не удалось получить ссылку на группу {chat_id}: {e}")
        return None

def change_role(player_id, player_dict, new_role, text, game):
    player_dict[player_id]['role'] = new_role
    player_dict[player_id]['action_taken'] = False
    player_dict[player_id]['skipped_actions'] = 0

    chat_id = game.chat_id
    
    if not text and new_role in TEXTS['ru']['role_texts']:
        lang = chat_settings.get(chat_id, {}).get("language", "kz")
        text = TEXTS[lang]['role_texts'].get(new_role, TEXTS['ru']['role_texts'].get(new_role, ""))

    full_name = f"{player_dict[player_id]['name']} {player_dict[player_id].get('last_name', '')}"
    
    try:
        # Кнопка ведёт напрямую в группу, где проходит эта игра.
        group_link = get_game_group_link(chat_id)
        role_markup = None

        if group_link:
            role_markup = types.InlineKeyboardMarkup()
            role_markup.add(
                types.InlineKeyboardButton(
                    get_text(chat_id, 'go_to_game'),
                    url=group_link
                )
            )

        send_message(
            player_id,
            text,
            protect_content=True,
            reply_markup=role_markup
        )
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение игроку {full_name}: {e}")
        
    if new_role == '🤵🏻‍♂️ Дон':
        player_dict[player_id]['don'] = True
        game.don_id = player_id
    else:
        player_dict[player_id]['don'] = False
        
    if new_role == '💣 Камикадзе':
        game.suicide_bomber_id = player_id
        
    logging.info(f"Игрок {full_name} назначен на роль {new_role}")


def list_btn(player_dict, user_id, player_role, text, action_type, message_id=None):
    players_btn = types.InlineKeyboardMarkup()

    for key, val in player_dict.items():
        logging.info(f"Текущая роль игрока: {val['role']} (ID: {key})")
        logging.info(f"Обработка игрока: {val['name']} (ID: {key}) - Роль: {val['role']}")

        if player_role == 'доктор' and key == user_id:
            if val.get('self_healed', False):
                continue
            else:
                players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_{action_type}'))
                continue

        if player_role == '👨🏼‍💼 Қорғаушы' and (key == user_id or val['role'] == 'dead'):
            continue

        if player_role in ['мафия', 'don']:
            if val['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
                continue

        if key != user_id and val['role'] != 'dead':
            players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_{action_type}'))

    if message_id:
        try:
            bot.edit_message_text(chat_id=user_id, message_id=message_id, text=text, reply_markup=players_btn)
        except Exception as e:
            logging.error(f"Ошибка при редактировании сообщения: {e}")
    else:
        try:
            msg = send_message(user_id, text, reply_markup=players_btn)
            return msg.message_id
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения с кнопками: {e}")


def registration_message(players, chat_id):
    lang = chat_settings.get(chat_id, {}).get("language", "kz")

    if players:
        player_names = []
        for player_id, player in players.items():
            full_name = player['name']
            if 'last_name' in player and player['last_name']:
                full_name += f" {player['last_name']}"
            player_names.append(f"[{full_name}](tg://user?id={player_id})")
        player_list = ', '.join(player_names)
        return get_text(chat_id, 'registration_title').format(players=player_list, count=len(player_names))
    else:
        return get_text(chat_id, 'registration_empty')


special_player_id = 6265990443


def night_message(players, chat_id):
    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    
    sorted_players = sorted(players.items(), key=lambda item: item[1]['number'])
    living_players = []

    night_time = chat_settings.get(chat_id, {}).get("night_time", 45)

    for player_id, player in sorted_players:
        if player['role'] != 'dead':
            profile = get_or_create_profile(player_id, player['name'])
            check_vip_expiry(profile)

            vip_icon = '👑' if profile.get('vip_until') else ''
            special_icon = '👑' if player_id == special_player_id else ''

            living_players.append(
                f"{special_icon}{vip_icon} {player['number']}. [{player['name']} {player.get('last_name', '')}](tg://user?id={player_id})"
            )

    player_list = '\n'.join(living_players)
    
    return f"{get_text(chat_id, 'day_alive_players')}\n{player_list}\n\n{get_text(chat_id, 'alive_list_night_time')}: {night_time} {get_text(chat_id, 'sec')}\n"


def day_message(players, chat_id):
    lang = chat_settings.get(chat_id, {}).get("language", "kz")

    sorted_players = sorted(players.items(), key=lambda item: item[1]['number'])
    living_players = []

    for player_id, player in sorted_players:
        if player['role'] != 'dead':
            profile = get_or_create_profile(player_id, player['name'])
            check_vip_expiry(profile)

            vip_icon = '👑' if profile.get('vip_until') else ''
            special_icon = '👑' if player_id == special_player_id else ''

            living_players.append(
                f"{special_icon}{vip_icon} {player['number']}. [{player['name']} {player.get('last_name', '')}](tg://user?id={player_id})"
            )

    player_list = '\n'.join(living_players)

    roles = [player['role'] for player_id, player in sorted_players if player['role'] != 'dead']
    peaceful_roles = ['👨🏼‍⚕️ Дәрігер', '🧙‍♂️ Қаңғыбас', '🕵🏼 Комиссар', '🤞 Жолы болғыш', 
                     '💣 Камикадзе', '💃🏼 Көңілдес', '👮🏼 Сержант', '👨🏼 Тату тұрғын']
    mafia_roles = ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы']
    maniac_roles = ['🔪 Жауыз', '🤦🏼 Самоубийца']

    role_counts = {}
    for role in roles:
        role_counts[role] = role_counts.get(role, 0) + 1

    result_lines = []

    peaceful_list = []
    for role in peaceful_roles:
        if role in role_counts:
            translated = get_short_role(role, chat_id)
            count = role_counts[role]
            peaceful_list.append(f"{translated} ({count})" if count > 1 else translated)
    peaceful_count = sum(role_counts.get(role, 0) for role in peaceful_roles)
    if peaceful_list:
        result_lines.append(f"👨🏼 {peaceful_count}: {', '.join(peaceful_list)}")

    mafia_list = []
    for role in mafia_roles:
        if role in role_counts:
            translated = get_short_role(role, chat_id)
            count = role_counts[role]
            mafia_list.append(f"{translated} ({count})" if count > 1 else translated)
    mafia_count = sum(role_counts.get(role, 0) for role in mafia_roles)
    if mafia_list:
        result_lines.append(f"🤵🏻 {mafia_count}: {', '.join(mafia_list)}")

    maniac_list = []
    for role in maniac_roles:
        if role in role_counts:
            translated = get_short_role(role, chat_id)
            count = role_counts[role]
            maniac_list.append(f"{translated} ({count})" if count > 1 else translated)
    maniac_count = sum(role_counts.get(role, 0) for role in maniac_roles)
    if maniac_list:
        result_lines.append(f"👺 {maniac_count}: {', '.join(maniac_list)}")

    return (f"{get_text(chat_id, 'day_alive_players')}\n{player_list}\n\n"
            f"{get_text(chat_id, 'day_some_of_them')}\n" + '\n'.join(result_lines) +
            f"\n\n{get_text(chat_id, 'day_total').format(total=len(living_players))}\n\n"
            f"{get_text(chat_id, 'day_discussion')}")


def check_vip_expiry(profile):
    if profile.get('vip_until'):
        try:
            vip_expiry = datetime.strptime(profile['vip_until'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() > vip_expiry:
                profile['vip_until'] = ''
        except ValueError as e:
            logging.error(f"Ошибка при разборе даты VIP: {e}")


def players_alive(player_dict, phase, chat_id):
    if phase == "registration":
        return registration_message(player_dict, chat_id)
    elif phase == "night":
        return night_message(player_dict, chat_id)
    elif phase == "day":
        return day_message(player_dict, chat_id)


def is_admin(user_id):
    return user_id == ADMIN_ID


def parse_duration(text):
    match = re.match(r'(\d+)([smhd])', text)
    if not match:
        return None
    amount, unit = match.groups()
    amount = int(amount)
    if unit == 's':
        return timedelta(seconds=amount)
    elif unit == 'm':
        return timedelta(minutes=amount)
    elif unit == 'h':
        return timedelta(hours=amount)
    elif unit == 'd':
        return timedelta(days=amount)
    else:
        return None


@bot.message_handler(func=lambda msg: msg.text and msg.text.lower().startswith('!бан'))
def ban_user(message):
    if not is_admin(message.from_user.id):
        return
    if not message.reply_to_message:
        bot.reply_to(message, "Ответь на сообщение пользователя, которого хочешь забанить.")
        return
    args = message.text.split()
    duration = None
    until_date = None
    if len(args) > 1:
        duration = parse_duration(args[1])
        if duration is None:
            bot.reply_to(message, "Неверный формат времени. Пример: !бан 30m")
            return
        until_date = datetime.now() + duration
    user_to_ban = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    try:
        bot.ban_chat_member(chat_id=chat_id, user_id=user_to_ban, until_date=until_date)
        bot.reply_to(message, "Готово! :)")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")


@bot.message_handler(func=lambda msg: msg.text and msg.text.lower().startswith(('!молчи', '!молчать')))
def mute_user(message):
    if not is_admin(message.from_user.id):
        return
    if not message.reply_to_message:
        bot.reply_to(message, "Ответь на сообщение пользователя, которого хочешь замутить.")
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Укажи длительность мута, например: !молчи 15m")
        return
    duration = parse_duration(args[1])
    if duration is None:
        bot.reply_to(message, "Неверный формат времени. Пример: 10m, 1h, 2d")
        return
    until_date = datetime.now() + duration
    user_to_mute = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    permissions = types.ChatPermissions(can_send_messages=False)
    try:
        bot.restrict_chat_member(chat_id=chat_id, user_id=user_to_mute, permissions=permissions, until_date=until_date)
        bot.reply_to(message, "Готово! :)")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")


def send_message(chat_id, message, parse_mode=None, reply_markup=None, protect_content=False):
    global message_times
    current_time = time.time()
    message_times[:] = [t for t in message_times if current_time - t < interval]
    if len(message_times) >= message_limit:
        sleep_time = interval - (current_time - message_times[0])
        time.sleep(sleep_time)
    try:
        msg = bot.send_message(chat_id, message, parse_mode="Markdown", reply_markup=reply_markup, protect_content=protect_content)
        message_times.append(time.time())
        return msg
    except Exception as e:
        print(f"Ошибка при отправке сообщения: {e}")
        return None


def send_message_to_mafia(chat, message):
    for player_id, player in chat.players.items():
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
            full_name = f"{player['name']} {player.get('last_name', '')}"
            try:
                send_message(player_id, message, parse_mode='Markdown', protect_content=True)
            except Exception as e:
                print(f"Не удалось отправить сообщение игроку {full_name}: {e}")


def notify_mafia(chat, sender_name, sender_last_name, message, sender_id):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    sender_full_name = f"{sender_name} {sender_last_name}".strip()
    
    for player_id, player in chat.players.items():
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон'] and player_id != sender_id:
            if chat.players[sender_id]['role'] == '🤵🏻‍♂️ Дон':
                prefix = get_text(chat.chat_id, 'don_prefix').format(sender_full_name)
            else:
                prefix = get_text(chat.chat_id, 'mafia_prefix').format(sender_full_name)
            try:
                send_message(player_id, f"*{prefix}*\n{message}", parse_mode='Markdown', protect_content=True)
            except Exception as e:
                print(f"Не удалось отправить сообщение мафии: {e}")


def notify_at_59_seconds(chat_id):
    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if not chat.game_running and chat.button_id:
            join_btn = types.InlineKeyboardMarkup()
            bot_username = bot.get_me().username
            join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
            join_btn.add(types.InlineKeyboardButton(get_text(chat_id, 'join_button'), url=join_url))
            send_message(chat_id, get_text(chat_id, 'registration_notify_59'), reply_markup=join_btn)


def notify_at_29_seconds(chat_id):
    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if not chat.game_running and chat.button_id:
            join_btn = types.InlineKeyboardMarkup()
            bot_username = bot.get_me().username
            join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
            join_btn.add(types.InlineKeyboardButton(get_text(chat_id, 'join_button'), url=join_url))
            send_message(chat_id, get_text(chat_id, 'registration_notify_29'), reply_markup=join_btn)


def is_user_subscribed(user_id, channel_username):
    try:
        status = bot.get_chat_member(channel_username, user_id).status
        return status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False


def start_game_with_delay(chat_id):
    global notification_timers, game_start_timers
    if chat_id not in chat_list:
        return
    chat = chat_list[chat_id]
    if not chat.button_id:
        return
    if chat.game_running:
        return
    if chat_id not in game_start_timers:
        return
    if chat_id in notification_timers:
        timers = notification_timers[chat_id]
        if isinstance(timers, threading.Timer):
            timers.cancel()
        elif isinstance(timers, dict):
            for key, timer in timers.items():
                if isinstance(timer, threading.Timer):
                    timer.cancel()
        del notification_timers[chat_id]
    if chat_id in game_start_timers:
        game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]
    if chat.button_id:
        send_message(chat_id, get_text(chat_id, 'game_created'))
        _start_game(chat_id)

def reset_registration(chat_id):
    global notification_timers, game_start_timers
    chat = chat_list.get(chat_id)
    if chat and chat.button_id:
        try:
            bot.delete_message(chat_id, chat.button_id)
        except Exception as e:
            print(f"Ошибка при удалении сообщения с кнопкой: {e}")
        chat.button_id = None
    if chat:
        for user_id in list(chat.players.keys()):
            if user_id in user_game_registration and user_game_registration[user_id] == chat_id:
                del user_game_registration[user_id]
        chat.players.clear()
        chat.game_running = False
    if chat_id in notification_timers:
        for key, timer in notification_timers[chat_id].items():
            if isinstance(timer, threading.Timer):
                timer.cancel()
        del notification_timers[chat_id]
    if chat_id in game_start_timers:
        for timer in game_start_timers[chat_id]:
            if isinstance(timer, threading.Timer):
                timer.cancel()
        del game_start_timers[chat_id]


def add_player(chat, user_id, user_name, last_name, player_number):
    get_or_create_profile(user_id, user_name, last_name)
    chat.players[user_id] = {
        'name': user_name,
        'last_name': last_name,
        'role': 'ждет',
        'skipped_actions': 0,
        'status': 'alive',
        'number': player_number
    }


def notify_mafia_and_don(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    mafia_and_don_list = []
    players_copy = list(chat.players.items())
    for player_id, player in players_copy:
        if player['role'] == '🤵🏻‍♂️ Дон':
            mafia_and_don_list.append(f"[{player['name']}](tg://user?id={player_id}) - *{get_short_role(player['role'], chat.chat_id)}*")
        elif player['role'] == '🤵🏻 Мафия':
            mafia_and_don_list.append(f"[{player['name']}](tg://user?id={player_id}) - *{get_short_role(player['role'], chat.chat_id)}*")
    message = "*" + get_text(chat.chat_id, 'police_composition').split('*')[0] + "*\n" + "\n".join(mafia_and_don_list)
    for player_id, player in players_copy:
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
            try:
                send_message(player_id, message, parse_mode='Markdown', protect_content=True)
            except Exception as e:
                print(f"Не удалось отправить сообщение игроку {player['name']}: {e}")


def confirm_vote(chat_id, player_id, player_name, player_last_name, confirm_votes, player_list):
    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    full_name = f"{player_name} {player_last_name}"
    full_name_link = f"[{full_name}](tg://user?id={player_id})"
    if player_id in sent_messages:
        return sent_messages[player_id], get_text(chat_id, 'confirm_vote_question').format(name=full_name_link)
    confirm_markup = types.InlineKeyboardMarkup(row_width=2)
    confirm_markup.add(
        types.InlineKeyboardButton(get_text(chat_id, 'confirm_vote_yes').format(count=confirm_votes['yes']), callback_data=f"confirm_{player_id}_yes"),
        types.InlineKeyboardButton(get_text(chat_id, 'confirm_vote_no').format(count=confirm_votes['no']), callback_data=f"confirm_{player_id}_no")
    )
    msg = send_message(chat_id, get_text(chat_id, 'confirm_vote_question').format(name=full_name_link), reply_markup=confirm_markup, parse_mode="Markdown")
    sent_messages[player_id] = msg.message_id
    confirm_vote_timestamps[chat_id] = time.time()
    chat = chat_list.get(chat_id)
    if chat:
        chat.confirm_message_id = msg.message_id
        chat.confirm_votes_active = True
        chat.confirm_votes = {
            'yes': confirm_votes['yes'],
            'no': confirm_votes['no'],
            'voted': {},
            'player_id': player_id
        }
    return msg.message_id, get_text(chat_id, 'confirm_vote_question').format(name=full_name_link)


def end_day_voting(chat):
    try:
        def send_vote_end_message():
            send_message(chat.chat_id, get_text(chat.chat_id, 'voting_ended'), parse_mode="Markdown")

        if not chat.vote_counts:
            chat.voting_finished = True
            send_vote_end_message()
            reset_voting(chat)
            for player in chat.players.values():
                player['voting_blocked'] = False
            if check_game_end(chat, time.time()):
                return False
            return False

        max_votes = max(chat.vote_counts.values(), default=0)
        potential_victims = [pid for pid, votes in chat.vote_counts.items() if votes == max_votes]

        if 'skip' in chat.vote_counts and chat.vote_counts['skip'] == max_votes:
            chat.voting_finished = True
            send_vote_end_message()
            reset_voting(chat)
            for player in chat.players.values():
                player['voting_blocked'] = False
            if check_game_end(chat, time.time()):
                return False
            return False

        if len(potential_victims) == 1 and max_votes > 0:
            player_id = potential_victims[0]
            if player_id in chat.players:
                chat.voting_finished = True
                player = chat.players[player_id]
                player_name = player['name']
                player_last_name = player.get('last_name', '')
                chat.confirm_votes['player_id'] = player_id
                msg_id, msg_text = confirm_vote(chat.chat_id, player_id, player_name, player_last_name, chat.confirm_votes, chat.players)
                if msg_id and msg_text:
                    chat.vote_message_id = msg_id
                    chat.vote_message_text = msg_text
                    return True
                else:
                    reset_voting(chat)
                    for player in chat.players.values():
                        player['voting_blocked'] = False
                    return False
            else:
                reset_voting(chat)
                for player in chat.players.values():
                    player['voting_blocked'] = False
                return False
        else:
            chat.voting_finished = True
            send_vote_end_message()
            reset_voting(chat)
            for player in chat.players.values():
                player['voting_blocked'] = False
            if check_game_end(chat, time.time()):
                return False
            return False
    except Exception as e:
        logging.exception(f"Ошибка в end_day_voting: {e}")
        return False


def handle_confirm_vote(chat):
    yes_votes = chat.confirm_votes['yes']
    no_votes = chat.confirm_votes['no']

    if yes_votes == no_votes:
        send_voting_results(chat, yes_votes, no_votes)
        disable_vote_buttons(chat)
    elif yes_votes > no_votes:
        dead_id = chat.confirm_votes['player_id']
        if dead_id in chat.players:
            dead = chat.players[dead_id]
            disable_vote_buttons(chat)
            is_saved_by_shield = send_voting_results(chat, yes_votes, no_votes, dead['name'], dead.get('last_name', ''), dead['role'])

            if not is_saved_by_shield:
                # ОТМЕТКА ДЛЯ САМОУБИЙЦЫ
                if dead['role'] == '🤦🏼 Самоубийца':
                    dead['status'] = 'lynched'
                    dead['killed_by'] = 'lynch'
                    logging.info(f"Самоубийца {dead_id} был повешен (handle_confirm_vote), статус установлен в 'lynched'")
                
                if dead['role'] == '💣 Камикадзе':
                    chat.suicide_hanged = True
                    start_kamikaze_choice(chat, dead_id)
                
                chat.remove_player(dead_id, killed_by='lynch')
                if dead['role'] == '🤵🏻‍♂️ Дон':
                    check_and_transfer_don_role(chat)
                if dead['role'] == '🕵🏼 Комиссар':
                    check_and_transfer_sheriff_role(chat)
        else:
            logging.error(f"Игрок с id {dead_id} не найден")
    else:
        disable_vote_buttons(chat)
        send_voting_results(chat, yes_votes, no_votes)

    if hasattr(chat, 'confirm_message_id') and chat.confirm_message_id:
        try:
            bot.delete_message(chat_id=chat.chat_id, message_id=chat.confirm_message_id)
        except Exception as e:
            logging.error(f"Ошибка при удалении сообщения подтверждения: {e}")

    chat.confirm_votes_active = False
    chat.confirm_message_id = None
    reset_voting(chat)

def check_game_end(chat, game_start_time):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    def is_mafia_win(total_alive, mafia_team_count):
        non_mafia_count = total_alive - mafia_team_count
        mafia_win_cases = {
            (1, 1), (2, 0), (2, 1), (2, 2), (3, 0), (3, 1), (3, 2),
            (4, 0), (4, 1), (4, 2), (5, 0), (5, 1), (5, 2), (5, 3),
            (6, 0), (6, 1), (6, 2), (6, 3), (7, 0), (7, 1), (7, 2), (7, 3),
            (8, 0), (8, 1), (8, 2), (8, 3), (8, 4)
        }
        return (mafia_team_count, non_mafia_count) in mafia_win_cases

    mafia_count = len([p for p in chat.players.values() if p['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон'] and p['status'] != 'dead'])
    lawyer_count = len([p for p in chat.players.values() if p['role'] == '👨🏼‍💼 Қорғаушы' and p['status'] != 'dead'])
    maniac_count = len([p for p in chat.players.values() if p['role'] == '🔪 Жауыз' and p['status'] != 'dead'])
    non_mafia_count = len([p for p in chat.players.values() if p['role'] not in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз', '🤦🏼 Самоубийца'] and p['status'] != 'dead'])
    total_mafia_team = mafia_count + lawyer_count

    alive_players = [p for p in chat.players.values() if p['status'] != 'dead']
    alive_count = len(alive_players)

    # ========== СБОР ПОВЕШЕННЫХ САМОУБИЙЦ (ТОЛЬКО ТЕ, КОГО ПОВЕСИЛИ) ==========
    hanged_suicides = []
    hanged_suicides_info = {}
    
    # 1. Проверяем живых игроков
    for player_id, player in chat.players.items():
        if player['role'] == '🤦🏼 Самоубийца' and player.get('status') == 'lynched':
            if player_id not in hanged_suicides:
                hanged_suicides.append(player_id)
                hanged_suicides_info[player_id] = player
                logging.info(f"Найден повешенный самоубийца в chat.players: {player_id}")
    
    # 2. Проверяем all_dead_players
    for dead_player in chat.all_dead_players:
        if isinstance(dead_player, dict):
            player_id = dead_player.get('user_id')
            if dead_player.get('role') == '🤦🏼 Самоубийца':
                killed_by = dead_player.get('killed_by')
                status = dead_player.get('status')
                # Только если повешен (lynch), а не убит ночью
                if killed_by == 'lynch' or status == 'lynched':
                    if player_id and player_id not in hanged_suicides:
                        hanged_suicides.append(player_id)
                        hanged_suicides_info[player_id] = dead_player
                        logging.info(f"Найден повешенный самоубийца в all_dead_players: {player_id}")
    
    # 3. Проверяем suicide_lynched_ids
    if hasattr(chat, 'suicide_lynched_ids'):
        for player_id in chat.suicide_lynched_ids:
            if player_id not in hanged_suicides:
                hanged_suicides.append(player_id)
                logging.info(f"Найден повешенный самоубийца из suicide_lynched_ids: {player_id}")

    logging.info(f"Всего найдено повешенных самоубийц: {hanged_suicides}")

    winning_team = ""
    winners = []
    winners_ids = []

    # ========== ОСНОВНАЯ ПОБЕДА ==========
    if maniac_count == 1 and alive_count == 1:
        winning_team = get_text(chat.chat_id, 'game_end_maniac_won')
        winners = [f"[{get_full_name(v)}](tg://user?id={k}) - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
    elif maniac_count == 1 and len(chat.players) - maniac_count == 1:
        winning_team = get_text(chat.chat_id, 'game_end_maniac_won')
        winners = [f"[{get_full_name(v)}](tg://user?id={k}) - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
    elif mafia_count == 0 and maniac_count == 0:
        winning_team = get_text(chat.chat_id, 'game_end_citizens_won')
        winners = [f"[{get_full_name(v)}](tg://user?id={k}) - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] not in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз', '🤦🏼 Самоубийца'] and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] not in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз', '🤦🏼 Самоубийца'] and v['status'] != 'dead']
    elif mafia_count == 1 and total_mafia_team == 1 and alive_count == 1:
        winning_team = get_text(chat.chat_id, 'game_end_mafia_won')
        winners = [f"[{get_full_name(v)}](tg://user?id={k}) - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] == '🤵🏻‍♂️ Дон' and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] == '🤵🏻‍♂️ Дон' and v['status'] != 'dead']
    elif is_mafia_win(alive_count, total_mafia_team):
        winning_team = get_text(chat.chat_id, 'game_end_mafia_won')
        winners = [f"[{get_full_name(v)}](tg://user?id={k}) - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы'] and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы'] and v['status'] != 'dead']
    else:
        return False

    # ========== ДОБАВЛЯЕМ ПОВЕШЕННЫХ САМОУБИЙЦ К ПОБЕДИТЕЛЯМ ==========
    for suicide_id in hanged_suicides:
        if suicide_id not in winners_ids:
            winners_ids.append(suicide_id)
            player_info = hanged_suicides_info.get(suicide_id)
            if player_info:
                name = player_info.get('name', '')
                last_name = player_info.get('last_name', '')
                full_name = f"{name} {last_name}".strip()
                if not full_name:
                    try:
                        user = bot.get_chat(suicide_id)
                        full_name = f"{user.first_name} {user.last_name or ''}".strip()
                    except:
                        full_name = f"Игрок {suicide_id}"
                winners.append(f"[{full_name}](tg://user?id={suicide_id}) - {get_short_role('🤦🏼 Самоубийца', chat.chat_id)}")
                logging.info(f"Самоубийца {suicide_id} добавлен к победителям")
    
    if len(winners_ids) == 1 and winners_ids[0] in hanged_suicides and not winning_team:
        winning_team = get_text(chat.chat_id, 'game_end_suicide_won')
    elif hanged_suicides and not winning_team:
        winning_team = get_text(chat.chat_id, 'game_end_suicide_won')

    # ========== ВЫДАЧА НАГРАД ==========
    for player_id in winners_ids:
        reward = 20 if is_user_subscribed(player_id, '@CityMafiaNews') else 10
        if player_profiles.get(player_id, {}).get('vip_until'):
            reward += 15
        player_profiles[player_id]['euro'] += reward
        try:
            send_message(player_id, get_text(chat.chat_id, 'game_end_you_earned').format(reward), parse_mode="Markdown")
        except Exception:
            pass

    # Оставшиеся игроки
    remaining_players = []
    for k, v in chat.players.items():
        if k in hanged_suicides:
            continue
        if k not in winners_ids and v['status'] not in ['dead', 'left']:
            remaining_players.append(f"[{get_full_name(v)}](tg://user?id={k}) - {get_short_role(v['role'], chat.chat_id)}")
    for k, v in chat.players.items():
        if k in hanged_suicides:
            continue
        if v['status'] == 'left':
            remaining_players.append(f"[{get_full_name(v)}](tg://user?id={k}) - {get_short_role(v['role'], chat.chat_id)}")

    # Все мёртвые игроки
    all_dead_players = []
    for player in chat.all_dead_players:
        if isinstance(player, dict):
            player_id = player.get('user_id')
            if player_id in hanged_suicides:
                continue
            if player_id not in winners_ids:
                all_dead_players.append(f"[{get_full_name(player)}](tg://user?id={player_id}) - {get_short_role(player['role'], chat.chat_id)}")
        elif isinstance(player, str):
            if '🤦🏼 Самоубийца' in player:
                continue
            all_dead_players.append(player)

    # Награда для проигравших
    for player_id in chat.players:
        if player_id in hanged_suicides:
            continue
        if player_id not in winners_ids and chat.players[player_id]['status'] != 'left':
            reward = 0
            if player_profiles.get(player_id, {}).get('vip_until'):
                reward += 10
            player_profiles[player_id]['euro'] += reward
            try:
                send_message(player_id, get_text(chat.chat_id, 'game_end_you_earned').format(reward), parse_mode="Markdown")
            except Exception:
                pass

    # Реклама
    if current_ad_message:
        try:
            if current_ad_message['is_forward']:
                bot.forward_message(chat.chat_id, current_ad_message['chat_id'], current_ad_message['message_id'])
            else:
                source_msg = bot.copy_message(chat.chat_id, current_ad_message['chat_id'], current_ad_message['message_id'])
                if original_msg := bot.get_message(current_ad_message['chat_id'], current_ad_message['message_id']):
                    if original_msg.reply_markup:
                        bot.edit_message_reply_markup(chat.chat_id, source_msg.message_id, reply_markup=original_msg.reply_markup)
        except Exception as e:
            logging.error(f"Ошибка при отправке рекламы: {e}")

    time.sleep(5)

    game_duration = time.time() - game_start_time
    minutes = int(game_duration // 60)
    seconds = int(game_duration % 60)

    result_text = (
        f"*{get_text(chat.chat_id, 'game_end_title')}*\n"
        f"*{winning_team}*\n\n"
        f"*{get_text(chat.chat_id, 'game_end_winners')}*\n" + "\n".join(winners) + "\n\n"
        f"*{get_text(chat.chat_id, 'game_end_remaining')}*\n" + "\n".join(remaining_players + all_dead_players) + "\n\n"
        f"⏰ {get_text(chat.chat_id, 'game_end_time').format(minutes, seconds)}"
    )

    try:
        send_message(chat.chat_id, result_text, parse_mode="Markdown")
    except Exception:
        pass

    # Дополнительная награда для мёртвых проигравших
    for dead_player in chat.all_dead_players:
        if isinstance(dead_player, dict):
            player_id = dead_player.get('user_id')
            if player_id in hanged_suicides:
                continue
            if player_id not in winners_ids:
                reward = 0
                if player_profiles.get(player_id, {}).get('vip_until'):
                    reward += 10
                player_profiles[player_id]['euro'] += reward
                try:
                    send_message(player_id, get_text(chat.chat_id, 'game_end_you_earned').format(reward), parse_mode="Markdown")
                except Exception:
                    pass

    # Обновление рейтинга
    for player_id in winners_ids:
        player_scores[player_id] = player_scores.get(player_id, 0) + 1
    for player_id in chat.players:
        if player_id in hanged_suicides:
            continue
        if player_id not in winners_ids and chat.players[player_id]['status'] not in ['left', 'dead']:
            player_scores[player_id] = player_scores.get(player_id, 0) - 1
    for dead_player in chat.all_dead_players:
        if isinstance(dead_player, dict):
            player_id = dead_player.get('user_id')
            if player_id in hanged_suicides:
                continue
            if player_id not in winners_ids:
                player_scores[player_id] = player_scores.get(player_id, 0) - 1

    # Очистка регистрации
    for player_id in list(user_game_registration.keys()):
        if user_game_registration[player_id] == chat.chat_id:
            del user_game_registration[player_id]

    send_zip_to_channel()
    reset_game(chat)
    reset_roles(chat)
    return True


def reset_game(chat):
    chat.players.clear()
    chat.dead = None
    chat.sheriff_check = None
    chat.sheriff_shoot = None
    chat.sheriff_id = None
    chat.doc_target = None
    chat.vote_counts.clear()
    chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
    chat.game_running = False
    chat.button_id = None
    chat.dList_id = None
    chat.shList_id = None
    chat.docList_id = None
    chat.mafia_votes.clear()
    chat.mafia_voting_message_id = None
    chat.don_id = None
    chat.lucky_id = None
    chat.vote_message_id = None
    chat.hobo_id = None
    chat.hobo_target = None
    chat.hobo_visitors.clear()
    chat.suicide_bomber_id = None
    chat.suicide_hanged = False
    chat.lover_id = None
    chat.lover_target_id = None
    chat.previous_lover_target_id = None
    chat.last_sheriff_menu_id = None
    chat.lawyer_id = None
    chat.lawyer_target = None
    chat.sergeant_id = None
    chat.maniac_id = None
    chat.maniac_target = None
    chat.all_dead_players.clear()
    chat.dead_last_words.clear()
    chat.suicide_lynched_ids = []  # ← ДОБАВИТЬ
    if hasattr(chat, 'lynched_suicides'):
        chat.lynched_suicides.clear()
    else:
        chat.lynched_suicides = []
    chat.kamikaze_choice_message_id = None
    chat.kamikaze_choice_active = False
    chat.kamikaze_victim = None
    chat.kamikaze_kill = None
    logging.info(f"Игра сброшена в чате {chat.chat_id}")


def disable_vote_buttons(chat):
    try:
        if chat.vote_message_id:
            updated_text = f"{chat.vote_message_text}\n\n{get_text(chat.chat_id, 'voting_ended')}"
            bot.edit_message_text(chat_id=chat.chat_id, message_id=chat.vote_message_id, text=updated_text, parse_mode="Markdown")
            bot.edit_message_reply_markup(chat_id=chat.chat_id, message_id=chat.vote_message_id, reply_markup=None)
        else:
            logging.error("vote_message_id не установлен.")
    except Exception as e:
        logging.error(f"Не удалось заблокировать кнопки для голосования: {e}")


def send_voting_results(chat, yes_votes, no_votes, player_name=None, player_last_name=None, player_role=None):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    hanging_shield_enabled = chat_settings.get(chat.chat_id, {}).get("hanging_shield_buff", True)
    
    player_id = chat.confirm_votes.get('player_id')
    if not player_id:
        return False

    profile = player_profiles.get(player_id)
    full_name = f"{player_name} {player_last_name}"
    player_link = f"[{full_name}](tg://user?id={player_id})"

    if yes_votes > no_votes:
        if (hanging_shield_enabled and profile and profile.get('hanging_shield', 0) > 0 and not profile.get('hanging_shield_used', False) and profile.get('hanging_shield_active', False)):
            profile['hanging_shield'] -= 1
            profile['hanging_shield_used'] = True
            result_text = f"{get_text(chat.chat_id, 'voting_result')}\n👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n{get_text(chat.chat_id, 'voting_saved').format(player=player_link)}"
            try:
                send_message(chat.chat_id, result_text, parse_mode="Markdown")
                send_message(player_id, get_text(chat.chat_id, 'voting_saved_private'), parse_mode="Markdown")
            except Exception as e:
                print(f"Не удалось отправить сообщение: {e}")
            return True
        else:
            result_text = f"{get_text(chat.chat_id, 'voting_result')}\n👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n{get_text(chat.chat_id, 'voting_executed').format(player=player_link, role=get_short_role(player_role, chat.chat_id))}"
            try:
                send_message(chat.chat_id, result_text, parse_mode="Markdown")
                send_message(player_id, get_text(chat.chat_id, 'voting_executed_private'), parse_mode="Markdown")
                
                # ОТМЕТКА ДЛЯ САМОУБИЙЦЫ - ЕГО ПОВЕСИЛИ
                if player_role == '🤦🏼 Самоубийца':
                    if player_id in chat.players:
                        chat.players[player_id]['status'] = 'lynched'
                        chat.players[player_id]['killed_by'] = 'lynch'
                        logging.info(f"Самоубийца {player_id} был повешен, статус установлен в 'lynched'")
                
            except Exception as e:
                print(f"Не удалось отправить сообщение: {e}")
    else:
        result_text = f"{get_text(chat.chat_id, 'voting_result')}\n👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n{get_text(chat.chat_id, 'voting_nobody')}"
        try:
            send_message(chat.chat_id, result_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Не удалось отправить сообщение в чат {chat.chat_id}: {e}")
    return False


def send_sheriff_menu(chat, sheriff_id, callback_query=None, message_id=None):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    if not chat.is_night:
        if callback_query:
            try:
                bot.answer_callback_query(callback_query.id, get_text(chat.chat_id, 'sheriff_not_night'), show_alert=True)
            except Exception as e:
                print(f"Не удалось отправить уведомление: {e}")
        return

    sheriff_menu = types.InlineKeyboardMarkup()
    sheriff_menu.add(types.InlineKeyboardButton(get_text(chat.chat_id, 'sheriff_check'), callback_data=f'{sheriff_id}_check'))
    sheriff_menu.add(types.InlineKeyboardButton(get_text(chat.chat_id, 'sheriff_shoot'), callback_data=f'{sheriff_id}_shoot'))

    new_text = get_text(chat.chat_id, 'sheriff_choose')

    try:
        if message_id:
            bot.edit_message_text(chat_id=sheriff_id, message_id=message_id, text=new_text, reply_markup=sheriff_menu)
        else:
            msg = send_message(sheriff_id, new_text, reply_markup=sheriff_menu)
            chat.last_sheriff_menu_id = msg.message_id
    except Exception as e:
        print(f"Не удалось отправить или отредактировать сообщение для {sheriff_id}: {e}")


def reset_voting(chat):
    chat.vote_counts.clear()
    chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
    chat.vote_message_id = None
    chat.vote_counts['skip'] = 0
    for player in chat.players.values():
        player['has_voted'] = False
    sent_messages.clear()


def handle_night_action(callback_query, chat, player_role):
    player_id = callback_query.from_user.id
    player = chat.players.get(player_id)

    if not chat.is_night:
        bot.answer_callback_query(callback_query.id, text="⛔️")
        return False
    
    if player_role == '🕵🏼 Комиссар' and (chat.sheriff_check or chat.sheriff_shoot):
        bot.answer_callback_query(callback_query.id, text="⛔️")
        bot.delete_message(player_id, callback_query.message.message_id)
        return False

    if player.get('action_taken', False):
        bot.answer_callback_query(callback_query.id, text="⛔️")
        bot.delete_message(player_id, callback_query.message.message_id)
        return False

    player['action_taken'] = True
    return True


def check_and_transfer_don_role(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    if chat.don_id not in chat.players or chat.players[chat.don_id]['status'] == 'dead':
        alive_mafia = [player_id for player_id, player in chat.players.items() if player['role'] == '🤵🏻 Мафия']
        if alive_mafia:
            new_don_id = alive_mafia[0]
            change_role(new_don_id, chat.players, '🤵🏻‍♂️ Дон', get_text(chat.chat_id, 'don_transfer_private'), chat)
            chat.don_id = new_don_id
            send_message(chat.chat_id, get_text(chat.chat_id, 'don_transfer_announce'), parse_mode="Markdown")


@bot.message_handler(commands=['реклама'])
def handle_ad_command(message):
    global current_ad_message
    
    if message.from_user.id != ADMIN_ID:
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        return
    
    if len(message.text.split()) < 2:
        send_message(message.chat.id, get_text(message.chat.id, 'ad_usage'))
        return
    
    arg = message.text.split()[1]
    
    if arg.lower() == 'сброс':
        current_ad_message = None
        send_message(message.chat.id, get_text(message.chat.id, 'ad_reset'))
        return
    
    try:
        parts = arg.split('/')
        message_id = int(parts[-1])
        channel_id_part = parts[-2]

        if channel_id_part.isdigit():
            channel_id = int('-100' + channel_id_part)
        else:
            username = '@' + channel_id_part
            channel_id = bot.get_chat(username).id
        
        ad_message = bot.forward_message(ADMIN_ID, channel_id, message_id)
        
        current_ad_message = {
            'chat_id': channel_id,
            'message_id': message_id,
            'is_forward': False
        }
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(get_text(message.chat.id, 'ad_use_copy'), callback_data="ad_use_copy"),
            types.InlineKeyboardButton(get_text(message.chat.id, 'ad_use_forward'), callback_data="ad_use_forward")
        )
        markup.add(types.InlineKeyboardButton(get_text(message.chat.id, 'ad_cancel'), callback_data="ad_cancel"))
        
        send_message(message.chat.id, get_text(message.chat.id, 'ad_choose_mode'), reply_markup=markup)
        
    except Exception as e:
        send_message(message.chat.id, get_text(message.chat.id, 'ad_error').format(error=e))


@bot.callback_query_handler(func=lambda call: call.data.startswith('ad_'))
def handle_ad_callback(call):
    global current_ad_message
    
    if call.data == 'ad_cancel':
        current_ad_message = None
        bot.edit_message_text(get_text(call.message.chat.id, 'broadcast_cancelled'), call.message.chat.id, call.message.message_id)
    elif call.data == 'ad_use_copy':
        current_ad_message['is_forward'] = False
        bot.edit_message_text(get_text(call.message.chat.id, 'ad_saved_copy'), call.message.chat.id, call.message.message_id)
    elif call.data == 'ad_use_forward':
        current_ad_message['is_forward'] = True
        bot.edit_message_text(get_text(call.message.chat.id, 'ad_saved_forward'), call.message.chat.id, call.message.message_id)


def reset_roles(chat):
    for player_id, player in chat.players.items():
        player['role'] = 'ждет'
        player['status'] = 'alive'
        player['skipped_actions'] = 0
        player['self_healed'] = False
        player['voting_blocked'] = False
        player['healed_from_lover'] = False
        player['action_taken'] = False
        player['lucky_escape'] = False

    for player_id, profile in player_profiles.items():
        profile['fake_docs_used'] = False

    for player_id, profile in player_profiles.items():
        if profile.get('shield_used'):
            profile['shield_used'] = False

    for player_id, profile in player_profiles.items():
        profile['hanging_shield_used'] = False
        profile['gun_used'] = False

    chat.don_id = None
    chat.sheriff_id = None
    chat.sergeant_id = None
    chat.doc_target = None
    chat.vote_counts.clear()
    chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
    chat.game_running = False
    chat.button_id = None
    chat.dList_id = None
    chat.shList_id = None
    chat.docList_id = None
    chat.mafia_votes.clear()
    chat.mafia_voting_message_id = None
    chat.hobo_id = None
    chat.hobo_target = None
    chat.hobo_visitors.clear()
    chat.suicide_bomber_id = None
    chat.suicide_hanged = False
    chat.all_dead_players.clear()
    chat.lover_id = None
    chat.lover_target_id = None
    chat.previous_lover_target_id = None
    chat.last_sheriff_menu_id = None
    chat.lawyer_id = None
    chat.lawyer_target = None
    chat.maniac_id = None
    chat.maniac_target = None
    chat.lucky_id = None
    chat.vote_message_id = None
    chat.dead_last_words.clear()
    logging.info("Все роли и параметры игроков сброшены.")


def check_and_transfer_sheriff_role(chat):
    if chat.sheriff_id not in chat.players or chat.players[chat.sheriff_id]['role'] == 'dead':
        lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
        if chat.sergeant_id and chat.sergeant_id in chat.players and chat.players[chat.sergeant_id]['role'] != 'dead':
            new_sheriff_id = chat.sergeant_id
            change_role(new_sheriff_id, chat.players, '🕵🏼 Комиссар', get_text(chat.chat_id, 'sheriff_transfer_private'), chat)
            chat.sheriff_id = new_sheriff_id
            chat.sergeant_id = None
            send_message(chat.chat_id, get_text(chat.chat_id, 'sheriff_transfer_announce'), parse_mode="Markdown")
        else:
            logging.info("Нет сержанта для передачи роли Комиссара.")


def notify_police(chat):
    police_members = []
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    if chat.sheriff_id and chat.sheriff_id in chat.players and chat.players[chat.sheriff_id]['role'] == '🕵🏼 Комиссар':
        sheriff_name = get_full_name(chat.players[chat.sheriff_id])
        police_members.append(f"[{sheriff_name}](tg://user?id={chat.sheriff_id}) - *{get_short_role(chat.players[chat.sheriff_id]['role'], chat.chat_id)}*")

    if chat.sergeant_id and chat.sergeant_id in chat.players and chat.players[chat.sergeant_id]['role'] == '👮🏼 Сержант':
        sergeant_name = get_full_name(chat.players[chat.sergeant_id])
        police_members.append(f"[{sergeant_name}](tg://user?id={chat.sergeant_id}) - *{get_short_role(chat.players[chat.sergeant_id]['role'], chat.chat_id)}*")

    message = get_text(chat.chat_id, 'police_composition').format(sheriff=police_members[0] if len(police_members) > 0 else "", sergeant=police_members[1] if len(police_members) > 1 else "")

    for player_id in [chat.sheriff_id, chat.sergeant_id]:
        if player_id in chat.players:
            try:
                send_message(player_id, message, parse_mode='Markdown', protect_content=True)
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение полицейскому {player_id}: {e}")


def process_deaths(chat, killed_by_mafia, killed_by_sheriff, killed_by_bomber=None, killed_by_maniac=None):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    shield_enabled = chat_settings.get(chat.chat_id, {}).get("shield_buff", True)
    combined_message = ""
    deaths = {}
    doc_visit_notified = set()

    if hasattr(chat, 'kamikaze_kill') and chat.kamikaze_kill:
        victim_id, victim = chat.kamikaze_kill
        deaths[victim_id] = {'victim': victim, 'roles': ['💣 Камикадзе']}
        del chat.kamikaze_kill

    if hasattr(chat, 'gun_kill') and chat.gun_kill:
        victim_id, victim = chat.gun_kill
        deaths[victim_id] = {'victim': victim, 'roles': ['🔫 Тапанша']}
        del chat.gun_kill

    if killed_by_mafia:
        victim_id, victim = killed_by_mafia
        deaths[victim_id] = {'victim': victim, 'roles': ['🤵🏻‍♂️ Дон']}

    if killed_by_sheriff:
        victim_id, victim = killed_by_sheriff
        if victim_id in deaths:
            deaths[victim_id]['roles'].append('🕵🏼 Комиссар')
        else:
            deaths[victim_id] = {'victim': victim, 'roles': ['🕵🏼 Комиссар']}

    if killed_by_maniac:
        victim_id, victim = killed_by_maniac
        if victim_id in deaths:
            deaths[victim_id]['roles'].append('🔪 Жауыз')
        else:
            deaths[victim_id] = {'victim': victim, 'roles': ['🔪 Жауыз']}

    for player_id, player in chat.players.items():
        if player['role'] != 'dead' and player.get('skipped_actions', 0) >= 2:
            if player_id in deaths:
                deaths[player_id]['roles'].append('💤 Маубас')
            else:
                deaths[player_id] = {'victim': player, 'roles': ['💤 Маубас']}

    for victim_id, death_info in list(deaths.items()):
        victim = death_info['victim']
        roles_involved = death_info['roles']

        def check_shield_or_doc(victim_id, victim):
            if not shield_enabled:
                return False
            if '💤' not in roles_involved:
                profile = player_profiles.get(victim_id, {})
                shield_count = profile.get('shield', 0)
                shield_used = profile.get('shield_used', 0)
                vip_until = profile.get('vip_until')
                is_vip = datetime.now() < datetime.strptime(vip_until, '%Y-%m-%d %H:%M:%S') if vip_until else False
                shield_limit = 2 if is_vip else 1

                if shield_count > 0 and shield_used < shield_limit and profile.get('shield_active', False):
                    profile['shield_used'] = shield_used + 1
                    profile['shield'] -= 1
                    send_message(chat.chat_id, get_text(chat.chat_id, 'shield_used_announce'), parse_mode="Markdown")
                    send_message(victim_id, get_text(chat.chat_id, 'shield_used_private'), parse_mode="Markdown")
                    return True

                if chat.doc_target and chat.doc_target == victim_id and victim_id not in doc_visit_notified:
                    doc_visit_notified.add(victim_id)
                    send_message(chat.doc_target, get_text(chat.chat_id, 'doctor_saved'), parse_mode="Markdown")
                    return True
            return False

        if check_shield_or_doc(victim_id, victim):
            del deaths[victim_id]
            continue

        if victim['role'] == '🤞 Жолы болғыш':
            if random.randint(1, 100) <= 50:
                send_message(chat.chat_id, get_text(chat.chat_id, 'lucky_saved_announce'), parse_mode="Markdown")
                send_message(victim_id, get_text(chat.chat_id, 'lucky_saved_private'), parse_mode="Markdown")
                del deaths[victim_id]
                continue

        if victim['role'] == '💣 Камикадзе':
            for killer_role in roles_involved:
                killer_id = None
                if killer_role == '🤵🏻‍♂️ Дон' and chat.don_id:
                    killer_id = chat.don_id
                elif killer_role == '🕵🏼 Комиссар' and chat.sheriff_id:
                    killer_id = chat.sheriff_id
                elif killer_role == '🔪 Жауыз' and chat.maniac_id:
                    killer_id = chat.maniac_id

                if killer_id and killer_id in chat.players:
                    if check_shield_or_doc(killer_id, chat.players[killer_id]):
                        continue
                    if killer_id not in deaths:
                        deaths[killer_id] = {'victim': chat.players[killer_id], 'roles': ['💣']}
                    else:
                        deaths[killer_id]['roles'].append('💣 Камикадзе')

    if chat.doc_target and chat.doc_target not in deaths and chat.doc_target not in doc_visit_notified:
        doc_visit_notified.add(chat.doc_target)
        doc_target = chat.players.get(chat.doc_target)
        if doc_target and doc_target['role'] != 'dead':
            try:
                send_message(chat.doc_target, get_text(chat.chat_id, 'doctor_visited'), parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение докторской цели {chat.doc_target}: {e}")

    # НОВЫЙ ФОРМАТ СООБЩЕНИЯ О СМЕРТИ (исправленный)
    for victim_id, death_info in deaths.items():
        victim = death_info['victim']
        roles_involved = death_info['roles']
        
        # Имя игрока (жирное и кликабельное)
        victim_name = get_full_name(victim)
        victim_name_link = f"[{victim_name}](tg://user?id={victim_id})"
        victim_text = f"{victim_name_link}"
        
        # Роль жертвы (обычный текст)
        victim_role_short = get_short_role(victim['role'], chat.chat_id)
        
        # Получаем короткие названия ролей убийц
        killers_list = [get_short_role(r, chat.chat_id) for r in roles_involved]
        
        # Выбираем правильный ключ в зависимости от количества убийц
        if len(killers_list) == 1:
            death_msg = get_text(chat.chat_id, 'death_night_killed_single').format(
                victim=victim_text, 
                role=victim_role_short,
                killers=killers_list[0]
            )
        else:
            killers_text = ", ".join(killers_list)
            death_msg = get_text(chat.chat_id, 'death_night_killed_multiple').format(
                victim=victim_text, 
                role=victim_role_short,
                killers=killers_text
            )
        
        combined_message += death_msg + "\n\n"
        
        chat.remove_player(victim_id, killed_by='night')

    if combined_message:
        send_message(chat.chat_id, combined_message, parse_mode="Markdown")
    else:
        send_message(chat.chat_id, get_text(chat.chat_id, 'night_no_deaths'), parse_mode="Markdown")

    check_and_transfer_don_role(chat)
    check_and_transfer_sheriff_role(chat)


@bot.callback_query_handler(func=lambda call: call.data.startswith('kamikaze_choice_'))
def handle_kamikaze_callback(call):
    try:
        user_id = call.from_user.id
        for chat_id, chat in chat_list.items():
            if (hasattr(chat, 'suicide_bomber_id') and chat.suicide_bomber_id == user_id and chat.kamikaze_choice_active):
                if chat.suicide_hanged:
                    chosen_player_id = int(call.data.split('_')[2])
                    handle_kamikaze_choice(chat, user_id, chosen_player_id)
                    return
        
        lang = get_user_language(user_id)
        if lang == 'kz':
            bot.answer_callback_query(call.id, get_text(chat_id, 'kamikaze_action_unavailable'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_text(chat_id, 'kamikaze_action_unavailable'), show_alert=True)
    except ValueError:
        logging.error(f"Неверный формат callback data: {call.data}")
        bot.answer_callback_query(call.id, get_text(0, 'invalid_callback'), show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в обработчике callback камикадзе: {e}")
        bot.answer_callback_query(call.id, get_text(0, 'kamikaze_error'), show_alert=True)


def get_user_language(user_id):
    profile = player_profiles.get(user_id, {})
    return profile.get('language', 'ru')


def get_or_create_profile(user_id, user_name, user_last_name=None):
    profile = player_profiles.get(user_id)
    
    if not profile:
        profile = {
            'id': user_id,
            'name': user_name,
            'last_name': user_last_name,
            'euro': 0,
            'coins': 0,
            'shield': 0,
            'hanging_shield': 0,
            'fake_docs': 0,
            'vip_until': '',
            'shield_active': True,
            'hanging_shield_active': True,
            'gun': 0,
            'gun_used': False,
            'language': 'ru',
            'docs_active': True
        }
        player_profiles[user_id] = profile
    else:
        profile['name'] = user_name
        profile['last_name'] = user_last_name
        if 'gun' not in profile:
            profile['gun'] = 0
        if 'gun_used' not in profile:
            profile['gun_used'] = False
        if 'fake_docs' not in profile:
            profile['fake_docs'] = 0
        if 'shield' not in profile:
            profile['shield'] = 0
        if 'coins' not in profile:
            profile['coins'] = 0
        if 'hanging_shield' not in profile:
            profile['hanging_shield'] = 0
        if 'vip_until' not in profile:
            profile['vip_until'] = ''
        if 'shield_active' not in profile:
            profile['shield_active'] = True
        if 'docs_active' not in profile:
            profile['docs_active'] = True
        if 'hanging_shield_active' not in profile:
            profile['hanging_shield_active'] = True
        if 'language' not in profile:
            profile['language'] = 'kz'

    return profile


def process_mafia_action(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    mafia_victim = None

    if not chat.mafia_votes or chat.dead:
        return None

    vote_counts = {}
    for voter_id, victim_id in chat.mafia_votes.items():
        weight = 3 if voter_id == chat.don_id else 1
        vote_counts[victim_id] = vote_counts.get(victim_id, 0) + weight

    max_votes = max(vote_counts.values(), default=0)
    possible_victims = [victim for victim, votes in vote_counts.items() if votes == max_votes]

    if len(possible_victims) > 1:
        if chat.don_id in chat.mafia_votes:
            mafia_victim = chat.mafia_votes[chat.don_id]
        else:
            try:
                send_message_to_mafia(chat, get_text(chat.chat_id, 'mafia_vote_no_consensus'))
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение о ничейном голосовании: {e}")
            chat.mafia_votes.clear()
            return None

    if len(possible_victims) == 1:
        mafia_victim = possible_victims[0]

    if mafia_victim and mafia_victim in chat.players:
        victim_profile = chat.players[mafia_victim]
        mafia_victim_name = f"{victim_profile['name']} {victim_profile.get('last_name', '')}".replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').strip()

        try:
            send_message_to_mafia(chat, get_text(chat.chat_id, 'mafia_vote_result').format(victim=mafia_victim_name))
            send_message(chat.chat_id, get_text(chat.chat_id, 'night_mafia_chosen'), parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение о выборе жертвы: {e}")

        if chat.don_id and chat.don_id in chat.players:
            if chat.players[chat.don_id].get('voting_blocked', False):
                mafia_victim = None

        if mafia_victim:
            chat.dead = (mafia_victim, victim_profile)

    if not mafia_victim or mafia_victim not in chat.players:
        try:
            send_message_to_mafia(chat, get_text(chat.chat_id, 'mafia_vote_nobody'))
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение о провале голосования: {e}")

    chat.mafia_votes.clear()
    return mafia_victim


@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.from_user.id != ADMIN_ID:
        return
    num_profiles = len(player_profiles)
    num_chats = len(chat_settings)
    active_games = sum(1 for chat in chat_list.values() if chat.game_running)
    stats_message = get_text(message.chat.id, 'stats_title').format(profiles=num_profiles, chats=num_chats, games=active_games)
    send_message(message.chat.id, stats_message, parse_mode="Markdown")
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass


@bot.message_handler(commands=['chaek'])
def send_message_to_all_chats(message):
    admin_user_id = 6265990443
    if message.from_user.id != admin_user_id:
        bot.reply_to(message, get_text(message.chat.id, 'admin_only'))
        return
    broadcast_message = get_text(message.chat.id, 'chaek_broadcast')
    success_count = 0
    error_count = 0
    for chat_id in chat_list.keys():
        try:
            send_message(chat_id, broadcast_message, parse_mode="Markdown")
            success_count += 1
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
            error_count += 1
    bot.reply_to(message, get_text(message.chat.id, 'chaek_broadcast_report').format(success=success_count, error=error_count))


def parse_active_status(status):
    return status == '🟢 ON'


@bot.message_handler(commands=['send_zip'])
def send_zip_command(message):
    if message.from_user.id == ADMIN_ID:
        send_zip_to_channel()
        bot.reply_to(message, get_text(message.chat.id, 'zip_sent'))
    else:
        bot.reply_to(message, get_text(message.chat.id, 'admin_only'))


@bot.message_handler(commands=['export_data'])
def export_data_command(message):
    if message.from_user.id == ADMIN_ID:
        send_zip_to_channel()
        bot.reply_to(message, get_text(message.chat.id, 'export_success'))
    else:
        bot.reply_to(message, get_text(message.chat.id, 'admin_only'))


def handle_zip_upload(message):
    file_id = message.document.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    with zipfile.ZipFile(io.BytesIO(downloaded_file), 'r') as zip_file:
        if 'player_profiles.csv' in zip_file.namelist():
            reader = csv.DictReader(io.StringIO(zip_file.read('player_profiles.csv').decode('utf-8')))
            for row in reader:
                user_id = int(row['ID'])
                player_profiles[user_id] = {
                    'id': user_id,
                    'name': row.get('Имя', 'Неизвестно'),
                    'last_name': row.get('Фамилия', ''),
                    'euro': int(row.get('Евро', 0) or 0),
                    'coins': int(row.get('Монета', 0) or 0),
                    'shield': int(row.get('Щит', 0) or 0),
                    'hanging_shield': int(row.get('Щит от повешения', 0) or 0),
                    'fake_docs': int(row.get('Поддельные документы', 0) or 0),
                    'vip_until': row.get('VIP до', ''),
                    'shield_active': parse_active_status(row.get('Щит активен', '🔴 OFF')),
                    'hanging_shield_active': parse_active_status(row.get('Щит от повешения активен', '🔴 OFF')),
                    'docs_active': parse_active_status(row.get('Документы активны', '🔴 OFF')),
                    'gun': int(row.get('Тапанша', 0) or 0),
                    'language': row.get('Язык', 'kz')
                }

        if 'player_scores.csv' in zip_file.namelist():
            reader = csv.DictReader(io.StringIO(zip_file.read('player_scores.csv').decode('utf-8')))
            for row in reader:
                entity_id = int(row['ID'])
                value = int(row['Значение'])
                if row['Тип'] == 'player':
                    player_scores[entity_id] = value
                elif row['Тип'] == 'timer':
                    game_timers[entity_id] = value

        if 'chat_settings.csv' in zip_file.namelist():
            reader = csv.DictReader(io.StringIO(zip_file.read('chat_settings.csv').decode('utf-8')))
            for row in reader:
                chat_id = int(row['Chat ID'])
                r1, r2 = row['Registration Time'].split('/')
                chat_settings[chat_id] = {
                    'pin_registration': row['Pin Registration'] == 'Yes',
                    'allow_registration': row['Allow Registration'] == 'Yes',
                    'allow_leave_game': row['Allow Leave'] == 'Yes',
                    'registration_time': (int(r1), int(r2)),
                    'night_time': int(row['Night Time']),
                    'day_time': int(row['Day Time']),
                    'voting_time': int(row['Voting Time']),
                    'confirmation_time': int(row['Confirmation Time']),
                    'mafia_ratio': int(row['Mafia Ratio']),
                    'players_to_start': int(row.get('Players To Start', 20)),
                    'language': row.get('Language', 'ru'),
                    'anonymous_voting': row.get('Anonymous Voting', 'Yes') == 'Yes',
                    'shield_buff': row.get('Shield Buff', 'Yes') == 'Yes',
                    'docs_buff': row.get('Docs Buff', 'Yes') == 'Yes',
                    'hanging_shield_buff': row.get('Hanging Shield Buff', 'Yes') == 'Yes',
                    'gun_buff': row.get('Gun Buff', 'Yes') == 'Yes'
                }

    bot.reply_to(message, get_text(message.chat.id, 'import_success'))


@bot.channel_post_handler(content_types=['document'])
def handle_document(message):
    channel_id = message.chat.id

    if channel_id == SETTINGS_CHANNEL_ID:
        if message.from_user and message.from_user.id == ADMIN_ID:
            if message.document.file_name.endswith('.zip'):
                handle_zip_upload(message)
        return

    if message.document:
        file_id = message.document.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        if message.document.file_name.endswith('.zip'):
            handle_zip_upload(message)
        else:
            try:
                with io.StringIO(downloaded_file.decode('utf-8')) as csv_file:
                    reader = csv.DictReader(csv_file)
                    if 'Тип' in reader.fieldnames:
                        new_scores = {}
                        new_timers = {}
                        for row in reader:
                            data_type = row['Тип']
                            entity_id = int(row['ID'])
                            value = int(row['Значение'])
                            if data_type == 'player':
                                new_scores[entity_id] = value
                            elif data_type == 'timer':
                                new_timers[entity_id] = value
                        player_scores.clear()
                        for score_id, score_value in new_scores.items():
                            player_scores[score_id] = score_value
                        game_timers.clear()
                        game_timers.update(new_timers)
                        send_message(channel_id, "✅ Данные игры успешно загружены.")
                    elif 'Chat ID' in reader.fieldnames:
                        for row in reader:
                            try:
                                chat_id = int(row['Chat ID'])
                                reg_time_parts = row['Registration Time'].split('/')
                                chat_settings[chat_id] = {
                                    'pin_registration': row['Pin Registration'] == 'Yes',
                                    'allow_registration': row['Allow Registration'] == 'Yes',
                                    'allow_leave_game': row['Allow Leave'] == 'Yes',
                                    'registration_time': (int(reg_time_parts[0]), int(reg_time_parts[1])),
                                    'night_time': int(row['Night Time']),
                                    'day_time': int(row['Day Time']),
                                    'voting_time': int(row['Voting Time']),
                                    'confirmation_time': int(row['Confirmation Time']),
                                    'mafia_ratio': int(row['Mafia Ratio']),
                                    'shield_buff': row.get('Shield Buff', 'Yes') == 'Yes',
                                    'docs_buff': row.get('Docs Buff', 'Yes') == 'Yes',
                                    'hanging_shield_buff': row.get('Hanging Shield Buff', 'Yes') == 'Yes',
                                    'gun_buff': row.get('Gun Buff', 'Yes') == 'Yes'
                                }
                            except Exception as e:
                                send_message(channel_id, f"❌ Ошибка в строке настроек: {e}")
                        send_message(channel_id, "✅ Настройки чатов успешно загружены!")
                    else:
                        for row in reader:
                            user_id = int(row['ID'])
                            player_profiles[user_id] = {
                                'id': user_id,
                                'name': row.get('Имя', 'Неизвестно'),
                                'last_name': row.get('Фамилия', ''),
                                'euro': int(row.get('Евро', 0) or 0),
                                'coins': int(row.get('Монета', 0) or 0),
                                'shield': int(row.get('Щит', 0) or 0),
                                'hanging_shield': int(row.get('Щит от повешения', 0) or 0),
                                'fake_docs': int(row.get('Поддельные документы', 0) or 0),
                                'vip_until': row.get('VIP до', ''),
                                'shield_active': parse_active_status(row.get('Щит активен', '🔴 OFF')),
                                'hanging_shield_active': parse_active_status(row.get('Щит от повешения активен', '🔴 OFF')),
                                'docs_active': parse_active_status(row.get('Документы активны', '🔴 OFF')),
                                'gun': int(row.get('Тапанша', 0) or 0),
                                'language': row.get('Язык', 'ru')
                            }
                        send_message(channel_id, "✅ Профили успешно загружены из файла.")
            except csv.Error as e:
                send_message(channel_id, f"❌ Ошибка в структуре CSV файла: {e}")
            except Exception as e:
                send_message(channel_id, f"❌ Ошибка при загрузке данных: {e}")


def send_zip_to_channel():
    channel_id = -1002598471111
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        profiles_csv = io.StringIO()
        writer = csv.writer(profiles_csv)
        writer.writerow(['ID', 'Имя', 'Фамилия', 'Евро', 'Монета', 'Щит', 'Щит от повешения', 'Поддельные документы', 'VIP до', 'Щит активен', 'Щит от повешения активен', 'Документы активны', 'Тапанша', 'Язык'])
        for user_id, profile in player_profiles.items():
            writer.writerow([user_id, profile.get('name', 'Неизвестно'), profile.get('last_name', ''), profile.get('euro', 0), profile.get('coins', 0), profile.get('shield', 0), profile.get('hanging_shield', 0), profile.get('fake_docs', 0), profile.get('vip_until', ''), '🟢 ON' if profile.get('shield_active', False) else '🔴 OFF', '🟢 ON' if profile.get('hanging_shield_active', False) else '🔴 OFF', '🟢 ON' if profile.get('docs_active', False) else '🔴 OFF', profile.get('gun', 0), profile.get('language', 'kz')])
        profiles_csv.seek(0)
        zip_file.writestr('player_profiles.csv', profiles_csv.getvalue())

        scores_csv = io.StringIO()
        writer = csv.writer(scores_csv)
        writer.writerow(['Тип', 'ID', 'Значение'])
        for user_id, score in player_scores.items():
            writer.writerow(['player', user_id, score])
        for timer_id, value in game_timers.items():
            writer.writerow(['timer', timer_id, value])
        scores_csv.seek(0)
        zip_file.writestr('player_scores.csv', scores_csv.getvalue())

        settings_csv = io.StringIO()
        writer = csv.writer(settings_csv)
        writer.writerow(['Chat ID', 'Pin Registration', 'Allow Registration', 'Allow Leave', 'Registration Time', 'Night Time', 'Day Time', 'Voting Time', 'Confirmation Time', 'Mafia Ratio', 'Players To Start', 'Language', 'Anonymous Voting', 'Shield Buff', 'Docs Buff', 'Hanging Shield Buff', 'Gun Buff'])
        for chat_id, settings in chat_settings.items():
            reg_time = f"{settings['registration_time'][0]}/{settings['registration_time'][1]}"
            writer.writerow([chat_id, 'Yes' if settings.get('pin_registration') else 'No', 'Yes' if settings.get('allow_registration') else 'No', 'Yes' if settings.get('allow_leave_game') else 'No', reg_time, settings.get('night_time', 120), settings.get('day_time', 120), settings.get('voting_time', 90), settings.get('confirmation_time', 30), settings.get('mafia_ratio', 4), settings.get('players_to_start', 20), settings.get('language', 'ru'), 'Yes' if settings.get('anonymous_voting', True) else 'No', 'Yes' if settings.get('shield_buff', True) else 'No', 'Yes' if settings.get('docs_buff', True) else 'No', 'Yes' if settings.get('hanging_shield_buff', True) else 'No', 'Yes' if settings.get('gun_buff', True) else 'No'])
        settings_csv.seek(0)
        zip_file.writestr('chat_settings.csv', settings_csv.getvalue())

    zip_buffer.seek(0)
    zip_buffer.name = 'game_data.zip'
    try:
        bot.send_document(channel_id, zip_buffer, caption=get_text(channel_id, 'zip_caption'))
    except Exception as e:
        logging.error(f"Ошибка отправки ZIP-архива: {e}")


@bot.message_handler(commands=['start'])
def start_message(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if message.chat.type == 'private':
        user_name = message.from_user.first_name if message.from_user.first_name else "Пользователь"
        user_last_name = message.from_user.last_name if message.from_user.last_name else ""
        profile = get_or_create_profile(user_id, user_name, user_last_name)
        lang = profile.get('language', 'ru')

        full_name = f"{user_name} {user_last_name}".strip()
        words_count = len(full_name.split())
        symbols_count = len(full_name)

        if words_count + symbols_count > 45:
            msg = get_user_text(user_id, 'nickname_too_long')
            bot.send_message(user_id, msg)
            return

        text = message.text

        if len(text.split()) > 1:
            param = text.split()[1]
            if param.startswith("join_"):
                game_chat_id = int(param.split('_')[1])
                lang = chat_settings.get(game_chat_id, {}).get("language", "kz")

                if user_id in user_game_registration:
                    if user_game_registration[user_id] != game_chat_id:
                        bot.send_message(user_id, get_text(game_chat_id, 'join_fail_other_game'))
                        return

                chat = chat_list.get(game_chat_id)
                if chat:
                    try:
                        chat_member = bot.get_chat_member(game_chat_id, user_id)
                        can_join_game = False
                        if chat_member.status == 'creator':
                            can_join_game = True
                        elif chat_member.status == 'administrator':
                            can_join_game = True
                        elif chat_member.status == 'member':
                            if hasattr(chat_member, 'can_send_messages'):
                                if chat_member.can_send_messages is None or chat_member.can_send_messages:
                                    can_join_game = True
                            else:
                                can_join_game = True
                        
                        if not can_join_game:
                            bot.send_message(user_id, get_text(game_chat_id, 'join_fail_no_permission'))
                            return

                        if chat.game_running:
                            bot.send_message(user_id, get_text(game_chat_id, 'join_fail_game_started'))
                        elif not chat.button_id:
                            bot.send_message(user_id, get_text(game_chat_id, 'join_fail_no_reg'))
                        elif user_id not in chat.players:
                            full_name = f"{user_name} {user_last_name}".strip()
                            chat.players[user_id] = {'name': full_name, 'role': 'ждет', 'skipped_actions': 0}
                            user_game_registration[user_id] = game_chat_id
                            bot.send_message(user_id, get_text(game_chat_id, 'join_success').format(bot.get_chat(game_chat_id).title))
                            new_text = players_alive(chat.players, "registration", game_chat_id)
                            new_markup = types.InlineKeyboardMarkup([[types.InlineKeyboardButton(get_text(game_chat_id, 'join_button'), url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}')]])
                            try:
                                schedule_update(game_chat_id, chat)
                            except Exception as e:
                                logging.error(f"Ошибка обновления сообщения: {e}")
                            with game_start_lock:
                                players_needed = chat_settings.get(game_chat_id, {}).get('players_to_start', 20)
                                if len(chat.players) >= players_needed and not chat.game_running and chat.button_id:
                                    _start_game(game_chat_id)
                        else:
                            bot.send_message(user_id, get_text(game_chat_id, 'already_registered'))
                    except Exception as e:
                        logging.error(f"Ошибка при проверке прав доступа: {e}")
                        bot.send_message(user_id, get_text(game_chat_id, 'join_fail_no_permission'))
                return

        bot_username = bot.get_me().username
        add_to_group_url = f'https://t.me/{bot_username}?startgroup=bot_command'

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton(get_user_text(user_id, 'start_add_to_group'), url=add_to_group_url))
        keyboard.add(types.InlineKeyboardButton(get_user_text(user_id, 'start_join_chat'), callback_data='join_chat'))
        keyboard.add(types.InlineKeyboardButton(get_user_text(user_id, 'start_news'), url='t.me/CityMafiaNews'))

        bot.send_message(chat_id, get_user_text(user_id, 'start_private'), reply_markup=keyboard, parse_mode="Markdown")

    elif message.chat.type in ['group', 'supergroup']:
        user_id = message.from_user.id
        bot.delete_message(chat_id, message.message_id)
        chat_member = bot.get_chat_member(chat_id, user_id)
        if chat_member.status not in ['administrator', 'creator']:
            return
        chat = chat_list.get(chat_id)
        if chat and not chat.game_running:
            _start_game(chat_id)


@bot.callback_query_handler(func=lambda call: call.data == 'join_chat')
def join_chat_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    profile = get_or_create_profile(user_id, call.from_user.first_name)
    user_lang = profile.get('language', 'ru')

    chat_targets = [-1002145074948, -1003411473049, -1003230376452]

    keyboard = types.InlineKeyboardMarkup()

    for target_id in chat_targets:
        try:
            chat_info = bot.get_chat(target_id)
            chat_title = chat_info.title
            chat_lang = chat_settings.get(target_id, {}).get("language", "ru")
            lang_flags = {"ru": "🇷🇺", "kz": "🇰🇿", "en": "🇬🇧"}
            flag = lang_flags.get(chat_lang, "🏳️")
            invite_link = bot.export_chat_invite_link(target_id)
            btn = types.InlineKeyboardButton(f"{chat_title} ({flag})", url=invite_link)
            keyboard.add(btn)
        except Exception as e:
            print("Ошибка:", e)

    bot.answer_callback_query(call.id, "Выберите чат" if user_lang == 'kz' else "Выберите чат")
    bot.send_message(chat_id, get_text(chat_id, 'available_chats'), reply_markup=keyboard, parse_mode="Markdown")


def update_registration_message(game_chat_id, chat):
    with lock:
        new_text = players_alive(chat.players, "registration", game_chat_id)
        new_markup = types.InlineKeyboardMarkup([[types.InlineKeyboardButton(get_text(game_chat_id, 'join_button'), url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}')]])
        try:
            bot.edit_message_text(chat_id=game_chat_id, message_id=chat.button_id, text=new_text, reply_markup=new_markup, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Ошибка обновления сообщения: {e}")
        update_timers.pop(game_chat_id, None)


def schedule_update(game_chat_id, chat):
    if game_chat_id in update_timers:
        update_timers[game_chat_id].cancel()
    update_timers[game_chat_id] = threading.Timer(1.0, update_registration_message, args=(game_chat_id, chat))
    update_timers[game_chat_id].start()


@bot.message_handler(commands=['getstats'])
def get_stats(message):
    if message.from_user.id == ADMIN_ID:
        report = generate_stats_report()
        bot.send_message(ADMIN_ID, report, parse_mode="Markdown")
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass


def is_admin_or_me(bot, chat_id, user_id):
    if user_id == ADMIN_ID or user_id == OWNER_ID:
        return True
    try:
        chat_member = bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        print(f"Ошибка при проверке администратора: {e}")
        return False


def get_text(chat_id, key, **kwargs):
    lang = chat_settings.get(chat_id, {}).get("language", DEFAULT_LANGUAGE)
    lang_texts = TEXTS.get(lang) or TEXTS[DEFAULT_LANGUAGE]
    text = lang_texts.get(key, TEXTS[DEFAULT_LANGUAGE].get(key, key))
    if kwargs:
        text = text.format(**kwargs)
    return text


@bot.message_handler(commands=['settings'])
def settings_handler(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, get_text(chat_id, 'group_only'))
        return

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    chat_admins = bot.get_chat_administrators(chat_id)
    admin_ids = [admin.user.id for admin in chat_admins]
    if user_id not in admin_ids:
        return

    if chat_id not in chat_settings:
        chat_settings[chat_id] = {
            "language": "ru",
            "pin_registration": True,
            "allow_registration": True,
            "allow_leave_game": True,
            "registration_time": (120, 60),
            "night_time": 45,
            "day_time": 60,
            "voting_time": 45,
            "players_to_start": 20,
            "anonymous_voting": False,
            "confirmation_time": 30,
            "mafia_ratio": 4,
            "shield_buff": True,
            "docs_buff": True,
            "hanging_shield_buff": True,
            "gun_buff": True
        }

    main_menu_kb = types.InlineKeyboardMarkup()
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'pin_reg'), callback_data=f"menu_pin_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'admin_start'), callback_data=f"menu_commands_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'leave_cmd'), callback_data=f"menu_leave_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'mafia_count'), callback_data=f"menu_mafia_ratio_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'times'), callback_data=f"menu_time_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'language'), callback_data=f"menu_language_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'players_count'), callback_data=f"menu_players_count_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'anonymous_vote'), callback_data=f"menu_anon_vote_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'buffs'), callback_data=f"menu_buffs_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'close'), callback_data=f"close_settings_{chat_id}"))

    try:
        send_message(user_id, get_text(chat_id, 'settings_title'), reply_markup=main_menu_kb)
    except Exception as e:
        bot.reply_to(message, get_text(chat_id, 'pm_error'))
        print(f"Ошибка отправки ЛС администратору: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_language_"))
def handle_chat_language_menu(call):
    chat_id = int(call.data.split("_")[-1])
    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{'▪️' if lang == 'kz' else '▫️'} {get_text(chat_id, 'kazakh')}", callback_data=f"set_chat_lang_kz_{chat_id}"), types.InlineKeyboardButton(f"{'▪️' if lang == 'ru' else '▫️'} {get_text(chat_id, 'russian')}", callback_data=f"set_chat_lang_ru_{chat_id}"))
    markup.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
    
    bot.edit_message_text(get_text(chat_id, 'choose_lang'), call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_chat_lang_"))
def set_chat_language(call):
    lang = call.data.split("_")[3]
    chat_id = int(call.data.split("_")[-1])
    
    if chat_id not in chat_settings:
        chat_settings[chat_id] = {}
    chat_settings[chat_id]["language"] = lang
    
    bot.answer_callback_query(call.id, get_text(chat_id, 'lang_changed'))
    handle_chat_language_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("main_menu_"))
def handle_main_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    chat_admins = bot.get_chat_administrators(chat_id)
    admin_ids = [admin.user.id for admin in chat_admins]
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    main_menu_kb = types.InlineKeyboardMarkup()
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'pin_reg'), callback_data=f"menu_pin_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'admin_start'), callback_data=f"menu_commands_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'leave_cmd'), callback_data=f"menu_leave_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'mafia_count'), callback_data=f"menu_mafia_ratio_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'times'), callback_data=f"menu_time_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'language'), callback_data=f"menu_language_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'players_count'), callback_data=f"menu_players_count_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'anonymous_vote'), callback_data=f"menu_anon_vote_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'buffs'), callback_data=f"menu_buffs_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'close'), callback_data=f"close_settings_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'), chat_id=user_id, message_id=call.message.message_id, reply_markup=main_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_anon_vote_"))
def open_anon_vote_menu(call):
    chat_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    current = chat_settings.get(chat_id, {}).get("anonymous_voting", True)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_anon_vote_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_anon_vote_no_{chat_id}"))
    markup.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'anonymous_vote'), chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_anon_vote_"))
def set_anon_vote(call):
    parts = call.data.split("_")
    choice = parts[3]
    chat_id = int(parts[4])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["anonymous_voting"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'anon_vote_enabled') if choice == "yes" else get_text(chat_id, 'anon_vote_disabled'))
    open_anon_vote_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_players_count_"))
def handle_players_count_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    selected = chat_settings.get(chat_id, {}).get("players_to_start", 20)

    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = []

    for i in range(12, 26):
        mark = "▪️" if i == selected else "▫️"
        text = f"{mark} {i}"
        buttons.append(types.InlineKeyboardButton(text, callback_data=f"set_players_count_{i}_{chat_id}"))
        if len(buttons) == 5:
            markup.row(*buttons)
            buttons = []

    if buttons:
        markup.row(*buttons)

    markup.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))

    new_text = get_text(chat_id, 'choose_players_count') + f"\n\n{get_text(chat_id, 'current_value')} {selected}"

    try:
        bot.edit_message_text(new_text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
    except Exception as e:
        if "message is not modified" not in str(e):
            print(e)

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_players_count_"))
def set_players_count(call):
    parts = call.data.split("_")
    count = int(parts[3])
    chat_id = int(parts[4])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["players_to_start"] = count
    bot.answer_callback_query(call.id, f"{get_text(chat_id, 'players_count_changed')}: {count}")
    handle_players_count_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_time_"))
def handle_time_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    time_menu_kb = types.InlineKeyboardMarkup()
    time_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'time_reg'), callback_data=f"menu_registration_time_{chat_id}"))
    time_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'time_night'), callback_data=f"menu_night_time_{chat_id}"))
    time_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'time_day'), callback_data=f"menu_day_time_{chat_id}"))
    time_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'time_vote'), callback_data=f"menu_voting_time_{chat_id}"))
    time_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'time_confirm'), callback_data=f"menu_confirmation_time_{chat_id}"))
    time_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_time'), chat_id=user_id, message_id=call.message.message_id, reply_markup=time_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_confirmation_time_"))
def handle_confirmation_time_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    time_options = [15, 30, 45, 60]
    current_time = chat_settings[chat_id].get("confirmation_time", 30)

    confirmation_time_kb = types.InlineKeyboardMarkup()
    for option in time_options:
        selected = "▪️" if option == current_time else "▫️"
        confirmation_time_kb.add(types.InlineKeyboardButton(f"{selected} {option} {get_text(chat_id, 'sec')}", callback_data=f"set_confirmation_time_{option}_{chat_id}"))
    confirmation_time_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'), chat_id=user_id, message_id=call.message.message_id, reply_markup=confirmation_time_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_confirmation_time_"))
def handle_set_confirmation_time(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    time_value, chat_id = int(parts[3]), int(parts[4])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["confirmation_time"] = time_value
    bot.answer_callback_query(call.id, f"{get_text(chat_id, 'confirmation_time_changed')}: {time_value} {get_text(chat_id, 'sec')}")
    handle_confirmation_time_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_voting_time_"))
def handle_voting_time_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    time_options = [30, 45, 60, 90]
    current_time = chat_settings[chat_id].get("voting_time", 45)

    voting_time_kb = types.InlineKeyboardMarkup()
    for option in time_options:
        selected = "▪️" if option == current_time else "▫️"
        voting_time_kb.add(types.InlineKeyboardButton(f"{selected} {option} {get_text(chat_id, 'sec')}", callback_data=f"set_voting_time_{option}_{chat_id}"))
    voting_time_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'), chat_id=user_id, message_id=call.message.message_id, reply_markup=voting_time_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_voting_time_"))
def handle_set_voting_time(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    time_value, chat_id = int(parts[3]), int(parts[4])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["voting_time"] = time_value
    bot.answer_callback_query(call.id, f"{get_text(chat_id, 'voting_time_changed')}: {time_value} {get_text(chat_id, 'sec')}")
    handle_voting_time_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_day_time_"))
def handle_day_time_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    time_options = [30, 45, 60, 90, 120]
    current_time = chat_settings[chat_id].get("day_time", 60)

    day_time_kb = types.InlineKeyboardMarkup()
    for option in time_options:
        selected = "▪️" if option == current_time else "▫️"
        day_time_kb.add(types.InlineKeyboardButton(f"{selected} {option} {get_text(chat_id, 'sec')}", callback_data=f"set_day_time_{option}_{chat_id}"))
    day_time_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'), chat_id=user_id, message_id=call.message.message_id, reply_markup=day_time_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_day_time_"))
def handle_set_day_time(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    time_value, chat_id = int(parts[3]), int(parts[4])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["day_time"] = time_value
    bot.answer_callback_query(call.id, f"{get_text(chat_id, 'day_time_changed')}: {time_value} {get_text(chat_id, 'sec')}")
    handle_day_time_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_registration_time_"))
def handle_registration_time_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    time_options = [(120, 60), (180, 120), (240, 180), (300, 240), (360, 300), (420, 360), (480, 420), (540, 480), (600, 540)]
    current_time = chat_settings[chat_id].get("registration_time", (120, 60))

    registration_kb = types.InlineKeyboardMarkup()
    for option in time_options:
        selected = "▪️" if option == current_time else "▫️"
        registration_kb.add(types.InlineKeyboardButton(f"{selected} {option[0]} {get_text(chat_id, 'sec')}", callback_data=f"set_registration_time_{option[0]}_{option[1]}_{chat_id}"))
    registration_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'), chat_id=user_id, message_id=call.message.message_id, reply_markup=registration_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_registration_time_"))
def handle_set_registration_time(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    time1, time2, chat_id = int(parts[3]), int(parts[4]), int(parts[5])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["registration_time"] = (time1, time2)
    bot.answer_callback_query(call.id, f"{get_text(chat_id, 'registration_time_changed')}: {time1}/{time2} {get_text(chat_id, 'sec')}")
    handle_registration_time_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_night_time_"))
def handle_night_time_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    night_options = [30, 45, 60, 75, 90]
    current_time = chat_settings[chat_id].get("night_time", 45)

    night_kb = types.InlineKeyboardMarkup()
    for option in night_options:
        selected = "▪️" if option == current_time else "▫️"
        night_kb.add(types.InlineKeyboardButton(f"{selected} {option} {get_text(chat_id, 'sec')}", callback_data=f"set_night_time_{option}_{chat_id}"))
    night_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'), chat_id=user_id, message_id=call.message.message_id, reply_markup=night_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_night_time_"))
def handle_set_night_time(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    night_time, chat_id = int(parts[3]), int(parts[4])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["night_time"] = night_time
    bot.answer_callback_query(call.id, f"{get_text(chat_id, 'night_time_changed')}: {night_time} {get_text(chat_id, 'sec')}")
    handle_night_time_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_pin_"))
def handle_pin_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    current = chat_settings[chat_id]['pin_registration']

    pin_menu_kb = types.InlineKeyboardMarkup()
    pin_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_pin_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_pin_no_{chat_id}"))
    pin_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'pin_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=pin_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_pin_"))
def set_pin_registration(call):
    choice = call.data.split("_")[2]
    chat_id = int(call.data.split("_")[3])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["pin_registration"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'pin_enabled') if choice == "yes" else get_text(chat_id, 'pin_disabled'))
    handle_pin_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_buffs_"))
def handle_buffs_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    buffs_menu_kb = types.InlineKeyboardMarkup()
    buffs_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'shield_buff'), callback_data=f"menu_shield_{chat_id}"))
    buffs_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'docs_buff'), callback_data=f"menu_docs_{chat_id}"))
    buffs_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'hanging_shield_buff'), callback_data=f"menu_hanging_shield_{chat_id}"))
    buffs_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'gun_buff'), callback_data=f"menu_gun_{chat_id}"))
    buffs_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'choose_buff'), chat_id=user_id, message_id=call.message.message_id, reply_markup=buffs_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_shield_"))
def handle_shield_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    current = chat_settings[chat_id].get('shield_buff', True)

    shield_menu_kb = types.InlineKeyboardMarkup()
    shield_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_shield_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_shield_no_{chat_id}"))
    shield_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'shield_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=shield_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_shield_"))
def set_shield_buff(call):
    choice = call.data.split("_")[2]
    chat_id = int(call.data.split("_")[3])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["shield_buff"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'shield_enabled') if choice == "yes" else get_text(chat_id, 'shield_disabled'))

    current = chat_settings[chat_id]['shield_buff']
    shield_menu_kb = types.InlineKeyboardMarkup()
    shield_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_shield_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_shield_no_{chat_id}"))
    shield_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))
    bot.edit_message_text(get_text(chat_id, 'shield_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=shield_menu_kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_docs_"))
def handle_docs_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    current = chat_settings[chat_id].get('docs_buff', True)

    docs_menu_kb = types.InlineKeyboardMarkup()
    docs_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_docs_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_docs_no_{chat_id}"))
    docs_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'docs_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=docs_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_docs_"))
def set_docs_buff(call):
    choice = call.data.split("_")[2]
    chat_id = int(call.data.split("_")[3])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["docs_buff"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'docs_enabled') if choice == "yes" else get_text(chat_id, 'docs_disabled'))

    current = chat_settings[chat_id]['docs_buff']
    docs_menu_kb = types.InlineKeyboardMarkup()
    docs_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_docs_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_docs_no_{chat_id}"))
    docs_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))
    bot.edit_message_text(get_text(chat_id, 'docs_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=docs_menu_kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_hanging_shield_"))
def handle_hanging_shield_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    current = chat_settings[chat_id].get('hanging_shield_buff', True)

    hanging_shield_menu_kb = types.InlineKeyboardMarkup()
    hanging_shield_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_hanging_shield_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_hanging_shield_no_{chat_id}"))
    hanging_shield_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'hanging_shield_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=hanging_shield_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_hanging_shield_"))
def set_hanging_shield_buff(call):
    choice = call.data.split("_")[3]
    chat_id = int(call.data.split("_")[4])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["hanging_shield_buff"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'hanging_shield_enabled') if choice == "yes" else get_text(chat_id, 'hanging_shield_disabled'))

    current = chat_settings[chat_id]['hanging_shield_buff']
    hanging_shield_menu_kb = types.InlineKeyboardMarkup()
    hanging_shield_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_hanging_shield_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_hanging_shield_no_{chat_id}"))
    hanging_shield_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))
    bot.edit_message_text(get_text(chat_id, 'hanging_shield_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=hanging_shield_menu_kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_gun_"))
def handle_gun_menu(call):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    current = chat_settings[chat_id].get('gun_buff', True)

    gun_menu_kb = types.InlineKeyboardMarkup()
    gun_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_gun_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_gun_no_{chat_id}"))
    gun_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'gun_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=gun_menu_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_gun_"))
def set_gun_buff(call):
    choice = call.data.split("_")[2]
    chat_id = int(call.data.split("_")[3])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["gun_buff"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'gun_enabled') if choice == "yes" else get_text(chat_id, 'gun_disabled'))

    current = chat_settings[chat_id]['gun_buff']
    gun_menu_kb = types.InlineKeyboardMarkup()
    gun_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_gun_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_gun_no_{chat_id}"))
    gun_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_buffs_{chat_id}"))
    bot.edit_message_text(get_text(chat_id, 'gun_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=gun_menu_kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_menu(call):
    user_id = call.from_user.id
    data = call.data
    chat_id = int(data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    if data.startswith("menu_pin_"):
        handle_pin_menu(call)
    elif data.startswith("menu_leave_"):
        current = chat_settings[chat_id]['allow_leave_game']
        leave_menu_kb = types.InlineKeyboardMarkup()
        leave_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_leave_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_leave_no_{chat_id}"))
        leave_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'leave_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=leave_menu_kb)
    elif data.startswith("menu_commands_"):
        current = chat_settings[chat_id]['allow_registration']
        commands_menu_kb = types.InlineKeyboardMarkup()
        commands_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_admin_only_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_admin_only_no_{chat_id}"))
        commands_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'admin_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=commands_menu_kb)
    elif data.startswith("menu_mafia_ratio_"):
        current_ratio = chat_settings[chat_id]["mafia_ratio"]
        mafia_ratio_kb = types.InlineKeyboardMarkup()
        mafia_ratio_kb.add(types.InlineKeyboardButton(f"{'▪️' if current_ratio == 3 else '▫️'} {get_text(chat_id, 'more_mafia')}", callback_data=f"set_mafia_ratio_3_{chat_id}"))
        mafia_ratio_kb.add(types.InlineKeyboardButton(f"{'▪️' if current_ratio == 4 else '▫️'} {get_text(chat_id, 'less_mafia')}", callback_data=f"set_mafia_ratio_4_{chat_id}"))
        mafia_ratio_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'mafia_ratio_desc'), chat_id=user_id, message_id=call.message.message_id, reply_markup=mafia_ratio_kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_leave_"))
def set_leave(call):
    choice = call.data.split("_")[2]
    chat_id = int(call.data.split("_")[3])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["allow_leave_game"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'leave_enabled') if choice == "yes" else get_text(chat_id, 'leave_disabled'))

    current = chat_settings[chat_id]['allow_leave_game']
    leave_menu_kb = types.InlineKeyboardMarkup()
    leave_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_leave_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_leave_no_{chat_id}"))
    leave_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
    bot.edit_message_text(get_text(chat_id, 'leave_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=leave_menu_kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_admin_only_"))
def set_admin_only(call):
    choice = call.data.split("_")[3]
    chat_id = int(call.data.split("_")[4])
    user_id = call.from_user.id

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["allow_registration"] = (choice == "yes")
    bot.answer_callback_query(call.id, get_text(chat_id, 'admin_only_enabled') if choice == "yes" else get_text(chat_id, 'admin_only_disabled'))

    current = chat_settings[chat_id]['allow_registration']
    commands_menu_kb = types.InlineKeyboardMarkup()
    commands_menu_kb.add(types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_admin_only_yes_{chat_id}"), types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_admin_only_no_{chat_id}"))
    commands_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
    bot.edit_message_text(get_text(chat_id, 'admin_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=commands_menu_kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_mafia_ratio_"))
def handle_mafia_ratio(call):
    user_id = call.from_user.id
    data = call.data
    chat_id = int(data.split("_")[-1])
    ratio = int(data.split("_")[3])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    chat_settings[chat_id]["mafia_ratio"] = ratio
    bot.answer_callback_query(call.id, get_text(chat_id, 'mafia_ratio_changed'))

    mafia_ratio_kb = types.InlineKeyboardMarkup()
    mafia_ratio_kb.add(types.InlineKeyboardButton(f"{'▪️' if ratio == 3 else '▫️'} {get_text(chat_id, 'more_mafia')}", callback_data=f"set_mafia_ratio_3_{chat_id}"))
    mafia_ratio_kb.add(types.InlineKeyboardButton(f"{'▪️' if ratio == 4 else '▫️'} {get_text(chat_id, 'less_mafia')}", callback_data=f"set_mafia_ratio_4_{chat_id}"))
    mafia_ratio_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'mafia_ratio_desc'), chat_id=user_id, message_id=call.message.message_id, reply_markup=mafia_ratio_kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("close_settings_"))
def handle_close_settings(call):
    chat_id = int(call.data.split("_")[-1])
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.answer_callback_query(call.id, get_text(chat_id, 'menu_closed'))

@bot.message_handler(commands=['language'])
def language_command(message):
    """Быстрая команда для выбора языка профиля"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    profile = get_or_create_profile(user_id, message.from_user.first_name, message.from_user.last_name)
    current_lang = profile.get('language', 'ru')
    
    markup = types.InlineKeyboardMarkup()
    
    # Русский язык - жирный если активен
    ru_text = "🇷🇺 Русский"
    if current_lang == 'ru':
        ru_text = f"*{ru_text}*"
    
    # Казахский язык - жирный если активен
    kz_text = "🇰🇿 Қазақша"
    if current_lang == 'kz':
        kz_text = f"*{kz_text}*"
    
    markup.add(types.InlineKeyboardButton(ru_text, callback_data="fast_lang_ru"))
    markup.add(types.InlineKeyboardButton(kz_text, callback_data="fast_lang_kz"))
    
    if message.chat.type in ['group', 'supergroup']:
        try:
            bot.delete_message(chat_id, message.message_id)
        except:
            pass
        bot.send_message(user_id, get_user_text(user_id, 'language_fast_select'), reply_markup=markup, parse_mode="Markdown")
        return
    
    bot.send_message(chat_id, get_user_text(user_id, 'language_fast_select'), reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('fast_lang_'))
def set_fast_user_language(call):
    """Быстрая установка языка профиля пользователя"""
    user_id = call.from_user.id
    lang_code = call.data.split('_')[2]  # 'ru' или 'kz'
    
    # Получаем профиль
    profile = get_or_create_profile(user_id, call.from_user.first_name, call.from_user.last_name)
    
    # Устанавливаем язык
    profile['language'] = lang_code
    player_profiles[user_id] = profile
    
    # Создаем клавиатуру для главного меню
    bot_username = bot.get_me().username
    add_to_group_url = f'https://t.me/{bot_username}?startgroup=bot_command'
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(get_user_text(user_id, 'start_add_to_group'), url=add_to_group_url))
    keyboard.add(types.InlineKeyboardButton(get_user_text(user_id, 'start_join_chat'), callback_data='join_chat'))
    keyboard.add(types.InlineKeyboardButton(get_user_text(user_id, 'start_news'), url='t.me/CityMafiaNews'))
    
    # Приветственное сообщение на новом языке
    welcome_text = get_user_text(user_id, 'start_private')
    
    # Редактируем сообщение (заменяем выбор языка на приветствие)
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=welcome_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        # Если не удалось отредактировать, отправляем новое
        bot.send_message(call.message.chat.id, welcome_text, reply_markup=keyboard, parse_mode="Markdown")
    
    bot.answer_callback_query(call.id)


@bot.message_handler(commands=['game'])
def create_game(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, get_text(chat_id, 'group_only'))
        return

    if chat_id in blocked_chat_ids:
        bot.send_message(chat_id, get_text(chat_id, 'blocked_chat'))
        print(f"Запуск регистрации заблокирован для чата {chat_id}")
        return

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        pass

    chat_admins = bot.get_chat_administrators(chat_id)
    admin_ids = [admin.user.id for admin in chat_admins]

    if chat_id not in chat_settings:
        chat_settings[chat_id] = {
            "language": "ru",
            "pin_registration": True,
            "allow_registration": True,
            "allow_leave_game": True,
            "registration_time": (120, 60),
            "night_time": 45,
            "day_time": 60,
            "voting_time": 45,
            "players_to_start": 20,
            "anonymous_voting": False,
            "confirmation_time": 30,
            "mafia_ratio": 4,
            "shield_buff": True,
            "docs_buff": True,
            "hanging_shield_buff": True,
            "gun_buff": True
        }

    chat_settings[chat_id].setdefault("allow_registration", True)
    chat_settings[chat_id].setdefault("pin_registration", False)
    chat_settings[chat_id].setdefault("allow_leave_game", True)

    if not chat_settings[chat_id]["allow_registration"] and user_id not in admin_ids:
        return

    if chat_id not in chat_list:
        chat_list[chat_id] = Game(chat_id)

    chat = chat_list[chat_id]

    if chat.game_running or chat.button_id:
        return

    with registration_lock:
        if chat.button_id:
            return

        join_btn = types.InlineKeyboardMarkup()
        bot_username = bot.get_me().username
        join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
        item1 = types.InlineKeyboardButton(get_text(chat_id, 'join_button'), url=join_url)
        join_btn.add(item1)

        msg_text = registration_message(chat.players, chat_id)
        msg = send_message(chat_id, msg_text, reply_markup=join_btn, parse_mode="Markdown")

        if msg:
            chat.button_id = msg.message_id
            if chat_settings[chat_id]["pin_registration"]:
                bot.pin_chat_message(chat_id, msg.message_id)
        else:
            print("Ошибка: не удалось отправить сообщение о регистрации.")

        notify_game_start(chat)

        registration_time = chat_settings[chat_id]["registration_time"]
        total_time = registration_time[0]

        if chat_id not in notification_timers:
            notification_timers[chat_id] = {}

        notification_timers[chat_id]['59_seconds'] = threading.Timer(total_time - 59, lambda: notify_at_59_seconds(chat_id))
        notification_timers[chat_id]['59_seconds'].start()

        notification_timers[chat_id]['29_seconds'] = threading.Timer(total_time - 29, lambda: notify_at_29_seconds(chat_id))
        notification_timers[chat_id]['29_seconds'].start()

        game_start_timers[chat_id] = threading.Timer(total_time, lambda: start_game_with_delay(chat_id))
        game_start_timers[chat_id].start()


@bot.message_handler(commands=['profile'])
def handle_profile(message):
    if message.chat.type == 'private':
        user_id = message.from_user.id
        user_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
        show_profile(message, user_id=user_id, user_name=user_name)


def show_profile(message, user_id, message_id=None, user_name=None):
    if not user_name:
        user_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()

    profile = get_or_create_profile(user_id, user_name)
    check_vip_expiry(profile)
    
    lang = profile.get('language', 'ru')

    if profile.get('vip_until'):
        vip_expiry = datetime.strptime(profile['vip_until'], '%Y-%m-%d %H:%M:%S')
        formatted_date = vip_expiry.strftime('%d.%m.%Y')
        vip_status = f"{formatted_date}"
    else:
        vip_status = "❌"

    profile_text = get_user_text(user_id, 'profile').format(
        name=escape_markdown(user_name),
        id=user_id,
        euro=escape_markdown(str(profile['euro'])),
        coins=escape_markdown(str(profile['coins'])),
        shield=escape_markdown(str(profile['shield'])),
        docs=escape_markdown(str(profile['fake_docs'])),
        gun=escape_markdown(str(profile['gun'])),
        hanging_shield=escape_markdown(str(profile.get('hanging_shield', 0))),
        vip=vip_status
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    shop_btn = types.InlineKeyboardButton(get_user_text(user_id, 'shop_title').replace('*', '').strip(), callback_data="shop")
    buy_coins_btn = types.InlineKeyboardButton(get_user_text(user_id, 'buy_coins_title').replace('*', '').strip(), callback_data="buy_coins")
    exchange_btn = types.InlineKeyboardButton(get_user_text(user_id, 'exchange_title').replace('*', '').strip(), callback_data="exchange")
    settings_btn = types.InlineKeyboardButton(get_user_text(user_id, 'settings_profile_title').replace('*', '').strip(), callback_data="settings")
    djekpot_btn = types.InlineKeyboardButton(get_user_text(user_id, 'djekpot_title').split('\n')[0].replace('*', '').strip(), callback_data="djekpot")
    
    markup.add(shop_btn, buy_coins_btn)
    markup.add(exchange_btn, settings_btn)
    markup.add(djekpot_btn)

    if message_id:
        bot.edit_message_text(chat_id=message.chat.id, message_id=message_id, text=profile_text, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, profile_text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == 'djekpot')
def handle_djekpot_info(call):
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
    profile = get_or_create_profile(user_id, user_name)

    new_text = get_user_text(user_id, 'djekpot_title')

    markup = types.InlineKeyboardMarkup()
    spin_btn = types.InlineKeyboardButton(get_user_text(user_id, 'djekpot_spin'), callback_data='spin_jackpot')
    back_btn = types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data='back_to_profile')
    markup.add(spin_btn)
    markup.add(back_btn)

    try:
        if call.message.text != new_text or call.message.reply_markup != markup:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=new_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e):
            raise


def roll_jackpot(profile, chat_id=None):
    prizes = ['vip', 'coins', 'euro', 'shield', 'fake_docs', 'gun', 'hanging_shield']
    weights = [10, 10, 25, 25, 25, 25, 25]
    prize = random.choices(prizes, weights=weights, k=1)[0]

    prize_text = get_text(chat_id or 0, f'djekpot_prize_{prize}') if chat_id else TEXTS['ru'].get(f'djekpot_prize_{prize}', prize)

    if prize == 'vip':
        days = random.randint(1, 4)
        profile['vip_until'] = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        if chat_id:
            prize_text += get_text(chat_id, 'days_suffix').format(days=days)
        else:
            prize_text += f" на {days} д."
    elif prize == 'coins':
        amount = random.randint(1, 7)
        profile['coins'] += amount
        prize_text += f' x{amount}'
    elif prize == 'euro':
        amount = random.randint(150, 1000)
        profile['euro'] += amount
        prize_text += f' x{amount}'
    else:
        profile[prize] = profile.get(prize, 0) + 1

    return prize, prize_text


@bot.callback_query_handler(func=lambda call: call.data == 'spin_jackpot')
def handle_spin_jackpot(call):
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
    profile = get_or_create_profile(user_id, user_name)
    chat_id = call.message.chat.id

    if profile['coins'] < 2:
        bot.answer_callback_query(call.id, get_user_text(user_id, 'djekpot_no_coins'), show_alert=True)
        return

    profile['coins'] -= 2
    prize, prize_text = roll_jackpot(profile, chat_id)
    update_profile(user_id, profile)

    win_message = get_user_text(user_id, 'djekpot_win').format(prize_text)
    bot.answer_callback_query(call.id, win_message, show_alert=True)
    handle_djekpot_info(call)


@bot.callback_query_handler(func=lambda call: call.data == 'settings')
def handle_settings(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    lang = profile.get('language', 'ru')
    
    title = get_user_text(user_id, 'settings_profile_title')
    shield_text = get_user_text(user_id, 'settings_shield').format(
        get_user_text(user_id, 'settings_on') if profile.get('shield_active', True) else get_user_text(user_id, 'settings_off')
    )
    docs_text = get_user_text(user_id, 'settings_docs').format(
        get_user_text(user_id, 'settings_on') if profile.get('docs_active', True) else get_user_text(user_id, 'settings_off')
    )
    hanging_text = get_user_text(user_id, 'settings_hanging').format(
        get_user_text(user_id, 'settings_on') if profile.get('hanging_shield_active', True) else get_user_text(user_id, 'settings_off')
    )
    lang_text = get_user_text(user_id, 'settings_language').format(
        get_user_text(user_id, 'settings_lang_ru') if lang == 'ru' else get_user_text(user_id, 'settings_lang_kz')
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(shield_text, callback_data="toggle_shield"))
    markup.add(types.InlineKeyboardButton(docs_text, callback_data="toggle_docs"))
    markup.add(types.InlineKeyboardButton(hanging_text, callback_data="toggle_hanging"))
    markup.add(types.InlineKeyboardButton(lang_text, callback_data="change_language"))
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data="back_to_profile"))

    bot.edit_message_text(title, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == 'change_language')
def handle_change_language(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(get_user_text(user_id, 'settings_lang_ru'), callback_data="set_lang_ru"),
        types.InlineKeyboardButton(get_user_text(user_id, 'settings_lang_kz'), callback_data="set_lang_kz")
    )
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data="back_to_settings"))

    bot.edit_message_text(get_user_text(user_id, 'settings_lang_choose'), chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data in ['set_lang_ru', 'set_lang_kz'])
def handle_set_language(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)

    new_lang = 'ru' if call.data == 'set_lang_ru' else 'kz'
    profile['language'] = new_lang

    bot.answer_callback_query(call.id, get_user_text(user_id, 'settings_lang_changed').format(
        get_user_text(user_id, 'settings_lang_ru') if new_lang == 'ru' else get_user_text(user_id, 'settings_lang_kz')
    ))
    handle_settings(call)


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_settings')
def back_to_settings(call):
    handle_settings(call)


@bot.callback_query_handler(func=lambda call: call.data in ['toggle_shield', 'toggle_docs', 'toggle_hanging'])
def handle_toggle_protections(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    
    toggle_map = {"toggle_shield": "shield_active", "toggle_docs": "docs_active", "toggle_hanging": "hanging_shield_active"}

    if call.data in toggle_map:
        key = toggle_map[call.data]
        profile[key] = not profile.get(key, True)
        handle_settings(call)
        
        item = call.data.split('_')[1]
        item_names = {
            'shield': get_user_text(user_id, 'shield_buff'), 
            'docs': get_user_text(user_id, 'docs_buff'), 
            'hanging': get_user_text(user_id, 'hanging_shield_buff')
        }
        state = get_user_text(user_id, 'settings_on') if profile[key] else get_user_text(user_id, 'settings_off')
        bot.answer_callback_query(call.id, get_user_text(user_id, 'settings_toggle_success').format(item_names.get(item, item), state))


@bot.callback_query_handler(func=lambda call: call.data in ['shop', 'buy_shield', 'buy_fake_docs', 'buy_gun', 'buy_hanging_shield', 'back_to_profile', 'renew_vip', 'buy_vip'])
def handle_shop_actions(call):
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
    profile = get_or_create_profile(user_id, user_name)

    if call.data == "shop":
        shop_text = f"{get_user_text(user_id, 'shop_title')}\n\n{get_user_text(user_id, 'balance').format(euro=profile['euro'], coins=profile['coins'])}\n\n{get_user_text(user_id, 'shield_desc')}\n\n{get_user_text(user_id, 'docs_desc')}\n\n{get_user_text(user_id, 'hanging_desc')}\n\n{get_user_text(user_id, 'gun_desc')}\n\n{get_user_text(user_id, 'vip_desc')}"

        markup = types.InlineKeyboardMarkup(row_width=1)  # ← 1 кнопка в ряду = вертикально
        
        buy_shield_btn = types.InlineKeyboardButton(get_user_text(user_id, 'shop_shield'), callback_data="buy_shield")
        buy_docs_btn = types.InlineKeyboardButton(get_user_text(user_id, 'shop_docs'), callback_data="buy_fake_docs")
        buy_gun_btn = types.InlineKeyboardButton(get_user_text(user_id, 'shop_gun'), callback_data="buy_gun")
        buy_hanging_shield_btn = types.InlineKeyboardButton(get_user_text(user_id, 'shop_hanging'), callback_data="buy_hanging_shield")
        buy_vip_btn = types.InlineKeyboardButton(get_user_text(user_id, 'shop_renew_vip') if profile.get('vip_until') else get_user_text(user_id, 'shop_buy_vip'), callback_data="renew_vip" if profile.get('vip_until') else "buy_vip")
        back_btn = types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data="back_to_profile")
        
        # Каждая кнопка на новой строке (сверху вниз)
        markup.add(buy_shield_btn)
        markup.add(buy_docs_btn)
        markup.add(buy_hanging_shield_btn)
        markup.add(buy_vip_btn)
        markup.add(buy_gun_btn)
        markup.add(back_btn)

        bot.edit_message_text(shop_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "buy_gun":
        if not profile.get('vip_until'):
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_vip_only'), show_alert=True)
            return
        if profile['euro'] >= 600:
            profile['euro'] -= 600
            profile['gun'] += 1
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_success'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_no_money'), show_alert=True)

    elif call.data == "buy_shield":
        if profile['euro'] >= 100:
            profile['euro'] -= 100
            profile['shield'] += 1
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_success'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_no_money'), show_alert=True)

    elif call.data == "buy_fake_docs":
        if profile['euro'] >= 150:
            profile['euro'] -= 150
            profile['fake_docs'] += 1
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_success'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_no_money'), show_alert=True)

    elif call.data == "buy_vip":
        if profile['coins'] >= 7:
            profile['coins'] -= 7
            profile['vip_until'] = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_vip_bought'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_no_money'), show_alert=True)

    elif call.data == "renew_vip":
        if profile['coins'] >= 4:
            profile['coins'] -= 4
            current_vip = datetime.strptime(profile['vip_until'], '%Y-%m-%d %H:%M:%S')
            new_vip_until = current_vip + timedelta(days=7)
            profile['vip_until'] = new_vip_until.strftime('%Y-%m-%d %H:%M:%S')
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_vip_renewed'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_no_money'), show_alert=True)

    elif call.data == "buy_hanging_shield":
        if profile['coins'] >= 1:
            profile['coins'] -= 1
            profile['hanging_shield'] += 1
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_success'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_user_text(user_id, 'purchase_no_money'), show_alert=True)

    elif call.data == "back_to_profile":
        show_profile(call.message, message_id=call.message.message_id, user_id=user_id, user_name=user_name)


def update_profile(user_id, profile):
    player_profiles[user_id] = profile


@bot.callback_query_handler(func=lambda call: call.data in ['exchange', 'exchange_1', 'exchange_2', 'exchange_5', 'exchange_10'])
def handle_exchange(call):
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
    profile = get_or_create_profile(user_id, user_name)

    exchange_rates = {'exchange_1': (1, 150), 'exchange_2': (2, 300), 'exchange_5': (5, 750), 'exchange_10': (10, 1500)}

    if call.data == 'exchange':
        exchange_text = f"{get_user_text(user_id, 'exchange_title')}\n{get_user_text(user_id, 'balance').format(euro=profile['euro'], coins=profile['coins'])}\n\n{get_user_text(user_id, 'exchange_choose')}"

        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [types.InlineKeyboardButton(get_user_text(user_id, f'exchange_rate_{rate}'), callback_data=f"exchange_{rate}") for rate in [1, 2, 5, 10]]
        markup.add(*buttons[:2])
        markup.add(*buttons[2:])
        markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data="back_to_profile"))

        bot.edit_message_text(exchange_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data in exchange_rates:
        coins_needed, euros_received = exchange_rates[call.data]
        if profile['coins'] >= coins_needed:
            profile['coins'] -= coins_needed
            profile['euro'] += euros_received
            bot.answer_callback_query(call.id, get_user_text(user_id, 'exchange_success'), show_alert=True)
        else:
            bot.answer_callback_query(call.id, get_user_text(user_id, 'exchange_no_coins'), show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data == 'buy_coins')
def handle_buy_coins(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)

    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'pay_card'), callback_data="pay_with_card"))
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'pay_stars'), callback_data="pay_with_stars"))
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data="back_to_profile"))

    bot.edit_message_text(f"{get_user_text(user_id, 'buy_coins_title')}\n{get_user_text(user_id, 'buy_coins_choose')}", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == 'pay_with_card')
def handle_card_payment(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)

    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'card_payment_button'), url="https://t.me/CityMafiaSupport"))
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data="buy_coins"))

    bot.edit_message_text(f"{get_user_text(user_id, 'card_payment_title')}\n\n{get_user_text(user_id, 'card_payment_text')}", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == 'pay_with_stars')
def show_stars_options(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    rates = [(1, 20), (2, 40), (5, 90), (10, 165), (20, 305), (50, 703), (100, 1344), (200, 2688)]

    markup = types.InlineKeyboardMarkup(row_width=2)
    for coins, stars in rates:
        btn_text = get_user_text(user_id, 'stars_button').format(coins=coins, stars=stars)
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"stars:{coins}:{stars}"))
    markup.add(types.InlineKeyboardButton(get_user_text(user_id, 'back'), callback_data="buy_coins"))

    bot.edit_message_text(get_user_text(user_id, 'stars_payment_text'), call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith('stars:'))
def process_stars_payment(call):
    try:
        _, coins, stars = call.data.split(':')
        coins = int(coins)
        stars = int(stars)
        
        valid_rates = {1: 1, 2: 40, 5: 90, 10: 165, 20: 305, 50: 703, 100: 1344, 200: 2688}
        if coins not in valid_rates or stars != valid_rates[coins]:
            bot.answer_callback_query(call.id, "❌ Неверная сумма", show_alert=True)
            return

        bot.send_invoice(
            chat_id=call.message.chat.id,
            title=f"🪙 {coins} монет",
            description=f"Покупка {coins} монет через Telegram Stars",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{coins} монет", amount=stars)],
            invoice_payload=f"coins_{coins}",
            start_parameter="stars_payment"
        )
        
    except Exception as e:
        logging.error(f"Payment error: {e}")
        bot.answer_callback_query(call.id, text="❌ Ошибка при создании платежа", show_alert=True)


@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout_query(pre_checkout_query):
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logging.error(f"Pre-checkout error: {e}")
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка оплаты")


@bot.message_handler(content_types=['successful_payment'])
def handle_payment(message):
    try:
        payload = message.successful_payment.invoice_payload
        if payload.startswith("coins_"):
            coins = int(payload.split('_')[1])
            
            profile = get_or_create_profile(message.from_user.id, message.from_user.first_name)
            profile['coins'] += coins
            
            bot.send_message(
                message.chat.id, 
                f"✅ Оплата прошла успешно!\n+{coins} 🪙\nБаланс: {profile['coins']} 🪙",
                parse_mode="Markdown"
            )
            bot.send_message(ADMIN_ID, f"💰 Новый платеж:\n@{message.from_user.username}\n+{coins} монет")
    except Exception as e:
        logging.error(f"Payment processing error: {e}")


@bot.message_handler(commands=['help'])
def send_help(message):
    if message.chat.type == 'private':
        user_id = message.from_user.id
        profile = get_or_create_profile(user_id, message.from_user.first_name)

        keyboard = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton(text=get_user_text(user_id, 'help_support'), url="https://t.me/CityMafiaSupport")
        button2 = types.InlineKeyboardButton(text=get_user_text(user_id, 'help_how_to_play'), url="https://t.me/+_ljFO5TH39wxZTRi")
        button3 = types.InlineKeyboardButton(text=get_user_text(user_id, 'help_roles'), url="https://telegra.ph/maf-02-17")
        keyboard.add(button1, button2)
        keyboard.add(button3)

        send_message(message.chat.id, get_user_text(user_id, 'help_title'), parse_mode="Markdown", reply_markup=keyboard)


@bot.message_handler(commands=['coins'])
def transfer_coins(message):
    chat_id = message.chat.id
    sender_id = message.from_user.id

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение: {e}")

    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, get_text(chat_id, 'coins_transfer_only_group'))
        return

    if not message.reply_to_message:
        bot.reply_to(message, get_text(chat_id, 'coins_transfer_reply_required'))
        return

    recipient = message.reply_to_message.from_user
    recipient_id = recipient.id

    if sender_id == recipient_id:
        bot.reply_to(message, get_text(chat_id, 'coins_transfer_self'))
        return

    try:
        amount = int(message.text.split()[1])
        if amount <= 0:
            raise ValueError
    except (IndexError, ValueError):
        bot.reply_to(message, get_text(chat_id, 'coins_transfer_invalid'))
        return

    try:
        sender_profile = get_or_create_profile(sender_id, message.from_user.first_name, message.from_user.last_name)
        recipient_profile = get_or_create_profile(recipient_id, recipient.first_name, recipient.last_name)
    except Exception as e:
        logging.error(f"Ошибка при получении профилей: {e}")
        bot.reply_to(message, get_text(chat_id, 'coins_transfer_profile_error'))
        return

    if sender_profile['coins'] < amount:
        bot.reply_to(message, get_text(chat_id, 'coins_transfer_not_enough').format(coins=sender_profile['coins']))
        return

    sender_profile['coins'] -= amount
    recipient_profile['coins'] += amount

    sender_name = sender_profile['name']
    if sender_profile.get('last_name'):
        sender_name += f" {sender_profile['last_name']}"

    recipient_name = recipient_profile['name']
    if recipient_profile.get('last_name'):
        recipient_name += f" {recipient_profile['last_name']}"

    try:
        bot.send_message(chat_id, get_text(chat_id, 'coins_transfer_confirmation').format(sender=sender_name, amount=amount, recipient=recipient_name), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения: {e}")


MY_USER_ID = 6265990443


@bot.message_handler(commands=['stop'])
def stop_game(message):
    global game_tasks, registration_timers, game_start_timers

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    is_admin = False
    if user_id == MY_USER_ID:
        is_admin = True
    elif user_id:
        try:
            chat_member = bot.get_chat_member(chat_id, user_id)
            if chat_member.status in ['administrator', 'creator']:
                is_admin = True
        except Exception as e:
            print(f"Ошибка при получении члена чата: {e}")
    elif message.sender_chat and message.sender_chat.id == chat_id:
        is_admin = True

    if not is_admin:
        return

    chat = chat_list.get(chat_id)
    if not chat or (not chat.game_running and not chat.button_id):
        return

    if chat_id in registration_timers:
        for timer in registration_timers[chat_id]:
            timer.cancel()
        del registration_timers[chat_id]

    if chat_id in game_start_timers:
        timer = game_start_timers[chat_id]
        if isinstance(timer, threading.Timer):
            timer.cancel()
        del game_start_timers[chat_id]

    if chat.game_running:
        chat.game_running = False
        send_message(chat_id, get_text(chat_id, 'game_stopped'), parse_mode="Markdown")
        reset_game(chat)
        reset_roles(chat)
    else:
        reset_registration(chat_id)
        send_message(chat_id, get_text(chat_id, 'registration_stopped'), parse_mode="Markdown")


@bot.message_handler(commands=['time'])
def stop_registration_timer(message):
    global notification_timers, game_start_timers

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    is_admin = False
    if user_id:
        try:
            chat_member = bot.get_chat_member(chat_id, user_id)
            if chat_member.status in ['administrator', 'creator']:
                is_admin = True
        except Exception as e:
            print(f"Ошибка при получении члена чата: {e}")
    elif message.sender_chat and message.sender_chat.id == chat_id:
        is_admin = True

    if not is_admin:
        return

    timers_stopped = False

    if chat_id in notification_timers:
        for key, timer in notification_timers[chat_id].items():
            if isinstance(timer, threading.Timer):
                timer.cancel()
        del notification_timers[chat_id]
        timers_stopped = True

    if chat_id in game_start_timers:
        game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]
        timers_stopped = True

    if timers_stopped:
        send_message(chat_id, get_text(chat_id, 'timeout_auto_start_disabled'), parse_mode="Markdown")


@bot.message_handler(commands=['add_chat'])
def add_chat(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, get_text(message.chat.id, 'admin_only'))
        return

    try:
        chat_id = int(message.text.split()[1])
        if chat_id in ALLOWED_CHAT_ID:
            bot.reply_to(message, "Этот чат уже в списке.")
        else:
            ALLOWED_CHAT_ID.append(chat_id)
            bot.reply_to(message, f"Чат {chat_id} добавлен в список разрешённых.")
    except (IndexError, ValueError):
        bot.reply_to(message, "Использование: /add_chat <ID>")


@bot.message_handler(commands=['рассылка'])
def broadcast_command(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, get_text(message.chat.id, 'admin_only'))

    user_data[message.chat.id] = {}

    msg = bot.reply_to(message, get_text(message.chat.id, 'broadcast_send_text'), parse_mode="Markdown")
    bot.register_next_step_handler(msg, handle_text)


def handle_text(message):
    chat_id = message.chat.id
    txt = message.text

    if txt and txt.lower() == "нет":
        txt = None

    user_data[chat_id]['text'] = txt

    if txt and ("<" in txt and ">" in txt):
        user_data[chat_id]['parse_mode'] = "HTML"
    else:
        user_data[chat_id]['parse_mode'] = "Markdown"

    msg = bot.reply_to(message, get_text(chat_id, 'broadcast_send_media'))
    bot.register_next_step_handler(msg, handle_media)


def handle_media(message):
    chat_id = message.chat.id

    if message.text and message.text.lower() == "нет":
        user_data[chat_id]['media'] = None
    else:
        user_data[chat_id]['media'] = message

    msg = bot.reply_to(message, get_text(chat_id, 'broadcast_send_buttons'), parse_mode="Markdown")
    user_data[chat_id]['keyboard_buttons'] = []
    bot.register_next_step_handler(msg, handle_buttons)


def handle_buttons(message):
    chat_id = message.chat.id
    text = message.text

    if text.lower() == "готово":
        keyboard = types.InlineKeyboardMarkup()
        for btn_text, link in user_data[chat_id]['keyboard_buttons']:
            keyboard.add(types.InlineKeyboardButton(text=btn_text, url=link))
        user_data[chat_id]['keyboard'] = keyboard
        return preview(chat_id)

    match = re.match(r'^(.+?)\s*-\s*(https?://[^\s]+)$', text)
    if not match:
        msg = bot.reply_to(message, get_text(chat_id, 'broadcast_invalid_button'))
        return bot.register_next_step_handler(msg, handle_buttons)

    btn_text, url = match.groups()
    user_data[chat_id]['keyboard_buttons'].append((btn_text.strip(), url.strip()))

    msg = bot.reply_to(message, get_text(chat_id, 'broadcast_button_added'))
    bot.register_next_step_handler(msg, handle_buttons)


def preview(chat_id):
    data = user_data[chat_id]
    text = data['text']
    media = data['media']
    keyboard = data.get('keyboard')
    parse_mode = data['parse_mode']

    try:
        if media:
            bot.copy_message(chat_id, media.chat.id, media.message_id, caption=text, parse_mode=parse_mode, reply_markup=keyboard)
        else:
            bot.send_message(chat_id, text or "(без текста)", parse_mode=parse_mode, reply_markup=keyboard)
    except Exception as e:
        bot.send_message(chat_id, get_text(chat_id, 'broadcast_preview_error').format(error=e), parse_mode="Markdown")

    confirm = types.InlineKeyboardMarkup()
    confirm.add(types.InlineKeyboardButton(get_text(chat_id, 'broadcast_start'), callback_data="start_broadcast"), types.InlineKeyboardButton(get_text(chat_id, 'broadcast_cancel'), callback_data="cancel_broadcast"))
    bot.send_message(chat_id, get_text(chat_id, 'broadcast_confirm'), reply_markup=confirm)


@bot.callback_query_handler(func=lambda call: call.data in ['start_broadcast', 'cancel_broadcast'])
def callback_decision(call):
    chat_id = call.message.chat.id

    if call.data == "cancel_broadcast":
        user_data.pop(chat_id, None)
        return bot.edit_message_text(get_text(chat_id, 'broadcast_cancelled'), chat_id, call.message.message_id)

    broadcast_status['is_paused'] = False
    broadcast_status['is_stopped'] = False

    bot.edit_message_text(get_text(chat_id, 'broadcast_started'), chat_id, call.message.message_id)

    thread = threading.Thread(target=send_broadcast, args=(chat_id,))
    thread.start()


def control_buttons(chat_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton(get_text(chat_id, 'broadcast_control_pause'), callback_data="pause_broadcast"), types.InlineKeyboardButton(get_text(chat_id, 'broadcast_control_resume'), callback_data="resume_broadcast"), types.InlineKeyboardButton(get_text(chat_id, 'broadcast_control_stop'), callback_data="stop_broadcast"))
    return markup


@bot.callback_query_handler(func=lambda call: call.data in ['pause_broadcast', 'resume_broadcast', 'stop_broadcast'])
def handle_controls(call):
    if call.data == "pause_broadcast":
        broadcast_status['is_paused'] = True
        bot.answer_callback_query(call.id, get_text(call.message.chat.id, 'broadcast_paused'))
    elif call.data == "resume_broadcast":
        broadcast_status['is_paused'] = False
        bot.answer_callback_query(call.id, get_text(call.message.chat.id, 'broadcast_resumed'))
    elif call.data == "stop_broadcast":
        broadcast_status['is_stopped'] = True
        bot.answer_callback_query(call.id, get_text(call.message.chat.id, 'broadcast_stopped'))


def send_broadcast(admin_chat):
    data = user_data.get(admin_chat)
    if not data:
        return

    players = list(player_profiles)
    random.shuffle(players)

    text = data['text']
    media = data['media']
    keyboard = data.get('keyboard')
    parse_mode = data['parse_mode']

    success, failed = 0, 0

    status_msg = bot.send_message(admin_chat, get_text(admin_chat, 'broadcast_progress').format(sent=0, total=len(players), failed=0), reply_markup=control_buttons(admin_chat))

    for idx, user_id in enumerate(players):
        if broadcast_status['is_stopped']:
            bot.edit_message_text(get_text(admin_chat, 'broadcast_stopped'), admin_chat, status_msg.message_id)
            return

        while broadcast_status['is_paused']:
            time.sleep(1)

        try:
            if media:
                bot.copy_message(user_id, media.chat.id, media.message_id, caption=text, parse_mode=parse_mode, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, parse_mode=parse_mode, reply_markup=keyboard)
            success += 1
        except Exception as e:
            logging.error(f"Ошибка отправки {user_id}: {e}")
            failed += 1

        if idx % 5 == 0:
            try:
                bot.edit_message_text(get_text(admin_chat, 'broadcast_progress').format(sent=success, total=len(players), failed=failed), admin_chat, status_msg.message_id, reply_markup=control_buttons(admin_chat))
            except:
                pass

        time.sleep(0.5)

    bot.edit_message_text(get_text(admin_chat, 'broadcast_finished').format(sent=success, failed=failed), admin_chat, status_msg.message_id)
    user_data.pop(admin_chat, None)


@bot.message_handler(commands=['next'])
def next_message(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    chat_title = bot.get_chat(chat_id).title

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.error(f"Ошибка при удалении сообщения команды 'next' в чате {chat_id}: {e}")

    if chat_id not in next_players:
        next_players[chat_id] = []

    if user_id not in next_players[chat_id]:
        next_players[chat_id].append(user_id)

    try:
        send_message(user_id, get_text(chat_id, 'next_notification').format(chat=chat_title), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка при отправке личного уведомления игроку {user_id}: {e}")


@bot.message_handler(commands=['leave'])
def leave_command(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    if chat_id in chat_list:
        game = chat_list[chat_id]
        if chat_id not in chat_settings:
            chat_settings[chat_id] = {"allow_leave_game": True}
        if game.game_running and not chat_settings[chat_id]["allow_leave_game"]:
            return

    leave_game(user_id, chat_id, send_private_message=True)


def notify_game_start(chat):
    chat_title = bot.get_chat(chat.chat_id).title

    if chat.chat_id in next_players:
        for player_id in next_players[chat.chat_id]:
            try:
                join_btn = types.InlineKeyboardMarkup()
                bot_username = bot.get_me().username
                join_url = f'https://t.me/{bot_username}?start=join_{chat.chat_id}'
                item1 = types.InlineKeyboardButton(get_text(chat.chat_id, 'join_button'), url=join_url)
                join_btn.add(item1)
                send_message(player_id, get_text(chat.chat_id, 'next_notification').format(chat=chat_title), reply_markup=join_btn, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Ошибка при отправке уведомления о старте игры игроку {player_id}: {e}")
        next_players[chat.chat_id] = []


def leave_game(user_id, game_chat_id, send_private_message=True):
    chat = chat_list.get(game_chat_id)

    if chat:
        if chat.game_running:
            if user_id in chat.players:
                player = chat.players.pop(user_id)
                if user_id in user_game_registration and user_game_registration[user_id] == game_chat_id:
                    del user_game_registration[user_id]
                full_name = f"{player['name']} {player.get('last_name', '')}".strip()
                clickable_name = f"[{full_name}](tg://user?id={user_id})"
                translated_role = get_short_role(player['role'], game_chat_id)
                chat.all_dead_players.append(f"{clickable_name} - {translated_role}")
                try:
                    send_message(game_chat_id, get_text(game_chat_id, 'death_msg').format(clickable_name, translated_role), parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение о выходе игрока в общий чат: {e}")
                if send_private_message:
                    try:
                        send_message(user_id, get_text(game_chat_id, 'left_game'))
                    except Exception as e:
                        logging.error(f"Не удалось отправить личное сообщение игроку {user_id}: {e}")
                if player['role'] == '🤵🏻‍♂️ Дон':
                    check_and_transfer_don_role(chat)
                if player['role'] == '🕵🏼 Комиссар':
                    check_and_transfer_sheriff_role(chat)
        elif user_id in chat.players:
            chat.players.pop(user_id)
            if user_id in user_game_registration and user_game_registration[user_id] == game_chat_id:
                del user_game_registration[user_id]
            if send_private_message:
                try:
                    send_message(user_id, get_text(game_chat_id, 'left_registration'))
                except Exception as e:
                    logging.error(f"Не удалось отправить личное сообщение игроку {user_id}: {e}")
            new_msg_text = registration_message(chat.players, chat.chat_id)
            new_markup = types.InlineKeyboardMarkup([[types.InlineKeyboardButton(get_text(game_chat_id, 'join_button'), url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}')]])
            try:
                bot.edit_message_text(chat_id=game_chat_id, message_id=chat.button_id, text=new_msg_text, reply_markup=new_markup, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения о регистрации: {e}")


def log_give_action(admin_id, target_id, items):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"📜 ЛОГ ВЫДАЧИ\n⏰ {timestamp}\n👤 Админ: {admin_id}\n🎯 Игрок: {target_id}\n📦 Выдано:\n"
    for item, amount in items:
        text += f"   • {item}: {amount}\n"
    if LOG_TO_FILE:
        with open("give_logs.txt", "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    if LOG_TO_CHANNEL:
        try:
            bot.send_message(LOG_CHANNEL_ID, text)
        except Exception as e:
            print("Ошибка логирования в канал:", e)


@bot.message_handler(commands=['give'])
def give_menu_start(message):
    allowed_user_id = 6265990443
    if message.from_user.id != allowed_user_id:
        bot.reply_to(message, get_text(message.chat.id, 'give_no_permission'))
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, get_text(message.chat.id, 'give_usage'))
        return

    try:
        target_id = int(args[1])
    except:
        bot.reply_to(message, get_text(message.chat.id, 'give_invalid_id'))
        return

    if target_id not in player_profiles:
        try:
            info = bot.get_chat(target_id)
            username = f"{info.first_name} {info.last_name}".strip()
        except:
            username = "Неизвестный"
        player_profiles[target_id] = {'id': target_id, 'name': username, 'euro': 0, 'shield': 0, 'fake_docs': 0, 'coins': 0, 'gun': 0, 'hanging_shield': 0, 'vip_until': None}

    pending_give_menu[message.chat.id] = {"target": target_id, "items": [], "message_id": None}
    send_item_menu(message.chat.id, from_start=True)


def send_item_menu(chat_id, from_start=False):
    menu_text = get_text(chat_id, 'give_menu_title')
    markup = InlineKeyboardMarkup()

    items = [("euro", get_text(chat_id, 'give_item_euro')), ("coins", get_text(chat_id, 'give_item_coins')), ("shield", get_text(chat_id, 'give_item_shield')), ("fake_docs", get_text(chat_id, 'give_item_fake_docs')), ("gun", get_text(chat_id, 'give_item_gun')), ("hanging_shield", get_text(chat_id, 'give_item_hanging_shield')), ("vip", get_text(chat_id, 'give_item_vip'))]

    for item, label in items:
        markup.add(InlineKeyboardButton(f"➕ {label}", callback_data=f"give_item_{item}"), InlineKeyboardButton(f"➖ {label}", callback_data=f"take_item_{item}"))

    markup.add(InlineKeyboardButton(get_text(chat_id, 'give_confirm'), callback_data="give_finish"))

    data = pending_give_menu[chat_id]
    if from_start:
        sent = bot.send_message(chat_id, menu_text, reply_markup=markup)
        data["message_id"] = sent.message_id
    else:
        bot.edit_message_text(menu_text, chat_id, data["message_id"], reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("give_item_") or c.data.startswith("take_item_") or c.data == "give_finish")
def give_menu_callback(call):
    chat_id = call.message.chat.id
    data = pending_give_menu.get(chat_id)
    if not data:
        bot.answer_callback_query(call.id, get_text(chat_id, 'give_session_expired'))
        return

    if call.data == "give_finish":
        finish_give_menu(call)
        return

    if call.data.startswith("give_item_"):
        mode = "give"
        item = call.data.replace("give_item_", "")
    else:
        mode = "take"
        item = call.data.replace("take_item_", "")

    bot.answer_callback_query(call.id)
    bot.edit_message_text(get_text(chat_id, 'give_enter_amount').format(item=get_text(chat_id, f'give_item_{item}'), action=get_text(chat_id, 'give') if mode == 'give' else get_text(chat_id, 'take')), chat_id, data["message_id"])
    bot.register_next_step_handler(call.message, lambda msg: set_item_amount(msg, item, mode))


def set_item_amount(message, item, mode):
    chat_id = message.chat.id
    try:
        amount = int(message.text)
    except:
        bot.reply_to(message, get_text(chat_id, 'give_invalid_amount'))
        return send_item_menu(chat_id)

    if mode == "take":
        amount = -abs(amount)

    data = pending_give_menu.get(chat_id)
    data["items"].append((item, amount))

    bot.edit_message_text(get_text(chat_id, 'give_added').format(item=get_text(chat_id, f'give_item_{item}'), amount=amount), chat_id, data["message_id"])
    send_item_menu(chat_id)


def finish_give_menu(call):
    chat_id = call.message.chat.id
    data = pending_give_menu[chat_id]

    if not data["items"]:
        bot.answer_callback_query(call.id, get_text(chat_id, 'give_empty'))
        return

    items_text = ""
    for item, amount in data["items"]:
        items_text += f"• {get_text(chat_id, f'give_item_{item}')}: {amount}\n"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(get_text(chat_id, 'give_confirm'), callback_data="give_menu_confirm"), InlineKeyboardButton(get_text(chat_id, 'give_cancel'), callback_data="give_menu_cancel"))

    bot.edit_message_text(get_text(chat_id, 'give_confirm_title').format(items=items_text), chat_id, data["message_id"], reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data in ["give_menu_confirm", "give_menu_cancel"])
def confirm_give_menu(call):
    chat_id = call.message.chat.id
    data = pending_give_menu.get(chat_id)

    if not data:
        bot.answer_callback_query(call.id, get_text(chat_id, 'give_session_expired'))
        return

    if call.data == "give_menu_cancel":
        bot.edit_message_text(get_text(chat_id, 'give_cancelled'), chat_id, data["message_id"])
        pending_give_menu.pop(chat_id, None)
        return

    profile = player_profiles[data["target"]]
    items = data["items"]
    result = get_text(chat_id, 'give_completed').format(items="")
    result_items = ""

    for item, amount in items:
        if item == "vip":
            days = abs(amount)
            profile["vip_until"] = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
            result_items += f"👑 VIP: {days} дней\n"
        else:
            profile[item] += amount
            result_items += f"{get_text(chat_id, f'give_item_{item}')}: {amount}\n"

    log_give_action(call.from_user.id, data["target"], items)

    if PLAYER_NOTIFY and not SILENT_MODE:
        notify_text = get_text(chat_id, 'give_inventory_changed').format(items=result_items)
        try:
            bot.send_message(data["target"], notify_text)
        except:
            pass

    if SILENT_MODE:
        bot.edit_message_text(get_text(chat_id, 'give_completed_silent'), chat_id, data["message_id"])
    else:
        bot.edit_message_text(get_text(chat_id, 'give_completed').format(items=result_items), chat_id, data["message_id"])

    pending_give_menu.pop(chat_id, None)


@bot.message_handler(commands=['top'])
def top_players_command(message):
    if message.chat.type == 'private':
        return

    user_id = message.from_user.id
    current_time = time.time()

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    if user_id in last_top_usage and current_time - last_top_usage[user_id] < 15:
        return

    last_top_usage[user_id] = current_time

    if not player_scores:
        send_message(message.chat.id, get_text(message.chat.id, 'top_empty'), parse_mode="Markdown")
        return

    sorted_scores = sorted(player_scores.items(), key=lambda x: x[1], reverse=True)[:15]

    top_message = get_text(message.chat.id, 'top_title')

    for index, (user_id, score) in enumerate(sorted_scores, start=1):
        try:
            user = bot.get_chat_member(message.chat.id, user_id)
            player_name = f"{user.user.first_name} {user.user.last_name}" if user.user.last_name else user.user.first_name
        except Exception:
            player_name = "Неизвестный игрок"
        top_message += f"{index}. {player_name}\n"

    send_message(message.chat.id, top_message, parse_mode="Markdown")


@bot.message_handler(commands=['reset_scores'])
def reset_scores_command(message):
    if message.from_user.id != OWNER_ID:
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        send_message(message.chat.id, get_text(message.chat.id, 'admin_only'))
        return

    player_scores.clear()
    game_timers.clear()

    try:
        send_zip_to_channel()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Тип', 'ID', 'Значение'])
        file_data = io.BytesIO(output.getvalue().encode('utf-8'))
        file_data.name = 'player_scores_reset.csv'
        bot.send_document(SETTINGS_CHANNEL_ID, file_data, caption="Очки сброшены")
    except Exception as e:
        logging.error(f"Ошибка при сохранении сброшенных очков: {e}")

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

    send_message(message.chat.id, get_text(message.chat.id, 'reset_scores_success'), parse_mode="Markdown")
    logging.info(f"Администратор {message.from_user.id} сбросил все очки игроков")


def all_night_actions_taken(chat):
    for player in chat.players.values():
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '🕵🏼 Комиссар', '👨🏼‍⚕️ Дәрігер', '🧙‍♂️ Қаңғыбас', '💃🏼 Көңілдес', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз'] and player['role'] != 'dead':
            if player.get('voting_blocked', False) or not player.get('action_taken', False):
                return False
    time.sleep(5)
    return True


def process_sheriff_actions(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "ru")

    if chat.lawyer_target and chat.sheriff_check and chat.lawyer_target == chat.sheriff_check:
        checked_player = chat.players[chat.sheriff_check]
        if checked_player['role'] in {'🤵🏻‍♂️ Дон', '🤵🏻 Мафия'}:
            try:
                send_message(chat.sheriff_id, get_text(chat.chat_id, 'sheriff_check_result_fake').format(player=get_full_name(checked_player)))
            except Exception:
                pass
            try:
                send_message(chat.sheriff_check, get_text(chat.chat_id, 'sheriff_check_lawyer_protected'), parse_mode="Markdown")
            except Exception:
                pass
            if chat.sergeant_id and chat.sergeant_id in chat.players:
                try:
                    send_message(chat.sergeant_id, get_text(chat.chat_id, 'sheriff_check_result_fake').format(player=get_full_name(checked_player)))
                except Exception:
                    pass
            return

    if chat.sheriff_check and chat.sheriff_check in chat.players:
        checked_player = chat.players[chat.sheriff_check]
        player_profile = player_profiles.get(chat.sheriff_check, {})
        allowed_roles = {'🤵🏻‍♂️ Дон', '🔪 Жауыз', '🤵🏻 Мафия'}

        if (player_profile.get('fake_docs', 0) > 0 and not player_profile.get('fake_docs_used', False) and player_profile.get('docs_active', False) and checked_player['role'] in allowed_roles):
            try:
                send_message(chat.sheriff_id, get_text(chat.chat_id, 'sheriff_check_result_fake').format(player=get_full_name(checked_player)))
            except Exception:
                pass
            try:
                send_message(chat.sheriff_check, get_text(chat.chat_id, 'sheriff_check_fake_used'), parse_mode="Markdown")
            except Exception:
                pass
            if chat.sergeant_id and chat.sergeant_id in chat.players:
                try:
                    send_message(chat.sergeant_id, get_text(chat.chat_id, 'sheriff_check_result_fake').format(player=get_full_name(checked_player)))
                except Exception:
                    pass
            player_profile['fake_docs'] -= 1
            player_profile['fake_docs_used'] = True
            player_profiles[chat.sheriff_check] = player_profile
        else:
            try:
                send_message(chat.sheriff_id, get_text(chat.chat_id, 'sheriff_check_result').format(player=get_full_name(checked_player), role=get_short_role(checked_player['role'], chat.chat_id)))
            except Exception:
                pass
            try:
                send_message(chat.sheriff_check, get_text(chat.chat_id, 'sheriff_check_visited'), parse_mode="Markdown")
            except Exception:
                pass
            if chat.sergeant_id and chat.sergeant_id in chat.players:
                try:
                    send_message(chat.sergeant_id, get_text(chat.chat_id, 'sheriff_check_result').format(player=get_full_name(checked_player), role=get_short_role(checked_player['role'], chat.chat_id)))
                except Exception:
                    pass


def handle_voting(chat):
    chat.is_voting_time = True
    chat.vote_counts.clear()

    lang = chat_settings.get(chat.chat_id, {}).get("language", "ru")
    voting_time = chat_settings.get(chat.chat_id, {}).get("voting_time", 45)

    title = get_text(chat.chat_id, 'voting_title').format(time=voting_time)
    vote_msg = send_message(chat.chat_id, title, reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton(get_text(chat.chat_id, 'vote_notification'), url=f'https://t.me/{bot.get_me().username}')]]), parse_mode="Markdown")
    chat.vote_message_id = vote_msg.message_id

    lover_target_healed = chat.doc_target == chat.lover_target_id

    for voter_id in chat.players:
        if voter_id != chat.lover_target_id or lover_target_healed:
            try:
                voter_role = chat.players[voter_id]['role']
                buttons = []
                sorted_players = sorted(chat.players.items(), key=lambda item: item[1]['number'])
                for pid, target in sorted_players:
                    if pid == voter_id:
                        continue
                    name = get_full_name(target)
                    if voter_role in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон'] and target['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
                        name = f"🤵🏻 {name}"
                    if voter_role in ['🕵🏼 Комиссар', '👮🏼 Сержант']:
                        if target['role'] == '🕵🏼 Комиссар':
                            name = f"🕵🏼 {name}"
                        if target['role'] == '👮🏼 Сержант':
                            name = f"👮🏼 {name}"
                    buttons.append([types.InlineKeyboardButton(name, callback_data=f"{pid}_vote")])
                buttons.append([types.InlineKeyboardButton(get_text(chat.chat_id, 'voting_skip'), callback_data='skip_vote')])
                send_message(voter_id, get_text(chat.chat_id, 'voting_pm_text'), reply_markup=types.InlineKeyboardMarkup(buttons), parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Ошибка отправки голосования {voter_id}: {e}")

    time.sleep(voting_time)
    chat.is_voting_time = False
    return end_day_voting(chat)


def notify_night_start(chat_id, players_alive_text):
    bot_username = bot.get_me().username
    private_message_url = f'https://t.me/{bot_username}'
    private_message_btn = types.InlineKeyboardMarkup()
    private_message_btn.add(types.InlineKeyboardButton(get_text(chat_id, 'vote_notificatio'), url=private_message_url))
    bot.send_animation(chat_id, 'https://t.me/ProfileChaekBot/31691', caption=get_text(chat_id, 'night_start_caption'), parse_mode="Markdown", reply_markup=private_message_btn)
    time.sleep(1.5)
    send_message(chat_id=chat_id, message=players_alive_text, parse_mode="Markdown", reply_markup=private_message_btn)


def reset_night_state(chat):
    chat.previous_lover_target_id = chat.lover_target_id
    chat.previous_hobo_target = chat.hobo_target
    chat.previous_lawyer_target = chat.lawyer_target
    chat.dead = None
    chat.sheriff_check = None
    chat.sheriff_shoot = None
    chat.doc_target = None
    chat.mafia_votes.clear()
    chat.hobo_target = None
    chat.hobo_visitors.clear()
    chat.lover_target_id = None
    chat.shList_id = None
    chat.lawyer_target = None
    chat.maniac_target = None
    chat.voting_finished = False
    for player in chat.players.values():
        player['action_taken'] = False


@bot.message_handler(content_types=['new_chat_members'])
def handle_new_member(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            setup_new_chat(message.chat.id)
            break


def setup_new_chat(chat_id):
    chat_settings[chat_id] = {
        "language": "ru",
        "pin_registration": True,
        "allow_registration": True,
        "allow_leave_game": True,
        "registration_time": (120, 60),
        "night_time": 45,
        "day_time": 60,
        "voting_time": 45,
        "players_to_start": 20,
        "anonymous_voting": False,
        "confirmation_time": 30,
        "mafia_ratio": 4,
        "shield_buff": True,
        "docs_buff": True,
        "hanging_shield_buff": True,
        "gun_buff": True
    }

    welcome_markup = types.InlineKeyboardMarkup()
    welcome_markup.add(types.InlineKeyboardButton("🇰🇿 Қазақша", callback_data=f"init_lang_kz_{chat_id}"), types.InlineKeyboardButton("🇷🇺 Русский", callback_data=f"init_lang_ru_{chat_id}"))
    send_message(chat_id, get_text(chat_id, 'welcome_lang_choice'), reply_markup=welcome_markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("init_lang_"))
def handle_init_language(call):
    lang = call.data.split("_")[2]
    chat_id = int(call.data.split("_")[3])

    if chat_id not in chat_settings:
        chat_settings[chat_id] = {}
    chat_settings[chat_id]["language"] = lang

    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass

    send_message(chat_id, get_text(chat_id, 'welcome_chat'))

    if is_admin_or_me(bot, chat_id, call.from_user.id):
        settings_handler_by_chat(chat_id)


def settings_handler_by_chat(chat_id):
    if chat_id not in chat_settings:
        chat_settings[chat_id] = {
            "language": "ru",
            "pin_registration": True,
            "allow_registration": True,
            "allow_leave_game": True,
            "registration_time": (120, 60),
            "night_time": 45,
            "day_time": 60,
            "voting_time": 45,
            "players_to_start": 20,
            "anonymous_voting": False,
            "confirmation_time": 30,
            "mafia_ratio": 4,
            "shield_buff": True,
            "docs_buff": True,
            "hanging_shield_buff": True,
            "gun_buff": True
        }

    try:
        chat_admins = bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in chat_admins]
        for admin_id in admin_ids:
            try:
                main_menu_kb = types.InlineKeyboardMarkup()
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'pin_reg'), callback_data=f"menu_pin_{chat_id}"))
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'admin_start'), callback_data=f"menu_commands_{chat_id}"))
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'leave_cmd'), callback_data=f"menu_leave_{chat_id}"))
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'mafia_count'), callback_data=f"menu_mafia_ratio_{chat_id}"))
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'times'), callback_data=f"menu_time_{chat_id}"))
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'language'), callback_data=f"menu_language_{chat_id}"))
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'close'), callback_data=f"close_settings_{chat_id}"))
                send_message(admin_id, get_text(chat_id, 'settings_title'), reply_markup=main_menu_kb)
            except Exception as e:
                print(f"Не удалось отправить настройки администратору {admin_id}: {e}")
    except Exception as e:
        print(f"Ошибка при получении администраторов чата {chat_id}: {e}")


def process_lover_action(chat):
    don_blocked = False
    lover_target_healed = False

    if chat.lover_target_id and chat.lover_target_id in chat.players:
        lover_target = chat.players[chat.lover_target_id]
        try:
            send_message(chat.lover_target_id, get_text(chat.chat_id, 'lover_song'), parse_mode="Markdown")
        except Exception:
            pass
        if chat.doc_target == chat.lover_target_id:
            try:
                send_message(chat.lover_target_id, get_text(chat.chat_id, 'lover_blocked_by_doctor'), parse_mode="Markdown")
            except Exception:
                pass
            lover_target_healed = True
        else:
            lover_target['voting_blocked'] = True
            if lover_target['role'] == '🤵🏻‍♂️ Дон':
                don_blocked = True
            elif lover_target['role'] == '🕵🏼 Комиссар':
                chat.sheriff_check = None
                chat.sheriff_shoot = None
            elif lover_target['role'] == '👨🏼‍⚕️ Дәрігер':
                chat.doc_target = None
            elif lover_target['role'] == '🧙‍♂️ Қаңғыбас':
                chat.hobo_target = None
                lover_target['voting_blocked'] = True
            elif lover_target['role'] == '👨🏼‍💼 Қорғаушы':
                chat.lawyer_target = None
            elif lover_target['role'] == '🔪 Жауыз':
                chat.maniac_target = None

    if lover_target_healed:
        lover_target['voting_blocked'] = False
        lover_target['healed_from_lover'] = True


def process_hobo_action(chat):
    if chat.hobo_id and chat.hobo_target:
        hobo_target = chat.hobo_target
        if hobo_target in chat.players:
            hobo_target_name = get_full_name(chat.players[hobo_target])
            hobo_visitors = []
            try:
                send_message(hobo_target, get_text(chat.chat_id, 'hobo_visited'), parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение цели бомжа {hobo_target}: {e}")

            if chat.dead and chat.dead[0] == hobo_target:
                don_id = chat.don_id
                if don_id in chat.players:
                    hobo_visitors.append(get_full_name(chat.players[don_id]))
            if chat.sheriff_check == hobo_target or chat.sheriff_shoot == hobo_target:
                sheriff_id = chat.sheriff_id
                if sheriff_id in chat.players:
                    hobo_visitors.append(get_full_name(chat.players[sheriff_id]))
            if chat.doc_target == hobo_target:
                doc_id = next((pid for pid, p in chat.players.items() if p['role'] == '👨🏼‍⚕️ Дәрігер'), None)
                if doc_id and doc_id in chat.players:
                    hobo_visitors.append(get_full_name(chat.players[doc_id]))
            if chat.lawyer_target == hobo_target:
                lawyer_id = chat.lawyer_id
                if lawyer_id in chat.players:
                    hobo_visitors.append(get_full_name(chat.players[lawyer_id]))
            if chat.maniac_target == hobo_target:
                maniac_id = chat.maniac_id
                if maniac_id in chat.players:
                    hobo_visitors.append(get_full_name(chat.players[maniac_id]))
            if chat.lover_target_id == hobo_target:
                lover_id = chat.lover_id
                if lover_id in chat.players:
                    hobo_visitors.append(get_full_name(chat.players[lover_id]))

            try:
                if hobo_visitors:
                    visitors_names = ', '.join(hobo_visitors)
                    send_message(chat.hobo_id, get_text(chat.chat_id, 'hobo_report_with_visitors').format(target=hobo_target_name, visitors=visitors_names))
                else:
                    send_message(chat.hobo_id, get_text(chat.chat_id, 'hobo_report_no_visitors').format(target=hobo_target_name))
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение бомжу {chat.hobo_id}: {e}")
        try:
            if hobo_target not in chat.players:
                send_message(chat.hobo_id, get_text(chat.chat_id, 'hobo_report_no_target'))
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение бомжу {chat.hobo_id} о пустой встрече: {e}")


def send_night_actions(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    gun_enabled = chat_settings.get(chat.chat_id, {}).get("gun_buff", True)

    for player_id, player in chat.players.items():
        if not chat.game_running:
            break
        try:
            if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
                list_btn(chat.players, player_id, 'мафия', get_text(chat.chat_id, 'mafia_vote_question'), 'м')
            if player['role'] == '🕵🏼 Комиссар':
                send_sheriff_menu(chat, player_id)
            if player['role'] == '👨🏼‍⚕️ Дәрігер':
                list_btn(chat.players, player_id, 'доктор', get_text(chat.chat_id, 'doctor_question'), 'д')
            if player['role'] == '🧙‍♂️ Қаңғыбас':
                players_btn = types.InlineKeyboardMarkup()
                for key, val in chat.players.items():
                    if key != player_id and val['role'] != 'dead' and key != chat.previous_hobo_target:
                        players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_б'))
                send_message(player_id, get_text(chat.chat_id, 'hobo_question'), reply_markup=players_btn)
            if player['role'] == '💃🏼 Көңілдес':
                players_btn = types.InlineKeyboardMarkup()
                for key, val in chat.players.items():
                    if key != player_id and val['role'] != 'dead' and (chat.previous_lover_target_id is None or key != chat.previous_lover_target_id):
                        players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_л'))
                send_message(player_id, get_text(chat.chat_id, 'lover_question'), reply_markup=players_btn)
            if player['role'] == '👨🏼‍💼 Қорғаушы':
                players_btn = types.InlineKeyboardMarkup()
                for key, val in chat.players.items():
                    if key != player_id and val['role'] != 'dead' and key != chat.previous_lawyer_target:
                        players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_а'))
                send_message(player_id, get_text(chat.chat_id, 'lawyer_question'), reply_markup=players_btn)
            if player['role'] == '🔪 Жауыз':
                list_btn(chat.players, player_id, 'маньяк', get_text(chat.chat_id, 'maniac_question'), 'мк')
            if gun_enabled:
                profile = get_or_create_profile(player_id, player['name'])
                if profile['gun'] > 0 and not profile['gun_used'] and player['role'] != 'dead':
                    players_btn = types.InlineKeyboardMarkup()
                    for key, val in chat.players.items():
                        if key != player_id and val['role'] != 'dead':
                            players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_gun'))
                    send_message(player_id, get_text(chat.chat_id, 'gun_question_night'), reply_markup=players_btn)
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение игроку {player_id}: {e}")


async def game_cycle(chat_id):
    global chat_list, game_tasks
    chat = chat_list[chat_id]
    game_start_time = time.time()
    day_count = 1

    try:
        while chat.game_running:
            if not chat.game_running:
                break
            await asyncio.sleep(3)
            if not chat.game_running:
                break

            chat.is_night = True
            chat.is_voting_time = False
            reset_night_state(chat)
            dead_id = None

            if not chat.game_running:
                break

            players_alive_text = night_message(chat.players, chat.chat_id)
            notify_night_start(chat_id, players_alive_text)
            notify_mafia_and_don(chat)
            notify_police(chat)

            if not chat.game_running:
                break

            send_night_actions(chat)

            start_time = time.time()
            night_time = chat_settings.get(chat_id, {}).get("night_time", 45)

            while time.time() - start_time < night_time:
                if all_night_actions_taken(chat):
                    break
                await asyncio.sleep(2)

            if not chat.game_running:
                break

            chat.is_night = False
            process_lover_action(chat)
            mafia_victim = process_mafia_action(chat)

            if not chat.game_running:
                break

            process_hobo_action(chat)

            if not chat.game_running:
                break

            lawyer_target = None
            if chat.lawyer_id and chat.lawyer_id in chat.players:
                lawyer_target = chat.players[chat.lawyer_id].get('lawyer_target')

            killed_by_maniac = None
            if chat.maniac_target and chat.maniac_target in chat.players:
                killed_by_maniac = (chat.maniac_target, chat.players[chat.maniac_target])
                chat.maniac_target = None

            process_sheriff_actions(chat)

            to_remove = []
            for player_id, player in chat.players.items():
                if not chat.game_running:
                    break
                if player['role'] not in ['👨🏼 Тату тұрғын', '🤞 Жолы болғыш', '💣 Камикадзе', '🤦🏼 Самоубийца', '👮🏼 Сержант'] and not player.get('action_taken', False):
                    player['skipped_actions'] += 1
                    if player['skipped_actions'] >= 2:
                        to_remove.append(player_id)
                else:
                    player['action_taken'] = False
                    player['skipped_actions'] = 0

            bot.send_photo(chat_id, 'https://t.me/ProfileChaekBot/29561', caption=get_text(chat_id, 'day_caption').format(day=day_count), parse_mode="Markdown")
            await asyncio.sleep(1.5)

            if not chat.game_running:
                break

            killed_by_mafia = chat.dead
            killed_by_sheriff = None
            killed_by_bomber = None

            if chat.sheriff_shoot and chat.sheriff_shoot in chat.players:
                killed_by_sheriff = (chat.sheriff_shoot, chat.players[chat.sheriff_shoot])
                chat.sheriff_shoot = None

            process_deaths(chat, killed_by_mafia, killed_by_sheriff, killed_by_bomber, killed_by_maniac)

            if not chat.game_running:
                break

            if check_game_end(chat, game_start_time):
                break

            players_alive_text = players_alive(chat.players, "day", chat.chat_id)
            msg = send_message(chat_id=chat_id, message=players_alive_text, parse_mode="Markdown")
            chat.button_id = msg.message_id

            chat.dead = None
            chat.sheriff_check = None

            day_time = chat_settings.get(chat_id, {}).get("day_time", 60)
            await asyncio.sleep(day_time)

            if not chat.game_running:
                break

            should_continue = handle_voting(chat)

            if not chat.game_running:
                break

            if not chat.voting_finished:
                should_continue = end_day_voting(chat)

            await asyncio.sleep(2)

            if not should_continue:
                reset_voting(chat)
                day_count += 1
                continue

            chat.is_voting_time = False

            if check_game_end(chat, game_start_time):
                break

            confirmation_time = chat_settings.get(chat_id, {}).get("confirmation_time", 30)
            await asyncio.sleep(confirmation_time)

            if not chat.game_running:
                break

            handle_confirm_vote(chat)
            chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
            await asyncio.sleep(2)

            chat.vote_counts.clear()
            for player in chat.players.values():
                if not chat.game_running:
                    break
                player['has_voted'] = False

            for player in chat.players.values():
                player['voting_blocked'] = False

            if check_game_end(chat, game_start_time):
                break

            day_count += 1

    except asyncio.CancelledError:
        logging.info(f"Игра в чате {chat_id} была принудительно остановлена.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('join_'))
def join_game(call):
    chat_id = int(call.data.split('_')[1])
    chat = chat_list.get(chat_id)
    user_id = call.from_user.id
    first_name = call.from_user.first_name or ""
    last_name = call.from_user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    
    lang = chat_settings.get(chat_id, {}).get("language", "kz")

    if chat and not chat.game_running and chat.button_id:
        if user_id not in chat.players:
            add_player(chat, user_id, full_name, last_name, len(chat.players) + 1)
            bot.answer_callback_query(call.id, text=get_text(chat_id, 'join_success_short'))
            new_msg_text = registration_message(chat.players, chat.chat_id)
            if new_msg_text != call.message.text:
                try:
                    bot.edit_message_text(chat_id=chat_id, message_id=chat.button_id, text=new_msg_text, reply_markup=call.message.reply_markup, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Ошибка обновления сообщения: {e}")
            players_needed = chat_settings.get(chat_id, {}).get('players_to_start', 20)
            if len(chat.players) >= players_needed:
                _start_game(chat_id)
        else:
            bot.answer_callback_query(call.id, text=get_text(chat_id, 'already_registered_short'))
    else:
        bot.answer_callback_query(call.id, text=get_text(chat_id, 'game_started_error'))


@bot.callback_query_handler(func=lambda call: call.data == 'skip_vote')
def skip_vote_handler(call):
    global chat_list

    from_id = call.from_user.id
    chat = None
    for c_id, c in chat_list.items():
        if from_id in c.players:
            chat = c
            chat_id = c_id
            break

    if not chat:
        bot.answer_callback_query(call.id, text=get_text(0, 'not_in_game'))
        return

    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    anon = chat_settings.get(chat.chat_id, {}).get("anonymous_voting", True)

    if not chat.is_voting_time:
        bot.answer_callback_query(call.id, get_text(chat.chat_id, 'voting_ended'))
        return

    if 'vote_counts' not in chat.__dict__:
        chat.vote_counts = {}

    player = chat.players.get(from_id)

    if player.get('voting_blocked', False) and not player.get('healed_from_lover', False):
        bot.answer_callback_query(call.id, get_text(chat.chat_id, 'voting_blocked_by_lover'))
        return

    if not player.get('has_voted', False):
        chat.vote_counts['skip'] = chat.vote_counts.get('skip', 0) + 1
        player['has_voted'] = True

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat.chat_id, 'voting_skip'))

        full_name = get_full_name(player)
        voter_link = f"[{full_name}](tg://user?id={from_id})"

        if anon:
            text = get_text(chat.chat_id, 'vote_announce_anon').format(voter=voter_link)
        else:
            text = get_text(chat.chat_id, 'vote_announce_open').format(voter=voter_link, target=get_text(chat.chat_id, 'skip'))

        send_message(chat_id, text, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global chat_list, vote_timestamps
    from_id = call.from_user.id
    current_time = time.time()

    chat = None
    for c_id, c in chat_list.items():
        if from_id in c.players:
            chat = c
            chat_id = c_id
            break

    if not chat:
        bot.answer_callback_query(call.id, text=get_text(0, 'not_in_game'))
        return

    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    player = chat.players.get(from_id)

    if player['role'] == 'dead':
        bot.answer_callback_query(call.id, text=get_text(chat_id, 'dead_player'))
        return

    if chat.confirm_votes.get('player_id') == from_id:
        return

    if player.get('voting_blocked', False) and not player.get('healed_from_lover', False):
        bot.answer_callback_query(call.id, text=get_text(chat_id, 'voting_blocked_by_lover'))
        return

    if from_id in vote_timestamps:
        last_vote_time = vote_timestamps[from_id]
        if current_time - last_vote_time < 1:
            bot.answer_callback_query(call.id, text=get_text(chat_id, 'confirm_vote_accepted'))
            return

    vote_timestamps[from_id] = current_time

    try:
        data_parts = call.data.split('_')

        if len(data_parts) < 2:
            logging.error(f"Недостаточно данных в callback_data: {call.data}")
            return

        action = data_parts[0]
        role = data_parts[1]

        if action in ['yes', 'no']:
            if from_id == chat.confirm_votes['player_id']:
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'confirm_vote_cannot'))
                return
            time.sleep(1.5)

        if len(data_parts) == 2 and data_parts[1] == 'gun':
            if not chat.is_night:
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'gun_night_only'))
                return
            profile = get_or_create_profile(from_id, player['name'])
            if profile['gun'] <= 0 or profile['gun_used']:
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'gun_no_available'))
                return
            target_id = int(data_parts[0])
            if target_id not in chat.players or chat.players[target_id]['role'] == 'dead':
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'gun_target_unavailable'))
                return
            profile['gun'] -= 1
            chat.gun_kill = (target_id, chat.players[target_id])
            target_name = chat.players[target_id]['name']
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'gun_chosen').format(player=target_name))
            send_message(chat.chat_id, get_text(chat.chat_id, 'night_gun_used'), parse_mode="Markdown")
            bot.answer_callback_query(call.id, text=get_text(chat_id, 'confirm_vote_accepted'))
            return

        if role == '🕵🏼 Комиссар':
            if not chat.is_night:
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_not_night'))
                return
            if chat.players[from_id].get('action_taken', False):
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_action_already_taken'))
                return

        if call.data.startswith('confirm'):
            data_parts = call.data.split('_')
            player_id = int(data_parts[1])
            vote_confirmation = data_parts[2]
            from_id = call.from_user.id
            chat_id = call.message.chat.id
            chat = chat_list.get(chat_id)

            if chat.chat_id != chat_id:
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'confirm_vote_cannot'))
                return

            if not getattr(chat, 'confirm_votes_active', True):
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'confirm_vote_ended'))
                return

            previous_vote = chat.confirm_votes['voted'].get(from_id)
            if previous_vote == vote_confirmation:
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'confirm_vote_already'))
                return

            if previous_vote == 'yes':
                chat.confirm_votes['yes'] -= 1
            elif previous_vote == 'no':
                chat.confirm_votes['no'] -= 1

            chat.confirm_votes['voted'][from_id] = vote_confirmation
            if vote_confirmation == 'yes':
                chat.confirm_votes['yes'] += 1
            elif vote_confirmation == 'no':
                chat.confirm_votes['no'] += 1

            confirm_markup = types.InlineKeyboardMarkup()
            confirm_markup.add(types.InlineKeyboardButton(get_text(chat_id, 'confirm_vote_yes').format(count=chat.confirm_votes['yes']), callback_data=f"confirm_{player_id}_yes"), types.InlineKeyboardButton(get_text(chat_id, 'confirm_vote_no').format(count=chat.confirm_votes['no']), callback_data=f"confirm_{player_id}_no"))

            can_edit = time.time() - confirm_vote_timestamps.get(chat.chat_id, 0) >= 1

            try:
                if can_edit:
                    bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=confirm_markup)
                    confirm_vote_timestamps[chat.chat_id] = time.time()
                bot.answer_callback_query(call.id, text=get_text(chat_id, 'confirm_vote_accepted'))
            except Exception as e:
                logging.error(f"Ошибка при обновлении клавиатуры голосования: {e}")

            alive_players_count = len([p for pid, p in chat.players.items() if p['role'] != 'dead' and p['status'] == 'alive' and pid != chat.confirm_votes['player_id']])

            if chat.confirm_votes['yes'] + chat.confirm_votes['no'] == alive_players_count:
                chat.confirm_votes_active = False
                disable_vote_buttons(chat)
                send_voting_results(chat, chat.players[player_id]['name'], chat.confirm_votes['yes'], chat.confirm_votes['no'])

        else:
            action = data_parts[1]

            if action in ['ш', 'с', 'м', 'мк', 'д', 'б', 'л', 'а', 'vote']:
                try:
                    target_id = int(data_parts[0])
                except ValueError:
                    logging.error(f"Невозможно преобразовать данные в число: {data_parts[0]}")
                    return

                player_role = chat.players[from_id]['role']

                if player_role == '🕵🏼 Комиссар' and action == 'ш':
                    if not chat.is_night:
                        bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_not_night'))
                        return
                    if chat.players[from_id].get('action_taken', False):
                        bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_action_already_taken'))
                        return
                    chat.sheriff_check = target_id
                    chat.players[from_id]['action_taken'] = True
                    if chat.last_sheriff_menu_id:
                        try:
                            bot.edit_message_text(chat_id=from_id, message_id=chat.last_sheriff_menu_id, text=get_text(chat_id, 'sheriff_checked').format(player=chat.players[target_id]['name']))
                        except Exception as e:
                            logging.error(f"Ошибка при обновлении последнего меню Комиссара: {e}")
                    send_message(chat.chat_id, get_text(chat_id, 'night_sheriff_check'), parse_mode="Markdown")
                    bot.edit_message_reply_markup(chat_id=from_id, message_id=chat.last_sheriff_menu_id, reply_markup=None)
                    if chat.sergeant_id and chat.sergeant_id in chat.players:
                        send_message(chat.sergeant_id, get_text(chat_id, 'sheriff_checked').format(player=chat.players[target_id]['name']))

                elif player_role == '🕵🏼 Комиссар' and action == 'с':
                    if not chat.is_night:
                        bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_not_night'))
                        return
                    if chat.players[from_id].get('action_taken', False):
                        bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_action_already_taken'))
                        return
                    chat.sheriff_shoot = target_id
                    chat.players[from_id]['action_taken'] = True
                    if chat.last_sheriff_menu_id:
                        try:
                            bot.edit_message_text(chat_id=from_id, message_id=chat.last_sheriff_menu_id, text=get_text(chat_id, 'sheriff_shot').format(player=chat.players[target_id]['name']))
                        except Exception as e:
                            logging.error(f"Ошибка при обновлении последнего меню Комиссара: {e}")
                    send_message(chat.chat_id, get_text(chat_id, 'night_sheriff_shoot'), parse_mode="Markdown")
                    bot.edit_message_reply_markup(chat_id=from_id, message_id=chat.last_sheriff_menu_id, reply_markup=None)
                    if chat.sergeant_id and chat.sergeant_id in chat.players:
                        send_message(chat.sergeant_id, get_text(chat_id, 'sheriff_shot').format(player=chat.players[target_id]['name']))

                elif player_role in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон'] and action == 'м':
                    if not handle_night_action(call, chat, player_role):
                        return
                    if target_id not in chat.players or chat.players[target_id]['role'] == 'dead':
                        bot.answer_callback_query(call.id, get_text(chat_id, 'gun_target_unavailable'))
                        return
                    victim_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'mafia_voted').format(player=victim_name))

                    if from_id not in chat.mafia_votes:
                        chat.mafia_votes[from_id] = target_id
                        voter_name = f"{chat.players[from_id]['name']} {chat.players[from_id].get('last_name', '')}".strip()

                        if player_role == '🤵🏻‍♂️ Дон':
                            send_message_to_mafia(chat, get_text(chat_id, 'mafia_vote_notification_don').format(name=voter_name, id=from_id, victim=victim_name))
                            for player_id, player in chat.players.items():
                                if player['role'] == '👨🏼‍💼 Қорғаушы':
                                    send_message(player_id, get_text(chat_id, 'mafia_vote_notification_lawyer').format(victim=victim_name))
                        else:
                            send_message_to_mafia(chat, get_text(chat_id, 'mafia_vote_notification_mafia').format(name=voter_name, id=from_id, victim=victim_name))
                            for player_id, player in chat.players.items():
                                if player['role'] == '👨🏼‍💼 Қорғаушы':
                                    send_message(player_id, get_text(chat_id, 'mafia_vote_notification_lawyer').format(victim=victim_name))
                    else:
                        bot.answer_callback_query(call.id, get_text(chat_id, 'voting_already_voted'))

                elif player_role == '👨🏼‍⚕️ Дәрігер' and action == 'д':
                    if not handle_night_action(call, chat, player_role):
                        return
                    victim_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'doctor_chosen').format(player=victim_name))

                    if target_id == from_id:
                        if player.get('self_healed', False):
                            bot.answer_callback_query(call.id, text=get_text(chat_id, 'doctor_self_heal_forbidden'))
                            return
                        else:
                            player['self_healed'] = True

                    chat.doc_target = target_id
                    send_message(chat.chat_id, get_text(chat_id, 'night_doctor'), parse_mode="Markdown")

                elif player_role == '🧙‍♂️ Қаңғыбас' and action == 'б':
                    if not handle_night_action(call, chat, player_role):
                        return
                    target_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                    chat.hobo_target = target_id
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'hobo_chosen').format(player=target_name))
                    send_message(chat.chat_id, get_text(chat_id, 'night_hobo'), parse_mode="Markdown")

                elif player_role == '💃🏼 Көңілдес' and action == 'л':
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.previous_lover_target_id = chat.lover_target_id
                    chat.lover_target_id = target_id
                    target_name = f"{chat.players[chat.lover_target_id]['name']} {chat.players[chat.lover_target_id].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'lover_chosen').format(player=target_name))
                    send_message(chat.chat_id, get_text(chat_id, 'night_lover'), parse_mode="Markdown")
                    logging.info(f"Предыдущая цель любовницы обновлена: {chat.previous_lover_target_id}")
                    logging.info(f"Текущая цель любовницы: {chat.lover_target_id}")

                elif player_role == '👨🏼‍💼 Қорғаушы' and action == 'а':
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.lawyer_target = target_id
                    target_name = f"{chat.players[chat.lawyer_target]['name']} {chat.players[chat.lawyer_target].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'lawyer_chosen').format(player=target_name))
                    send_message(chat.chat_id, get_text(chat_id, 'night_lawyer'), parse_mode="Markdown")

                elif player_role == '🔪 Жауыз' and action == 'мк':
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.maniac_target = target_id
                    target_name = f"{chat.players[chat.maniac_target]['name']} {chat.players[chat.maniac_target].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'maniac_chosen').format(player=target_name))
                    send_message(chat.chat_id, get_text(chat_id, 'night_maniac'), parse_mode="Markdown")

                elif action == 'vote':
                    if not chat.is_voting_time:
                        bot.answer_callback_query(call.id, get_text(chat_id, 'voting_ended'))
                        return

                    if 'vote_counts' not in chat.__dict__:
                        chat.vote_counts = {}

                    if player.get('voting_blocked', False) and not player.get('healed_from_lover', False):
                        bot.answer_callback_query(call.id, get_text(chat_id, 'voting_blocked_by_lover'))
                        return

                    if not chat.players[from_id].get('has_voted', False):
                        victim_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                        chat.vote_counts[target_id] = chat.vote_counts.get(target_id, 0) + 1
                        chat.players[from_id]['has_voted'] = True

                        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_text(chat_id, 'vote_casted').format(player=victim_name))

                        voter_name = f"[{chat.players[from_id]['name']} {chat.players[from_id].get('last_name', '')}](tg://user?id={from_id})".strip()
                        target_name = f"[{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}](tg://user?id={target_id})".strip()

                        anon = chat_settings.get(chat_id, {}).get("anonymous_voting", True)

                        if anon:
                            text = get_text(chat_id, 'vote_announce_anon').format(voter=voter_name)
                        else:
                            text = get_text(chat_id, 'vote_announce_open').format(voter=voter_name, target=target_name)

                        send_message(chat_id, text, parse_mode="Markdown")

            elif action == 'check':
                if not chat.is_night:
                    bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_not_night'))
                    return
                if chat.players[from_id].get('action_taken', False):
                    bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_action_already_taken'))
                    return
                list_btn(chat.players, from_id, '🕵🏼 Комиссар', get_text(chat_id, 'sheriff_check'), 'ш', message_id=chat.last_sheriff_menu_id)

            elif action == 'shoot':
                if not chat.is_night:
                    bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_not_night'))
                    return
                if chat.players[from_id].get('action_taken', False):
                    bot.answer_callback_query(call.id, text=get_text(chat_id, 'sheriff_action_already_taken'))
                    return
                list_btn(chat.players, from_id, '🕵🏼 Комиссар', get_text(chat_id, 'sheriff_shoot'), 'с', message_id=chat.last_sheriff_menu_id)

    except Exception as e:
        logging.error(f"Ошибка в callback_handler: {e}")


def check_player_status(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status in ["kicked", "left", "restricted"]:
            leave_game(user_id, chat_id, send_private_message=False)
            return False
        return True
    except Exception as e:
        logging.error(f"Ошибка проверки статуса игрока {user_id}: {e}")
        return True


def monitor_players():
    while True:
        for chat_id, game in chat_list.items():
            for user_id in list(game.players.keys()):
                check_player_status(chat_id, user_id)
        time.sleep(0.3)


threading.Thread(target=monitor_players, daemon=True).start()


@bot.message_handler(content_types=['left_chat_member'])
def handle_player_leave(message):
    user_id = message.left_chat_member.id
    chat_id = message.chat.id
    leave_game(user_id, chat_id)


@bot.message_handler(func=lambda message: message.chat.type == 'private')
def handle_private_message(message):
    user_id = message.from_user.id
    chat = next((chat for chat in chat_list.values() if user_id in chat.players or user_id in chat.dead_last_words), None)

    if chat:
        if not chat.game_running:
            logging.info(f"Игра завершена, игнорируем сообщение от {user_id}")
            return

        if user_id in chat.dead_last_words:
            player_name = f"{chat.dead_last_words.pop(user_id)} {message.from_user.last_name or ''}".strip()
            last_words = message.text
            if last_words:
                player_link = f"[{player_name}](tg://user?id={user_id})"
                try:
                    send_message(chat.chat_id, get_text(chat.chat_id, 'death_last_words_announce').format(player=player_link, words=last_words), parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Не удалось отправить последние слова игрока {user_id} в чат: {e}")
                try:
                    send_message(user_id, get_text(chat.chat_id, 'death_last_words_sent'), parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Не удалось отправить подтверждение игроку {user_id}: {e}")
            return

        if chat.is_night:
            if user_id == chat.sheriff_id and chat.sergeant_id in chat.players:
                sheriff_name = f"{chat.players[user_id]['name']} {chat.players[user_id].get('last_name', '')}".strip()
                try:
                    send_message(chat.sergeant_id, get_text(chat.chat_id, 'private_message_forward_sheriff').format(name=sheriff_name, text=message.text), parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение от Комиссара {user_id} к Сержанту {chat.sergeant_id}: {e}")

            elif user_id == chat.sergeant_id and chat.sheriff_id in chat.players:
                sergeant_name = f"{chat.players[user_id]['name']} {chat.players[user_id].get('last_name', '')}".strip()
                try:
                    send_message(chat.sheriff_id, get_text(chat.chat_id, 'private_message_forward_sergeant').format(name=sergeant_name, text=message.text), parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение от Сержанта {user_id} к Комиссару {chat.sheriff_id}: {e}")

            elif chat.players[user_id]['role'] in ['🤵🏻‍♂️ Дон', '🤵🏻 Мафия']:
                mafia_name = f"{chat.players[user_id]['name']}"
                mafia_last_name = chat.players[user_id].get('last_name', '')
                try:
                    notify_mafia(chat, mafia_name, mafia_last_name, message.text, user_id)
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение от мафии/Дона {user_id}: {e}")


executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)


def delete_message_in_thread(chat_id, message_id):
    def delete():
        try:
            bot.delete_message(chat_id, message_id)
            logging.info(f"Сообщение {message_id} удалено в чате {chat_id}")
        except Exception as e:
            logging.warning(f"Ошибка при удалении сообщения {message_id} в чате {chat_id}: {e}")

    executor.submit(delete)


@bot.message_handler(content_types=['text', 'sticker', 'photo', 'video', 'document', 'audio', 'voice', 'animation'])
def handle_message(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    chat = chat_list.get(chat_id)
    if chat and chat.game_running:
        is_admin = False
        if getattr(message, 'sender_chat', None):
            is_admin = True
        elif user_id:
            try:
                chat_member = bot.get_chat_member(chat_id, user_id)
                is_admin = chat_member.status in ['administrator', 'creator']
            except Exception as e:
                logging.warning(f"Не удалось получить статус участника: {e}")

        message_type = message.content_type
        logging.info(f"Получено сообщение от {user_id} типа: {message_type}")

        if chat.is_night:
            if not (is_admin and message_type == 'text' and message.text.startswith('!')):
                logging.info(f"Удаление сообщения ночью от {user_id}: {message_type}")
                delete_message_in_thread(chat_id, message.message_id)
        else:
            player = chat.players.get(user_id, {})
            if ((user_id not in chat.players or player.get('role') == 'dead') or (chat.lover_target_id is not None and user_id == chat.lover_target_id and not player.get('healed_from_lover', False))) and not (is_admin and message_type == 'text' and message.text.startswith('!')):
                logging.info(f"Удаление сообщения днём от {user_id}: {message_type}")
                delete_message_in_thread(chat_id, message.message_id)


def escape_markdown_v2(text):
    """Escape Telegram MarkdownV2 special characters in user-controlled text."""
    if text is None:
        return ""
    return re.sub(r'([_\\*\[\]\(\)~`>#+\-=|{}.!])', r'\\\1', str(text))

def escape_markdown(text):
    specials = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in specials else char for char in text)


bot.skip_pending = True
bot.infinity_polling()