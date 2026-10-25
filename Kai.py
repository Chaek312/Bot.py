import random
from random import shuffle
import asyncio
import logging
# ===== aiogram 3 compatibility bridge =====
# The game logic remains synchronous; Telegram transport is handled by aiogram 3.
import os as _os
import asyncio as _asyncio
import threading as _threading
from io import BytesIO as _BytesIO

from aiogram import Bot as _AioBot, Dispatcher as _AioDispatcher
from aiogram import types as _aio_types
from aiogram.types import (
    InlineKeyboardButton as _AioInlineKeyboardButton,
    InlineKeyboardMarkup as _AioInlineKeyboardMarkup,
    ChatPermissions as _AioChatPermissions,
    LabeledPrice as _AioLabeledPrice,
    ReplyParameters as _AioReplyParameters,
    BufferedInputFile as _AioBufferedInputFile,
)

LabeledPrice = _AioLabeledPrice
ApiTelegramException = Exception

class _CompatInlineKeyboardMarkup(_AioInlineKeyboardMarkup):
    def __init__(self, inline_keyboard=None, row_width=3, **kwargs):
        # TeleBot allowed InlineKeyboardMarkup() and also
        # InlineKeyboardMarkup([[button1, button2], [button3]]).
        # aiogram 3 requires inline_keyboard=... as a keyword field.
        # Normalize both forms here so the old game code remains compatible.
        if inline_keyboard is None:
            inline_keyboard = kwargs.pop("inline_keyboard", None)
        if inline_keyboard is None:
            inline_keyboard = []
        elif isinstance(inline_keyboard, tuple):
            inline_keyboard = [list(row) if isinstance(row, (list, tuple)) else [row]
                               for row in inline_keyboard]
        elif isinstance(inline_keyboard, list):
            # A flat [button1, button2] is also accepted for convenience.
            if inline_keyboard and not isinstance(inline_keyboard[0], (list, tuple)):
                inline_keyboard = [inline_keyboard]
            else:
                inline_keyboard = [list(row) if isinstance(row, (list, tuple)) else [row]
                                   for row in inline_keyboard]
        super().__init__(inline_keyboard=inline_keyboard)
        self.row_width = row_width

    def add(self, *buttons):
        row = []
        for button in buttons:
            if isinstance(button, (list, tuple)):
                for b in button:
                    if b is not None:
                        row.append(b)
            elif button is not None:
                row.append(button)
        if row:
            self.inline_keyboard.append(row)
        return self

    def row(self, *buttons):
        return self.add(*buttons)

def _CompatInlineKeyboardButton(text=None, **kwargs):
    # TeleBot allowed the button text as the first positional argument.
    # aiogram 3's Pydantic model requires keyword arguments, so normalize it.
    if text is not None:
        kwargs['text'] = text
    return _AioInlineKeyboardButton(**kwargs)


class _TypesCompat:
    InlineKeyboardMarkup = _CompatInlineKeyboardMarkup
    # staticmethod is required here: otherwise Python binds the function to
    # the _TypesCompat instance and passes an extra self argument.
    InlineKeyboardButton = staticmethod(_CompatInlineKeyboardButton)
    ChatPermissions = _AioChatPermissions

types = _TypesCompat()

class AiogramTeleBotCompat:
    """Small TeleBot-compatible facade backed by aiogram 3.

    Existing synchronous game functions call this object synchronously, while
    incoming Telegram updates are received by aiogram Dispatcher.
    """
    def __init__(self, token, parse_mode=None):
        self.token = token
        self.parse_mode = parse_mode
        self.skip_pending = True
        self._message_handlers = []
        self._callback_handlers = []
        self._channel_handlers = []
        self._pre_checkout_handlers = []
        self._next_steps = {}
        self._api_loop = None
        self._api_thread = None
        self._api_bot = None
        self._api_ready = _threading.Event()
        self._me = None

    def _start_api_loop(self):
        if self._api_thread and self._api_thread.is_alive():
            return
        def runner():
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            self._api_loop = loop
            self._api_bot = _AioBot(self.token)
            self._api_ready.set()
            loop.run_forever()
            try:
                loop.run_until_complete(self._api_bot.session.close())
            except Exception:
                pass
            loop.close()
        self._api_thread = _threading.Thread(target=runner, daemon=True)
        self._api_thread.start()
        self._api_ready.wait(timeout=10)

    def _call(self, coro):
        self._start_api_loop()
        future = _asyncio.run_coroutine_threadsafe(coro, self._api_loop)
        return future.result(timeout=120)

    # ---- handler registration ----
    def message_handler(self, commands=None, content_types=None, func=None, **kwargs):
        def decorator(fn):
            self._message_handlers.append({"fn": fn, "commands": commands, "content_types": content_types, "func": func})
            return fn
        return decorator

    def callback_query_handler(self, func=None, **kwargs):
        def decorator(fn):
            self._callback_handlers.append({"fn": fn, "func": func})
            return fn
        return decorator

    def channel_post_handler(self, content_types=None, func=None, **kwargs):
        def decorator(fn):
            self._channel_handlers.append({"fn": fn, "content_types": content_types, "func": func})
            return fn
        return decorator

    def pre_checkout_query_handler(self, func=None, **kwargs):
        def decorator(fn):
            self._pre_checkout_handlers.append({"fn": fn, "func": func})
            return fn
        return decorator

    def register_next_step_handler(self, message, callback, *args, **kwargs):
        chat_id = getattr(getattr(message, 'chat', None), 'id', None)
        if chat_id is None:
            return None
        # TeleBot tracks next-step handlers by chat. These flows are used
        # primarily in private chats in this project.
        self._next_steps[chat_id] = (callback, args, kwargs)
        return None

    # ---- synchronous Bot API facade ----
    def send_message(self, chat_id, text, **kwargs):
        return self._call(self._api_bot.send_message(chat_id=chat_id, text=text, **kwargs))

    def reply_to(self, message, text, **kwargs):
        kwargs['reply_parameters'] = _AioReplyParameters(message_id=message.message_id)
        return self.send_message(message.chat.id, text, **kwargs)

    def send_photo(self, chat_id, photo, **kwargs):
        return self._call(self._api_bot.send_photo(chat_id=chat_id, photo=photo, **kwargs))

    def send_animation(self, chat_id, animation, **kwargs):
        return self._call(self._api_bot.send_animation(chat_id=chat_id, animation=animation, **kwargs))

    def send_video(self, chat_id, video, **kwargs):
        return self._call(self._api_bot.send_video(chat_id=chat_id, video=video, **kwargs))

    def send_voice(self, chat_id, voice, **kwargs):
        return self._call(self._api_bot.send_voice(chat_id=chat_id, voice=voice, **kwargs))

    def send_audio(self, chat_id, audio, **kwargs):
        return self._call(self._api_bot.send_audio(chat_id=chat_id, audio=audio, **kwargs))

    def send_sticker(self, chat_id, sticker, **kwargs):
        return self._call(self._api_bot.send_sticker(chat_id=chat_id, sticker=sticker, **kwargs))

    def send_document(self, chat_id, document, **kwargs):
        if hasattr(document, 'read'):
            data = document.read()
            name = getattr(document, 'name', 'document.bin')
            document = _AioBufferedInputFile(data, filename=_os.path.basename(name))
        return self._call(self._api_bot.send_document(chat_id=chat_id, document=document, **kwargs))

    def send_invoice(self, chat_id, **kwargs):
        # TeleBot code in this project uses invoice_payload; aiogram 3
        # expects the Bot API field as `payload`.
        if "invoice_payload" in kwargs and "payload" not in kwargs:
            kwargs["payload"] = kwargs.pop("invoice_payload")
        return self._call(self._api_bot.send_invoice(chat_id=chat_id, **kwargs))

    def copy_message(self, chat_id, from_chat_id, message_id, **kwargs):
        return self._call(self._api_bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id, **kwargs))

    def forward_message(self, chat_id, from_chat_id, message_id, **kwargs):
        return self._call(self._api_bot.forward_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id, **kwargs))

    def delete_message(self, chat_id, message_id):
        return self._call(self._api_bot.delete_message(chat_id=chat_id, message_id=message_id))

    def edit_message_text(self, text=None, chat_id=None, message_id=None, **kwargs):
        # Supports both TeleBot positional order and keyword usage.
        return self._call(self._api_bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs))

    def edit_message_reply_markup(self, chat_id, message_id, **kwargs):
        return self._call(self._api_bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, **kwargs))

    def answer_callback_query(self, callback_query_id, text=None, **kwargs):
        return self._call(self._api_bot.answer_callback_query(callback_query_id=callback_query_id, text=text, **kwargs))

    def answer_pre_checkout_query(self, pre_checkout_query_id, ok, **kwargs):
        return self._call(self._api_bot.answer_pre_checkout_query(pre_checkout_query_id=pre_checkout_query_id, ok=ok, **kwargs))

    def get_chat(self, chat_id):
        return self._call(self._api_bot.get_chat(chat_id=chat_id))

    def get_chat_member(self, chat_id, user_id):
        return self._call(self._api_bot.get_chat_member(chat_id=chat_id, user_id=user_id))

    def get_chat_administrators(self, chat_id):
        return self._call(self._api_bot.get_chat_administrators(chat_id=chat_id))

    def export_chat_invite_link(self, chat_id):
        return self._call(self._api_bot.export_chat_invite_link(chat_id=chat_id))

    def pin_chat_message(self, chat_id, message_id, **kwargs):
        return self._call(self._api_bot.pin_chat_message(chat_id=chat_id, message_id=message_id, **kwargs))

    def ban_chat_member(self, chat_id, user_id, **kwargs):
        return self._call(self._api_bot.ban_chat_member(chat_id=chat_id, user_id=user_id, **kwargs))

    def restrict_chat_member(self, chat_id, user_id, permissions, **kwargs):
        return self._call(self._api_bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions, **kwargs))

    def get_me(self):
        if self._me is None:
            self._me = self._call(self._api_bot.get_me())
        return self._me

    def get_file(self, file_id):
        return self._call(self._api_bot.get_file(file_id=file_id))

    def download_file(self, file_path):
        output = _BytesIO()
        self._call(self._api_bot.download_file(file_path=file_path, destination=output))
        return output.getvalue()

    def get_message(self, chat_id, message_id):
        # Bot API does not provide arbitrary message retrieval. The old code
        # only used this to copy an ad keyboard, so returning None is safe.
        return None

    async def _dispatch_message(self, message):
        next_step = self._next_steps.pop(message.chat.id, None)
        if next_step:
            fn, args, kwargs = next_step
            try:
                fn(message, *args, **kwargs)
            except Exception:
                logging.exception("Ошибка next-step handler")
            return

        for h in self._message_handlers:
            if self._matches_message(h, message):
                try:
                    h['fn'](message)
                except Exception:
                    logging.exception("Ошибка message handler: %s", h['fn'].__name__)
                return

    @staticmethod
    def _matches_message(h, message):
        content_types = h.get('content_types')
        if content_types:
            ct = str(getattr(message, 'content_type', ''))
            if ct not in content_types:
                return False
        commands = h.get('commands')
        if commands:
            text = getattr(message, 'text', None) or ''
            first = text.split()[0] if text.split() else ''
            command = first.split('@', 1)[0]
            if not command.startswith('/') or command[1:] not in commands:
                return False
        predicate = h.get('func')
        if predicate is not None:
            try:
                if not predicate(message):
                    return False
            except Exception:
                return False
        return True

    async def _dispatch_callback(self, call):
        for h in self._callback_handlers:
            predicate = h.get('func')
            try:
                if predicate is not None and not predicate(call):
                    continue
                h['fn'](call)
            except Exception:
                logging.exception("Ошибка callback handler: %s", h['fn'].__name__)
            return

    async def _dispatch_channel(self, message):
        for h in self._channel_handlers:
            content_types = h.get('content_types')
            if content_types and str(getattr(message, 'content_type', '')) not in content_types:
                continue
            predicate = h.get('func')
            if predicate is not None and not predicate(message):
                continue
            try:
                h['fn'](message)
            except Exception:
                logging.exception("Ошибка channel handler: %s", h['fn'].__name__)
            return

    async def _dispatch_pre_checkout(self, query):
        for h in self._pre_checkout_handlers:
            predicate = h.get('func')
            try:
                if predicate is not None and not predicate(query):
                    continue
                h['fn'](query)
            except Exception:
                logging.exception("Ошибка pre-checkout handler: %s", h['fn'].__name__)
            return

    async def _run(self):
        self._start_api_loop()
        poll_bot = _AioBot(self.token)
        dp = _AioDispatcher()

        @dp.message()
        async def _all_messages(message):
            await self._dispatch_message(message)

        @dp.callback_query()
        async def _all_callbacks(call):
            await self._dispatch_callback(call)

        @dp.channel_post()
        async def _all_channel_posts(message):
            await self._dispatch_channel(message)

        @dp.pre_checkout_query()
        async def _all_pre_checkout(query):
            await self._dispatch_pre_checkout(query)

        await dp.start_polling(poll_bot, allowed_updates=dp.resolve_used_update_types())

    def infinity_polling(self, *args, **kwargs):
        _asyncio.run(self._run())

    def stop_polling(self):
        # Kept for compatibility; aiogram polling exits on shutdown signal.
        pass

import time
import threading
import io
import re
import csv
from datetime import datetime, timedelta
import concurrent.futures
from collections import defaultdict
import hashlib
import zipfile
import sqlite3
import json
import os

notification_timers = {}

# Ограничение частоты отправки сообщений Telegram
message_times = []
message_limit = 30
interval = 1.0

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "7605504614:AAF_8F_O3uQsQ7MVOWS2PjL0lqsp3_KGroM"
bot = AiogramTeleBotCompat(BOT_TOKEN)

chat_list = {}
# Чаты, которым запрещён запуск игр
blocked_chat_ids = set()
game_tasks = {}
registration_timers = {}
game_start_timers = {}
user_game_registration = {}
vote_timestamps = {}
next_players = {}
registration_lock = threading.Lock()
game_start_lock = threading.Lock()
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
# Timestamp throttle for editing the day-vote confirmation keyboard.
confirm_vote_timestamps = {}

# Runtime/UI state (не постоянные данные — хранится только в RAM)
pending_give_menu = {}

# Настройки логирования / уведомлений
LOG_TO_FILE = False
LOG_TO_CHANNEL = False
LOG_CHANNEL_ID = CHANNEL_ID
PLAYER_NOTIFY = True
SILENT_MODE = False

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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_weekly_scores (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                week_key TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id, week_key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS public_gifts (
                gift_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                recipients_limit INTEGER NOT NULL,
                claimed_json TEXT NOT NULL DEFAULT '[]',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_config (
                config_id INTEGER PRIMARY KEY CHECK(config_id = 1),
                config_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_claims (
                user_id INTEGER PRIMARY KEY,
                claimed_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS allowed_chats (
                chat_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Переносим исходный список только при первом запуске новой таблицы.
        count = conn.execute("SELECT COUNT(*) FROM allowed_chats").fetchone()[0]
        if count == 0:
            conn.executemany("INSERT OR IGNORE INTO allowed_chats (chat_id) VALUES (?)",
                             [(int(cid),) for cid in ALLOWED_CHAT_ID])
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
            self[key] = default  # persist nested default to SQLite
        return self[key]

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


def _current_week_key():
    # ISO-неделя начинается в понедельник; на новой неделе используется новый рейтинг.
    return datetime.now().date().strftime("%G-W%V")


def update_chat_weekly_score(chat_id, user_id, won):
    """Обновляет очки игрока только в этом чате и только в текущей неделе.

    До 10 очков поражения не отнимают очки. После достижения 10 очков
    поражения уменьшают рейтинг, но он не опускается ниже 10.
    """
    chat_id, user_id = int(chat_id), int(user_id)
    week_key = _current_week_key()
    with _db_lock:
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            row = conn.execute(
                "SELECT score FROM chat_weekly_scores WHERE chat_id=? AND user_id=? AND week_key=?",
                (chat_id, user_id, week_key),
            ).fetchone()
            score = int(row[0]) if row else 0
            if won:
                score += 1
            elif score >= 10:
                score = max(10, score - 1)
            conn.execute(
                """INSERT INTO chat_weekly_scores (chat_id,user_id,week_key,score,updated_at)
                   VALUES (?,?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(chat_id,user_id,week_key) DO UPDATE SET
                   score=excluded.score, updated_at=CURRENT_TIMESTAMP""",
                (chat_id, user_id, week_key, score),
            )
            conn.commit()
            return score


def get_chat_weekly_scores(chat_id, limit=15):
    week_key = _current_week_key()
    with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
        rows = conn.execute(
            """SELECT user_id, score FROM chat_weekly_scores
               WHERE chat_id=? AND week_key=? AND score>0
               ORDER BY score DESC, updated_at ASC LIMIT ?""",
            (int(chat_id), week_key, int(limit)),
        ).fetchall()
    return [(int(user_id), int(score)) for user_id, score in rows]


init_profile_database()
# Загружаем разрешённые чаты из SQLite при каждом запуске.
with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as _conn:
    _saved_allowed_chats = _conn.execute("SELECT chat_id FROM allowed_chats ORDER BY added_at, chat_id").fetchall()
ALLOWED_CHAT_ID = [int(row[0]) for row in _saved_allowed_chats]
player_profiles = SQLiteProfiles()
chat_settings = SQLiteSettings()
player_scores = SQLiteScores()
# ================== ГЛОБАЛЬНЫЙ СЛОВАРЬ ТЕКСТОВ ==================
TEXTS = {
    'ru': {
        # Общие
        'yes': "Да",
        'no': "Нет",
        'back': "🔙 Назад",
        'close': "❌ Закрыть",
        'skip': "🚷 Пропустить",
        'join_button': "🤵🏻 Присоединиться",
        'game_created': "Игра создана!",
        'game_not_started': "*Игра не запущена!*\nДля начала новой игры напишите /game",
        'game_already_running': "Игра уже запущена.",
        'insufficient_players': "Недостаточно игроков для начала игры...",
        'game_started': "Игра начинается!",
        'game_stopped': "🚫 *Игру остановил администратор!*",
        'registration_stopped': "🚫 *Регистрацию остановил администратор*",
        'timeout_auto_start_disabled': "*Таймер автоматического запуска игры был отключён. *\nЗапустите игру вручную с помощью команды /start.",
        'not_in_game': "⛔️ Вы не в игре.",
        'already_registered': "✅ Вы уже присоединились к игре! :)",
        'join_success': "🎲 Вы присоединились к игре в чате {}!",
        'join_success_short': "Вы присоединились к игре!",
        'join_fail_game_started': "🚫 Не удалось присоединиться — игра уже началась!",
        'join_fail_no_reg': "🚫 Не удалось присоединиться — игра ещё не началась!",
        'join_fail_no_permission': "🚫 Не удалось присоединиться — у вас нет прав на отправку сообщений в группе.",
        'join_fail_not_in_chat': "🚫 Не удалось подключиться в игру — вы не в чате.",
        'join_fail_other_game': "🚫 Вы уже зарегистрированы в другой игре",
        'left_game': "🚫 Вы вышли из игры",
        'left_registration': "🚫 Вы отказались от участия в игре.",
        'death_msg': "⚰️ {} не выдержал гнетущую атмосферу этого города и повесился. Он был *{}*.",
        'admin_only': "У вас нет прав для выполнения этой команды.",
        'group_only': "Эту команду можно использовать только в групповом чате.",
        'pm_error': "Не удалось отправить настройки в личные сообщения. Проверьте, что бот может писать вам.",
        'no_rights': "У вас нет прав для изменения настроек.",
        'settings_title': "Настройки чата",
        'pin_reg': "Закреплять регистрацию",
        'admin_start': "Только админ запускает игру",
        'team_admin_start': "Только админ запускает командную игру",
        'leave_cmd': "Включить/выключить /leave",
        'mafia_count': "Количество мафии",
        'times': "Времена",
        'language': "Сменить язык",
        'players_count': "Количество игроков для старта",
        'anonymous_vote': "Анонимное голосование",
        'buffs': "Баффы",
        'choose_lang': "Выберите язык чата",
        'kazakh': "🇰🇿 Қазақша",
        'russian': "🇷🇺 Русский",
        'lang_changed': "Язык чата изменен!",
        'time_reg': "⏰ Время регистрации",
        'time_night': "🌙 Ночное время",
        'alive_list_night_time': "🌙 Ночное время",
        'go_to_game': "🎮 Перейти в игру",
        'time_day': "☀️ Дневное время",
        'time_vote': "🗳 Время голосования",
        'time_confirm': "👍🏼|👎🏼 Время подтверждения",
        'select_time': "Выберите, какое время изменить:",
        'select_option': "Выберите:",
        'sec': "сек",
        'current_value': "Текущее значение:",
        'more_mafia': "Больше (1/3)",
        'less_mafia': "Меньше (1/4)",
        'mafia_ratio_desc': "Выберите количество мафии:\nБольше - каждый 3-й игрок,\nМеньше - каждый 4-й игрок будет мафией.",
        'pin_question': "Закреплять сообщение при регистрации?",
        'leave_question': "Разрешить игрокам использовать /leave?",
        'admin_question': "Разрешить запускать игру только администраторам?",
        'team_admin_question': "Разрешить запускать командную игру (/teamgame) только администраторам?",
        'team_admin_only_enabled': "Командную игру может запускать только администратор",
        'team_admin_only_disabled': "Командную игру может запускать любой участник",
        'menu_closed': "Меню закрыто.",
        'time_changed': "Время изменено",
        'registration_time_changed': "Время регистрации изменено",
        'night_time_changed': "Ночное время изменено",
        'day_time_changed': "Дневное время изменено",
        'voting_time_changed': "Время голосования изменено",
        'confirmation_time_changed': "Время подтверждения изменено",
        'pin_enabled': "Закрепление регистрации включено",
        'pin_disabled': "Закрепление регистрации выключено",
        'leave_enabled': "Команда /leave включена",
        'leave_disabled': "Команда /leave выключена",
        'admin_only_enabled': "Только админ может запускать игру",
        'admin_only_disabled': "Любой может запускать игру",
        'mafia_ratio_changed': "Количество мафии изменено",
        'anon_vote_enabled': "Анонимное голосование включено",
        'anon_vote_disabled': "Анонимное голосование выключено",
        'choose_buff': "Выберите бафф для изменения:",
        'shield_buff': "⚔️ Щит",
        'shield_question': "Разрешить использовать бафф щита в этом чате?",
        'shield_enabled': "Бафф щита включен",
        'shield_disabled': "Бафф щита выключен",
        'docs_buff': "📂 Фальшивые документы",
        'docs_question': "Разрешить использовать бафф фальшивых документов в этом чате?",
        'docs_enabled': "Бафф фальшивых документов включен",
        'docs_disabled': "Бафф фальшивых документов выключен",
        'hanging_shield_buff': "⚖️ Защита от повешения",
        'hanging_shield_question': "Разрешить использовать бафф защиты от повешения в этом чате?",
        'hanging_shield_enabled': "Бафф защиты от повешения включен",
        'hanging_shield_disabled': "Бафф защиты от повешения выключен",
        'gun_buff': "🔫 Пистолет",
        'gun_question': "Разрешить использовать бафф пистолета в этом чате?",
        'gun_enabled': "Бафф пистолета включен",
        'gun_disabled': "Бафф пистолета выключен",
        'choose_players_count': "При скольких игроках игра должна начинаться автоматически?",
        'players_count_changed': "Количество игроков изменено",
        'profile': "*Ваш профиль*\n\n👤 {name}\n🪪 ID: `{id}`\n\n💶 Евро: {euro}\n🪙 Монеты: {coins}\n\n⚔️ Защита: {shield}\n📁 Документы: {docs}\n🔫 Пистолет: {gun}\n⚖️ Защита от повешения: {hanging_shield}\n\n👑 VIP-статус: {vip}",
        'shop_title': "🛒 *Магазин*",
        'balance': "💶 _Евро_: {euro}\n🪙 _Монеты_: {coins}",
        'shield_desc': "⚔️ *Защита*\nЕсли кто-то нападет на вас, щит может один раз спасти вас.",
        'docs_desc': "📁 *Документы*\nДля ролей против комиссара (Дон, Мафия и т.д.). Если комиссар проверит вас, он увидит вас как мирного жителя.",
        'hanging_desc': "⚖️ *Защита от повешения*\nСпасет вас от повешения.",
        'gun_desc': "🔫 *Пистолет*\nПозволяет ночью убить любого игрока.",
        'vip_desc': "👑 *7-дневный VIP-статус*\nС VIP-статусом:\n– За победу получаете 💶 15\n– За поражение получаете 💶 10 бонус\n– Рядом с вашим именем в списке живых игроков будет отображаться такой знак 👑\n– При VIP вы можете купить 🔫 Пистолет\n– 🪽 Щит можно использовать дважды в течение игры",
        'shop_shield': "⚔️ Защита - 💶 100",
        'shop_docs': "📁 Документы - 💶 150",
        'shop_gun': "🔫 Пистолет - 💶 600",
        'shop_hanging': "⚖️ Защита от повешения - 🪙 1",
        'shop_buy_vip': "👑 Купить VIP - 7 🪙",
        'shop_renew_vip': "👑 Продлить VIP - 4 🪙",
        'purchase_success': "✅ Покупка успешно завершена",
        'purchase_no_money': "❌ Недостаточно средств для покупки",
        'purchase_vip_only': "❌ Доступно только для VIP!",
        'purchase_vip_bought': "👑 VIP-статус активирован на 7 дней!",
        'purchase_vip_renewed': "👑 Ваш VIP-статус продлен на 7 дней!",
        'exchange_title': "💰 *Обмен*",
        'exchange_choose': "Выберите вариант обмена:",
        'exchange_success': "✅ Обмен успешно завершен!",
        'exchange_no_coins': "❌ Недостаточно монет!",
        'exchange_rate_1': "1🪙 → 150💶",
        'exchange_rate_2': "2🪙 → 300💶",
        'exchange_rate_5': "5🪙 → 750💶",
        'exchange_rate_10': "10🪙 → 1500💶",
        'buy_coins_title': "💰 *Покупка монет*",
        'buy_coins_choose': "Выберите способ оплаты:",
        'pay_card': "💳 Оплата картой",
        'pay_stars': "⭐️ Telegram Stars",
        'card_payment_title': "💳 *Оплата картой*",
        'card_payment_text': "🌍 *Принимаем платежи вручную*\nСейчас мы можем принимать платежи через чат поддержки.",
        'card_payment_button': "Сделать платеж",
        'stars_payment_text': "🪙 Оплата через Telegram Stars:",
        'stars_button': "{coins}🪙 → {stars}⭐️",
        'help_title': "🗂️ *Ссылки*",
        'help_support': "🛠️ Техническая помощь",
        'help_how_to_play': "Как играть?",
        'help_roles': "🤵🏻 Роли",
        'top_empty': "🏆 *15 лучших игроков недели:*\n\n❌ В настоящее время в рейтинге нет игроков. Играй, чтобы попасть в список лучших!",
        'top_title': "🏆 *15 лучших игроков недели:*\n\n",
        'reset_scores_success': "✅ Все очки и таймеры успешно сброшены!",
        'coins_transfer_only_group': "🔸 Эта команда доступна только в группах!",
        'coins_transfer_reply_required': "🔸 Чтобы отправить монеты, ответь на сообщение пользователя!\nНапример: /coins 10",
        'coins_transfer_self': "🔸 Нельзя отправить монеты самому себе!",
        'coins_transfer_invalid': "🔸 Неверное количество! Пример: /coins 10",
        'coins_transfer_profile_error': "🔸 Ошибка! Не удалось получить профили.",
        'coins_transfer_not_enough': "🔸 Недостаточно монет! У вас: {coins} 🪙",
        'coins_transfer_confirmation': "*{sender}* отправил *{amount}* 🪙 *{recipient}*",
        'next_notification': "🔔 Вам придет уведомление о регистрации на новую игру в чате {chat}.",
        'kamikaze_question': "Кого заберешь с собой в могилу?",
        'kamikaze_no_target': "❌ Этот игрок уже мертв...",
        'kamikaze_chosen': "✅ Ты выбрал!",
        'kamikaze_announcement': "💣 *Камикадзе* решил забрать кого-то с собой...",
        'kamikaze_timeout': "⏰ Время вышло, ты никого не выбрал.",
        'kamikaze_action_unavailable': "❌ Это действие недоступно",
        'kamikaze_error': "❌ Ошибка при обработке выбора",
        'sheriff_not_night': "Действия доступны только ночью.",
        'sheriff_choose': "Выбери, что делать этой ночью",
        'sheriff_check': "🔍 Проверить",
        'sheriff_shoot': "🔫 Выстрелить",
        'mafia_vote_question': "Кого сделаем жертвой?",
        'doctor_question': "Кого будем лечить?",
        'hobo_question': "К кому пойдём искать бутылку?",
        'lover_question': "Кому доставим удовольствие?",
        'lawyer_question': "Кого защитим?",
        'maniac_question': "Кого убьём?",
        'gun_question_night': "🔫 В кого целишься?",
        'night_start_caption': "🌙 *Наступила ночь*\nТолько самые смелые и бесстрашные выходят на улицу. Днём мы пересчитаем, кто остался...",
        'night_mafia_chosen': "🤵🏻 *Мафия* выбрала жертву...",
        'night_sheriff_check': "🕵🏼 *Комиссар* отправился искать преступников...",
        'night_sheriff_shoot': "🕵🏼 *Комиссар* начал стрелять...",
        'night_doctor': "👨🏼‍⚕️ *Доктор* отправился спасать чью-то жизнь…",
        'night_hobo': "🧙‍♂️ *Бомж* отправился искать бутылку в чужом доме…",
        'night_lover': "💃🏼 *Любовница* отправилась к своему выбору...",
        'night_lawyer': "👨🏼‍💼 *Адвокат* ищет клиента для защиты...",
        'night_maniac': "🔪 *Маньяк* отправился на ночную охоту...",
        'night_gun_used': "🔫 Кто-то использовал оружие ночью...",
        'night_no_deaths': "_🤷 Как ни странно, этой ночью никто не погиб…_",
        'day_caption': "🌞 *День {day}*\nВосход солнца подсвечивает кровь, пролитую прошлой ночью...",
        'day_alive_players': "*Живые игроки:*",
        'day_some_of_them': "*Среди них:*",
        'day_total': "👥 Всего: *{total}*",
        'day_discussion': "Пришло время обсудить события ночи и провести расследование...",
        'voting_title': "*Время найти и наказать виновных.*\nГолосование продлится {time} секунд",
        'voting_pm_text': "*Время искать виновных!*\nКого хочешь повесить?",
        'voting_skip': "🚷 Пропустить голосование",
        'voting_already_voted': "Вы уже проголосовали.",
        'voting_ended': "_Голосование завершено_",
        'voting_nobody': "Народ не смог прийти к согласию...\nНикто не был повешен,\nвсе разошлись по домам...",
        'voting_result': "*Результаты голосования:*",
        'voting_saved': "⚖️ Однако {player} спасся от повешения!",
        'voting_saved_private': "*Когда тебя собирались повесить, Щит от повешения спас тебя! 🛡️*",
        'voting_executed': "_Сегодня_ {player} _был повешен_\nОн был *{role}*.",
        'voting_executed_private': "*На дневном собрании тебя повесили без единого сомнения :(*",
        'confirm_vote_question': "Вы действительно хотите казнить {name}?",
        'confirm_vote_yes': "👍🏼 {count}",
        'confirm_vote_no': "👎🏼 {count}",
        'confirm_vote_already': "Вы уже выбрали это",
        'confirm_vote_accepted': "Голос принят!",
        'confirm_vote_cannot': "Вы не можете голосовать.",
        'confirm_vote_ended': "Голосование завершено",
        'role_texts': {
            '🤵🏻‍♂️ Дон': "Вы - 🤵🏻‍♂️ Дон!\n\nГлава мафии! Вы решаете, кто отправится в вечный сон этой ночью...",
            '🤵🏻 Мафия': "Вы — 🤵🏻 Мафия!\n\nВаша задача - подчиняться Дону и устранять противников. Однажды вы тоже можете стать Доном...",
            '👨🏼‍⚕️ Дәрігер': "Вы — 👨🏼‍⚕️ Доктор!\n\nВы решаете, кого спасти этой ночью…",
            '🤦🏼 Самоубийца': "Вы — 🤦🏼 Самоубийца!\n\nВаша задача - быть повешенным на городском собрании!",
            '🧙‍♂️ Қаңғыбас': "Вы — 🧙‍♂️ Бомж!\n\nМожете стать свидетелем убийства, встретив любого человека за бутылку.",
            '🕵🏼 Комиссар': "Вы — 🕵🏼 Комиссар!\n\nЗащитник города и главная угроза для мафии...",
            '🤞 Жолы болғыш': "Вы — 🤞 Счастливчик!\n\nВаша задача - выявлять преступников на городском собрании.",
            '💣 Камикадзе': "Вы — 💣 Камикадзе!\n\nЕсли вас попытаются повесить, вы можете выбрать, кого взять с собой в могилу.",
            '💃🏼 Көңілдес': "Вы — 💃🏼 Любовница!\n\nИспользуйте свои навыки, чтобы усыпить любого игрока на день.",
            '👨🏼‍💼 Қорғаушы': "Вы — 👨🏼‍💼 Адвокат!\n\nВы решаете, кого защищать этой ночью.",
            '👮🏼 Сержант': "Вы — 👮🏼 Сержант!\n\nВы помощник Комиссара.",
            '🔪 Жауыз': "Вы — 🔪 Маньяк!\n\nВ городе не должно остаться никого в живых. Кроме вас, конечно :)",
            '👨🏼 Тату тұрғын': "Вы — 👨🏼 Мирный житель!\n\nВаша главная задача - выявлять мафию и вешать преступников на городском собрании."
        },
        'death_night_message': "*Тебя убили ночью :(*\nТы можешь отправить своё последнее сообщение",
        'death_last_words_sent': "*Сообщение получено и отправлено в чат.*",
        'death_last_words_announce': "Кто-то из жителей услышал предсмертный крик {player}:\n_{words}_",
        'shield_used_announce': "🪽 Кто-то из игроков использовал защиту",
        'shield_used_private': "⚔️ Кто-то покушался на тебя, но твоя защита спасла тебя!",
        'doctor_saved': "👨🏼‍⚕️ *Доктор* тебя спас",
        'doctor_visited': "👨🏼‍⚕️ Доктор приходил к тебе в гости",
        'lucky_saved_announce': "🤞 Кому-то повезло этой ночью",
        'lucky_saved_private': "🤞 На тебя покушались этой ночью, но тебе повезло!",
        'don_transfer_announce': "🤵🏻 *Мафия* 🤵🏻‍♂️ *Дон* передал свою роль",
        'don_transfer_private': "Теперь ты 🤵🏻‍♂️ Дон!",
        'sheriff_transfer_announce': "👮🏼 *Сержант* унаследовал роль 🕵🏼 *Комиссара*",
        'sheriff_transfer_private': "Теперь ты 🕵🏼 Комиссар!",
        'mafia_vote_result': "*Голосование завершено*\nМафия выбрала жертвой {victim}",
        'mafia_vote_no_consensus': "*Голосование завершено.*\nСемья не пришла к единому мнению и никого не убила",
        'mafia_vote_nobody': "*Голосование завершено.*\nСемья не смогла выбрать жертву",
        'lover_song': "💃🏼 Любовница напела: \"Иди ко мне, забудь обо всём...\"",
        'lover_blocked_by_doctor': "💃🏼 *Любовница* хотела тебя соблазнить, но увидела, что ты с 👨🏼‍⚕️ *Доктором*, и ушла.",
        'lover_visited': "💃🏼 Любовница пришла к тебе...",
        'hobo_visited': "🧙🏼‍♂️ *Бомж* пришёл к тебе ночью попросить бутылку.",
        'hobo_report_with_visitors': "Ты пришёл ночью к {target} за бутылкой и увидел: {visitors}.",
        'hobo_report_no_visitors': "Ты пришёл ночью к {target} за бутылкой, но ничего подозрительного не заметил.",
        'hobo_report_no_target': "Ты никого не встретил этой ночью.",
        'lawyer_protected': "👨🏼‍💼 Адвокат защитил тебя этой ночью.",
        'game_end_title': "*Игра окончена!*",
        'game_end_winners': "Победители:",
        'game_end_remaining': "Оставшиеся игроки:",
        'game_end_time': "Время игры: {} мин. {} сек.",
        'game_end_you_earned': "*Игра окончена!*\nВы получили {} 💶",
        'game_end_mafia_won': "Мафия победила",
        'game_end_citizens_won': "Мирные жители победили",
        'game_end_maniac_won': "Маньяк победил",
        'game_end_suicide_won': "Самоубийца победил",
        'police_composition': "🚨 *Полицейский состав:*\n{sheriff}\n{sergeant}",
        'registration_title': "*Ведётся набор игроков*\n{players}\n_{count} человек присоединилось_",
        'registration_empty': "*Ведётся набор игроков*\n_Зарегистрированных нет_",
        'registration_notify_59': "⏰ До конца регистрации осталось *59 сек*",
        'registration_notify_29': "⏰ До конца регистрации осталось *29 сек*",
        'start_private': "*Привет!*\nЯ 🤵🏻 *Мафия* бот-ведущий.\nДобавьте меня в чат, сделайте администратором и начните играть бесплатно",
        'start_add_to_group': "🤵🏽 Добавить бота в свой чат",
        'start_join_chat': "Войти в чат",
        'start_news': "📰 Новости",
        'welcome_chat': "Привет! :)\nЯ бот ведущий для игры в 🤵🏻 Мафию\nЧтобы начать игру, для начала выдайте мне права админстратора:\n🛑 Удалять сообщение\n🛑 Закреплять сообщение\n🛑 Блокировать пользывателей\n⚙️ Используйте команду /settings для изменения настроек.",
        'welcome_lang_choice': "Выберите язык",
        'available_chats': "*Список чатов:*",
        'settings_sent': "Настройки отправлены в личные сообщения.",
        'no_active_game': "Нет активной игры для выхода.",
        'cannot_leave_game': "Выход из игры запрещен настройками чата.",
        'leave_disabled_by_admin': "Выход из игры во время игры запрещен администратором.",
        'voting_blocked_by_lover': "💃🏼 Со мной все забывается...",
        'sheriff_action_already_taken': "Вы уже сделали свой выбор сегодня вечером.",
        'sheriff_check_result': "Ты проверил игрока {player}, и его роль — {role}.",
        'sheriff_check_result_fake': "Ты проверил игрока {player}, и его роль — 👨🏼 Мирный житель.",
        'sheriff_check_visited': "🕵🏼 *Комиссар* решил заглянуть к тебе.",
        'sheriff_check_fake_used': "🕵🏼 *Комиссар* пришёл к тебе, но ты показал фальшивые документы.",
        'sheriff_check_lawyer_protected': "🕵🏼 Комиссар пришёл к тебе, но адвокат показал, что ты мирный житель.",
        'sheriff_shot': "Вы пошли стрелять в {player}",
        'sheriff_checked': "Вы пошли проверять {player}",
        'doctor_self_heal_forbidden': "Вы уже лечили себя, выберите другого игрока.",
        'doctor_chosen': "Вы выбрали лечение для {player}",
        'mafia_voted': "Вы проголосовали за {player}",
        'mafia_vote_notification_don': "🤵🏻‍♂️ *Дон* [{name}](tg://user?id={id}) проголосовал за {victim}",
        'mafia_vote_notification_mafia': "🤵🏻 Мафия [{name}](tg://user?id={id}) проголосовал за {victim}",
        'mafia_vote_notification_lawyer': "🤵🏻‍♂️ Дон ??? проголосовал за {victim}",
        'hobo_chosen': "Вы пошли за бутылкой к {player}",
        'lover_chosen': "Вы отправились доставлять удовольствие {player}",
        'lawyer_chosen': "Вы выбрали защиту для {player}",
        'maniac_chosen': "Вы выбрали убийство для {player}",
        'gun_chosen': "🔫 Вы прицелились в {player}",
        'gun_no_available': "❌ У вас нет доступного пистолета!",
        'gun_night_only': "🔫 Пистолет можно использовать только ночью!",
        'gun_target_unavailable': "❌ Цель недоступна!",
        'vote_casted': "Вы выбрали {player}",
        'vote_announce_anon': "{voter} проголосовал",
        'vote_announce_open': "{voter} проголосовал за {target}",
        'vote_notification': "🗳 Проголосовать",
        'vote_notificatio': "Перейти к боту",
        'private_message_forward_sheriff': "🕵🏼 *Комиссар {name}*:\n{text}",
        'private_message_forward_sergeant': "👮🏼 *Сержант {name}*:\n{text}",
        'give_menu_title': "Выберите предмет и действие:",
        'give_item_euro': "💶 Евро",
        'give_item_coins': "🪙 Монеты",
        'give_item_shield': "⚔️ Защита",
        'give_item_fake_docs': "📁 Фейк доки",
        'give_item_gun': "🔫 Пушка",
        'give_item_hanging_shield': "⚖️ Щит от повешения",
        'give_item_vip': "👑 VIP",
        'give_enter_amount': "Введите количество для {item}:\n(действие: {action})",
        'give_added': "Добавлено: {item} = {amount}\n\nДобавить ещё?",
        'give_confirm_title': "Подтвердите выдачу:\n\n{items}",
        'give_confirm': "✅ Подтвердить",
        'give_cancel': "❌ Отмена",
        'give_cancelled': "❌ Отменено.",
        'give_completed': "🎁 Выдача выполнена:\n\n{items}",
        'give_completed_silent': "✔ Выдача выполнена (скрытый режим).",
        'give_inventory_changed': "📥 Вам изменили инвентарь:\n\n{items}",
        'give_session_expired': "Сессия истекла.",
        'give_empty': "Нельзя отправить пустую выдачу!",
        'give_invalid_amount': "❌ Количество должно быть числом.",
        'give_no_permission': "❌ У вас нет доступа.",
        'give_usage': "Используйте: /give <user_id>",
        'give_invalid_id': "❌ user_id должен быть числом.",
        'broadcast_send_text': "✍️ *Отправь текст рассылки.*\nПоддерживается:\n— HTML (`<b>жирный</b>`)\n— Markdown (`**жирный**`)\n— Кликабельные ссылки\n\n_Если текста нет — отправь слово 'нет'_",
        'broadcast_send_media': "📎 Теперь отправь МЕДИА (фото/видео/гиф/документ/аудио) или напиши «нет»",
        'broadcast_send_buttons': "🔘 Теперь отправь КНОПКИ.\nФормат:\n`Текст - https://ссылка`\nДля нескольких кнопок отправь несколько сообщений.\n\nКогда закончишь — напиши «готово».",
        'broadcast_invalid_button': "❌ Неверный формат. Пример: `Канал - https://t.me/...`",
        'broadcast_button_added': "Добавлено. Можешь отправить ещё или напиши «готово».",
        'broadcast_preview_error': "❌ Ошибка предпросмотра:\n`{error}`",
        'broadcast_confirm': "Все готово. Запускаем?",
        'broadcast_start': "✅ Начать рассылку",
        'broadcast_cancel': "♻️ Отмена",
        'broadcast_started': "🚀 Рассылка началась!",
        'broadcast_cancelled': "❌ Отменено.",
        'broadcast_paused': "⏸ Приостановлено.",
        'broadcast_resumed': "▶️ Возобновлено.",
        'broadcast_stopped': "🛑 Остановлено.",
        'broadcast_progress': "📤 Рассылка...\nОтправлено: {sent} / {total}\nОшибок: {failed}",
        'broadcast_finished': "✅ Готово!\n\nОтправлено: {sent}\nОшибок: {failed}",
        'broadcast_control_pause': "⏸ Пауза",
        'broadcast_control_resume': "▶️ Продолжить",
        'broadcast_control_stop': "🛑 Стоп",
        'settings_not_available': "Настройки недоступны. Бот не является администратором чата.",
        'djekpot_title': "🎰 *Джекпот*\n\nЗаплати 2 монеты и выиграй случайный приз:\n- 👑 VIP\n- 🪙 Монеты\n- 💶 Евро\n- ⚔️ Защита\n- 📁 Документы\n- 🔫 Пистолет\n- ⚖️ Защита от повешения",
        'djekpot_spin': "Крутить за 2 🪙",
        'djekpot_no_coins': "❌ У вас недостаточно монет",
        'djekpot_win': "🎰 Вы выиграли: {}!",
        'djekpot_prize_vip': "👑 VIP",
        'djekpot_prize_coins': "🪙 Монеты",
        'djekpot_prize_euro': "💶 Евро",
        'djekpot_prize_shield': "⚔️ Защита",
        'djekpot_prize_fake_docs': "📁 Документы",
        'djekpot_prize_gun': "🔫 Пистолет",
        'djekpot_prize_hanging_shield': "⚖️ Защита от повешения",
        'settings_profile_title': "⚙️ *Настройки*",
        'settings_shield': "⚔️ Защита {}",
        'settings_docs': "📁 Документы {}",
        'settings_hanging': "⚖️ Защита от повешения {}",
        'settings_language': "🌐 Язык: {}",
        'settings_on': "🟢 ON",
        'settings_off': "🔴 OFF",
        'settings_lang_ru': "🇷🇺 Русский",
        'settings_lang_kz': "🇰🇿 Казахский",
        'settings_lang_choose': "🌐 Тілді таңдаңыз / Выберите язык",
        'settings_lang_changed': "Язык изменен на {}",
        'settings_toggle_success': "{} {}",
        'stats_title': "📊 *Статистика бота:*\n\n👤 Профилей игроков: *{profiles}*\n💬 Чатов с настройками: *{chats}*\n🎲 Активных игр: *{games}*",
        'export_success': "✅ Все данные экспортированы.",
        'import_success': "✅ Данные успешно загружены из архива!",
        'import_error': "❌ Ошибка при загрузке данных: {error}",
        'blocked_chat': "🚫 В этом чате запуск игры заблокирован из-за нарушения правил.\nВладельцу чата рекомендуется обратиться в техподдержку.",
        'ad_usage': "Использование: /реклама [ссылка на сообщение] или /реклама сброс",
        'ad_reset': "✅ Реклама сброшена",
        'ad_choose_mode': "Выберите режим отправки рекламы:",
        'ad_use_copy': "✅ Использовать как есть",
        'ad_use_forward': "🔄 Пересылать",
        'ad_cancel': "❌ Отменить",
        'ad_saved_copy': "✅ Реклама сохранена (будет скопирована)",
        'ad_saved_forward': "✅ Реклама сохранена (будет переслана)",
        'ad_error': "Ошибка: {error}\nПроверьте ссылку и права бота в канале.",
        'chaek_broadcast': "*Ойын уақытша тоқтатылды.*\n*🛠️ Бот жаңартылу үстінде!*\nӨтінемін, бірнеше минут күтіп, ойынды қайта бастаңыз.\n\n_Еш уайымдамаңыз — сіздің барлық қорғанысыңыз, құжатыңыз және қалған ресурстарыңыз толық сақталады!_",
        'chaek_broadcast_report': "📤 Сообщение отправлено в {success} чатов.\n❌ Ошибки при отправке в {error} чатов.",
        # Короткие названия ролей (ru)
        'short_role_don': "🤵🏻‍♂️ Дон",
        'short_role_mafia': "🤵🏻 Мафия",
        'short_role_doctor': "👨🏼‍⚕️ Доктор",
        'short_role_suicide': "🤦🏼 Самоубийца",
        'short_role_hobo': "🧙‍♂️ Бомж",
        'short_role_sheriff': "🕵🏼 Комиссар",
        'short_role_lucky': "🤞 Счастливчик",
        'short_role_kamikaze': "💣 Камикадзе",
        'short_role_lover': "💃🏼 Любовница",
        'short_role_lawyer': "👨🏼‍💼 Адвокат",
        'short_role_sergeant': "👮🏼 Сержант",
        'short_role_maniac': "🔪 Маньяк",
        'short_role_citizen': "👨🏼 Мирный житель",
        # НОВЫЕ КЛЮЧИ ДЛЯ ЛОКАЛИЗАЦИИ
        'game_created': "Игра создана!",
        'game_not_started': "*Игра не запущена!*\nДля начала новой игры напишите /game",
        'join_success_short': "Вы присоединились к игре!",
        'already_registered_short': "Вы уже зарегистрированы в этой игре",
        'game_started_error': "Ошибка: игра уже началась или регистрация не открыта",
        'dead_player': "⛔️ Вы мертвы",
        'mafia_prefix': "🤵🏻 Мафия {}:",
        'don_prefix': "🤵🏻‍♂️ Дон {}:",
        'zip_caption': "Архив с данными игры",
        'zip_sent': "✅ ZIP-архив с данными отправлен в канал.",
        'nickname_too_long': "❗ Ваш ник слишком длинный. Пожалуйста, сделайте его короче (сумма слов и символов не должна превышать 45).",
        'days_suffix': " на {days} д.",
        'kamikaze_error': "❌ Ошибка при обработке выбора",
        'stars_button': "{coins}🪙 → {stars}⭐️",
        'already_in_game': "⛔️ Вы уже в игре",
        'language_fast_select': "🌐 Выберите язык / Choose language",
        'death_night_killed_single': "Сегодня был жестоко убит этой ночью *{role}* {victim}...\nГоворят, у него в гостях был {killers}",
'death_night_killed_multiple': "Сегодня был жестоко убит этой ночью *{role}* {victim}...\nГоворят, у него в гостях были {killers}",
        'already_voted': "Вы уже проголосовали",
        'invalid_callback': "❌ Неверный формат данных",
    },
    'kz': {
        # Общие
        'yes': "Иә",
        'language_fast_select': "🌐 Выберите язык / Choose language",
        'no': "Жоқ",
        'back': "🔙 Артқа",
        'close': "❌ Жабу",
        'skip': "🚷 Өткізіп жіберу",
        'join_button': "🤵🏻 Қосылу",
        'game_created': "Ойын жасалды!",
        'game_not_started': "*Ойын басталмаған!*\nЖаңа ойынды бастау үшін /game деп жазыңыз",
        'game_already_running': "Ойын басталып кетті.",
        'insufficient_players': "Ойынды бастау үшін адам жеткіліксіз...",
        'game_started': "Ойын басталды!",
        'game_stopped': "🚫 *Ойынды әкімші тоқтатты!*",
        'registration_stopped': "🚫 *Тіркеуді әкімші тоқтатты*",
        'timeout_auto_start_disabled': "*Ойынның автоматты бастау таймері өшірулі тұр. Сол үшін *\nОйынды /start пәрменін пайдаланып қолмен бастаңыз.",
        'not_in_game': "⛔️ Сіз ойында жоқсыз.",
        'already_registered': "✅ Ойынға қосылдыңыз! :)",
        'join_success': "🎲 {0} чатындағы ойынға қосылдыңыз!",
        'join_success_short': "Сіз ойынға қосылдыңыз!",
        'join_fail_game_started': "🚫 Қосылу мүмкін болмады, ойын басталып кетті!",
        'join_fail_no_reg': "🚫 Қосылу мүмкін болмады, ойын әлі басталмаған!",
        'join_fail_no_permission': "🚫 Ойынға қосыла алмайсыз, себебі топта хабарлама жіберуге рұқсатыңыз жоқ.",
        'join_fail_not_in_chat': "🚫 Ойынға қосылу мүмкін болмады — сіз чатта жоқсыз.",
        'join_fail_other_game': "🚫 Басқа ойынға қосылып қойғансыз",
        'left_game': "🚫 Сіз ойыннан шықтыңыз",
        'left_registration': "🚫 Сіз ойынға тіркелуден бас тарттыңыз.",
        'death_msg': "⚰️ {} бұл қаланың ауыр атмосферасына шыдай алмай асылып кетті. Ол *{}* болған еді.",
        'admin_only': "Бұл команданы орындауға құқығыңыз жоқ.",
        'group_only': "Бұл команданы тек топта қолдануға болады.",
        'pm_error': "Баптауларды жеке хабарламаға жіберу мүмкін емес. Бот сізге хабар жібере алатынын тексеріңіз.",
        'no_rights': "Баптауларды өзгерту құқығыңыз жоқ.",
        'settings_title': "Чат баптаулары",
        'pin_reg': "📌 Тіркелуді бекіту",
        'admin_start': "👑 Ойынды тек әкімші бастайды",
        'team_admin_start': "🔵🟡 Командалық ойынды тек әкімші бастайды",
        'team_admin_question': "Командалық ойынды (/teamgame) тек әкімшілер бастай алсын ба?",
        'team_admin_only_enabled': "Командалық ойынды тек әкімші бастай алады",
        'team_admin_only_disabled': "Командалық ойынды кез келген адам бастай алады",
        'leave_cmd': "🚪 /leave командасын қосу/өшіру",
        'mafia_count': "🤵 Мафия саны",
        'times': "⏱️ Уақыттар",
        'language': "🌐 Тілді өзгерту",
        'players_count': "👥 Ойын басталатын ойыншылар саны",
        'anonymous_vote': "😶‍🌫️ Анонимді дауыс беру",
        'buffs': "Баффтар",
        'choose_lang': "Чат тілін таңдаңыз",
        'kazakh': "🇰🇿 Қазақша",
        'russian': "🇷🇺 Русский",
        'lang_changed': "Чат тілі өзгертілді!",
        'time_reg': "⏰ Тіркелу уақыты",
        'time_night': "🌙 Түн уақыты",
        'alive_list_night_time': "🌙 Түн уақыты",
        'go_to_game': "🎮 Ойынға өту",
        'time_day': "☀️ Күндізгі уақыт",
        'time_vote': "🗳 Дауыс беру уақыты",
        'time_confirm': "👍🏼|👎🏼 Дауыс беруді растау уақыты",
        'select_time': "Қай уақытты өзгерткіңіз келетінін таңдаңыз:",
        'select_option': "Таңдаңыз:",
        'sec': "сек",
        'current_value': "Қазіргі мән:",
        'more_mafia': "Көбірек (1/3)",
        'less_mafia': "Азырақ (1/4)",
        'mafia_ratio_desc': "Мафия санын таңдаңыз:\nКөбірек нұсқасында әрбір 3-ші адам,\nал азырақ нұсқасында әрбір 4-ші адам мафия болады.",
        'pin_question': "Тіркелу хабарламасын бекіту керек пе?",
        'leave_question': "Ойыншыларға /leave командасын қолдануға рұқсат ету керек пе?",
        'admin_question': "Ойынды тек әкімші бастай алатындай ету керек пе?",
        'menu_closed': "Меню жабылды.",
        'time_changed': "Уақыт өзгертілді",
        'registration_time_changed': "Тіркелу уақыты өзгертілді",
        'night_time_changed': "Түн уақыты өзгертілді",
        'day_time_changed': "Күндізгі уақыт өзгертілді",
        'voting_time_changed': "Дауыс беру уақыты өзгертілді",
        'confirmation_time_changed': "Растау уақыты өзгертілді",
        'pin_enabled': "Тіркелу хабарламасын бекіту қосылды",
        'pin_disabled': "Тіркелу хабарламасын бекіту өшірілді",
        'leave_enabled': "/leave командасы қосылды",
        'leave_disabled': "/leave командасы өшірілді",
        'admin_only_enabled': "Тек әкімші ойынды бастай алады",
        'admin_only_disabled': "Кез келген ойынды бастай алады",
        'mafia_ratio_changed': "Мафия саны өзгертілді",
        'anon_vote_enabled': "Анонимді дауыс беру қосылды",
        'anon_vote_disabled': "Анонимді дауыс беру өшірілді",
        'choose_buff': "Өзгерткіңіз келетін баффты таңдаңыз:",
        'shield_buff': "⚔️ Қорғаныс",
        'shield_question': "Осы чатта Қорғаныс баффын қолдануға рұқсат ету керек пе?",
        'shield_enabled': "Қорғаныс баффы қосылды",
        'shield_disabled': "Қорғаныс баффы өшірілді",
        'docs_buff': "📂 Жалған құжаттар",
        'docs_question': "Осы чатта жалған құжаттар баффын қолдануға рұқсат ету керек пе?",
        'docs_enabled': "Жалған құжаттар баффы қосылды",
        'docs_disabled': "Жалған құжаттар баффы өшірілді",
        'hanging_shield_buff': "⚖️ Дарға асудан қорғаныс",
        'hanging_shield_question': "Осы чатта дарға асудан қорғаныс баффын қолдануға рұқсат ету керек пе?",
        'hanging_shield_enabled': "Дарға асудан қорғаныс баффы қосылды",
        'hanging_shield_disabled': "Дарға асудан қорғаныс баффы өшірілді",
        'gun_buff': "🔫 Тапанша",
        'gun_question': "Осы чатта пистолет баффын қолдануға рұқсат ету керек пе?",
        'gun_enabled': "Тапанша баффы қосылды",
        'gun_disabled': "Тапанша баффы өшірілді",
        'choose_players_count': "Қанша ойыншы жиналғанда ойын автоматты түрде басталады?",
        'players_count_changed': "Ойыншылар саны өзгертілді",
        'profile': "*Бейініңіз*\n\n👤 {name}\n🪪 ID: `{id}`\n\n💶 Еуро: {euro}\n🪙 Тиын: {coins}\n\n⚔️ Қорғаныс: {shield}\n📁 Құжат: {docs}\n🔫 Тапанша: {gun}\n⚖️ Дарға қарсы қорғаныс: {hanging_shield}\n\n👑 VIP-дәреже: {vip}",
        'shop_title': "🛒 *Дүкен*",
        'balance': "💶 _Еуро_: {euro}\n🪙 _Тиын_: {coins}",
        'shield_desc': "⚔️ *Қорғаныс*\nбіреу-міреу сізді өлтіреміз деп шабуылдаса, қалқан сізді бір мәрте құтқарып қала алады.",
        'docs_desc': "📁 *Құжат*\nкомиссарға қарсы рөлдерге арналған (Дон, Мафия ж/е т. б.). Комиссар сізді тексерем десе, сізді ол бейбіт тұрғын ретінде көреді.",
        'hanging_desc': "⚖️ *Дарға қарсы қорғаныс*\nДарға асылып қалудан сақтап қалады.\nОсы дүниені сатып алсаңыз, тіпті барлығы сізге қарсы келген кезде де, ешкім сізді асып өлтіре алмайды!",
        'gun_desc': "🔫 *Тапанша*\nТүн жамылып, кез келген ойыншыны өлтіруге мүмкіндік береді.",
        'vip_desc': "👑 *7 күндік VIP-дәреже*\nVIP-дәрежені алған соң:\n- Жеңген сайын 💶 15 алып отырасыз\n- Жеңіліп қалсаңыз 💶 10 бонус аласыз\n- Тірі ойыншылар тізімінде атыңыздың жанында осындай 👑 белгі тұрады\n- Зат сатып алу 🔫 Тапанша аласыз\n- 🪽Қалқанды ойын барысында екі рет пайдалана аласыз",
        'shop_shield': "⚔️ Қорғаныс - 💶 100",
        'shop_docs': "📁 Құжат - 💶 150",
        'shop_gun': "🔫 Тапанша - 💶 600",
        'shop_hanging': "⚖️ Дарға қарсы қорғаныс - 🪙 1",
        'shop_buy_vip': "👑 VIP сатып алy - 7 🪙",
        'shop_renew_vip': "👑 VIP жаңарту - 4 🪙",
        'purchase_success': "✅ Сатып алу сәтті аяқталды",
        'purchase_no_money': "❌ Сатып алуға ақшаңыз жетпейді",
        'purchase_vip_only': "❌ Тек VIP-терге ғана қолжетімді!",
        'purchase_vip_bought': "👑 VIP дәрежесі 7 күнге іске қосылды!",
        'purchase_vip_renewed': "👑 VIP мәртебеңіз 7 күнге ұзартылды!",
        'exchange_title': "💰 *Алмастыру*",
        'exchange_choose': "Алмастыру опциясын таңдаңыз:",
        'exchange_success': "✅ Алмастыру сәтті өтті!",
        'exchange_no_coins': "❌ Тиын жеткіліксіз!",
        'exchange_rate_1': "1🪙 → 150💶",
        'exchange_rate_2': "2🪙 → 300💶",
        'exchange_rate_5': "5🪙 → 750💶",
        'exchange_rate_10': "10🪙 → 1500💶",
        'buy_coins_title': "💰 *Тиын сатып алу*",
        'buy_coins_choose': "Төлем әдісін таңдаңыз:",
        'pay_card': "💳 Қартымен төлеу",
        'pay_stars': "⭐️ Telegram Stars",
        'card_payment_title': "💳 *Қартымен төлеу*",
        'card_payment_text': "🌍 *Төлемдерді қолмен қабылдаймыз*\nҚазір біз қолдау чаты арқылы төлемді қабылдай аламыз.",
        'card_payment_button': "Төлем жасау",
        'stars_payment_text': "🪙 Telegram Stars арқылы төлеу:",
        'stars_button': "{coins}🪙 → {stars}⭐️",
        'help_title': "🗂️ *Сілтемелер*",
        'help_support': "🛠️ Техникалық көмек",
        'help_how_to_play': "Қалай ойнау керек?",
        'help_roles': "🤵🏻 Рөлдер",
        'top_empty': "🏆 *Аптаның 15 үздік ойыншысы:*\n\n❌ Қазіргі уақытта рейтингте ешқандай ойыншы жоқ. Үздіктер тізіміне ену үшін, ойынды ойнаңыз!",
        'top_title': "🏆 *Аптаның 15 үздік ойыншысы:*\n\n",
        'reset_scores_success': "✅ Барлық ұпайлар мен таймерлер сәтті қалпына келтірілді!",
        'coins_transfer_only_group': "🔸 Бұл команда тек топтарда қолжетімді!",
        'coins_transfer_reply_required': "🔸 Монет жіберу үшін адамның хабарламасына жауап ретінде жаз!\nМысалы: /coins 10",
        'coins_transfer_self': "🔸 Өзіңізге монет жібере алмайсыз!",
        'coins_transfer_invalid': "🔸 Қате сан! Мысалы: /coins 10",
        'coins_transfer_profile_error': "🔸 Қате! Профильдерді алу мүмкін болмады.",
        'coins_transfer_not_enough': "🔸 Монет жеткіліксіз! Сізде: {coins} 🪙",
        'coins_transfer_confirmation': "*{sender}* жіберді *{amount}* 🪙 *{recipient}*",
        'next_notification': "🔔 Сізге {chat} чатына жаңа ойынға тіркелу туралы хат келеді.",
        'kamikaze_question': "Кімді өзіңмен бірге аласың?",
        'kamikaze_no_target': "❌ Бұл ойыншы қазірдің өзінде өлі...",
        'kamikaze_chosen': "✅ Сен таңдауыңды жасадың!",
        'kamikaze_announcement': "💣 *Камикадзе* өзімен бірге біреуді алуды шешті...",
        'kamikaze_timeout': "⏰ Уақытың бітіп қалды, сен ешкімді таңдамадың.",
        'kamikaze_action_unavailable': "❌ Бұл әрекет қолжетімсіз",
        'kamikaze_error': "❌ Таңдауды өңдеу кезінде қате",
        'sheriff_not_night': "Бұл әрекеттер тек түнде ғана қолжетімді.",
        'sheriff_choose': "Осы түні не істейтініңді таңда",
        'sheriff_check': "🔍 Тескеру",
        'sheriff_shoot': "🔫 Ату",
        'mafia_vote_question': "Кімді құрбан етеміз?",
        'doctor_question': "Кімді емдейміз?",
        'hobo_question': "Кімге бөтелке іздеп барамыз?",
        'lover_question': "Кімге ләззат береміз?",
        'lawyer_question': "Кімді қорғаймыз?",
        'maniac_question': "Кімді атасың?",
        'gun_question_night': "🔫 Кімді көздейсің?",
        'night_start_caption': "🌙 *Түн болды*\nДалаға тек ең батыл және қорықпайтын адамдар шығады. Күндіз олардың тірісін санаймыз...",
        'night_mafia_chosen': "🤵🏻 *Мафия* құрбанын таңдады...",
        'night_sheriff_check': "🕵🏼 *Комиссар* бұзақыларды іздеуге кетті...",
        'night_sheriff_shoot': "🕵🏼 *Комиссар* тапаншасын оқтай бастады...",
        'night_doctor': "👨🏼‍⚕️ *Дәрігер* біреудің өмірін құтқаруға үшін шықты…",
        'night_hobo': "🧙‍♂️ *Қаңғыбас* бөтелке іздеп, біреудің үйіне кетті…",
        'night_lover': "💃🏼 *Көңілдес* өз таңдауына қонаққа кетті...",
        'night_lawyer': "👨🏼‍💼 *Қорғаушы* қорғау үшін клиент іздейді...",
        'night_maniac': "🔪 *Жауыз* түнгі аңшылыққа шықты...",
        'night_gun_used': "🔫 Біреу түнде қаруын қолданды...",
        'night_no_deaths': "_🤷 Неткен ғажап! Бұл түнде ешкім көз жұмбады…_",
        'day_caption': "🌞 *{day}-ші күн*\nКүн шығып, өткен түнде төгілген қанды қатыртады...",
        'day_alive_players': "*Тірі ойыншылар:*",
        'day_some_of_them': "*Оның кейбіреуі:*",
        'day_total': "👥 Барлығы: *{total}*",
        'day_discussion': "Түнде не болғанын талқылап, тергейтін уақыт келді...",
        'voting_title': "*Айыптыларды табу және жазалау уақыты келді.*\nДауыс беру {time} секундқа созылады",
        'voting_pm_text': "*Айыптыларды іздеу уақыты келді!*\nКімді асқың келеді?",
        'voting_skip': "🚷 Өткізіп жіберу",
        'voting_already_voted': "Сіз дауыс беріп қойғансыз.",
        'voting_ended': "_Дауыс беру аяқталды_",
        'voting_nobody': "Халық келісе алмады...\nЕшкімді аспай,\nбәрі үйлеріне қайтты...",
        'voting_result': "*Дауыс беру нәтижесі:*",
        'voting_saved': "⚖️ Алайда {player} өзін дарға асудан сақтап қалды!",
        'voting_saved_private': "*Сені дарға асқалы жатқанда, Дарға қарсы қорғаныс құтқарып қалды! 🛡️*",
        'voting_executed': "Бүгін {player} дегенді дарға астық\nОл *{role}* болды..",
        'voting_executed_private': "*Күндізгі жиналыста сені бір сөзден дарға асты :(*",
        'confirm_vote_question': "Расымен де {name} дегенді жазалағыңыз келе ме ?",
        'confirm_vote_yes': "👍🏼 {count}",
        'confirm_vote_no': "👎🏼 {count}",
        'confirm_vote_already': "Сіз бұл таңдау жасадыңыз",
        'confirm_vote_accepted': "Дауыс қабылданды!",
        'confirm_vote_cannot': "Сіз дауыс бере алмайсыз.",
        'confirm_vote_ended': "Дауыс беру аяқталды",
        'role_texts': {
            '🤵🏻‍♂️ Дон': "Сен - 🤵🏻‍♂️ Донсың!\n\n(Мафияның басшысы!)Бұл түні кімнің мәңгі ұйқыға кететінін шешесің...",
            '🤵🏻 Мафия': "Сіз — 🤵🏻 Мафия!\n\nМіндетіңіз - Донға бағыну және сізге қарсы шыққандарды өлтіру. Бір күні сіз де Дон болуыңыз мүмкін...",
            '👨🏼‍⚕️ Дәрігер': "Сіз — 👨🏼‍⚕️ Дәрігер!\n\nТүнде кімді құтқаратыныңызды сіз шешесіз…",
            '🤦🏼 Самоубийца': "Сіз — 🤦🏼 Суицид!\n\nСіздің міндетіңіз - қалалық жиналыста дарға асылу!",
            '🧙‍♂️ Қаңғыбас': "Сіз — 🧙‍♂️ Қаңғыбас!\n\nКез келген адамға бір шыны үшін жолығып, кісі өлтіру куәгері бола аласыз.",
            '🕵🏼 Комиссар': "Сіз — 🕵🏼 Комиссар!\n\nҚаланың қорғаушысы мен мафияның басты қорқынышы...",
            '🤞 Жолы болғыш': "Сіз — 🤞 Жолы болғыш!\n\nМіндетіңіз — қалалық жиналыста бұзақыларды дарға асу.",
            '💣 Камикадзе': "Сіз — 💣 Камикадзе!\n\nЕгер олар сізді асып тастауға тырысса, ойыншылардың қайсысын өзіңізбен бірге қабірге апаратыныңызды таңдай аласыз.",
            '💃🏼 Көңілдес': "Сіз — 💃🏼 Көңілдес!\n\nҚалаған ойыншыны бір күнге ұйықтату үшін дағдыларыңызды пайдаланыңыз.",
            '👨🏼‍💼 Қорғаушы': "Сіз — 👨🏼‍💼 Қорғаушы!\n\nТүнде кімді қорғайтыныңызды шешесіз.",
            '👮🏼 Сержант': "Сіз — 👮🏼 Сержант!\n\nКомиссардың көмекшісісіз.",
            '🔪 Жауыз': "Сіз — 🔪 Жауыз!\n\nҚалада ешкім тірі қалмауы керек. Әлбетте, сізден басқасы :)",
            '👨🏼 Тату тұрғын': "Сіз — 👨🏼 Тату тұрғын!\n\nСіздің басты міндетіңіз — мафияны тауып, қалалық жиналыста оңбағандарды дарға асу."
        },
        'death_night_message': "*Сені түнде өлтірді :(*\nӨлім туралы хабарламаңды жібере аласың",
        'death_last_words_sent': "*Хабарлама қабылданып, чатқа жіберілді.*",
        'death_last_words_announce': "Тұрғындардың біреуі {player} өлер алдында айғайлағанын есітіпті:\n_{words}_",
        'shield_used_announce': "🪽 Ойыншылардың біреуі қорғанысын жұмсады",
        'shield_used_private': "⚔️ Біреу саған қастандық жасады, бірақ қорғанысың сақтап қалды!",
        'doctor_saved': "👨🏼‍⚕️ *Дәрігер* сені емдеп алды",
        'doctor_visited': "👨🏼‍⚕️ Дәрігер қонағыңызға келді",
        'lucky_saved_announce': "🤞 Кейбір ойыншылардың жолы болды",
        'lucky_saved_private': "🤞 Осы түні саған қастық жасалды, бірақ сенің жолың болды!",
        'don_transfer_announce': "🤵🏻 *Мафия* 🤵🏻‍♂️ *Дон* рөлін өзіне мұра етті",
        'don_transfer_private': "Енді сен 🤵🏻‍♂️ Донсың!",
        'sheriff_transfer_announce': "👮🏼 *Сержант* 🕵🏼 *Комиссар* рөлін өзіне мұра етті",
        'sheriff_transfer_private': "Енді сен 🕵🏼 Комиссарсың!",
        'mafia_vote_result': "*Дауыс беру аяқталды*\nМафия {victim} дегенді құрбан етті",
        'mafia_vote_no_consensus': "*Дауыс беру аяқталды.*\nОтбасы ортақ шешімге келе алмай, ешкімде құрбан етпеді",
        'mafia_vote_nobody': "*Дауыс беру аяқталды.*\nОтбасы ортақ шешімге келе алмай, ешкімде құрбан етпеді",
        'lover_song': "💃🏼 Көңілдес \"Маған кел, бәрін ұмыт...\", - деп ән салды",
        'lover_blocked_by_doctor': "💃🏼 *Көңілдес* сені тыныштандырғысы келді, бірақ 👨🏼‍⚕️ *Дәрігердің* сенімен екенін көріп, кетіп қалды!",
        'lover_visited': "💃🏼 Көңілдес саған келді...",
        'hobo_visited': "🧙🏼‍♂️ *Қаңғыбас* түнде сенен бір бөтелке сұрауға кетті.",
        'hobo_report_with_visitors': "Түнде сен {target} деген бөтелке алуға барып, {visitors} дегенді көрдің.",
        'hobo_report_no_visitors': "Сен {target} дегенге бөтелке іздеуге барғанда, күдікті ештеңе байқаған жоқсың.",
        'hobo_report_no_target': "Сен бұл түні ешкімді жолықтырмадың.",
        'lawyer_protected': "👨🏼‍💼 Қорғаушы сені бұл түні қорғады.",
        'game_end_title': "*Ойын аяқталды!*",
        'game_end_winners': "Жеңімпаздар:",
        'game_end_remaining': "Қалған ойыншылар:",
        'game_end_time': "Ойын уақыты: {} мин. {} сек.",
        'game_end_you_earned': "*Ойын аяқталды!*\nСен {} 💶 алдың",
        'game_end_mafia_won': "Мафия жеңді",
        'game_end_citizens_won': "Халық жеңді",
        'game_end_maniac_won': "Жауыз жеңді",
        'game_end_suicide_won': "Өз-өзіне қол жұмсаушы жеңді",
        'police_composition': "🚨 *Полициялық құрам:*\n{sheriff}\n{sergeant}",
        'registration_title': "*Ойыншы жинап жатырмыз*\n{players}\n_{count} адам қосылды_",
        'registration_empty': "*Ойыншы жинап жатырмыз*\n_Әзірге ешкім жоқ_",
        'registration_notify_59': "⏰ Тіркелудің бітуіне *59 сек* қалды",
        'registration_notify_29': "⏰ Тіркелудің бітуіне *29 сек* қалды",
        'start_private': "*Сәлем!*\nМен 🤵🏻 *Мафия* ойнынын жүргізуші-ботымын.\nМені чатқа қосып, әкімші етіңіз және тегін ойнай бастаңыз",
        'start_add_to_group': "🤵🏽 Ботты өз чатыңа қосу",
        'start_join_chat': "Чатқа кіру",
        'start_news': "📰 Жаңалықтар",
        'welcome_chat': "Сәлем! :)\nМен 🤵🏻 Мафия ойынын жүргізетін ботпын\nОйынды бастау үшін маған төмендегі әкімші құқықтарын беріңіз:\n🛑 Хат жою\n🛑 Пайдаланушы бұғаттау\n🛑 Хат бекіту\n⚙️ Баптауларды өзгерту үшін /settings пәрменін пайдаланыңыз",
        'welcome_lang_choice': "Тілді таңдаңыз",
        'available_chats': "*Қол жетімді чаттар:*",
        'settings_sent': "Баптаулар жеке хабарламаға жіберілді.",
        'no_active_game': "Шығатын белсенді ойын жоқ.",
        'cannot_leave_game': "Ойыннан шығу чат баптауларымен шектелген.",
        'leave_disabled_by_admin': "Ойын кезінде ойыннан шығу әкімшімен шектелген.",
        'voting_blocked_by_lover': "💃🏼 Менімен бірге бәрін ұмыт...",
        'sheriff_action_already_taken': "Сіз бүгін кешке өз таңдауыңызды жасадыңыз.",
        'sheriff_check_result': "Сен {player} дегенді тексеріп, оның рөлі - {role} екенін анықтадың.",
        'sheriff_check_result_fake': "Сен {player} дегенді тексеріп, оның рөлі - 👨🏼 Тату тұрғын екенін анықтадың.",
        'sheriff_check_visited': "🕵🏼 *Комиссар* саған қонаққа баруды шешті.",
        'sheriff_check_fake_used': "🕵🏼 *Комиссар* сені іздеп келді, бірақ сен жалған құжаттарды көрсеттің.",
        'sheriff_check_lawyer_protected': "🕵🏼 Комиссар сені іздеп келді, бірақ қорғаушы саған тату тұрғын рөлін берді.",
        'sheriff_shot': "Сіз өлтіруге бардыңыз {player}",
        'sheriff_checked': "Сіз тексеруге бардың {player}",
        'doctor_self_heal_forbidden': "Сіз өзіңізді емдедіңіз, басқа ойыншыны таңдаңыз.",
        'doctor_chosen': "Сіз емдеуді таңдадыңыз {player}",
        'mafia_voted': "Сіз дауыс бердіңіз {player}",
        'mafia_vote_notification_don': "🤵🏻‍♂️ *Дон* [{name}](tg://user?id={id}) дауыс берді {victim}",
        'mafia_vote_notification_mafia': "🤵🏻 Мафия [{name}](tg://user?id={id}) дауыс берді {victim}",
        'mafia_vote_notification_lawyer': "🤵🏻 Мафия ??? дауыс берді {victim}",
        'hobo_chosen': "Сіз бөтелке алуға бардыңыз {player}",
        'lover_chosen': "Сен ләззат сыйлауға кеттің {player}",
        'lawyer_chosen': "Сіз қорғауды таңдадыңыз {player}",
        'maniac_chosen': "Сіз өлтіруді таңдадыңыз {player}",
        'gun_chosen': "🔫 {player} дегенді көздедің",
        'gun_no_available': "❌ Сізде қолданатын пистолет жоқ!",
        'gun_night_only': "🔫 Пистолетті тек түнде қолдануға болады!",
        'gun_target_unavailable': "❌ Мақсат қолжетімсіз!",
        'vote_casted': "Сіз таңдадыңыз {player}",
        'vote_announce_anon': "{voter} дауыс берді",
        'vote_announce_open': "{voter} өз дауысын {target} үшін берді",
        'vote_notification': "🗳 Дауыс беру",
        'vote_notificatio': "Ботқа өту",
        'private_message_forward_sheriff': "🕵🏼 *Комиссар {name}*:\n{text}",
        'private_message_forward_sergeant': "👮🏼 *Сержант {name}*:\n{text}",
        'give_menu_title': "Таңдаңыз:",
        'give_item_euro': "💶 Еуро",
        'give_item_coins': "🪙 Тиын",
        'give_item_shield': "⚔️ Қорғаныс",
        'give_item_fake_docs': "📁 Жалған құжат",
        'give_item_gun': "🔫 Тапанша",
        'give_item_hanging_shield': "⚖️ Дардан қорғаныс",
        'give_item_vip': "👑 VIP",
        'give_enter_amount': "{item} үшін санды енгізіңіз:\n(әрекет: {action})",
        'give_added': "Қосылды: {item} = {amount}\n\nТағы қосу?",
        'give_confirm_title': "Беруді растаңыз:\n\n{items}",
        'give_confirm': "✅ Растау",
        'give_cancel': "❌ Бас тарту",
        'give_cancelled': "❌ Бас тартылды.",
        'give_completed': "🎁 Беру орындалды:\n\n{items}",
        'give_completed_silent': "✔ Беру орындалды (жасырын режим).",
        'give_inventory_changed': "📥 Сізге инвентарь өзгертілді:\n\n{items}",
        'give_session_expired': "Сессия аяқталды.",
        'give_empty': "Бос беруді жіберу мүмкін емес!",
        'give_invalid_amount': "❌ Сан сан болуы керек.",
        'give_no_permission': "❌ Сізде рұқсат жоқ.",
        'give_usage': "Қолдану: /give <user_id>",
        'give_invalid_id': "❌ user_id сан болуы керек.",
        'broadcast_send_text': "✍️ *Рассылка мәтінін жіберіңіз.*\nҚолдау көрсетіледі:\n— HTML (`<b>қалың</b>`)\n— Markdown (`**қалың**`)\n— Басуды сілтемелер\n\n_Мәтін жоқ болса — 'жоқ' деп жіберіңіз_",
        'broadcast_send_media': "📎 Енді МЕДИА (сурет/бейне/гиф/құжат/аудио) жіберіңіз немесе «жоқ» деп жазыңыз",
        'broadcast_send_buttons': "🔘 Енді ТҮЙМЕЛЕРДІ жіберіңіз.\nПішім:\n`Мәтін - https://сілтеме`\nБірнеше түйме үшін бірнеше хабарлама жіберіңіз.\n\nАяқтағанда — «дайын» деп жазыңыз.",
        'broadcast_invalid_button': "❌ Қате пішім. Мысалы: `Арна - https://t.me/...`",
        'broadcast_button_added': "Қосылды. Тағы жіберуге болады немесе «дайын» деп жазыңыз.",
        'broadcast_preview_error': "❌ Алдын ала қарау қатесі:\n`{error}`",
        'broadcast_confirm': "Барлығы дайын. Іске қосамыз?",
        'broadcast_start': "✅ Рассылканы бастау",
        'broadcast_cancel': "♻️ Бас тарту",
        'broadcast_started': "🚀 Рассылка басталды!",
        'broadcast_cancelled': "❌ Бас тартылды.",
        'broadcast_paused': "⏸ Тоқтатылды.",
        'broadcast_resumed': "▶️ Жалғасты.",
        'broadcast_stopped': "🛑 Тоқтатылды.",
        'broadcast_progress': "📤 Рассылка...\nЖіберілді: {sent} / {total}\nҚателер: {failed}",
        'broadcast_finished': "✅ Дайын!\n\nЖіберілді: {sent}\nҚателер: {failed}",
        'broadcast_control_pause': "⏸ Пауза",
        'broadcast_control_resume': "▶️ Жалғастыру",
        'broadcast_control_stop': "🛑 Тоқтату",
        'settings_not_available': "Баптаулар қолжетімсіз. Бот чат әкімшісі емес.",
        'djekpot_title': "🎰 *Джекпот*\n\n2 монета төлеп, кездейсоқ сыйлықты ұтып алыңыз:\n- 👑 VIP\n- 🪙 Монета\n- 💶 Еуро\n- ⚔️ Қорғаныс\n- 📁 Құжат\n- 🔫 Тапанша\n- ⚖️ Дардан қорғаныс",
        'djekpot_spin': "2🪙 Айналдыру",
        'djekpot_no_coins': "❌ Монета жеткіліксіз",
        'djekpot_win': "🎰 Сіз ұтып алдыңыз: {}!",
        'djekpot_prize_vip': "👑 VIP",
        'djekpot_prize_coins': "🪙 Монета",
        'djekpot_prize_euro': "💶 Еуро",
        'djekpot_prize_shield': "⚔️ Қорғаныс",
        'djekpot_prize_fake_docs': "📁 Құжат",
        'djekpot_prize_gun': "🔫 Тапанша",
        'djekpot_prize_hanging_shield': "⚖️ Дардан қорғаныс",
        'settings_profile_title': "⚙️ *Баптаулар*",
        'settings_shield': "⚔️ Қорғаныс {}",
        'settings_docs': "📁 Құжат {}",
        'settings_hanging': "⚖️ Дарға қарсы {}",
        'settings_language': "🌐 Тіл: {}",
        'settings_on': "🟢 ON",
        'settings_off': "🔴 OFF",
        'settings_lang_ru': "🇷🇺 Орысша",
        'settings_lang_kz': "🇰🇿 Қазақша",
        'settings_lang_choose': "🌐 Тілді таңдаңыз / Выберите язык",
        'settings_lang_changed': "Тіл {} өзгертілді",
        'settings_toggle_success': "{} {}",
        'stats_title': "📊 *Бот статистикасы:*\n\n👤 Ойыншы профильдері: *{profiles}*\n💬 Баптаулары бар чаттар: *{chats}*\n🎲 Белсенді ойындар: *{games}*",
        'export_success': "✅ Барлық деректер экспортталды.",
        'import_success': "✅ Деректер архивтен сәтті жүктелді!",
        'import_error': "❌ Деректерді жүктеу кезінде қате: {error}",
        'blocked_chat': "🚫 Осы чатта ойынды бастау ережелерді бұзғаны үшін бұғатталған.\nЧат иесіне техникалық қолдауға хабарласу ұсынылады.",
        'ad_usage': "Қолдану: /реклама [хабарлама сілтемесі] немесе /реклама сброс",
        'ad_reset': "✅ Жарнама қалпына келтірілді",
        'ad_choose_mode': "Жарнаманы жіберу режимін таңдаңыз:",
        'ad_use_copy': "✅ Көшіріп қолдану",
        'ad_use_forward': "🔄 Жолдау",
        'ad_cancel': "❌ Болдырмау",
        'ad_saved_copy': "✅ Жарнама сақталды (көшіріледі)",
        'ad_saved_forward': "✅ Жарнама сақталды (жолданады)",
        'ad_error': "Қате: {error}\nСілтемені және боттың арнадағы құқықтарын тексеріңіз.",
        'chaek_broadcast': "*Ойын уақытша тоқтатылды.*\n*🛠️ Бот жаңартылу үстінде!*\nӨтінемін, бірнеше минут күтіп, ойынды қайта бастаңыз.\n\n_Еш уайымдамаңыз — сіздің барлық қорғанысыңыз, құжатыңыз және қалған ресурстарыңыз толық сақталады!_",
        'chaek_broadcast_report': "📤 Хабарлама {success} чатқа жіберілді.\n❌ {error} чатқа жіберу кезінде қателер.",
        # Короткие названия ролей (kz)
        'short_role_don': "🤵🏻‍♂️ Дон",
        'short_role_mafia': "🤵🏻 Мафия",
        'short_role_doctor': "👨🏼‍⚕️ Дәрігер",
        'short_role_suicide': "🤦🏼 Өз-өзіне қол жұмсаушы",
        'short_role_hobo': "🧙‍♂️ Қаңғыбас",
        'short_role_sheriff': "🕵🏼 Комиссар",
        'short_role_lucky': "🤞 Сәтті",
        'short_role_kamikaze': "💣 Камикадзе",
        'short_role_lover': "💃🏼 Көңілдес",
        'short_role_lawyer': "👨🏼‍💼 Қорғаушы",
        'short_role_sergeant': "👮🏼 Сержант",
        'short_role_maniac': "🔪 Жауыз",
        'short_role_citizen': "👨🏼 Бейбіт тұрғын",
        # НОВЫЕ КЛЮЧИ ДЛЯ ЛОКАЛИЗАЦИИ
        'game_created': "Ойын жасалды!",
        'game_not_started': "*Ойын басталмаған!*\nЖаңа ойынды бастау үшін /game деп жазыңыз",
        'join_success_short': "Сіз ойынға қосылдыңыз!",
        'already_registered_short': "Сіз бұл ойынға тіркелгенсіз",
        'game_started_error': "Қате: ойын басталып кетті немесе тіркеу ашылмаған",
        'dead_player': "⛔️ Сіз өлдіңіз",
        'mafia_prefix': "🤵🏻 Мафия {}:",
        'don_prefix': "🤵🏻‍♂️ Дон {}:",
        'zip_caption': "Ойын деректері бар мұрағат",
        'zip_sent': "✅ ZIP-мұрағат деректері бар арнаға жіберілді.",
        'nickname_too_long': "❗ Лақап атыңыз тым ұзын. Оны қысқартыңыз (сөздер мен таңбалар қосындысы 45-тен аспауы керек).",
        'days_suffix': " {days} күнге",
        'kamikaze_error': "❌ Таңдауды өңдеу кезінде қате",
        'stars_button': "{coins}🪙 → {stars}⭐️",
        'already_in_game': "⛔️ Сіз ойындасыз",
        'already_voted': "Сіз дауыс бердіңіз",
        'death_night_killed_single': "Түнде *{role}* {victim} аяусыз өлтірілген болды...\nОның үйінде {killers} болған деседі",
        'death_night_killed_multiple': "Түнде *{role}* {victim} аяусыз өлтірілген болды...\nОның үйінде {killers} болған деседі",
        'invalid_callback': "❌ Қате деректер форматы",
    }
}

# Функция для получения текста по ключу и языку чата

# Функция для получения текста по языку пользователя
def get_user_text(user_id, key, **kwargs):
    """Получает локализованный текст по языку пользователя"""
    profile = player_profiles.get(user_id, {})
    lang = profile.get('language', 'ru')
    text = TEXTS[lang].get(key, TEXTS['ru'].get(key, key))
    if kwargs:
        text = text.format(**kwargs)
    return text

# Функция для перевода роли (полное описание)
def translate_role(role, lang):
    """Переводит роль на нужный язык (полное описание)"""
    return TEXTS[lang].get('role_texts', {}).get(role, role)

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
    return TEXTS[lang].get(key, role)

# Единое экранирование для Telegram legacy Markdown (parse_mode="Markdown").
# Важно: сохраняем исходные символы ника, включая [] и •, а не подменяем их.
def escape_markdown_name(value):
    value = str(value or '').strip()
    # Обратный слеш экранируется первым, чтобы не экранировать добавленные ниже слеши повторно.
    for char in ('\\', '_', '*', '`', '[', ']', '(', ')'):
        value = value.replace(char, '\\' + char)
    return value

def user_link(name, user_id):
    safe_name = escape_markdown_name(name) or 'Игрок'
    return f"[{safe_name}](tg://user?id={int(user_id)})"

# Единое получение имени без лишнего разделителя, даже если фамилия не указана.
def get_full_name(player):
    first_name = str(player.get('name', '') or '').strip()
    last_name = str(player.get('last_name', '') or '').strip()
    if first_name and last_name and first_name.casefold().endswith((' ' + last_name).casefold()):
        return first_name
    full_name = ' '.join(part for part in (first_name, last_name) if part).strip()
    return full_name or 'Игрок'

# ================== КЛАСС GAME ==================
class Game:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = {}
        self.team_mode = False
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
        players_list = ", ".join([get_full_name(player) for player in self.players.values()])
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
        full_name = get_full_name(dead_player)
        clickable_name = user_link(full_name, player_id)

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
            player_name = get_full_name(player)
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

    if getattr(game, 'team_mode', False):
        team = player_dict[player_id].get('team')
        team_name = '🔵 Синяя команда' if team == 'blue' else '🟡 Жёлтая команда'
        text = f"{team_name}\n\n{text}"

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


def registration_keyboard(chat_id):
    """Клавиатура регистрации. Для /teamgame кнопки открывают личку бота
    так же, как обычная кнопка «Присоединиться», но сразу передают выбранную команду."""
    chat = chat_list.get(chat_id)
    markup = types.InlineKeyboardMarkup(row_width=2)
    bot_username = bot.get_me().username

    if chat and getattr(chat, 'team_mode', False):
        blue_url = f'https://t.me/{bot_username}?start=teamjoin_{chat_id}_blue'
        yellow_url = f'https://t.me/{bot_username}?start=teamjoin_{chat_id}_yellow'
        markup.add(
            types.InlineKeyboardButton('🔵', url=blue_url),
            types.InlineKeyboardButton('🟡', url=yellow_url)
        )
    else:
        join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
        markup.add(types.InlineKeyboardButton(get_text(chat_id, 'join_button'), url=join_url))
    return markup


def registration_message(players, chat_id):
    lang = chat_settings.get(chat_id, {}).get("language", "kz")

    if players:
        player_names = []
        for player_id, player in players.items():
            full_name = get_full_name(player)
            team_icon = ''
            game = chat_list.get(chat_id)
            if game and getattr(game, 'team_mode', False):
                team_icon = '🔵 ' if player.get('team') == 'blue' else ('🟡 ' if player.get('team') == 'yellow' else '')
            player_names.append(f"{team_icon}{user_link(full_name, player_id)}")
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
            team_icon = ''
            game = chat_list.get(chat_id)
            if game and getattr(game, 'team_mode', False):
                team = player.get('team')
                team_icon = '🔵' if team == 'blue' else ('🟡' if team == 'yellow' else '')

            living_players.append(
                f"{team_icon} {special_icon}{vip_icon}{' ' if (special_icon or vip_icon) else ''}{player['number']}. {user_link(get_full_name(player), player_id)}"
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
            team_icon = ''
            game = chat_list.get(chat_id)
            if game and getattr(game, 'team_mode', False):
                team = player.get('team')
                team_icon = '🔵' if team == 'blue' else ('🟡' if team == 'yellow' else '')

            living_players.append(
                f"{team_icon} {special_icon}{vip_icon}{' ' if (special_icon or vip_icon) else ''}{player['number']}. {user_link(get_full_name(player), player_id)}"
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
            join_btn = registration_keyboard(chat_id)
            send_message(chat_id, get_text(chat_id, 'registration_notify_59'), reply_markup=join_btn)


def notify_at_29_seconds(chat_id):
    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if not chat.game_running and chat.button_id:
            join_btn = registration_keyboard(chat_id)
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
        chat.team_mode = False
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


def add_player(chat, user_id, user_name, last_name, player_number, team=None):
    get_or_create_profile(user_id, user_name, last_name)
    chat.players[user_id] = {
        'name': user_name,
        'last_name': last_name,
        'role': 'ждет',
        'skipped_actions': 0,
        'status': 'alive',
        'number': player_number
    }
    if team:
        chat.players[user_id]['team'] = team


def notify_mafia_and_don(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    mafia_and_don_list = []
    players_copy = list(chat.players.items())
    for player_id, player in players_copy:
        if player['role'] == '🤵🏻‍♂️ Дон':
            mafia_and_don_list.append(f"{user_link(get_full_name(player), player_id)} - *{get_short_role(player['role'], chat.chat_id)}*")
        elif player['role'] == '🤵🏻 Мафия':
            mafia_and_don_list.append(f"{user_link(get_full_name(player), player_id)} - *{get_short_role(player['role'], chat.chat_id)}*")
    message = "*" + get_text(chat.chat_id, 'police_composition').split('*')[0] + "*\n" + "\n".join(mafia_and_don_list)
    for player_id, player in players_copy:
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
            try:
                send_message(player_id, message, parse_mode='Markdown', protect_content=True)
            except Exception as e:
                print(f"Не удалось отправить сообщение игроку {player['name']}: {e}")


def confirm_vote(chat_id, player_id, player_name, player_last_name, confirm_votes, player_list):
    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    full_name = f"{player_name} {player_last_name}".strip()
    full_name_link = user_link(full_name, player_id)
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

    team_mode = getattr(chat, 'team_mode', False)
    team_winners_ids = []
    team_winning_text = ''
    if team_mode:
        blue_alive = [k for k, v in chat.players.items() if v.get('team') == 'blue' and v.get('status') not in ['dead', 'left']]
        yellow_alive = [k for k, v in chat.players.items() if v.get('team') == 'yellow' and v.get('status') not in ['dead', 'left']]
        if blue_alive and yellow_alive:
            return False
        if blue_alive:
            team_winners_ids = blue_alive
            team_winning_text = ('🔵 Көк команда жеңді!' if chat_settings.get(chat.chat_id, {}).get('language', 'ru') == 'kz' else '🔵 Синяя команда победила!')
        elif yellow_alive:
            team_winners_ids = yellow_alive
            team_winning_text = ('🟡 Сары команда жеңді!' if chat_settings.get(chat.chat_id, {}).get('language', 'ru') == 'kz' else '🟡 Жёлтая команда победила!')
        else:
            return False

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
    if team_mode:
        winning_team = team_winning_text
        winners_ids = team_winners_ids
        winners = [f"{user_link(get_full_name(chat.players[k]), k)} - {get_short_role(chat.players[k]['role'], chat.chat_id)}" for k in winners_ids]
    elif maniac_count == 1 and alive_count == 1:
        winning_team = get_text(chat.chat_id, 'game_end_maniac_won')
        winners = [f"{user_link(get_full_name(v), k)} - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
    elif maniac_count == 1 and len(chat.players) - maniac_count == 1:
        winning_team = get_text(chat.chat_id, 'game_end_maniac_won')
        winners = [f"{user_link(get_full_name(v), k)} - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] == '🔪 Жауыз' and v['status'] != 'dead']
    elif mafia_count == 0 and maniac_count == 0:
        winning_team = get_text(chat.chat_id, 'game_end_citizens_won')
        winners = [f"{user_link(get_full_name(v), k)} - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] not in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз', '🤦🏼 Самоубийца'] and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] not in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз', '🤦🏼 Самоубийца'] and v['status'] != 'dead']
    elif mafia_count == 1 and total_mafia_team == 1 and alive_count == 1:
        winning_team = get_text(chat.chat_id, 'game_end_mafia_won')
        winners = [f"{user_link(get_full_name(v), k)} - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] == '🤵🏻‍♂️ Дон' and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] == '🤵🏻‍♂️ Дон' and v['status'] != 'dead']
    elif is_mafia_win(alive_count, total_mafia_team):
        winning_team = get_text(chat.chat_id, 'game_end_mafia_won')
        winners = [f"{user_link(get_full_name(v), k)} - {get_short_role(v['role'], chat.chat_id)}" for k, v in chat.players.items() if v['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы'] and v['status'] != 'dead']
        winners_ids = [k for k, v in chat.players.items() if v['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы'] and v['status'] != 'dead']
    else:
        return False

    # ========== ДОБАВЛЯЕМ ПОВЕШЕННЫХ САМОУБИЙЦ К ПОБЕДИТЕЛЯМ ==========
    if not team_mode:
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
                    winners.append(f"{user_link(full_name, suicide_id)} - {get_short_role('🤦🏼 Самоубийца', chat.chat_id)}")
                    logging.info(f"Самоубийца {suicide_id} добавлен к победителям")
    
    if not team_mode and len(winners_ids) == 1 and winners_ids[0] in hanged_suicides and not winning_team:
        winning_team = get_text(chat.chat_id, 'game_end_suicide_won')
    elif not team_mode and hanged_suicides and not winning_team:
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

    # Цвет команды для итогового списка (только /teamgame).
    def team_icon(player):
        if not team_mode or not isinstance(player, dict):
            return ''
        team = player.get('team')
        return '🔵 ' if team == 'blue' else ('🟡 ' if team == 'yellow' else '')

    # Добавляем цвет команды в финальный список победителей.
    if team_mode:
        winners = [
            f"{team_icon(chat.players.get(k, {}))}{user_link(get_full_name(chat.players[k]), k)} - {get_short_role(chat.players[k]['role'], chat.chat_id)}"
            for k in winners_ids if k in chat.players
        ]

    # Оставшиеся игроки
    remaining_players = []
    for k, v in chat.players.items():
        if k in hanged_suicides:
            continue
        if k not in winners_ids and v['status'] not in ['dead', 'left']:
            remaining_players.append(f"{team_icon(v)}{user_link(get_full_name(v), k)} - {get_short_role(v['role'], chat.chat_id)}")
    for k, v in chat.players.items():
        if k in hanged_suicides:
            continue
        if v['status'] == 'left':
            remaining_players.append(f"{team_icon(v)}{user_link(get_full_name(v), k)} - {get_short_role(v['role'], chat.chat_id)}")

    # Все мёртвые игроки
    all_dead_players = []
    for player in chat.all_dead_players:
        if isinstance(player, dict):
            player_id = player.get('user_id')
            if player_id in hanged_suicides:
                continue
            if player_id not in winners_ids:
                all_dead_players.append(f"{team_icon(player)}{user_link(get_full_name(player), player_id)} - {get_short_role(player['role'], chat.chat_id)}")
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

    # Недельный рейтинг отдельный для каждого чата.
    # Победители получают +1; проигравшие до 10 очков не теряют очки,
    # а после достижения 10 рейтинг не опускается ниже 10.
    scored_players = set()
    for player_id in winners_ids:
        update_chat_weekly_score(chat.chat_id, player_id, won=True)
        scored_players.add(player_id)
    for player_id in chat.players:
        if player_id in scored_players or player_id in hanged_suicides:
            continue
        if chat.players[player_id]['status'] not in ['left', 'dead']:
            update_chat_weekly_score(chat.chat_id, player_id, won=False)
            scored_players.add(player_id)
    for dead_player in chat.all_dead_players:
        if isinstance(dead_player, dict):
            player_id = dead_player.get('user_id')
            if player_id in scored_players or player_id in hanged_suicides:
                continue
            if player_id not in winners_ids:
                update_chat_weekly_score(chat.chat_id, player_id, won=False)
                scored_players.add(player_id)

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
    chat.team_mode = False
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
    full_name = f"{player_name} {player_last_name}".strip()
    player_link = user_link(full_name, player_id)

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
        police_members.append(f"{user_link(sheriff_name, chat.sheriff_id)} - *{get_short_role(chat.players[chat.sheriff_id]['role'], chat.chat_id)}*")

    if chat.sergeant_id and chat.sergeant_id in chat.players and chat.players[chat.sergeant_id]['role'] == '👮🏼 Сержант':
        sergeant_name = get_full_name(chat.players[chat.sergeant_id])
        police_members.append(f"{user_link(sergeant_name, chat.sergeant_id)} - *{get_short_role(chat.players[chat.sergeant_id]['role'], chat.chat_id)}*")

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
        victim_name_link = user_link(victim_name, victim_id)
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


@bot.message_handler(commands=['language'])
def language_command(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    profile = get_or_create_profile(
        user_id,
        message.from_user.first_name or "Пользователь",
        message.from_user.last_name or ""
    )
    lang = profile.get('language', 'ru')
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="fast_lang_ru"),
        types.InlineKeyboardButton("🇰🇿 Қазақша", callback_data="fast_lang_kz")
    )
    prompt = "😛 Тілді таңдаңыз / Choose language" if lang == 'kz' else "😛 Выберите язык / Choose language"
    bot.send_message(message.chat.id, prompt, reply_markup=keyboard)


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
            selected_team = None
            if param.startswith("teamjoin_"):
                parts = param.split('_')
                if len(parts) != 3 or parts[2] not in ('blue', 'yellow'):
                    bot.send_message(user_id, "🚫 Некорректная ссылка на командную игру.")
                    return
                try:
                    game_chat_id = int(parts[1])
                except ValueError:
                    bot.send_message(user_id, "🚫 Некорректная ссылка на игру.")
                    return
                selected_team = parts[2]
            elif param.startswith("join_"):
                try:
                    game_chat_id = int(param.split('_')[1])
                except (ValueError, IndexError):
                    bot.send_message(user_id, "🚫 Некорректная ссылка на игру.")
                    return
            else:
                game_chat_id = None

            if game_chat_id is not None:
                lang = chat_settings.get(game_chat_id, {}).get("language", "kz")

                if user_id in user_game_registration:
                    if user_game_registration[user_id] != game_chat_id:
                        bot.send_message(user_id, get_text(game_chat_id, 'join_fail_other_game'))
                        return

                chat = chat_list.get(game_chat_id)
                if chat:
                    try:
                        chat_member = bot.get_chat_member(game_chat_id, user_id)
                        if getattr(chat_member, 'status', None) in ('left', 'kicked'): 
                            bot.send_message(user_id, get_text(game_chat_id, 'join_fail_not_in_chat'))
                            return
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
                            if getattr(chat, 'team_mode', False):
                                # Для /teamgame команда уже передана через deep-link из кнопки в группе.
                                # Без выбранной команды присоединение не выполняем.
                                if selected_team not in ('blue', 'yellow'):
                                    bot.send_message(user_id, '🎨 Выберите команду кнопкой 🔵 или 🟡 под регистрацией в группе.')
                                    return
                                chat.players[user_id] = {
                                    'name': user_name,
                                    'last_name': user_last_name,
                                    'role': 'ждет',
                                    'skipped_actions': 0,
                                    'team': selected_team
                                }
                            else:
                                chat.players[user_id] = {'name': user_name, 'last_name': user_last_name, 'role': 'ждет', 'skipped_actions': 0}
                            user_game_registration[user_id] = game_chat_id
                            bot.send_message(user_id, get_text(game_chat_id, 'join_success').format(bot.get_chat(game_chat_id).title))
                            new_text = players_alive(chat.players, "registration", game_chat_id)
                            new_markup = registration_keyboard(game_chat_id)
                            try:
                                schedule_update(game_chat_id, chat)
                            except Exception as e:
                                logging.error(f"Ошибка обновления сообщения: {e}")
                            with game_start_lock:
                                players_needed = chat_settings.get(game_chat_id, {}).get('players_to_start', 20)
                                if len(chat.players) >= players_needed and not chat.game_running and chat.button_id:
                                    _start_game(game_chat_id)
                        else:
                            if getattr(chat, 'team_mode', False) and selected_team in ('blue', 'yellow'):
                                chat.players[user_id]['team'] = selected_team
                                icon = '🔵' if selected_team == 'blue' else '🟡'
                                bot.send_message(user_id, f'🎨 Команда изменена на {icon}.')
                                schedule_update(game_chat_id, chat)
                            else:
                                bot.send_message(user_id, get_text(game_chat_id, 'already_registered'))
                    except Exception as e:
                        logging.error(f"Ошибка при проверке членства в чате: {e}")
                        # Если Telegram не смог подтвердить членство, не добавляем игрока в игру.
                        try:
                            bot.send_message(user_id, get_text(game_chat_id, 'join_fail_not_in_chat'))
                        except Exception:
                            pass
                return

        bot_username = bot.get_me().username
        add_to_group_url = f'https://t.me/{bot_username}?startgroup=bot_command'

        language_keyboard = types.InlineKeyboardMarkup(row_width=2)
        language_keyboard.add(
            types.InlineKeyboardButton("🇷🇺 Русский", callback_data="fast_lang_ru"),
            types.InlineKeyboardButton("🇰🇿 Қазақша", callback_data="fast_lang_kz")
        )
        language_prompt = "😛 Тілді таңдаңыз / Choose language" if lang == 'kz' else "😛 Выберите язык / Choose language"
        bot.send_message(
            chat_id,
            language_prompt,
            reply_markup=language_keyboard
        )

    elif message.chat.type in ['group', 'supergroup']:
        user_id = message.from_user.id
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

        chat = chat_list.get(chat_id)
        # /start не должен создавать или запускать игру, если регистрация
        # не открывалась и игровой сессии в чате нет.
        if not chat or (not chat.button_id and not chat.game_running):
            bot.send_message(
                chat_id,
                get_text(chat_id, 'game_not_started'),
                parse_mode="Markdown"
            )
            return

        try:
            chat_member = bot.get_chat_member(chat_id, user_id)
        except Exception:
            return
        if chat_member.status not in ['administrator', 'creator']:
            return
        if chat and not chat.game_running and chat.button_id:
            _start_game(chat_id)


@bot.callback_query_handler(func=lambda call: call.data in ('fast_lang_ru', 'fast_lang_kz'))
def set_welcome_language(call):
    """Сохраняет выбранный язык и показывает главное приветственное меню."""
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name, call.from_user.last_name)
    lang_code = 'ru' if call.data == 'fast_lang_ru' else 'kz'
    profile['language'] = lang_code
    player_profiles[user_id] = profile

    bot_username = bot.get_me().username
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(
        get_user_text(user_id, 'start_add_to_group'),
        url=f'https://t.me/{bot_username}?startgroup=bot_command'))
    keyboard.add(types.InlineKeyboardButton(
        get_user_text(user_id, 'start_join_chat'), callback_data='join_chat'))
    keyboard.add(types.InlineKeyboardButton(
        get_user_text(user_id, 'start_news'), url='https://t.me/CityMafiaNews'))

    welcome_text = get_user_text(user_id, 'start_private')
    try:
        bot.edit_message_text(chat_id=call.message.chat.id,
                              message_id=call.message.message_id,
                              text=welcome_text, reply_markup=keyboard,
                              parse_mode='Markdown')
    except Exception:
        bot.send_message(call.message.chat.id, welcome_text,
                         reply_markup=keyboard, parse_mode='Markdown')
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'join_chat')
def join_chat_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    profile = get_or_create_profile(user_id, call.from_user.first_name)
    user_lang = profile.get('language', 'ru')

    chat_targets = list(ALLOWED_CHAT_ID)

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
        new_markup = registration_keyboard(game_chat_id)
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
    lang = chat_settings.get(chat_id, {}).get("language", "ru")
    text = TEXTS[lang].get(key, TEXTS['ru'].get(key, key))
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
            "allow_registration": False,
            "allow_team_registration": False,
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
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'team_admin_start'), callback_data=f"menu_team_commands_{chat_id}"))
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
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'team_admin_start'), callback_data=f"menu_team_commands_{chat_id}"))
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
    elif data.startswith("menu_team_commands_"):
        current = chat_settings[chat_id].get('allow_team_registration', True)
        team_commands_kb = types.InlineKeyboardMarkup()
        team_commands_kb.add(
            types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_team_admin_only_yes_{chat_id}"),
            types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_team_admin_only_no_{chat_id}")
        )
        team_commands_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'team_admin_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=team_commands_kb)
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_team_admin_only_"))
def set_team_admin_only(call):
    parts = call.data.split("_")
    choice = parts[4]
    chat_id = int(parts[5])
    user_id = call.from_user.id
    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return
    # SQLiteSettings — DB-backed mapping, у него нет dict.setdefault().
    # Создаём настройки чата через поддерживаемый интерфейс, если их ещё нет.
    settings = chat_settings.get(chat_id)
    if settings is None:
        chat_settings[chat_id] = {}
        settings = chat_settings.get(chat_id, {})
    enabled = (choice == "yes")
    settings["allow_team_registration"] = enabled
    bot.answer_callback_query(
        call.id,
        get_text(chat_id, 'team_admin_only_enabled' if enabled else 'team_admin_only_disabled')
    )
    current = chat_settings[chat_id]["allow_team_registration"]
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton(f"{'▪️' if current else '▫️'} {get_text(chat_id, 'yes')}", callback_data=f"set_team_admin_only_yes_{chat_id}"),
        types.InlineKeyboardButton(f"{'▫️' if current else '▪️'} {get_text(chat_id, 'no')}", callback_data=f"set_team_admin_only_no_{chat_id}")
    )
    kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
    bot.edit_message_text(get_text(chat_id, 'team_admin_question'), chat_id=user_id, message_id=call.message.message_id, reply_markup=kb)


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

def _create_game(message, team_mode=False):
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
            "allow_registration": False,
            "allow_team_registration": False,
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

    # SQLiteSettingsDict inherits dict, but dict.setdefault() may bypass our
    # persistence hook. Use explicit assignment for missing defaults.
    settings = chat_settings.get(chat_id)
    if settings is None:
        settings = {
            "language": "ru",
            "pin_registration": False,
            "allow_registration": False,
            "allow_team_registration": False,
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
            "gun_buff": True,
        }
        chat_settings[chat_id] = settings
        settings = chat_settings.get(chat_id)
    defaults = {
        "allow_registration": False,
        "allow_team_registration": False,
        "pin_registration": False,
        "allow_leave_game": True,
        "registration_time": (120, 60),
    }
    for key, value in defaults.items():
        if key not in settings:
            settings[key] = value

    # YES means only administrators can start; NO means everyone can start.
    if team_mode and settings.get("allow_team_registration", False) and user_id not in admin_ids:
        return
    if not team_mode and settings.get("allow_registration", False) and user_id not in admin_ids:
        return

    if chat_id not in chat_list:
        chat_list[chat_id] = Game(chat_id)

    chat = chat_list[chat_id]

    if chat.game_running or chat.button_id:
        return

    chat.team_mode = team_mode

    with registration_lock:
        if chat.button_id:
            return

        join_btn = registration_keyboard(chat_id)

        msg_text = registration_message(chat.players, chat_id)
        msg = send_message(chat_id, msg_text, reply_markup=join_btn, parse_mode="Markdown")

        if msg:
            chat.button_id = msg.message_id
            if chat_settings[chat_id]["pin_registration"]:
                try:
                    bot.pin_chat_message(chat_id, msg.message_id)
                except Exception as pin_error:
                    # A pin failure (e.g. missing admin permission) must not
                    # abort game registration after the registration message was sent.
                    logging.warning(
                        "Не удалось закрепить сообщение регистрации в чате %s: %s",
                        chat_id, pin_error
                    )
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


@bot.message_handler(commands=['game'])
def create_game(message):
    _create_game(message, team_mode=False)


@bot.message_handler(commands=['teamgame'])
def create_team_game(message):
    _create_game(message, team_mode=True)

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
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(shield_text, callback_data="toggle_shield"))
    markup.add(types.InlineKeyboardButton(docs_text, callback_data="toggle_docs"))
    markup.add(types.InlineKeyboardButton(hanging_text, callback_data="toggle_hanging"))
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
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO allowed_chats (chat_id) VALUES (?)", (chat_id,))
            conn.commit()
        if cursor.rowcount == 0:
            if chat_id not in ALLOWED_CHAT_ID:
                ALLOWED_CHAT_ID.append(chat_id)
            bot.reply_to(message, "Этот чат уже в списке.")
        else:
            if chat_id not in ALLOWED_CHAT_ID:
                ALLOWED_CHAT_ID.append(chat_id)
            bot.reply_to(message, f"Чат {chat_id} добавлен в список разрешённых и сохранён в SQLite.")
    except (IndexError, ValueError):
        bot.reply_to(message, "Использование: /add_chat <ID группы>")


# Надёжная рассылка: отдельное состояние на администратора и защита от параллельных запусков.
user_data = globals().get('user_data', {})
broadcast_jobs = globals().get('broadcast_jobs', {})
broadcast_jobs_lock = threading.RLock()


def _broadcast_is_admin(user_id):
    return bool(user_id and int(user_id) == int(ADMIN_ID))


def _broadcast_get_text(chat_id, key):
    return get_text(chat_id, key)


@bot.message_handler(commands=['рассылка'])
def broadcast_command(message):
    if not _broadcast_is_admin(getattr(getattr(message, 'from_user', None), 'id', None)):
        return bot.reply_to(message, get_text(message.chat.id, 'admin_only'))

    chat_id = message.chat.id
    with broadcast_jobs_lock:
        job = broadcast_jobs.get(chat_id)
        if job and job.get('running'):
            return bot.reply_to(message, "⚠️ Рассылка уже выполняется. Останови её перед запуском новой.")
        user_data[chat_id] = {
            'text': None,
            'media': None,
            'parse_mode': 'HTML',
            'keyboard_buttons': [],
            'created_by': message.from_user.id,
        }

    msg = bot.reply_to(message, get_text(chat_id, 'broadcast_send_text'), parse_mode="Markdown")
    bot.register_next_step_handler(msg, handle_text)


def handle_text(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id)
    if not data or not _broadcast_is_admin(getattr(getattr(message, 'from_user', None), 'id', None)):
        return
    txt = (message.text or '').strip()
    if txt.lower() in ('нет', 'жоқ', 'жок', 'no'):
        txt = None
    data['text'] = txt or None
    # Telegram HTML is predictable; MarkdownV2 is deliberately not forced on arbitrary text.
    data['parse_mode'] = 'HTML' if data['text'] and ('<' in data['text'] and '>' in data['text']) else 'Markdown'
    msg = bot.reply_to(message, get_text(chat_id, 'broadcast_send_media'))
    bot.register_next_step_handler(msg, handle_media)


def handle_media(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id)
    if not data or not _broadcast_is_admin(getattr(getattr(message, 'from_user', None), 'id', None)):
        return
    if message.content_type == 'text' and (message.text or '').strip().lower() in ('нет', 'жоқ', 'жок', 'no'):
        data['media'] = None
    else:
        allowed_media_types = {'photo', 'video', 'animation', 'document', 'audio', 'voice'}
        if message.content_type not in allowed_media_types:
            msg = bot.reply_to(message, "❌ Отправь фото, видео, GIF, документ или аудио. Если медиа не нужно — напиши «нет».")
            return bot.register_next_step_handler(msg, handle_media)
        data['media'] = message
    msg = bot.reply_to(message, get_text(chat_id, 'broadcast_send_buttons'), parse_mode="Markdown")
    data['keyboard_buttons'] = []
    bot.register_next_step_handler(msg, handle_buttons)


def handle_buttons(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id)
    if not data or not _broadcast_is_admin(getattr(getattr(message, 'from_user', None), 'id', None)):
        return
    text = (message.text or '').strip()
    if text.lower() in ('готово', 'дайын', 'дайын!', 'done'):
        if not data.get('text') and not data.get('media'):
            msg = bot.reply_to(message, "❌ Рассылка не может быть пустой. Отправь текст или медиа.")
            return bot.register_next_step_handler(msg, handle_buttons)
        keyboard = types.InlineKeyboardMarkup()
        for btn_text, link in data['keyboard_buttons']:
            keyboard.add(types.InlineKeyboardButton(text=btn_text, url=link))
        data['keyboard'] = keyboard if data['keyboard_buttons'] else None
        return preview(chat_id)

    match = re.match(r'^(.+?)\s*-\s*(https?://[^\s]+)$', text)
    if not match:
        msg = bot.reply_to(message, get_text(chat_id, 'broadcast_invalid_button'))
        return bot.register_next_step_handler(msg, handle_buttons)

    btn_text, url = match.groups()
    btn_text, url = btn_text.strip(), url.strip()
    if not btn_text or len(btn_text) > 64:
        msg = bot.reply_to(message, "❌ Текст кнопки должен содержать от 1 до 64 символов.")
        return bot.register_next_step_handler(msg, handle_buttons)
    if not url.startswith(('https://', 'http://')):
        msg = bot.reply_to(message, get_text(chat_id, 'broadcast_invalid_button'))
        return bot.register_next_step_handler(msg, handle_buttons)
    data['keyboard_buttons'].append((btn_text, url))
    msg = bot.reply_to(message, get_text(chat_id, 'broadcast_button_added'))
    bot.register_next_step_handler(msg, handle_buttons)


def preview(chat_id):
    data = user_data.get(chat_id)
    if not data:
        return
    text, media = data.get('text'), data.get('media')
    keyboard, parse_mode = data.get('keyboard'), data.get('parse_mode', 'HTML')
    try:
        if media:
            # copy_message is used for the preview to preserve the original media type.
            if text:
                bot.copy_message(chat_id, media.chat.id, media.message_id, caption=text,
                                 parse_mode=parse_mode, reply_markup=keyboard)
            else:
                bot.copy_message(chat_id, media.chat.id, media.message_id, reply_markup=keyboard)
        elif text:
            bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "❌ Пустая рассылка: добавь текст или медиа.")
            return
    except Exception as e:
        logging.exception("Ошибка предпросмотра рассылки")
        bot.send_message(chat_id, "❌ Не удалось показать предпросмотр. Проверь текст/форматирование и попробуй заново.")
        return

    confirm = types.InlineKeyboardMarkup()
    confirm.add(
        types.InlineKeyboardButton(get_text(chat_id, 'broadcast_start'), callback_data="start_broadcast"),
        types.InlineKeyboardButton(get_text(chat_id, 'broadcast_cancel'), callback_data="cancel_broadcast"),
    )
    bot.send_message(chat_id, get_text(chat_id, 'broadcast_confirm'), reply_markup=confirm)


@bot.callback_query_handler(func=lambda call: call.data in ['start_broadcast', 'cancel_broadcast'])
def callback_decision(call):
    chat_id = call.message.chat.id
    if not _broadcast_is_admin(getattr(getattr(call, 'from_user', None), 'id', None)):
        return bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)

    if call.data == "cancel_broadcast":
        with broadcast_jobs_lock:
            job = broadcast_jobs.get(chat_id)
            if job and job.get('running'):
                return bot.answer_callback_query(call.id, "Сначала останови активную рассылку.", show_alert=True)
            user_data.pop(chat_id, None)
        bot.answer_callback_query(call.id)
        return bot.edit_message_text(get_text(chat_id, 'broadcast_cancelled'), chat_id, call.message.message_id)

    with broadcast_jobs_lock:
        if chat_id in broadcast_jobs and broadcast_jobs[chat_id].get('running'):
            return bot.answer_callback_query(call.id, "Рассылка уже выполняется.", show_alert=True)
        data = user_data.get(chat_id)
        if not data or (not data.get('text') and not data.get('media')):
            return bot.answer_callback_query(call.id, "Рассылка пустая. Создай её заново.", show_alert=True)
        job = {'running': True, 'paused': threading.Event(), 'stop': threading.Event()}
        job['paused'].set()  # set = sending is allowed; clear = paused
        broadcast_jobs[chat_id] = job

    bot.answer_callback_query(call.id)
    bot.edit_message_text(get_text(chat_id, 'broadcast_started'), chat_id, call.message.message_id)
    thread = threading.Thread(target=send_broadcast, args=(chat_id, job), daemon=True)
    thread.start()


def control_buttons(chat_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(get_text(chat_id, 'broadcast_control_pause'), callback_data="pause_broadcast"),
        types.InlineKeyboardButton(get_text(chat_id, 'broadcast_control_resume'), callback_data="resume_broadcast"),
        types.InlineKeyboardButton(get_text(chat_id, 'broadcast_control_stop'), callback_data="stop_broadcast"),
    )
    return markup


@bot.callback_query_handler(func=lambda call: call.data in ['pause_broadcast', 'resume_broadcast', 'stop_broadcast'])
def handle_controls(call):
    chat_id = call.message.chat.id
    if not _broadcast_is_admin(getattr(getattr(call, 'from_user', None), 'id', None)):
        return bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
    with broadcast_jobs_lock:
        job = broadcast_jobs.get(chat_id)
    if not job or not job.get('running'):
        return bot.answer_callback_query(call.id, "Активной рассылки нет.", show_alert=True)

    if call.data == "pause_broadcast":
        job['paused'].clear()
        bot.answer_callback_query(call.id, get_text(chat_id, 'broadcast_paused'))
    elif call.data == "resume_broadcast":
        job['paused'].set()
        bot.answer_callback_query(call.id, get_text(chat_id, 'broadcast_resumed'))
    elif call.data == "stop_broadcast":
        job['stop'].set()
        job['paused'].set()  # wake worker if it was paused
        bot.answer_callback_query(call.id, get_text(chat_id, 'broadcast_stopped'))


def send_broadcast(admin_chat, job=None):
    if job is None:
        with broadcast_jobs_lock:
            job = broadcast_jobs.get(admin_chat)
    data = user_data.get(admin_chat)
    if not data or not job:
        return

    # Snapshot IDs before sending, so profile updates during the run don't mutate iteration.
    try:
        players = list(player_profiles.keys()) if hasattr(player_profiles, 'keys') else list(player_profiles)
    except Exception:
        players = list(player_profiles)
    players = list(dict.fromkeys(int(uid) for uid in players if str(uid).lstrip('-').isdigit()))
    random.shuffle(players)

    text, media = data.get('text'), data.get('media')
    keyboard, parse_mode = data.get('keyboard'), data.get('parse_mode', 'HTML')
    success = failed = 0
    blocked_or_unreachable = 0
    try:
        status_msg = bot.send_message(
            admin_chat,
            get_text(admin_chat, 'broadcast_progress').format(sent=0, total=len(players), failed=0),
            reply_markup=control_buttons(admin_chat),
        )
    except Exception:
        logging.exception("Не удалось создать статус рассылки")
        with broadcast_jobs_lock:
            job['running'] = False
        return

    try:
        for idx, user_id in enumerate(players, start=1):
            if job['stop'].is_set():
                bot.edit_message_text(get_text(admin_chat, 'broadcast_stopped'), admin_chat, status_msg.message_id)
                return
            job['paused'].wait()
            if job['stop'].is_set():
                bot.edit_message_text(get_text(admin_chat, 'broadcast_stopped'), admin_chat, status_msg.message_id)
                return

            try:
                if media:
                    if text:
                        bot.copy_message(user_id, media.chat.id, media.message_id, caption=text,
                                         parse_mode=parse_mode, reply_markup=keyboard)
                    else:
                        bot.copy_message(user_id, media.chat.id, media.message_id, reply_markup=keyboard)
                elif text:
                    bot.send_message(user_id, text, parse_mode=parse_mode, reply_markup=keyboard)
                else:
                    raise ValueError("Пустая рассылка")
                success += 1
            except Exception as e:
                failed += 1
                error_text = str(e).lower()
                if any(token in error_text for token in ('blocked', 'chat not found', 'user is deactivated', 'forbidden')):
                    blocked_or_unreachable += 1
                logging.warning("Ошибка рассылки пользователю %s: %s", user_id, e)

            # Обновляем статус не чаще одного раза на 10 получателей и в конце.
            if idx % 10 == 0 or idx == len(players):
                try:
                    bot.edit_message_text(
                        get_text(admin_chat, 'broadcast_progress').format(sent=success, total=len(players), failed=failed),
                        admin_chat, status_msg.message_id, reply_markup=control_buttons(admin_chat),
                    )
                except Exception:
                    pass
            # Небольшая пауза снижает риск Telegram rate limit.
            time.sleep(0.7)

        finished_text = get_text(admin_chat, 'broadcast_finished').format(sent=success, failed=failed)
        finished_text += f"\n\nВсего получателей: {len(players)}\nНедоступных/заблокировавших бота: {blocked_or_unreachable}"
        try:
            bot.edit_message_text(finished_text, admin_chat, status_msg.message_id)
        except Exception:
            bot.send_message(admin_chat, finished_text)
    except Exception:
        logging.exception("Критическая ошибка рассылки")
        try:
            bot.send_message(admin_chat, "❌ Рассылка прервана из-за внутренней ошибки. Подробности записаны в журнал.")
        except Exception:
            pass
    finally:
        with broadcast_jobs_lock:
            job['running'] = False
            if broadcast_jobs.get(admin_chat) is job:
                broadcast_jobs.pop(admin_chat, None)
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
                full_name = get_full_name(player)
                clickable_name = user_link(full_name, user_id)
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
            new_markup = registration_keyboard(game_chat_id)
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


# ================== ПУБЛИЧНЫЕ ПОДАРКИ И /GIFT ==================
PUBLIC_GIFT_ITEMS = {
    'euro': ('💶 Евро', 'euro'),
    'coins': ('🪙 Монеты', 'coins'),
    'shield': ('🛡️ Защита', 'shield'),
    'fake_docs': ('📁 Документы', 'fake_docs'),
    'hanging_shield': ('⚖️ Защита от повешения', 'hanging_shield'),
    'gun': ('🔫 Пистолет', 'gun'),
}
public_gift_sessions = {}


def _gift_config_read():
    with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
        row = conn.execute('SELECT config_json FROM gift_config WHERE config_id=1').fetchone()
    if not row:
        return {'items': {}, 'interval_seconds': 86400, 'enabled': False}
    try:
        cfg = json.loads(row[0])
        return cfg if isinstance(cfg, dict) else {'items': {}, 'interval_seconds': 86400, 'enabled': False}
    except Exception:
        return {'items': {}, 'interval_seconds': 86400, 'enabled': False}


def _gift_config_write(config):
    with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
        conn.execute("""INSERT INTO gift_config(config_id, config_json) VALUES(1, ?)
                        ON CONFLICT(config_id) DO UPDATE SET config_json=excluded.config_json""",
                     (_json_dumps(config),))
        conn.commit()


def _gift_claimed_ids(gift_id):
    with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
        row = conn.execute('SELECT claimed_json FROM public_gifts WHERE gift_id=? AND active=1', (gift_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return []


def start_public_gift(message):
    # /give в группе запускает открытую раздачу без ответа на сообщение.
    chat_id = message.chat.id
    sender_id = message.from_user.id
    sender_profile = player_profiles.get(sender_id)
    if not sender_profile:
        bot.reply_to(message, '❌ У тебя нет профиля. Открой личку бота и создай профиль перед отправкой подарка.')
        return
    session_key = f'{sender_id}:{chat_id}'
    sender_name = (message.from_user.full_name or message.from_user.first_name or str(sender_id))
    public_gift_sessions[session_key] = {
        'sender_id': sender_id, 'chat_id': chat_id, 'sender_name': sender_name,
        'items': {}, 'step': 'item'
    }
    try:
        bot.send_message(sender_id,
                         '🎁 Настрой подарок для чата. Выбери предмет и укажи количество НА ОДНОГО участника. '
                         'Каждый желающий сможет получить подарок, пока в твоём профиле хватает выбранных предметов. '
                         'Предметы будут списываться с твоего профиля отдельно за каждого получателя.',
                         reply_markup=_public_gift_keyboard(session_key))
        bot.reply_to(message, '🎁 Отправил тебе меню подарка в личные сообщения. Продолжи там.')
    except Exception as e:
        public_gift_sessions.pop(session_key, None)
        bot.reply_to(message, '❌ Не могу написать тебе в личку. Сначала открой бота и нажми /start.')
        logging.warning('Не удалось отправить меню публичного подарка в личку %s: %s', sender_id, e)


def _public_gift_keyboard(session_key):
    data = public_gift_sessions[session_key]
    markup = types.InlineKeyboardMarkup(row_width=2)
    for key, (label, _) in PUBLIC_GIFT_ITEMS.items():
        current = int(data['items'].get(key, 0) or 0)
        markup.add(
            types.InlineKeyboardButton(f'➕ {label} ({current})', callback_data=f'pg_item:{key}:add'),
            types.InlineKeyboardButton(f'➖ {label}', callback_data=f'pg_item:{key}:remove')
        )
    markup.add(types.InlineKeyboardButton('✅ Проверить и подтвердить', callback_data='pg_confirm'))
    markup.add(types.InlineKeyboardButton('❌ Отмена', callback_data='pg_cancel'))
    return markup


def public_gift_amount_step(message, session_key, item, mode='add'):
    data = public_gift_sessions.get(session_key)
    if not data or message.from_user.id != data['sender_id']:
        return
    try:
        amount = int((message.text or '').strip())
    except Exception:
        bot.reply_to(message, '❌ Введи целое положительное число.')
        bot.register_next_step_handler(message, lambda msg, sk=session_key, it=item, md=mode: public_gift_amount_step(msg, sk, it, md))
        return
    if amount <= 0 or amount > 1000000:
        bot.reply_to(message, '❌ Количество должно быть от 1 до 1 000 000.')
        bot.register_next_step_handler(message, lambda msg, sk=session_key, it=item, md=mode: public_gift_amount_step(msg, sk, it, md))
        return
    current = int(data['items'].get(item, 0) or 0)
    updated = current + amount if mode == 'add' else current - amount
    if updated > 0:
        data['items'][item] = updated
    else:
        data['items'].pop(item, None)
    data['step'] = 'item'
    bot.send_message(message.chat.id, 'Настрой подарок дальше:', reply_markup=_public_gift_keyboard(session_key))


def public_gift_recipients_step(message, session_key):
    data = public_gift_sessions.get(session_key)
    if not data or message.from_user.id != data['sender_id']:
        return
    try: amount = int((message.text or '').strip())
    except Exception:
        bot.reply_to(message, '❌ Введи число от 1 до 100.'); bot.register_next_step_handler(message, lambda msg, sk=session_key: public_gift_recipients_step(msg, sk)); return
    if not 1 <= amount <= 100:
        bot.reply_to(message, '❌ Число получателей должно быть от 1 до 100.'); bot.register_next_step_handler(message, lambda msg, sk=session_key: public_gift_recipients_step(msg, sk)); return
    data['recipients'] = amount
    data['step'] = 'item'
    bot.send_message(message.chat.id, 'Количество получателей сохранено. Продолжай настройку:', reply_markup=_public_gift_keyboard(session_key))


@bot.callback_query_handler(func=lambda c: c.data.startswith('pg_item:') or c.data in ('pg_recipients','pg_confirm','pg_cancel'))
def public_gift_callback(call):
    session_key = next((k for k, v in public_gift_sessions.items() if v['sender_id'] == call.from_user.id), None)
    if not session_key:
        bot.answer_callback_query(call.id, 'Сессия подарка не найдена или истекла.', show_alert=True)
        return
    data = public_gift_sessions[session_key]
    if call.data == 'pg_cancel':
        public_gift_sessions.pop(session_key, None)
        try: bot.edit_message_text('❌ Отправка подарка отменена.', call.message.chat.id, call.message.message_id)
        except Exception: pass
        bot.answer_callback_query(call.id)
        return
    if call.data.startswith('pg_item:'):
        parts = call.data.split(':')
        item = parts[1] if len(parts) > 1 else ''
        mode = parts[2] if len(parts) > 2 else 'add'
        if item not in PUBLIC_GIFT_ITEMS or mode not in ('add', 'remove'):
            bot.answer_callback_query(call.id, 'Неизвестный предмет.', show_alert=True); return
        data['step'] = 'amount:' + item + ':' + mode
        bot.answer_callback_query(call.id)
        action = 'добавить' if mode == 'add' else 'убрать'
        bot.send_message(call.from_user.id, f'Введи количество {PUBLIC_GIFT_ITEMS[item][0]} на ОДНОГО получателя, которое нужно {action}:')
        bot.register_next_step_handler(call.message, lambda msg, sk=session_key, it=item, md=mode: public_gift_amount_step(msg, sk, it, md))
        return
    if call.data == 'pg_confirm':
        if not data['items']:
            bot.answer_callback_query(call.id, 'Сначала выбери хотя бы один предмет.', show_alert=True); return
        profile = player_profiles.get(data['sender_id'])
        if not profile:
            bot.answer_callback_query(call.id, 'Профиль отправителя не найден.', show_alert=True); return
        # Не списываем весь подарок заранее: каждый участник получает выбранное
        # количество, которое списывается с отправителя в момент получения.
        for item, each_amount in data['items'].items():
            balance = int(profile.get(item, 0) or 0)
            if balance < each_amount:
                bot.answer_callback_query(call.id,
                    f'Не хватает предмета «{PUBLIC_GIFT_ITEMS[item][0]}» даже на одного участника. У тебя: {balance}.',
                    show_alert=True)
                return
        gift_id = hashlib.sha256(f'{data["sender_id"]}:{time.time_ns()}'.encode()).hexdigest()[:16]
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            conn.execute('INSERT INTO public_gifts(gift_id, chat_id, sender_id, items_json, recipients_limit, claimed_json, active) VALUES(?,?,?,?,?,?,1)',
                         (gift_id, data['chat_id'], data['sender_id'], _json_dumps(data['items']), -1, '[]'))
            conn.commit()
        sender_name = data.get('sender_name') or (call.from_user.full_name or call.from_user.first_name or str(data['sender_id']))
        announce = (f'🎁 {sender_name} отправил чату подарок!\n\n' +
                    '\n'.join(f'• {PUBLIC_GIFT_ITEMS[k][0]}: {v} на человека' for k, v in data['items'].items()) +
                    '\n\n🎁 Подарок получили: пока никто\n\nНажми «Получить подарок», чтобы забрать награду. ' 
                    'Подарок доступен всем желающим, пока у отправителя хватает предметов.')
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton('🎁 Получить подарок', callback_data=f'pg_claim:{gift_id}'))
        try:
            bot.send_message(data['chat_id'], announce, reply_markup=markup)
            bot.edit_message_text('✅ Подарок опубликован в чате. Предметы будут списываться по мере получения.', call.message.chat.id, call.message.message_id)
            public_gift_sessions.pop(session_key, None)
        except Exception as e:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute('DELETE FROM public_gifts WHERE gift_id=?', (gift_id,)); conn.commit()
            bot.answer_callback_query(call.id, 'Не удалось опубликовать подарок. Предметы не списывались.', show_alert=True)
            logging.exception('Не удалось опубликовать публичный подарок: %s', e)
            return
        bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith('pg_claim:'))
def public_gift_claim(call):
    gift_id = call.data.split(':', 1)[1]
    user_id = call.from_user.id
    with _db_lock:
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            row = conn.execute('SELECT chat_id, sender_id, items_json, recipients_limit, claimed_json, active FROM public_gifts WHERE gift_id=?', (gift_id,)).fetchone()
        if not row or not row[5]:
            bot.answer_callback_query(call.id, 'Этот подарок уже недоступен.', show_alert=True); return
        chat_id, sender_id, items_json, limit_count, claimed_json, active = row
        claimed = json.loads(claimed_json or '[]')
        if user_id in claimed:
            bot.answer_callback_query(call.id, 'Ты уже получил этот подарок.', show_alert=True); return
        sender_profile = player_profiles.get(sender_id)
        recipient_profile = player_profiles.get(user_id)
        if not recipient_profile:
            bot.answer_callback_query(call.id, 'Сначала создай профиль в боте, затем забери подарок.', show_alert=True); return
        if not sender_profile:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute('UPDATE public_gifts SET active=0 WHERE gift_id=?', (gift_id,)); conn.commit()
            bot.answer_callback_query(call.id, 'Подарок закрыт: профиль отправителя недоступен.', show_alert=True); return
        items = json.loads(items_json)
        # Без лимита по количеству людей: раздача работает, пока хватает предметов.
        for item, amount in items.items():
            balance = int(sender_profile.get(item, 0) or 0)
            if balance < int(amount):
                with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                    conn.execute('UPDATE public_gifts SET active=0 WHERE gift_id=?', (gift_id,)); conn.commit()
                bot.answer_callback_query(call.id, 'Подарок закончился: у отправителя больше не хватает предметов.', show_alert=True)
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=types.InlineKeyboardMarkup())
                except Exception:
                    pass
                return
        for item, amount in items.items():
            sender_profile[item] = int(sender_profile.get(item, 0) or 0) - int(amount)
            recipient_profile[item] = int(recipient_profile.get(item, 0) or 0) + int(amount)
        claimed.append(user_id)
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            conn.execute('UPDATE public_gifts SET claimed_json=?, active=1 WHERE gift_id=?', (_json_dumps(claimed), gift_id))
            conn.commit()
    bot.answer_callback_query(call.id, '🎁 Подарок получен!')
    try:
        bot.send_message(user_id, '🎁 Ты получил подарок!\n' + '\n'.join(f'{PUBLIC_GIFT_ITEMS.get(k,(k,k))[0]}: {v}' for k,v in items.items()))
    except Exception:
        pass
    try:
        names = []
        for claimed_id in claimed:
            if claimed_id == user_id:
                name = call.from_user.full_name or call.from_user.first_name or str(claimed_id)
            else:
                prof = player_profiles.get(claimed_id)
                name = (prof.get('name') if prof else None) or f'Игрок {claimed_id}'
            names.append('• ' + str(name))
        sender_prof = player_profiles.get(sender_id)
        original_first_line = (call.message.text or '').splitlines()
        sender_line = original_first_line[0] if original_first_line else '🎁 Игрок отправил чату подарок!'
        announce = (sender_line + '\n\n' +
                    '\n'.join(f'• {PUBLIC_GIFT_ITEMS.get(k,(k,k))[0]}: {v} на человека' for k,v in items.items()) +
                    f'\n\n🎁 Подарок получили ({len(claimed)}):\n' + '\n'.join(names))
        can_continue = all(int(sender_prof.get(k, 0) or 0) >= int(v) for k, v in items.items()) if sender_prof else False
        if not can_continue:
            with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
                conn.execute('UPDATE public_gifts SET active=0 WHERE gift_id=?', (gift_id,)); conn.commit()
            announce += '\n\n❌ Подарок закончился.'
            markup = types.InlineKeyboardMarkup()
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton('🎁 Получить подарок', callback_data=f'pg_claim:{gift_id}'))
        bot.edit_message_text(announce, chat_id, call.message.message_id, reply_markup=markup)
    except Exception:
        logging.exception('Не удалось обновить объявление публичного подарка')


def _parse_gift_duration(value):
    m = re.fullmatch(r'(\d+)([smhd])', value.lower())
    if not m: return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {'s':1, 'm':60, 'h':3600, 'd':86400}[unit]


@bot.message_handler(commands=['gift'])
def claim_configured_gift(message):
    if message.chat.type != 'private':
        bot.reply_to(message, '🎁 Команда /gift работает в личных сообщениях боту.')
        return
    user_id = message.from_user.id
    profile = player_profiles.get(user_id)
    if not profile:
        bot.reply_to(message, '❌ Сначала создай профиль City Mafia, затем используй /gift.')
        return
    config = _gift_config_read()
    if not config.get('enabled') or not config.get('items'):
        bot.reply_to(message, '🎁 Сейчас подарок недоступен. Следи за новостями!')
        return
    now = int(time.time())
    with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
        row = conn.execute('SELECT claimed_at FROM gift_claims WHERE user_id=?', (user_id,)).fetchone()
        interval = max(0, int(config.get('interval_seconds', 86400)))
        if row and now - int(row[0]) < interval:
            remaining = interval - (now - int(row[0]))
            hours, rem = divmod(remaining, 3600); minutes = rem // 60
            bot.reply_to(message, f'⏳ Ты уже забирал подарок. Следующий можно получить через {hours} ч. {minutes} мин.')
            return
        items = config.get('items', {})
        for item, amount in items.items():
            if item == 'vip':
                days = int(amount)
                old = profile.get('vip_until')
                try:
                    current = datetime.strptime(old, '%Y-%m-%d %H:%M:%S') if old else datetime.now()
                    if current < datetime.now(): current = datetime.now()
                except Exception: current = datetime.now()
                profile['vip_until'] = (current + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
            else:
                profile[item] = int(profile.get(item, 0) or 0) + int(amount)
        conn.execute('INSERT INTO gift_claims(user_id, claimed_at) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET claimed_at=excluded.claimed_at', (user_id, now))
        conn.commit()
    labels = {'euro':'💶 Евро', 'coins':'🪙 Монеты', 'fake_docs':'📁 Документы', 'hanging_shield':'⚖️ Защита от повешения', 'gun':'🔫 Пистолет', 'shield':'⚔️ Защита', 'vip':'👑 VIP (дней)'}
    bot.reply_to(message, '🎁 Ты получил подарок!\n' + '\n'.join(f'{labels.get(k,k)}: {v}' for k,v in items.items()))


@bot.message_handler(commands=['gifte'])
def configure_gift_command(message):
    if message.from_user.id not in (ADMIN_ID, OWNER_ID):
        bot.reply_to(message, '❌ Эта команда доступна только владельцу бота.')
        return
    args = (message.text or '').replace(',', ' ').split()[1:]
    if args and args[-1].lower() == 'vip':
        args.append('7')
    if not args:
        bot.reply_to(message, 'Настройка подарка:\n/gifte euro 500 coins 10 vip 7 — задать награду (VIP указывается в днях)\n/gifte time 24h — период между получениями\n/gifte reset — сбросить время получения у всех\n/gifte off — отключить /gift\n/gifte on — включить /gift')
        return
    action = args[0].lower()
    config = _gift_config_read()
    if action == 'time':
        if len(args) < 2 or _parse_gift_duration(args[1]) is None:
            bot.reply_to(message, 'Укажи период, например: /gifte time 24h или /gifte time 7d'); return
        config['interval_seconds'] = _parse_gift_duration(args[1]); _gift_config_write(config)
        bot.reply_to(message, f'✅ Период получения подарка: {args[1]}.'); return
    if action == 'reset':
        with sqlite3.connect(PROFILE_DB_PATH, timeout=30) as conn:
            conn.execute('DELETE FROM gift_claims'); conn.commit()
        bot.reply_to(message, '✅ Время получения подарка сброшено у всех игроков.'); return
    if action == 'off':
        config['enabled'] = False; _gift_config_write(config); bot.reply_to(message, '✅ /gift отключена.'); return
    if action == 'on':
        if not config.get('items'):
            bot.reply_to(message, 'Сначала настрой награду: /gifte euro 500 coins 10 vip 7'); return
        config['enabled'] = True; _gift_config_write(config); bot.reply_to(message, '✅ /gift включена.'); return
    allowed = {'euro','coins','shield','fake_docs','hanging_shield','gun','vip'}
    if len(args) % 2:
        bot.reply_to(message, '❌ Нужно указывать пары «предмет количество». Пример: /gifte euro 500 coins 10 vip 7'); return
    items = {}
    for i in range(0, len(args), 2):
        item = args[i].lower()
        try: amount = int(args[i+1])
        except ValueError:
            bot.reply_to(message, f'❌ Количество для {item} должно быть целым числом.'); return
        if item not in allowed or amount <= 0:
            bot.reply_to(message, f'❌ Неизвестный предмет или неверное количество: {item} {amount}.'); return
        items[item] = amount
    config['items'] = items; config['enabled'] = True
    if 'interval_seconds' not in config: config['interval_seconds'] = 86400
    _gift_config_write(config)
    bot.reply_to(message, '✅ Подарок настроен и включён:\n' + '\n'.join(f'• {k}: {v}' for k,v in items.items()) +
                 f'\nПериод: {config["interval_seconds"]} сек.\nИгроки могут забрать его командой /gift в личке.')


@bot.message_handler(commands=['give'])
def give_menu_start(message):
    # В группе /give запускает публичный подарок без ответа на сообщение.
    # Админская выдача по ID сохраняется в личке.
    if message.chat.type in ('group', 'supergroup'):
        start_public_gift(message)
        return
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
    markup = types.InlineKeyboardMarkup()

    items = [("euro", get_text(chat_id, 'give_item_euro')), ("coins", get_text(chat_id, 'give_item_coins')), ("shield", get_text(chat_id, 'give_item_shield')), ("fake_docs", get_text(chat_id, 'give_item_fake_docs')), ("gun", get_text(chat_id, 'give_item_gun')), ("hanging_shield", get_text(chat_id, 'give_item_hanging_shield')), ("vip", get_text(chat_id, 'give_item_vip'))]

    for item, label in items:
        markup.add(types.InlineKeyboardButton(f"➕ {label}", callback_data=f"give_item_{item}"), types.InlineKeyboardButton(f"➖ {label}", callback_data=f"take_item_{item}"))

    markup.add(types.InlineKeyboardButton(get_text(chat_id, 'give_confirm'), callback_data="give_finish"))

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

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(get_text(chat_id, 'give_confirm'), callback_data="give_menu_confirm"), types.InlineKeyboardButton(get_text(chat_id, 'give_cancel'), callback_data="give_menu_cancel"))

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

    requester_id = message.from_user.id
    current_time = time.time()

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    # Ограничение отдельно для каждого пользователя, как и раньше.
    top_usage_key = (message.chat.id, requester_id)
    if top_usage_key in last_top_usage and current_time - last_top_usage[top_usage_key] < 15:
        return
    last_top_usage[top_usage_key] = current_time

    sorted_scores = get_chat_weekly_scores(message.chat.id, 15)
    if not sorted_scores:
        send_message(message.chat.id, get_text(message.chat.id, 'top_empty'), parse_mode="Markdown")
        return

    top_message = get_text(message.chat.id, 'top_title')
    for index, (player_id, score) in enumerate(sorted_scores, start=1):
        try:
            member = bot.get_chat_member(message.chat.id, player_id)
            user = member.user
            # Показываем имя и фамилию Telegram, если фамилия указана.
            player_name = f"{user.first_name} {user.last_name}" if user.last_name else (user.first_name or "Игрок")
            # Экранируем Markdown, чтобы символы в имени не ломали оформление.
            player_name = str(player_name).replace('\\', '\\\\').replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[')
        except Exception:
            player_name = f"Игрок {player_id}"
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
    bot.send_animation(chat_id, 'https://t.me/ProfileChaekBot/31699', caption=get_text(chat_id, 'night_start_caption'), parse_mode="Markdown", reply_markup=private_message_btn)
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
            "allow_registration": False,
            "allow_team_registration": False,
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
                main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'team_admin_start'), callback_data=f"menu_team_commands_{chat_id}"))
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


@bot.callback_query_handler(func=lambda call: call.data.startswith('teamjoin_'))
def team_join_game(call):
    parts = call.data.split('_')
    if len(parts) != 3:
        bot.answer_callback_query(call.id, text='Ошибка выбора команды.')
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        bot.answer_callback_query(call.id, text='Ошибка игры.')
        return

    team = parts[2]
    user_id = call.from_user.id
    chat = chat_list.get(chat_id)

    if team not in ('blue', 'yellow') or not chat or chat.game_running or not chat.button_id or not getattr(chat, 'team_mode', False):
        bot.answer_callback_query(call.id, text='Регистрация уже закрыта.')
        return

    # Команду можно выбрать только будучи участником именно этой группы.
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status not in ('creator', 'administrator', 'member'):
            bot.answer_callback_query(call.id, text='Сначала вступите в группу.')
            return
    except Exception:
        bot.answer_callback_query(call.id, text='Не удалось проверить участие в группе.')
        return

    if user_id in user_game_registration and user_game_registration[user_id] != chat_id:
        bot.answer_callback_query(call.id, text='Вы уже участвуете в другой игре.')
        return

    if user_id in chat.players:
        # Разрешаем поменять цвет до старта регистрации.
        chat.players[user_id]['team'] = team
        icon = '🔵' if team == 'blue' else '🟡'
        bot.answer_callback_query(call.id, text=f'Команда изменена: {icon}')
        schedule_update(chat_id, chat)
        return

    first_name = call.from_user.first_name or ''
    last_name = call.from_user.last_name or ''
    full_name = f'{first_name} {last_name}'.strip()
    add_player(chat, user_id, first_name, last_name, len(chat.players) + 1, team=team)
    user_game_registration[user_id] = chat_id

    icon = '🔵' if team == 'blue' else '🟡'
    bot.answer_callback_query(call.id, text=f'Вы выбрали {icon}')
    try:
        bot.send_message(user_id, f'🎨 Вы выбрали команду {icon}.')
    except Exception:
        pass

    schedule_update(chat_id, chat)
    players_needed = chat_settings.get(chat_id, {}).get('players_to_start', 20)
    if len(chat.players) >= players_needed and not chat.game_running and chat.button_id:
        _start_game(chat_id)


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
            add_player(chat, user_id, first_name, last_name, len(chat.players) + 1)
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
        voter_link = user_link(full_name, from_id)

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
                            send_message_to_mafia(chat, get_text(chat_id, 'mafia_vote_notification_don').format(name=escape_markdown_name(voter_name), id=from_id, victim=victim_name))
                            for player_id, player in chat.players.items():
                                if player['role'] == '👨🏼‍💼 Қорғаушы':
                                    send_message(player_id, get_text(chat_id, 'mafia_vote_notification_lawyer').format(victim=victim_name))
                        else:
                            send_message_to_mafia(chat, get_text(chat_id, 'mafia_vote_notification_mafia').format(name=escape_markdown_name(voter_name), id=from_id, victim=victim_name))
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

                        voter_name = user_link(get_full_name(chat.players[from_id]), from_id)
                        target_name = user_link(get_full_name(chat.players[target_id]), target_id)

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
                player_link = user_link(player_name, user_id)
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
    """Экранирует пользовательский текст для legacy Markdown тем же правилом, что и имена."""
    return escape_markdown_name(text)


bot.infinity_polling()
