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
from datetime import datetime
import concurrent.futures
from collections import defaultdict
import hashlib
from telebot.types import LabeledPrice
import zipfile
import io




notification_timers = {}


logging.basicConfig(level=logging.INFO)

bot = telebot.TeleBot("7605504614:AAG5jdSx_Mod9xeiw8LG9sPQf2D10eu5PzQ")
PAYMENT_PROVIDER_TOKEN = '5775769170:LIVE:TG_nf2yxA3F_086xA76SyiLao4A'  # Никому не показывать!

# Словарь со всеми чатами и игроками в этих чатах
chat_list = {}
game_tasks = {}
registration_timers = {}
game_start_timers = {}
user_game_registration = {}  # {user_id: game_chat_id}
# Словарь для хранения времени последнего нажатия кнопки каждым игроком
vote_timestamps = {}
next_players = {}
registration_lock = threading.Lock()
player_scores = {}  # Очки игроков
game_timers = {}  # Таймеры игр
update_timers = {} 
lock = threading.Lock()  # Блокировка, чтобы избежать одновременных вызовов
ALLOWED_CHAT_ID = [-1002145074948, -1002398622601, -1002279830772] # Замени на реальный ID чата
OFFICIAL_CHAT_LINK = "https://t.me/CityMafiaSupportBot"  # Замени на ссылку на официальный чат
ADMIN_ID = 6265990443
CHANNEL_ID = -1002598471111
SETTINGS_CHANNEL_ID = -1002687818190  # ID канала для настроек чатов
OWNER_ID = 6265990443
AD_CHANNEL_ID = -1002501442029  # ID вашего канала с рекламой
current_ad_message = None# ID канала с файлами
last_top_usage = {}  # Храним время последнего использования команды для каждого пользователя
player_profiles = {}
sent_messages = {}
chat_settings = {}
# Глобальные переменные для контроля голосования
confirm_vote_timestamps = {}  # Время последнего обновления голосования
sent_messages = {}  # Хранит message_id отправленных сообщений
message_times = []
message_limit = 35  # Лимит на 30 сообщений в секунду
interval = 1  # Интервал в 1 секунду
user_data = {}
broadcast_status = {
    'is_paused': False,
    'is_stopped': False
}

game_start_lock = threading.Lock()

# В коде, где проверяется условие:



class Game:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = {}
        self.dead_last_words = {}  # Инициализация словаря для последних слов убитых игроков
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
        self.hobo_id = None  # ID Бомжа
        self.hobo_target = None  # Цель Бомжа
        self.hobo_visitors = []  # Посетители цели Бомжа
        self.suicide_bomber_id = None  # ID Смертника
        self.suicide_hanged = False  # Переменная для отслеживания повешенного самоубийцы
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
        self.is_night = False  # Ночь только для этого чата
        self.is_voting_time = False  # Голосование только для этого чата

    def update_player_list(self):
        players_list = ", ".join([f"{player['name']} {player.get('last_name', '')}" for player in self.players.values()])
        return players_list

    def remove_player(chat, player_id, killed_by=None):
        if player_id in chat.players:
            dead_player = chat.players.pop(player_id)

        # Удаляем игрока из глобального списка регистрации
            if player_id in user_game_registration and user_game_registration[player_id] == chat.chat_id:
                del user_game_registration[player_id]

        # Получаем язык чата
            lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

        # Переводим роль
            role = translate_role(dead_player['role'], lang)

        # Формируем имя
            full_name = f"{dead_player['name']} {dead_player.get('last_name', '')}".strip()
            clickable_name = f"[{full_name}](tg://user?id={player_id})"

        # Добавляем в список мертвых
            chat.all_dead_players.append(f"{clickable_name} - {role}")

            if killed_by == 'night':
                try:
                    death_messages = {
                        'ru': "*Тебя убили ночью :(*\nТы можешь отправить своё последнее сообщение",
                        'kz': "*Сенi өлтірді :(*\nӨлім туралы хабарламаңды жібере аласың"
                    }
                    send_message(player_id, death_messages[lang], parse_mode='Markdown')
                    chat.dead_last_words[player_id] = full_name  # Сохраняем полное имя
                except Exception as e:
                    print(f"Не удалось отправить сообщение игроку {full_name}: {e}")

REQUIRED_CHANNEL = "@citymafianews"  # канал для подписки

# Глобальные переменные
gift_claims = {}
current_gifts = {}
gift_expire = None


# 🔒 Проверка подписки
def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False


# 🎁 Команда для игроков
@bot.message_handler(commands=['gift'])
def handle_gift_command(message):
    global current_gifts, gift_claims, gift_expire

    if message.chat.type != 'private':
        try:
        except:
            pass
        return

    user_id = message.from_user.id
    profile = get_or_create_profile(user_id, message.from_user.first_name)
    lang = profile.get('language', 'ru')

    # 🔒 Проверка подписки
    if not is_subscribed(user_id):
        texts = {
            'kz': f"❌ Сыйлық алу үшін {REQUIRED_CHANNEL} каналына жазылыңыз!",
            'ru': f"❌ Чтобы получить подарок, подпишитесь на канал {REQUIRED_CHANNEL}!"
        }
        bot.send_message(user_id, texts[lang])
        return

    # ⏳ Проверка срока действия подарков
    if gift_expire and datetime.now() > gift_expire:
        current_gifts = {}
        gift_claims = {}
        gift_expire = None
        return

    # Если подарки не установлены
    if not current_gifts:
        return

    # Проверка — уже получал подарок или нет
    if user_id in gift_claims:
        return

    # Выдаем подарки
    rewards = []
    for gift_type, gift_amount in current_gifts.items():
        if gift_type == 'vip':
            if profile.get('vip_until'):
                current_vip = datetime.strptime(profile['vip_until'], '%Y-%m-%d %H:%M:%S')
                new_vip_until = current_vip + timedelta(days=gift_amount)
            else:
                new_vip_until = datetime.now() + timedelta(days=gift_amount)
            profile['vip_until'] = new_vip_until.strftime('%Y-%m-%d %H:%M:%S')
            rewards.append(f"{gift_amount} күн 👑 VIP" if lang == 'kz' else f"{gift_amount} дней 👑 VIP")
        else:
            profile[gift_type] = profile.get(gift_type, 0) + gift_amount
            reward_texts = {
                'coins': {'kz': f"{gift_amount} 🪙", 'ru': f"{gift_amount} 🪙"},
                'euro': {'kz': f"{gift_amount} 💶", 'ru': f"{gift_amount} 💶"},
                'shield': {'kz': f"{gift_amount} ⚔️ Қорғаныс", 'ru': f"{gift_amount} ⚔️ Защита"},
                'fake_docs': {'kz': f"{gift_amount} 📁 Құжат", 'ru': f"{gift_amount} 📁 Документы"},
                'hanging_shield': {'kz': f"{gift_amount} ⚖️ Дарға қарсы қорғаныс", 'ru': f"{gift_amount} ⚖️ Защита от повешения"},
                'gun': {'kz': f"{gift_amount} 🔫 Тапанша", 'ru': f"{gift_amount} 🔫 Пистолет"}
            }
            rewards.append(reward_texts[gift_type][lang])

    gift_claims[user_id] = True
    update_profile(user_id, profile)

    if lang == 'kz':
        message_text = "🎁 Сізге сыйлықтар:\n" + "\n".join(f"• {r}" for r in rewards)
    else:
        message_text = "🎁 Вам подарки:\n" + "\n".join(f"• {r}" for r in rewards)

    bot.send_message(user_id, message_text)


# ⚙️ Установка подарков (админ)
@bot.message_handler(commands=['set_gift'])
def set_gift_command(message):
    global current_gifts, gift_claims, gift_expire

    if message.from_user.id != ADMIN_ID:
        return

    try:
        args = message.text.split()[1:]

        if not args or args[0] == 'help':
            help_text = """🎁 Установка подарков:
/set_gift coins 10 - 10 монет
/set_gift coins 10, euro 50 - несколько подарков
/set_gift coins 10, vip 3 2d - подарки действуют 2 дня

Срок можно указывать:
1h = 1 час
1d = 1 день
30m = 30 минут

Очистить:
/set_gift clear"""
            bot.reply_to(message, help_text)
            return

        if args[0] == 'clear':
            current_gifts = {}
            gift_claims = {}
            gift_expire = None
            bot.reply_to(message, "✅ Все подарки очищены!")
            return

        # Срок жизни
        duration = None
        if args[-1][-1] in ['h', 'd', 'm'] and args[-1][:-1].isdigit():
            unit = args[-1][-1]
            value = int(args[-1][:-1])
            if unit == 'h':
                duration = timedelta(hours=value)
            elif unit == 'd':
                duration = timedelta(days=value)
            elif unit == 'm':
                duration = timedelta(minutes=value)
            args = args[:-1]

        gifts = {}
        valid_types = {
            'coins': 'coins',
            'euro': 'euro',
            'shield': 'shield',
            'docs': 'fake_docs',
            'hanging': 'hanging_shield',
            'vip': 'vip',
            'gun': 'gun'
        }

        gift_args = ' '.join(args).split(',')
        for gift_arg in gift_args:
            gift_arg = gift_arg.strip()
            if not gift_arg:
                continue

            parts = gift_arg.split()
            if len(parts) < 2:
                bot.reply_to(message, f"❌ Неверный формат: {gift_arg}")
                return

            gift_type = parts[0].lower()
            try:
                gift_amount = int(parts[1])
            except ValueError:
                bot.reply_to(message, f"❌ Количество должно быть числом: {gift_arg}")
                return

            if gift_type not in valid_types:
                bot.reply_to(message, f"❌ Неверный тип подарка: {gift_type}")
                return

            gifts[valid_types[gift_type]] = gift_amount

        current_gifts = gifts
        gift_claims = {}
        gift_expire = datetime.now() + duration if duration else None

        expire_text = f"\n⏳ Действует до {gift_expire.strftime('%d.%m %H:%M')}" if gift_expire else ""
        bot.reply_to(message, f"✅ Подарки установлены: {gifts}{expire_text}")

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


# 👑 Проверка текущих подарков (только для админа)
@bot.message_handler(commands=['gift_info'])
def gift_info_command(message):
    global current_gifts, gift_claims, gift_expire

    if message.from_user.id != ADMIN_ID:
        return

    if not current_gifts:
        bot.reply_to(message, "❌ Подарки не установлены!")
        return

    gift_list = []
    type_names = {
        'coins': 'монет', 'euro': 'евро', 'shield': 'защит',
        'fake_docs': 'документов', 'hanging_shield': 'защит от повешения',
        'vip': 'дней VIP', 'gun': 'пистолетов'
    }

    for gift_type, amount in current_gifts.items():
        gift_list.append(f"{amount} {type_names[gift_type]}")

    expire_text = f"\n⏳ Действует до {gift_expire.strftime('%d.%m %H:%M')}" if gift_expire else ""
    bot.reply_to(message, f"🎁 Текущие подарки:\n{', '.join(gift_list)}\n\nПолучили уже: {len(gift_claims)} игроков{expire_text}")


def _start_game(chat_id):
    global notification_timers

    # Получаем текущий язык чата
    lang = chat_settings.get(chat_id, {}).get("language", "kz")

    # Проверка существования чата
    if chat_id not in chat_list:
        if lang == "kz":
            send_message(chat_id, 'Алдымен /game пәрменін пайдаланып ойын жасаңыз.')
        if lang == "ru":
            send_message(chat_id, 'Сначала создайте игру с помощью команды /game')
        return

    chat = chat_list[chat_id]
    
    # Проверка на уже запущенную игру
    if chat.game_running:
        return

    # Проверка минимального количества игроков
    if len(chat.players) < 4:
        if lang == "kz":
            send_message(chat_id, '*Ойынды бастау үшін адам жеткіліксіз...*', parse_mode="Markdown")
        if lang == "ru":
            send_message(chat_id, '*Недостаточно игроков для начала игры...*', parse_mode="Markdown")
        reset_registration(chat_id)
        return

    # Удаление сообщения о регистрации
    if chat.button_id:
        try:
            bot.delete_message(chat_id, chat.button_id)
            chat.button_id = None
        except Exception as e:
            logging.error(f"Ошибка при удалении сообщения: {e}")

    # Очистка таймеров
    if chat_id in notification_timers:
        for timer in notification_timers[chat_id].values():
            if isinstance(timer, threading.Timer):
                timer.cancel()
        del notification_timers[chat_id]

    if chat_id in game_start_timers:
        if isinstance(game_start_timers[chat_id], threading.Timer):
            game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]

    # Запуск игры
    chat.game_running = True
    chat.game_start_time = time.time()

    if lang == "kz":
        send_message(chat_id, '*Ойын басталды!*', parse_mode="Markdown")
    if lang == "ru":
        send_message(chat_id, '*Игра начинается!*', parse_mode="Markdown")

    # Распределение ролей
    players_list = list(chat.players.items())
    shuffle(players_list)
    num_players = len(players_list)
    
    # Получаем настройку пропорции мафии
    mafia_ratio = chat_settings.get(chat_id, {}).get("mafia_ratio", 4)
    num_mafias = max(1, num_players // mafia_ratio)
    mafia_assigned = 0

    # Присвоение номеров игрокам
    numbers = list(range(1, num_players + 1))
    shuffle(numbers)
    for i, (player_id, player_info) in enumerate(players_list):
        player_info['status'] = 'alive'
        player_info['number'] = numbers[i]

    # Назначение Дона (первый в списке)
    don_id = players_list[0][0]
    change_role(don_id, chat.players, '🧔🏻‍♂️ Дон', '', chat)
    chat.don_id = don_id
    mafia_assigned += 1

    # Назначение Мафии
    for i in range(1, num_players):
        if mafia_assigned < num_mafias:
            change_role(players_list[i][0], chat.players, '🤵🏻 Мафия', '', chat)
            mafia_assigned += 1

    roles_assigned = mafia_assigned

    # Назначение Доктора (при 4+ игроках)
    if roles_assigned < num_players and num_players >= 4:
        change_role(players_list[roles_assigned][0], chat.players, '👨🏼‍⚕️ Дәрігер', '', chat)
        roles_assigned += 1

    # Назначение Самоубийцы (при 30+ игроках)
    if roles_assigned < num_players and num_players >= 30:
        change_role(players_list[roles_assigned][0], chat.players, '🤦‍♂️ Самоубийца', '', chat)
        chat.suicide_bomber_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Бомжа (при 8+ игроках)
    if roles_assigned < num_players and num_players >= 8:
        change_role(players_list[roles_assigned][0], chat.players, '🧙‍♂️ Қаңғыбас', '', chat)
        chat.hobo_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Комиссара (при 6+ игроках)
    if roles_assigned < num_players and num_players >= 6:
        change_role(players_list[roles_assigned][0], chat.players, '🕵🏼 Комиссар', '', chat)
        chat.sheriff_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Счастливчика (при 7+ игроках)
    if roles_assigned < num_players and num_players >= 7:
        change_role(players_list[roles_assigned][0], chat.players, '🤞 Жолы болғыш', '', chat)
        chat.lucky_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Камикадзе (при 12+ игроках)
    if roles_assigned < num_players and num_players >= 12:
        change_role(players_list[roles_assigned][0], chat.players, '💣 Камикадзе', '', chat)
        chat.suicide_bomber_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Любовницы (при 10+ игроках)
    if roles_assigned < num_players and num_players >= 10:
        change_role(players_list[roles_assigned][0], chat.players, '💃🏼 Көңілдес', '', chat)
        chat.lover_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Адвоката (при 16+ игроках)
    if roles_assigned < num_players and num_players >= 16:
        change_role(players_list[roles_assigned][0], chat.players, '👨🏼‍💼 Қорғаушы', '', chat)
        roles_assigned += 1

    # Назначение Сержанта (при 12+ игроках)
    if roles_assigned < num_players and num_players >= 12:
        change_role(players_list[roles_assigned][0], chat.players, '👮🏼 Сержант', '', chat)
        chat.sergeant_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Маньяка (при 14+ игроках)
    if roles_assigned < num_players and num_players >= 14:
        change_role(players_list[roles_assigned][0], chat.players, '🔪 Жауыз', '', chat)
        chat.maniac_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Остальные игроки - мирные жители
    for i in range(roles_assigned, num_players):
        change_role(players_list[i][0], chat.players, '👨🏼 Тату тұрғын', '', chat)

    # Проверка, чтобы никто не остался без роли
    for player_id, player_info in chat.players.items():
        if player_info['role'] == 'ждет':
            change_role(player_id, chat.players, '👨🏼 Тату тұрғын', '', chat)

    # Запуск игрового цикла
    thread = threading.Thread(target=lambda: asyncio.run(game_cycle(chat_id)))
    thread.start()


def change_role(player_id, player_dict, new_role, text, game):
    player_dict[player_id]['role'] = new_role
    player_dict[player_id]['action_taken'] = False
    player_dict[player_id]['skipped_actions'] = 0

    chat_id = game.chat_id  # ИЛИ другой способ получения chat_id, в зависимости от структуры вашего класса Game
    
    # Получаем язык из настроек чата
    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    
    # Получаем язык из настроек чата
    # Тексты для всех ролей
    role_texts = {
        '🧔🏻‍♂️ Дон': {
            "kz": "Сен - 🧔🏻‍♂️ Донсың!\n\n(Мафияның басшысы!)Бұл түні кімнің мәңгі ұйқыға кететінін шешесің...",
            "ru": "Вы - 🧔🏻‍♂️ Дон!\n\nГлава мафии! Вы решаете, кто отправится в вечный сон этой ночью..."
        },
        '🤵🏻 Мафия': {
            "kz": "Сіз — 🤵🏻 Мафия!\n\nМіндетіңіз - Донға бағыну және сізге қарсы шыққандарды өлтіру. Бір күні сіз де Дон болуыңыз мүмкін...",
            "ru": "Вы — 🤵🏻 Мафия!\n\nВаша задача - подчиняться Дону и устранять противников. Однажды вы тоже можете стать Доном..."
        },
        '👨🏼‍⚕️ Дәрігер': {
            "kz": "Сіз — 👨🏼‍⚕️ Дәрігер!\n\nТүнде кімді құтқаратыныңызды сіз шешесіз…",
            "ru": "Вы — 👨🏼‍⚕️ Доктор!\n\nВы решаете, кого спасти этой ночью…"
        },
        '🤦‍♂️ Самоубийца': {
            "kz": "Сіз — 🤦‍♂️ Самоубийца!\n\nСіздің міндетіңіз - қалалық жиналыста дарға асылу!",
            "ru": "Вы — 🤦‍♂️ Самоубийца!\n\nВаша задача - быть повешенным на городском собрании!"
        },
        '🧙‍♂️ Қаңғыбас': {
            "kz": "Сіз — 🧙‍♂️ Қаңғыбас!\n\nКез келген адамға бір шыны үшін жолығып, кісі өлтіру куәгері бола аласыз.",
            "ru": "Вы — 🧙‍♂️ Бомж!\n\nМожете стать свидетелем убийства, встретив любого человека за бутылку."
        },
        '🕵🏼 Комиссар': {
            "kz": "Сіз — 🕵🏼 Комиссар!\n\nҚаланың қорғаушысы мен мафияның басты қорқынышы...",
            "ru": "Вы — 🕵🏼 Комиссар!\n\nЗащитник города и главная угроза для мафии..."
        },
        '🤞 Жолы болғыш': {
            "kz": "Сіз — 🤞 Жолы болғыш!\n\nМіндетіңіз — қалалық жиналыста бұзақыларды дарға асу.",
            "ru": "Вы — 🤞 Счастливчик!\n\nВаша задача - выявлять преступников на городском собрании."
        },
        '💣 Камикадзе': {
            "kz": "Сіз — 💣 Камикадзе!\n\nЕгер олар сізді асып тастауға тырысса, ойыншылардың қайсысын өзіңізбен бірге қабірге апаратыныңызды таңдай аласыз.",
            "ru": "Вы — 💣 Камикадзе!\n\nЕсли вас попытаются повесить, вы можете выбрать, кого взять с собой в могилу."
        },
        '💃🏼 Көңілдес': {
            "kz": "Сіз — 💃🏼 Көңілдес!\n\nҚалаған ойыншыны бір күнге ұйықтату үшін дағдыларыңызды пайдаланыңыз.",
            "ru": "Вы — 💃🏼 Любовница!\n\nИспользуйте свои навыки, чтобы усыпить любого игрока на день."
        },
        '👨🏼‍💼 Қорғаушы': {
            "kz": "Сіз — 👨🏼‍💼 Қорғаушы!\n\nТүнде кімді қорғайтыныңызды шешесіз.",
            "ru": "Вы — 👨🏼‍💼 Адвокат!\n\nВы решаете, кого защищать этой ночью."
        },
        '👮🏼 Сержант': {
            "kz": "Сіз — 👮🏼 Сержант!\n\nКомиссардың көмекшісісіз.",
            "ru": "Вы — 👮🏼 Сержант!\n\nВы помощник Комиссара."
        },
        '🔪 Жауыз': {
            "kz": "Сіз — 🔪 Жауыз!\n\nҚалада ешкім тірі қалмауы керек. Әлбетте, сізден басқасы :)",
            "ru": "Вы — 🔪 Маньяк!\n\nВ городе не должно остаться никого в живых. Кроме вас, конечно :)"
        },
        '👨🏼 Тату тұрғын': {
            "kz": "Сіз — 👨🏼 Тату тұрғын!\n\nСіздің басты міндетіңіз — мафияны тауып, қалалық жиналыста оңбағандарды дарға асу.",
            "ru": "Вы — 👨🏼 Мирный житель!\n\nВаша главная задача - выявлять мафию и вешать преступников на городском собрании."
        }
    }

    # Если текст не передан, используем стандартный для роли
    if not text and new_role in role_texts:
        text = role_texts[new_role].get(lang, role_texts[new_role]["kz"])

    full_name = f"{player_dict[player_id]['name']} {player_dict[player_id].get('last_name', '')}"
    
    try:
        send_message(player_id, text, protect_content=True)
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение игроку {full_name}: {e}")
        
    # Установка специальных флагов для особых ролей
    if new_role == '🧔🏻‍♂️ Дон':
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
        # Логируем текущую роль каждого игрока
        logging.info(f"Текущая роль игрока: {val['role']} (ID: {key})")
        logging.info(f"Обработка игрока: {val['name']} (ID: {key}) - Роль: {val['role']}")

        # Условие для доктора, чтобы не лечить себя дважды
        if player_role == 'доктор' and key == user_id:
            logging.info(f"Доктор {val['name']} - self_healed: {val.get('self_healed', False)}")
            if val.get('self_healed', False):
                logging.info(f"Доктор {val['name']} уже лечил себя, не добавляем в список.")
                continue
            else:
                logging.info(f"Доктор {val['name']} еще не лечил себя, добавляем в список.")
                players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_{action_type}'))
                continue

        # Условие для адвоката, чтобы он не выбирал мертвых игроков и самого себя
        if player_role == '👨🏼‍💼 Қорғаушы' and (key == user_id or val['role'] == 'dead'):
            logging.info(f"Адвокат не может выбрать мертвого игрока или самого себя.")
            continue

        # Убираем мафию и дона из списка для мафии и дона
        if player_role in ['мафия', 'don']:
            logging.info(f"Текущая роль {player_role}, проверяем игрока {val['name']} с ролью {val['role']}")
            if val['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон']:
                logging.info(f"Игрок {val['name']} (Мафия или Дон) исключен из списка выбора.")
                continue  # Пропускаем союзников

        # Добавление остальных игроков в список
        if key != user_id and val['role'] != 'dead':
            players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_{action_type}'))

    logging.info(f"Редактирование сообщения с кнопками для {player_role}.")

    if message_id:
        try:
            bot.edit_message_text(chat_id=user_id, message_id=message_id, text=text, reply_markup=players_btn)
        except Exception as e:
            logging.error(f"Ошибка при редактировании сообщения: {e}")
    else:
        try:
            msg = send_message(user_id, text, reply_markup=players_btn)
            logging.info(f"Сообщение с кнопками отправлено, message_id: {msg.message_id}")
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

        if lang == 'kz':
            return f"*Ойыншы жинап жатырмыз*\n{player_list}\n_{len(player_names)} адам қосылды_"
        else:
            return f"*Ведётся набор игроков*\n{player_list}\n_{len(player_names)} человек присоединилось_"
    else:
        return (
            "*Ойыншы жинап жатырмыз*\n_Әзірге ешкім жоқ_"
            if lang == 'kz'
            else "*Ведётся набор игроков*\n_Зарегистрированных нет_"
        )


# Формирование сообщения с живыми игроками
# ID игрока, которому всегда добавляется ♠️
special_player_id = 6265990443

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def night_message(players, chat_id):
    # Получаем язык чата из настроек
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
    
    # Тексты на разных языках
    texts = {
        'kz': {
            'title': "*Тірі ойыншылар:*",
            'time_left': f"_Ұйықтауға {night_time} секунд қалды._"
        },
        'ru': {
            'title': "*Живые игроки:*",
            'time_left': f"_До сна осталось {night_time} секунд._"
        }
    }
    
    return f"{texts[lang]['title']}\n{player_list}\n\n{texts[lang]['time_left']}\n"

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
    mafia_roles = ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы']
    maniac_roles = ['🔪 Жауыз', '🤦‍♂️ Самоубийца']

    role_counts = {}
    for role in roles:
        role_counts[role] = role_counts.get(role, 0) + 1

    result_lines = []

    peaceful_list = []
    for role in peaceful_roles:
        if role in role_counts:
            translated = translate_role(role, lang)
            count = role_counts[role]
            peaceful_list.append(f"{translated} ({count})" if count > 1 else translated)
    peaceful_count = sum(role_counts.get(role, 0) for role in peaceful_roles)
    if peaceful_list:
        result_lines.append(f"👨🏼 {peaceful_count}: {', '.join(peaceful_list)}")

    mafia_list = []
    for role in mafia_roles:
        if role in role_counts:
            translated = translate_role(role, lang)
            count = role_counts[role]
            mafia_list.append(f"{translated} ({count})" if count > 1 else translated)
    mafia_count = sum(role_counts.get(role, 0) for role in mafia_roles)
    if mafia_list:
        result_lines.append(f"🤵🏻 {mafia_count}: {', '.join(mafia_list)}")

    maniac_list = []
    for role in maniac_roles:
        if role in role_counts:
            translated = translate_role(role, lang)
            count = role_counts[role]
            maniac_list.append(f"{translated} ({count})" if count > 1 else translated)
    maniac_count = sum(role_counts.get(role, 0) for role in maniac_roles)
    if maniac_list:
        result_lines.append(f"👺 {maniac_count}: {', '.join(maniac_list)}")

    texts = {
        'kz': {
            'title': "*Тірі ойыншылар:*",
            'some_of_them': "*Оның кейбіреуі:*",
            'total': "👥 Барлығы: *{}*",
            'discussion': "Түнде не болғанын талқылап, тергейтін уақыт келді..."
        },
        'ru': {
            'title': "*Живые игроки:*",
            'some_of_them': "*Среди них:*",
            'total': "👥 Всего: *{}*",
            'discussion': "Пришло время обсудить события ночи и провести расследование..."
        }
    }

    return (f"{texts[lang]['title']}\n{player_list}\n\n"
            f"{texts[lang]['some_of_them']}\n" + '\n'.join(result_lines) +
            f"\n\n{texts[lang]['total'].format(len(living_players))}\n\n"
            f"{texts[lang]['discussion']}")

def check_vip_expiry(profile):
    # Проверка истечения срока действия VIP
    if profile.get('vip_until'):
        try:
            vip_expiry = datetime.strptime(profile['vip_until'], '%Y-%m-%d %H:%M:%S')
            logging.debug(f"Проверка VIP для {profile.get('name', 'Неизвестный')} - срок действия до: {vip_expiry}")

            if datetime.now() > vip_expiry:
                profile['vip_until'] = ''  # Деактивация VIP
                logging.info(f"VIP-статус истек для {profile.get('name', 'Неизвестный')} (ID: {profile.get('id')})")
            else:
                logging.debug(f"VIP-статус еще активен для {profile.get('name', 'Неизвестный')}")
        except ValueError as e:
            logging.error(f"Ошибка при разборе даты VIP для {profile.get('name', 'Неизвестный')}: {e}")
    else:
        logging.debug(f"У {profile.get('name', 'Неизвестный')} нет активного VIP-статуса.")
    
def players_alive(player_dict, phase, chat_id):
    if phase == "registration":
        return registration_message(player_dict, chat_id)
    elif phase == "night":
        return night_message(player_dict, chat_id)  # Добавляем chat_id
    elif phase == "day":
        return day_message(player_dict, chat_id)  # Добавляем chat_id

def emoji(role):
    emojis = {
        'мафия': '🤵🏻',
        'Комиссар ': '🕵🏼️‍♂️',
        'мирный житель': '👨🏼',
        'Дәрігер': '👨🏼‍⚕️'
    }
    return emojis.get(role, '')


# Укажи свой Telegram ID здесь (можно узнать через @userinfobot)
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

# !бан
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
        if until_date:
            bot.reply_to(message, f"Готово! :)")
        else:
            bot.reply_to(message, "Готово! :)")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

# !молчи и !молчать
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
        bot.restrict_chat_member(chat_id=chat_id, user_id=user_to_mute,
                                 permissions=permissions, until_date=until_date)
        bot.reply_to(message, f"Готово! :)")
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
        return msg  # <-- Возвращаем объект сообщения
    except Exception as e:
        print(f"Ошибка при отправке сообщения: {e}")
        return None  # <-- В случае ошибки вернёт None

def voice_handler(chat_id):
    global chat_list
    chat = chat_list[chat_id]
    players = chat.players
    votes = []
    for player_id, player in players.items():
        if 'voice' in player:
            votes.append(player['voice'])
            del player['voice']
    if votes:
        dead_id = max(set(votes), key=votes.count)
        dead = players.pop(dead_id)
        return dead

def send_message_to_mafia(chat, message):
    for player_id, player in chat.players.items():
        if player['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон']:
            full_name = f"{player['name']} {player.get('last_name', '')}"
            try:
                send_message(player_id, message, parse_mode='Markdown', protect_content=True)  # Добавлено
            except Exception as e:
                print(f"Не удалось отправить сообщение игроку {full_name}: {e}")

def notify_mafia(chat, sender_name, sender_last_name, message, sender_id):
    sender_full_name = f"{sender_name} {sender_last_name}"
    for player_id, player in chat.players.items():
        if player['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон'] and player_id != sender_id:
            # Формируем префикс с эмодзи и ролью
            if chat.players[sender_id]['role'] == '🧔🏻‍♂️ Дон':
                prefix = f"🧔🏻‍♂️ Дон {sender_full_name}:"
            else:
                prefix = f"🤵🏻 Мафия {sender_full_name}:"

            try:
                send_message(
                    player_id, 
                    f"*{prefix}*\n{message}", 
                    parse_mode='Markdown', 
                    protect_content=True
                )
            except Exception as e:
                print(f"Не удалось отправить сообщение мафии {player.get('name')} {player.get('last_name', '')}: {e}")
        elif player['role'] == '👨🏼‍💼 Қорғаушы':
            # Пропускаем отправку адвокату, как обсуждали ранее
            pass
                
def notify_at_59_seconds(chat_id):
    """Уведомление за 59 секунд до окончания регистрации."""
    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if not chat.game_running and chat.button_id:
            lang = chat_settings.get(chat_id, {}).get("language", "kz")

            texts = {
                "kz": {
                    "join": "🤵🏻 Қосылу",
                    "msg": "⏰ Тіркелудің бітуіне *59 сек* қалды"
                },
                "ru": {
                    "join": "🤵🏻 Присоединиться",
                    "msg": "⏰ До конца регистрации осталось *59 сек*"
                }
            }

            t = texts.get(lang, texts["kz"])

            join_btn = types.InlineKeyboardMarkup()
            bot_username = bot.get_me().username
            join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
            join_btn.add(types.InlineKeyboardButton(t["join"], url=join_url))

            send_message(chat_id, t["msg"], reply_markup=join_btn)


def notify_at_29_seconds(chat_id):
    """Уведомление за 29 секунд до окончания регистрации."""
    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if not chat.game_running and chat.button_id:
            lang = chat_settings.get(chat_id, {}).get("language", "kz")

            texts = {
                "kz": {
                    "join": "🤵🏻 Қосылу",
                    "msg": "⏰ Тіркелудің бітуіне *29 сек* қалды"
                },
                "ru": {
                    "join": "🤵🏻 Присоединиться",
                    "msg": "⏰ До конца регистрации осталось *29 сек*"
                }
            }

            t = texts.get(lang, texts["kz"])

            join_btn = types.InlineKeyboardMarkup()
            bot_username = bot.get_me().username
            join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
            join_btn.add(types.InlineKeyboardButton(t["join"], url=join_url))

            send_message(chat_id, t["msg"], reply_markup=join_btn)

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
        return  # Если чат не найден, выходим

    chat = chat_list[chat_id]

    # Проверяем, что регистрация не была отменена
    if not chat.button_id:
        return  # Если кнопка регистрации удалена, не запускаем игру

    # Проверяем, что игра не началась
    if chat.game_running:
        return  # Если игра уже началась, ничего не делаем

    # Проверяем, был ли отменён таймер
    if chat_id not in game_start_timers:
        return  # Если таймер старта был удалён, не начинаем игру

    # Отменяем все таймеры уведомлений
    if chat_id in notification_timers:
        timers = notification_timers[chat_id]
        if isinstance(timers, threading.Timer):
            timers.cancel()
        elif isinstance(timers, dict):
            for key, timer in timers.items():
                if isinstance(timer, threading.Timer):
                    timer.cancel()
        del notification_timers[chat_id]  # Удаляем запись

    # Удаляем таймер старта игры
    if chat_id in game_start_timers:
        game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]

    # Запускаем игру только если кнопка регистрации ещё существует
    if chat.button_id:
        _start_game(chat_id)
    
def reset_registration(chat_id):
    global notification_timers, game_start_timers
    chat = chat_list.get(chat_id)

    # Удаляем текущее сообщение о регистрации
    if chat and chat.button_id:
        try:
            bot.delete_message(chat_id, chat.button_id)
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Ошибка при удалении сообщения с кнопкой: {e}")
        chat.button_id = None

    # Очищаем список игроков и сбрасываем их регистрацию
    if chat:
        for user_id in list(chat.players.keys()):
            if user_id in user_game_registration and user_game_registration[user_id] == chat_id:
                del user_game_registration[user_id]

        chat.players.clear()
        chat.game_running = False

    # Отменяем все таймеры уведомлений, если они есть
    if chat_id in notification_timers:
        for key, timer in notification_timers[chat_id].items():  # Перебираем таймеры
            if isinstance(timer, threading.Timer):  # Проверяем, что это таймер
                timer.cancel()  # Отменяем каждый
        del notification_timers[chat_id]  # Удаляем из словаря

    # Отменяем все таймеры старта игры, если они есть
    if chat_id in game_start_timers:
        for timer in game_start_timers[chat_id]:  # Возможно, тут тоже должен быть перебор по ключам
            if isinstance(timer, threading.Timer):  # Проверяем, что это таймер
                timer.cancel()
        del game_start_timers[chat_id]

def add_player(chat, user_id, user_name, last_name, player_number):
    # Создаем профиль игрока при присоединении
    get_or_create_profile(user_id, user_name, last_name)  # Передаем фамилию
    
    chat.players[user_id] = {
        'name': user_name, 
        'last_name': last_name,  # Сохраняем фамилию
        'role': 'ждет', 
        'skipped_actions': 0, 
        'status': 'alive', 
        'number': player_number
    }

def notify_mafia_and_don(chat):
    # Получаем язык из настроек чата (по умолчанию казахский)
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    
    mafia_and_don_list = []
    players_copy = list(chat.players.items())

    for player_id, player in players_copy:
        if player['role'] == '🧔🏻‍♂️ Дон':
            mafia_and_don_list.append(f"[{player['name']}](tg://user?id={player_id}) - 🧔🏻‍♂️ *Дон*")
        elif player['role'] == '🤵🏻 Мафия':
            mafia_and_don_list.append(f"[{player['name']}](tg://user?id={player_id}) - 🤵🏻 *Мафия*")

    # Тексты на разных языках
    messages = {
        'kz': "*Өз жақтастарыңды біле жүр*:\n",
        'ru': "*Знай своих союзников*:\n"
    }
    
    message = messages[lang] + "\n".join(mafia_and_don_list)

    for player_id, player in players_copy:
        if player['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон']:
            try:
                send_message(player_id, message, parse_mode='Markdown', protect_content=True)
            except Exception as e:
                print(f"Не удалось отправить сообщение игроку {player['name']} ({player_id}): {e}")

def confirm_vote(chat_id, player_id, player_name, player_last_name, confirm_votes, player_list):
    lang = chat_settings.get(chat_id, {}).get("language", "kz")

    texts = {
        "kz": {
            "confirm_msg": "Расымен де {name} дегенді жазалағыңыз келе ме ?",
            "yes": "👍🏼 {count}",
            "no": "👎🏼 {count}"
        },
        "ru": {
            "confirm_msg": "Вы действительно хотите казнить {name}?",
            "yes": "👍🏼 {count}",
            "no": "👎🏼 {count}"
        }
    }

    t = texts.get(lang, texts["kz"])
    full_name = f"{player_name} {player_last_name}"
    full_name_link = f"[{full_name}](tg://user?id={player_id})"

    if player_id in sent_messages:
        logging.info(f"Сообщение подтверждения для {full_name} уже отправлено.")
        return sent_messages[player_id], t["confirm_msg"].format(name=full_name)

    confirm_markup = types.InlineKeyboardMarkup(row_width=2)
    confirm_markup.add(
        types.InlineKeyboardButton(t["yes"].format(count=confirm_votes['yes']), callback_data=f"confirm_{player_id}_yes"),
        types.InlineKeyboardButton(t["no"].format(count=confirm_votes['no']), callback_data=f"confirm_{player_id}_no")
    )

    msg = send_message(
        chat_id,
        t["confirm_msg"].format(name=full_name_link),
        reply_markup=confirm_markup,
        parse_mode="Markdown"
    )

    logging.info(f"Сообщение подтверждения голосования отправлено с message_id: {msg.message_id}")
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

    return msg.message_id, t["confirm_msg"].format(name=full_name_link)

def end_day_voting(chat):
    try:
        lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

        def send_vote_end_message():
            if lang == 'kz':
                send_message(chat.chat_id, "*Дауыс беру аяқталды*\nХалық келісе алмады... Ешкімді аспай, бәрі үйлеріне қайтты...", parse_mode="Markdown")
            if lang == 'ru':
                send_message(chat.chat_id, "*Голосование завершено*\nНарод не смог договориться... Никто не был повешен, все разошлись по домам.", parse_mode="Markdown")

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

                msg_id, msg_text = confirm_vote(
                    chat.chat_id, player_id, player_name, player_last_name, chat.confirm_votes, chat.players
                )

                if msg_id and msg_text:
                    chat.vote_message_id = msg_id
                    chat.vote_message_text = msg_text
                    return True
                else:
                    logging.warning("Не удалось отправить сообщение подтверждения.")
                    reset_voting(chat)
                    for player in chat.players.values():
                        player['voting_blocked'] = False
                    return False
            else:
                logging.error(f"Игрок с id {player_id} не найден в chat.players")
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

    # Обрабатываем только если идет подтверждающее голосование
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
                chat.remove_player(dead_id)
                if dead['role'] == '🧔🏻‍♂️ Дон':
                    check_and_transfer_don_role(chat)
                if dead['role'] == '🕵🏼 Комиссар':
                    check_and_transfer_sheriff_role(chat)
        else:
            logging.error(f"Игрок с id {dead_id} не найден в chat.players")
    else:
        disable_vote_buttons(chat)
        send_voting_results(chat, yes_votes, no_votes)

    # Удаляем сообщение подтверждения если оно есть
    if hasattr(chat, 'confirm_message_id') and chat.confirm_message_id:
        try:
            bot.delete_message(chat_id=chat.chat_id, message_id=chat.confirm_message_id)
        except Exception as e:
            logging.error(f"Ошибка при удалении сообщения подтверждения: {e}")

    # Деактивируем голосование и сбрасываем данные
    chat.confirm_votes_active = False
    chat.confirm_message_id = None
    reset_voting(chat)

def disable_vote_buttons(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    texts = {
        "kz": {
            "voting_ended": "_Дауыс беру аяқталды_"
        },
        "ru": {
            "voting_ended": "_Голосование завершено_"
        }
    }

    t = texts.get(lang, texts["kz"])

    try:
        if chat.vote_message_id:
            logging.info(f"Попытка удаления кнопок голосования с message_id: {chat.vote_message_id}")
            
            updated_text = f"{chat.vote_message_text}\n\n{t['voting_ended']}"
            bot.edit_message_text(
                chat_id=chat.chat_id,
                message_id=chat.vote_message_id,
                text=updated_text,
                parse_mode="Markdown"
            )
            bot.edit_message_reply_markup(
                chat_id=chat.chat_id,
                message_id=chat.vote_message_id,
                reply_markup=None
            )
        else:
            logging.error("vote_message_id не установлен.")
    except Exception as e:
        logging.error(f"Не удалось заблокировать кнопки для голосования: {e}")


def send_voting_results(chat, yes_votes, no_votes, player_name=None, player_last_name=None, player_role=None):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    
    # Словарь переводов ролей
    role_translations = {
        'ru': {
            '🧔🏻‍♂️ Дон': '🧔🏻‍♂️ Дон',
            '🤵🏻 Мафия': '🤵🏻 Мафия',
            '👨🏼‍⚕️ Дәрігер': '👨🏼‍⚕️ Доктор',
            '🕵🏼 Комиссар': '🕵🏼 Комиссар',
            '👨🏼 Тату тұрғын': '👨🏼 Мирный житель',
            '🧙‍♂️ Қаңғыбас': '🧙‍♂️ Бомж',
            '🤞 Жолы болғыш': '🤞 Счастливчик',
            '💣 Камикадзе': '💣 Камикадзе',
            '💃🏼 Көңілдес': '💃🏼 Любовница',
            '👨🏼‍💼 Қорғаушы': '👨🏼‍💼 Адвокат',
            '👮🏼 Сержант': '👮🏼 Сержант',
            '🔪 Жауыз': '🔪 Маньяк',
            '🤦‍♂️ Самоубийца': 'Самоубийца'
        },
        'kz': {
            '🧔🏻‍♂️ Дон': '🧔🏻‍♂️ Дон',
            '🤵🏻 Мафия': '🤵🏻 Мафия',
            '👨🏼‍⚕️ Дәрігер': '👨🏼‍⚕️ Дәрігер',
            '🕵🏼 Комиссар': '🕵🏼 Комиссар',
            '👨🏼 Тату тұрғын': '👨🏼 Тату тұрғын',
            '🧙‍♂️ Қаңғыбас': '🧙‍♂️ Қаңғыбас',
            '🤞 Жолы болғыш': '🤞 Жолы болғыш',
            '💣 Камикадзе': '💣 Камикадзе',
            '💃🏼 Көңілдес': '💃🏼 Көңілдес',
            '👨🏼‍💼 Қорғаушы': '👨🏼‍💼 Қорғаушы',
            '👮🏼 Сержант': '👮🏼 Сержант',
            '🔪 Жауыз': '🔪 Жауыз',
            '🤦‍♂️ Самоубийца': 'Өз-өзіне қол жұмсаушы'
        }
    }

    player_id = chat.confirm_votes.get('player_id')
    if not player_id:
        print("ОШИБКА: player_id отсутствует в confirm_votes:", chat.confirm_votes)
        return False

    profile = player_profiles.get(player_id)
    full_name = f"{player_name} {player_last_name}"
    player_link = f"[{full_name}](tg://user?id={player_id})"

    # Тексты сообщений — теперь player_link уже определена
    texts = {
        "kz": {
            "result": "*Дауыс беру нәтижесі:*",
            "saved": f"⚖️ Алайда {player_link} өзін дарға асудан сақтап қалды!",
            "saved_private": "*Сені дарға асқалы жатқанда, Дарға қарсы қорғаныс құтқарып қалды! 🛡️*",
            "executed": f"_Бүгін_ {player_link} _дегенді дарға астық_\nОл *{role_translations[lang].get(player_role, player_role)}* болды..",
            "executed_private": "*Күндізгі жиналыста сені бір сөзден дарға асты :(*",
            "nobody": "Халық келісе алмады...\nЕшкімді аспай,\nбәрі үйлеріне қайтты..."
        },
        "ru": {
            "result": "*Результаты голосования:*",
            "saved": f"⚖️ Однако {player_link} спасся от повешения!",
            "saved_private": "*Когда тебя собирались повесить, Щит от повешения спас тебя! 🛡️*",
            "executed": f"_Сегодня_ {player_link} _был повешен_\nОн был *{role_translations[lang].get(player_role, player_role)}*.",
            "executed_private": "*На дневном собрании тебя повесили без единого сомнения :(*",
            "nobody": "Народ не смог прийти к согласию...\nНикто не был повешен,\nвсе разошлись по домам..."
        }
    }

    t = texts.get(lang, texts["kz"])

    if yes_votes > no_votes:
        if profile and profile.get('hanging_shield', 0) > 0 and not profile.get('hanging_shield_used', False) and profile.get('hanging_shield_active', False):
            profile['hanging_shield'] -= 1
            profile['hanging_shield_used'] = True

            result_text = f"{t['result']}\n👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n{t['saved']}"
            try:
                send_message(chat.chat_id, result_text, parse_mode="Markdown")
                send_message(player_id, t['saved_private'], parse_mode="Markdown")
            except Exception as e:
                print(f"Не удалось отправить сообщение: {e}")
            return True
        else:
            result_text = f"{t['result']}\n👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n{t['executed']}"
            try:
                send_message(chat.chat_id, result_text, parse_mode="Markdown")
                send_message(player_id, t['executed_private'], parse_mode="Markdown")
            except Exception as e:
                print(f"Не удалось отправить сообщение: {e}")
    else:
        result_text = f"{t['result']}\n👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n{t['nobody']}"
        try:
            send_message(chat.chat_id, result_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Не удалось отправить сообщение в чат {chat.chat_id}: {e}")

    return False


def send_sheriff_menu(chat, sheriff_id, callback_query=None, message_id=None):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    texts = {
        "kz": {
            "not_night": "Бұл әрекеттер тек түнде ғана қолжетімді.",
            "choose": "Осы түні не істейтініңді таңда",
            "check": "🔍 Тескеру",
            "shoot": "🔫 Ату"
        },
        "ru": {
            "not_night": "Действия доступны только ночью.",
            "choose": "Выбери, что делать этой ночью",
            "check": "🔍 Проверить",
            "shoot": "🔫 Выстрелить"
        }
    }

    t = texts.get(lang, texts["kz"])

    if not chat.is_night:
        if callback_query:
            try:
                bot.answer_callback_query(callback_query.id, t["not_night"], show_alert=True)
            except Exception as e:
                print(f"Не удалось отправить уведомление: {e}")
        return

    sheriff_menu = types.InlineKeyboardMarkup()
    sheriff_menu.add(types.InlineKeyboardButton(t['check'], callback_data=f'{sheriff_id}_check'))
    sheriff_menu.add(types.InlineKeyboardButton(t['shoot'], callback_data=f'{sheriff_id}_shoot'))

    new_text = t["choose"]

    try:
        if message_id:
            bot.edit_message_text(chat_id=sheriff_id, message_id=message_id, text=new_text, reply_markup=sheriff_menu)
        else:
            msg = send_message(sheriff_id, new_text, reply_markup=sheriff_menu)
            chat.last_sheriff_menu_id = msg.message_id
    except Exception as e:
        print(f"Не удалось отправить или отредактировать сообщение для {sheriff_id}: {e}")

def reset_voting(chat):
    # Очищаем все переменные, связанные с голосованием
    chat.vote_counts.clear()
    chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
    chat.vote_message_id = None
    chat.vote_counts['skip'] = 0
    # Сбрасываем флаг голосования у каждого игрока
    for player in chat.players.values():
        player['has_voted'] = False

    # Сбрасываем отправленные сообщения
    sent_messages.clear()  # Очищаем словарь sent_messages

def handle_night_action(callback_query, chat, player_role):
    player_id = callback_query.from_user.id
    player = chat.players.get(player_id)

    if not chat.is_night:
        bot.answer_callback_query(callback_query.id, text="⛔️")
        return False
    
    # Проверка, совершил ли Комиссар уже проверку или стрельбу
    if player_role == '🕵🏼 Комиссар' and (chat.sheriff_check or chat.sheriff_shoot):
        bot.answer_callback_query(callback_query.id, text="⛔️")
        bot.delete_message(player_id, callback_query.message.message_id)
        return False

    if player.get('action_taken', False):
        bot.answer_callback_query(callback_query.id, text="⛔️")
        bot.delete_message(player_id, callback_query.message.message_id)
        return False

    player['action_taken'] = True  # Отмечаем, что действие совершено
    return True


def check_and_transfer_don_role(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    # Локализованные тексты
    texts = {
        'ru': {
            'became_don': 'Теперь ты 🧔🏻‍♂️ Дон!',
            'don_inherited': '🤵🏻 *Мафия* 🧔🏻‍♂️ *Дон* передал свою роль'
        },
        'kz': {
            'became_don': 'Енді сен 🧔🏻‍♂️ Донсың!',
            'don_inherited': '🤵🏻 *Мафия* 🧔🏻‍♂️ *Дон* рөлін өзіне мұра етті'
        }
    }[lang]

    if chat.don_id not in chat.players or chat.players[chat.don_id]['status'] == 'dead':
        # Дон мертв, проверяем, есть ли еще мафия
        alive_mafia = [player_id for player_id, player in chat.players.items() if player['role'] == '🤵🏻 Мафия']
        if alive_mafia:
            new_don_id = alive_mafia[0]
            change_role(new_don_id, chat.players, '🧔🏻‍♂️ Дон', texts['became_don'], chat)
            chat.don_id = new_don_id
            send_message(chat.chat_id, texts['don_inherited'], parse_mode="Markdown")
        else:
            logging.info("Все мафиози мертвы, роль Дона не передана.")

def check_game_end(chat, game_start_time):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    text = {
        'ru': {
            'game_over': "Игра окончена! 🙂",
            'winners': "Победители:",
            'remaining': "Оставшиеся игроки:",
            'time': "Время игры: {} мин. {} сек.",
            'you_earned': "*Игра окончена!*\nВы получили {} 💶",
            'suicide_win': "Ты победил как самоубийца! 💶 20",
            'teams': {
                'Самоубийца': "Самоубийца",
                'Жауыз': "Маньяк",
                'Халық': "Мирные жители",
                'won': "победили",
                'Мафия': "Мафия"
            }
        },
        'kz': {
            'game_over': "Ойын аяқталды! 🙂",
            'winners': "Жеңімпаздар:",
            'remaining': "Қалған ойыншылар:",
            'time': "Ойын уақыты: {} мин. {} сек.",
            'you_earned': "*Ойын аяқталды!*\nСен {} 💶 алдың",
            'suicide_win': "Сен өз-өзіне қол жұмсаушы ретінде жеңдің! 💶 20",
            'teams': {
                'Самоубийца': "Өз-өзіне қол жұмсаушы",
                'Жауыз': "Жауыз",
                'Халық': "Халық",
                'won': "жеңді",
                'Мафия': "Мафия"
            }
        }
    }[lang]

    def is_mafia_win(total_alive, mafia_team_count):
        non_mafia_count = total_alive - mafia_team_count
        mafia_win_cases = {
            (1, 1),
            (2, 0), (2, 1), (2, 2),
            (3, 0), (3, 1), (3, 2),
            (4, 0), (4, 1), (4, 2),
            (5, 0), (5, 1), (5, 2), (5, 3),
            (6, 0), (6, 1), (6, 2), (6, 3),
            (7, 0), (7, 1), (7, 2), (7, 3),
            (8, 0), (8, 1), (8, 2), (8, 3), (8, 4)
        }
        return (mafia_team_count, non_mafia_count) in mafia_win_cases

    mafia_count = len([p for p in chat.players.values() if p['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон'] and p['status'] != 'dead'])
    lawyer_count = len([p for p in chat.players.values() if p['role'] == '👨🏼‍💼 Қорғаушы' and p['status'] != 'dead'])
    maniac_count = len([p for p in chat.players.values() if p['role'] == '🔪 Жауыз' and p['status'] != 'dead'])
    non_mafia_count = len([p for p in chat.players.values() if p['role'] not in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз'] and p['status'] != 'dead'])
    total_mafia_team = mafia_count + lawyer_count

    alive_players = [p for p in chat.players.values() if p['status'] != 'dead']
    alive_count = len(alive_players)

    suicide_player = [
        p for p in chat.players.values()
        if p['role'] == '🤦‍♂️ Самоубийца' and p['status'] == 'lynched'
    ]

    if suicide_player:
        winning_team = text['teams']['Самоубийца']
        winners = [
            f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
            for k, v in chat.players.items()
            if v['role'] == '🤦‍♂️ Самоубийца' and v['status'] == 'lynched'
        ]

    elif maniac_count == 1 and alive_count == 1:
        winning_team = text['teams']['Жауыз']
        winners = [
            f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
            for k, v in chat.players.items()
            if v['role'] == '🔪 Жауыз' and v['status'] != 'dead'
        ]

    elif maniac_count == 1 and len(chat.players) - maniac_count == 1:
        winning_team = text['teams']['Жауыз']
        winners = [
            f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
            for k, v in chat.players.items()
            if v['role'] == '🔪 Жауыз' and v['status'] != 'dead'
        ]

    elif mafia_count == 0 and maniac_count == 0:
        winning_team = text['teams']['Халық']
        winners = [
            f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
            for k, v in chat.players.items()
            if v['role'] not in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз']
            and v['status'] != 'dead'
        ]

    elif mafia_count == 1 and total_mafia_team == 1 and alive_count == 1:
        winning_team = text['teams']['Мафия']
        winners = [
            f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
            for k, v in chat.players.items()
            if v['role'] == '🧔🏻‍♂️ Дон' and v['status'] != 'dead'
        ]

    elif is_mafia_win(alive_count, total_mafia_team):
        winning_team = text['teams']['Мафия']
        winners = [
            f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
            for k, v in chat.players.items()
            if v['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон', '👨🏼‍💼 Қорғаушы']
            and v['status'] != 'dead'
        ]

    else:
        return False

    winners_ids = [k for k, v in chat.players.items() if f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}" in winners]

    for player_id in winners_ids:
        reward = 20 if is_user_subscribed(player_id, '@CityMafiaNews') else 10
        if player_profiles.get(player_id, {}).get('vip_until'):
            reward += 15
        player_profiles[player_id]['euro'] += reward
        try:
            send_message(player_id, text['you_earned'].format(reward), parse_mode="Markdown")
        except Exception:
            pass

    if suicide_player:
        for player_id, player in chat.players.items():
            if player['role'] == '🤦‍♂️ Самоубийца' and player['status'] == 'lynched':
                try:
                    send_message(player_id, text['suicide_win'])
                except Exception:
                    pass

    remaining_players = [
        f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
        for k, v in chat.players.items()
        if k not in winners_ids and v['status'] not in ['dead', 'left']
    ]
    remaining_players.extend([
        f"[{get_full_name(v)}](tg://user?id={k}) - {translate_role(v['role'], lang)}"
        for k, v in chat.players.items()
        if v['status'] == 'left'
    ])

    all_dead_players = []
    for player in chat.all_dead_players:
        if isinstance(player, dict):
            all_dead_players.append(
                f"[{get_full_name(player)}](tg://user?id={player['user_id']}) - {translate_role(player['role'], lang)}"
            )
        else:
            all_dead_players.append(player)

    for player_id in chat.players:
        if player_id not in winners_ids and chat.players[player_id]['status'] != 'left':
            reward = 0
            if player_profiles.get(player_id, {}).get('vip_until'):
                reward += 10
            player_profiles[player_id]['euro'] += reward
            try:
                send_message(player_id, text['you_earned'].format(reward), parse_mode="Markdown")
            except Exception:
                pass

    # Определяем язык чата и выбираем соответствующую рекламу
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    current_ad = current_ad_message_ru if lang == 'ru' else current_ad_message_kz

    if current_ad:
        try:
            if current_ad['is_forward']:
                bot.forward_message(chat.chat_id, current_ad['chat_id'], current_ad['message_id'])
            else:
                # Копируем сообщение с сохранением разметки
                original_msg = bot.get_message(current_ad['chat_id'], current_ad['message_id'])
                source_msg = bot.copy_message(
                    chat.chat_id, 
                    current_ad['chat_id'], 
                    current_ad['message_id'],
                    reply_markup=original_msg.reply_markup if original_msg.reply_markup else None
                )
        except Exception as e:
            logging.error(f"Ошибка при отправке рекламы: {e}")

    time.sleep(5)

    game_duration = time.time() - game_start_time
    minutes = int(game_duration // 60)
    seconds = int(game_duration % 60)

    result_text = (
        f"*{text['game_over']}*\n"
        f"*{winning_team}* {text['teams']['won']}\n\n"
        f"*{text['winners']}*\n" + "\n".join(winners) + "\n\n"
        f"*{text['remaining']}*\n" + "\n".join(remaining_players + all_dead_players) + "\n\n"
        f"⏰ {text['time'].format(minutes, seconds)}"
    )

    try:
        send_message(chat.chat_id, result_text, parse_mode="Markdown")
    except Exception:
        pass

    for dead_player in chat.all_dead_players:
        if isinstance(dead_player, dict):
            player_id = dead_player['user_id']
        elif isinstance(dead_player, str):
            player_id = int(dead_player.split('=')[1].split(')')[0])
        reward = 0
        if player_profiles.get(player_id, {}).get('vip_until'):
            reward += 10
        player_profiles[player_id]['euro'] += reward
        try:
            send_message(player_id, text['you_earned'].format(reward), parse_mode="Markdown")
        except Exception:
            pass

    for player_id in winners_ids:
        player_scores[player_id] = player_scores.get(player_id, 0) + 1

    for player_id in chat.players:
        if player_id not in winners_ids and chat.players[player_id]['status'] not in ['left', 'dead']:
            player_scores[player_id] = player_scores.get(player_id, 0) - 1

    for dead_player in chat.all_dead_players:
        if isinstance(dead_player, dict):
            player_id = dead_player['user_id']
        elif isinstance(dead_player, str):
            player_id = int(dead_player.split('=')[1].split(')')[0])
        if player_id not in winners_ids:
            player_scores[player_id] = player_scores.get(player_id, 0) - 1

    for player_id in list(user_game_registration.keys()):
        if user_game_registration[player_id] == chat.chat_id:
            del user_game_registration[player_id]

    send_zip_to_channel()
    reset_game(chat)
    reset_roles(chat)
    return True

# Глобальные переменные для рекламы (добавьте в начало файла)
current_ad_message_ru = None
current_ad_message_kz = None

# Добавляем новую команду для управления рекламой
@bot.message_handler(commands=['реклама'])
def handle_ad_command(message):
    global current_ad_message_ru, current_ad_message_kz
    
    # Проверяем права администратора
    if message.from_user.id != ADMIN_ID:
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        return
    
    # Проверяем формат команды
    if len(message.text.split()) < 2:
        send_message(message.chat.id, "Использование: /реклама [ссылка на сообщение] [язык] или /реклама сброс [язык]")
        return
    
    args = message.text.split()
    
    if args[1].lower() == 'сброс':
        lang = args[2].lower() if len(args) > 2 else None
        if lang == 'ru':
            current_ad_message_ru = None
            send_message(message.chat.id, "✅ Реклама для русских сброшена")
        elif lang == 'kz':
            current_ad_message_kz = None
            send_message(message.chat.id, "✅ Реклама для казахских сброшена")
        else:
            current_ad_message_ru = None
            current_ad_message_kz = None
            send_message(message.chat.id, "✅ Вся реклама сброшена")
        return
    
    # Определяем язык
    lang = args[2].lower() if len(args) > 2 else 'all'
    
    # Пытаемся извлечь ID сообщения из ссылки
    try:
        # Формат ссылки: https://t.me/c/123456789/123 или https://t.me/CityMafiaAdvertising/123
        parts = args[1].split('/')
        message_id = int(parts[-1])
        channel_id_part = parts[-2]

        if channel_id_part.isdigit():
            # Приватный канал с числовым ID (формат: /c/123456789/123)
            channel_id = int('-100' + channel_id_part)
        else:
            # Публичный канал с @username (формат: /CityMafiaAdvertising/123)
            username = '@' + channel_id_part
            channel_id = bot.get_chat(username).id
        
        # Получаем сообщение из канала
        ad_message = bot.forward_message(ADMIN_ID, channel_id, message_id)
        
        # Сохраняем временную информацию о рекламе
        temp_ad_data = {
            'chat_id': channel_id,
            'message_id': message_id
        }
        
        # Создаем клавиатуру в зависимости от выбора языка
        markup = types.InlineKeyboardMarkup()
        if lang == 'all':
            markup.add(
                types.InlineKeyboardButton("🇷🇺 Для русских", callback_data=f"ad_ru_copy_{message_id}"),
                types.InlineKeyboardButton("🇰🇿 Для казахских", callback_data=f"ad_kz_copy_{message_id}")
            )
        else:
            markup.add(
                types.InlineKeyboardButton("✅ Использовать как есть", callback_data=f"ad_{lang}_copy_{message_id}"),
                types.InlineKeyboardButton("🔄 Пересылать", callback_data=f"ad_{lang}_forward_{message_id}")
            )
        markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="ad_cancel"))
        
        lang_text = "для всех языков" if lang == 'all' else f"для {'русских' if lang == 'ru' else 'казахских'}"
        send_message(message.chat.id, f"Выберите режим отправки рекламы {lang_text}:", reply_markup=markup)
        
    except Exception as e:
        send_message(message.chat.id, f"Ошибка: {e}\nПроверьте ссылку и права бота в канале.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('ad_'))
def handle_ad_callback(call):
    global current_ad_message_ru, current_ad_message_kz
    
    if call.data == 'ad_cancel':
        bot.edit_message_text("Рекламное сообщение отменено", call.message.chat.id, call.message.message_id)
        return
    
    try:
        # Парсим callback data: ad_ru_copy_123 или ad_kz_forward_456
        parts = call.data.split('_')
        lang = parts[1]  # ru или kz
        mode = parts[2]  # copy или forward
        message_id = int(parts[3]) if len(parts) > 3 else None
        
        # Получаем информацию о сообщении из пересланного сообщения
        if call.message.reply_to_message and call.message.reply_to_message.forward_from_chat:
            chat_id = call.message.reply_to_message.forward_from_chat.id
            message_id = call.message.reply_to_message.forward_from_message_id
        else:
            # Если нет пересланного сообщения, используем данные из callback
            chat_id = call.message.chat.id
        
        ad_data = {
            'chat_id': chat_id,
            'message_id': message_id,
            'is_forward': (mode == 'forward')
        }
        
        if lang == 'ru':
            current_ad_message_ru = ad_data
            bot.edit_message_text(f"✅ Реклама для русских сохранена ({'пересылается' if mode == 'forward' else 'копируется'})", call.message.chat.id, call.message.message_id)
        elif lang == 'kz':
            current_ad_message_kz = ad_data
            bot.edit_message_text(f"✅ Реклама для казахских сохранена ({'пересылается' if mode == 'forward' else 'копируется'})", call.message.chat.id, call.message.message_id)
            
    except Exception as e:
        bot.edit_message_text(f"Ошибка: {e}", call.message.chat.id, call.message.message_id)

def reset_game(chat):
    chat.players.clear()  # Очищаем список игроков
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
    chat.suicide_bomber_id = None  # Сбрасываем ID смертника
    chat.suicide_hanged = False  # Сбрасываем статус самоубийцы
    chat.lover_id = None  # Сбрасываем роль любовницы
    chat.lover_target_id = None  # Сбрасываем цель любовницы
    chat.previous_lover_target_id = None  # Сбрасываем предыдущую цель любовницы
    chat.lawyer_id = None  # Сбрасываем ID адвоката
    chat.lawyer_target = None  # Сбрасываем цель адвоката
    chat.sergeant_id = None  # Сбрасываем ID сержанта
    chat.maniac_id = None  # Сбрасываем ID маньяка
    chat.maniac_target = None  # Сбрасываем цель маньяка
    logging.info(f"Игра сброшена в чате {chat.chat_id}")

def reset_roles(chat):
    """
    Сбрасывает роли и параметры всех игроков в чате.
    """
    for player_id, player in chat.players.items():
        player['role'] = 'ждет'  # Возвращаем всех игроков в состояние ожидания
        player['status'] = 'alive'  # Сбрасываем статус игрока на живой
        player['skipped_actions'] = 0  # Сбрасываем количество пропущенных действий
        player['self_healed'] = False  # Сбрасываем статус самовосстановления для доктора
        player['voting_blocked'] = False  # Сбрасываем блокировку голосования для любовницы
        player['healed_from_lover'] = False  # Сбрасываем флаг лечения от любовницы
        player['action_taken'] = False  # Сбрасываем флаг того, что игрок совершил действие ночью
        player['lucky_escape'] = False  # Сбрасываем флаг "счастливчика", если он спас себя
        profile['gun_used'] = False


    for player_id, profile in player_profiles.items():
         profile['fake_docs_used'] = False  # Сбрасываем флаг, чтобы в новой игре документы работали снова

    for player_id, profile in player_profiles.items():
         if profile.get('shield_used'):  # Проверяем, был ли щит использован
             profile['shield_used'] = False  # Сбрасываем использование щита

    for player_id, profile in player_profiles.items():
         profile['hanging_shield_used'] = False  # Сбрасываем использование щита от повешения

    # Сбрасываем специфические роли
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
    chat.hobo_visitors.clear()  # Очищаем список посетителей цели Бомжа
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
    chat.lucky_id = None  # Сбрасываем ID "Счастливчика"
    chat.vote_message_id = None
    chat.dead_last_words.clear()  # Сбрасываем последние слова убитых игроков

    logging.info("Все роли и параметры игроков сброшены.")

def escape_markdown(text):
    escape_chars = r'\*_`['
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)


def check_and_transfer_sheriff_role(chat):
    if chat.sheriff_id not in chat.players or chat.players[chat.sheriff_id]['role'] == 'dead':
        # Получаем язык чата
        lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

        # Комиссар мертв, проверяем, есть ли сержант
        if chat.sergeant_id and chat.sergeant_id in chat.players and chat.players[chat.sergeant_id]['role'] != 'dead':
            new_sheriff_id = chat.sergeant_id

            # Текст уведомления игроку
            if lang == 'kz':
                sheriff_text = "Енді сен 🕵🏼 Комиссарсың!"
            if lang == 'ru':
                sheriff_text = "Теперь ты 🕵🏼 Комиссар!"

            change_role(new_sheriff_id, chat.players, '🕵🏼 Комиссар', sheriff_text, chat)
            chat.sheriff_id = new_sheriff_id
            chat.sergeant_id = None  # Сержант больше не нужен

            # Сообщение в чат
            if lang == 'kz':
                msg = "👮🏼 *Сержант* 🕵🏼 *Комиссар* рөлін өзіне мұра етті"
            if lang == 'ru':
                msg = "👮🏼 *Сержант* унаследовал роль 🕵🏼 *Комиссара*"
            send_message(chat.chat_id, msg, parse_mode="Markdown")
        else:
            logging.info("Нет сержанта для передачи роли Комиссара.")

def notify_police(chat):
    police_members = []

    # Получаем язык чата
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    if chat.sheriff_id and chat.sheriff_id in chat.players and chat.players[chat.sheriff_id]['role'] == '🕵🏼 Комиссар':
        sheriff_name = get_full_name(chat.players[chat.sheriff_id])
        if lang == 'kz':
            police_members.append(f"[{sheriff_name}](tg://user?id={chat.sheriff_id}) - 🕵🏼 *Комиссар*")
        if lang == 'ru':
            police_members.append(f"[{sheriff_name}](tg://user?id={chat.sheriff_id}) - 🕵🏼 *Комиссар*")

    if chat.sergeant_id and chat.sergeant_id in chat.players and chat.players[chat.sergeant_id]['role'] == '👮🏼 Сержант':
        sergeant_name = get_full_name(chat.players[chat.sergeant_id])
        if lang == 'kz':
            police_members.append(f"[{sergeant_name}](tg://user?id={chat.sergeant_id}) - 👮🏼 *Сержант*")
        if lang == 'ru':
            police_members.append(f"[{sergeant_name}](tg://user?id={chat.sergeant_id}) - 👮🏼 *Сержант*")

    if lang == 'kz':
        message = "🚨 *Полициялық құрам:*\n" + "\n".join(police_members)
    if lang == 'ru':
        message = "🚨 *Полицейский состав:*\n" + "\n".join(police_members)

    for player_id in [chat.sheriff_id, chat.sergeant_id]:
        if player_id in chat.players:
            try:
                send_message(player_id, message, parse_mode='Markdown', protect_content=True)
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение полицейскому {player_id}: {e}")

# Глобальный словарь переводов ролей (вынеси в начало файла)
role_translations = {
    'ru': {
        '🧔🏻‍♂️ Дон': '🧔🏻‍♂️ Дон',
        '🤵🏻 Мафия': '🤵🏻 Мафия',
        '👨🏼‍⚕️ Дәрігер': '👨🏼‍⚕️ Доктор',
        '🕵🏼 Комиссар': '🕵🏼 Комиссар',
        '👨🏼 Тату тұрғын': '👨🏼 Мирный житель',
        '🧙‍♂️ Қаңғыбас': '🧙‍♂️ Бомж',
        '🤞 Жолы болғыш': '🤞 Счастливчик',
        '💣 Камикадзе': '💣 Камикадзе',
        '💃🏼 Көңілдес': '💃🏼 Любовница',
        '👨🏼‍💼 Қорғаушы': '👨🏼‍💼 Адвокат',
        '👮🏼 Сержант': '👮🏼 Сержант',
        '🔪 Жауыз': '🔪 Маньяк',
        '🤦‍♂️ Самоубийца': 'Самоубийца',
        '💤 Маубас': '💤 Лентяй',
        '💣': '💣 Камикадзе'
    },
    'kz': {
        '🧔🏻‍♂️ Дон': '🧔🏻‍♂️ Дон',
        '🤵🏻 Мафия': '🤵🏻 Мафия',
        '👨🏼‍⚕️ Дәрігер': '👨🏼‍⚕️ Дәрігер',
        '🕵🏼 Комиссар': '🕵🏼 Комиссар',
        '👨🏼 Тату тұрғын': '👨🏼 Тату тұрғын',
        '🧙‍♂️ Қаңғыбас': '🧙‍♂️ Қаңғыбас',
        '🤞 Жолы болғыш': '🤞 Жолы болғыш',
        '💣 Камикадзе': '💣 Камикадзе',
        '💃🏼 Көңілдес': '💃🏼 Көңілдес',
        '👨🏼‍💼 Қорғаушы': '👨🏼‍💼 Қорғаушы',
        '👮🏼 Сержант': '👮🏼 Сержант',
        '🔪 Жауыз': '🔪 Жауыз',
        '🤦‍♂️ Самоубийца': 'Өз-өзіне қол жұмсаушы',
        '💤 Маубас': '💤 Маубас',
        '💣': '💣 Камикадзе'
    }
}

def translate_role(role, lang):
    return role_translations.get(lang, {}).get(role, role)


def process_deaths(chat, killed_by_mafia, killed_by_sheriff, killed_by_bomber=None, killed_by_maniac=None):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    combined_message = ""
    deaths = {}
    doc_visit_notified = set()  # 🔒 Чтобы не отправлять одно и то же сообщение дважды

    if hasattr(chat, 'gun_kill') and chat.gun_kill:
        victim_id, victim = chat.gun_kill
        deaths[victim_id] = {'victim': victim, 'roles': ['🔫 Тапанша']}
        del chat.gun_kill

    if killed_by_mafia:
        victim_id, victim = killed_by_mafia
        deaths[victim_id] = {'victim': victim, 'roles': ['🧔🏻‍♂️ Дон']}

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

                    if lang == 'kz':
                        send_message(chat.chat_id, "🪽 Ойыншылардың біреуі қорғанысын жұмсады")
                        send_message(victim_id, "⚔️ Біреу саған қастандық жасады, бірақ қорғанысың сақтап қалды!")
                    if lang == 'ru':
                        send_message(chat.chat_id, "🪽 Кто-то из игроков использовал защиту")
                        send_message(victim_id, "⚔️ Кто-то покушался на тебя, но твоя защита спасла тебя!")
                    return True

                if chat.doc_target and chat.doc_target == victim_id and victim_id not in doc_visit_notified:
                    doc_visit_notified.add(victim_id)
                    if lang == 'kz':
                        send_message(chat.doc_target, '👨🏼‍⚕️ *Дәрігер* сені емдеп алды', parse_mode="Markdown")
                    if lang == 'ru':
                        send_message(chat.doc_target, '👨🏼‍⚕️ *Доктор* тебя спас', parse_mode="Markdown")
                    return True
            return False

        if check_shield_or_doc(victim_id, victim):
            del deaths[victim_id]
            continue

        if victim['role'] == '🤞 Жолы болғыш':
            if random.randint(1, 100) <= 50:
                if lang == 'kz':
                    send_message(chat.chat_id, "🤞 Кейбір ойыншылардың жолы болды")
                    send_message(victim_id, "🤞 Осы түні саған қастық жасалды, бірақ сенің жолың болды!")
                if lang == 'ru':
                    send_message(chat.chat_id, "🤞 Кому-то повезло этой ночью")
                    send_message(victim_id, "🤞 На тебя покушались этой ночью, но тебе повезло!")
                del deaths[victim_id]
                continue

        if victim['role'] == '💣 Камикадзе':
            for killer_role in roles_involved:
                killer_id = None
                if killer_role == '🧔🏻‍♂️ Дон' and chat.don_id:
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

    # 👇 Сообщение докторской цели, если она не умерла и ещё не уведомлена
    if chat.doc_target and chat.doc_target not in deaths and chat.doc_target not in doc_visit_notified:
        doc_visit_notified.add(chat.doc_target)
        doc_target = chat.players.get(chat.doc_target)
        if doc_target and doc_target['role'] != 'dead':
            if lang == 'kz':
                msg = "👨🏼‍⚕️ Дәрігер қонағыңызға келді"
            else:
                msg = "👨🏼‍⚕️ Доктор приходил к тебе в гости"
            try:
                send_message(chat.doc_target, msg, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение докторской цели {chat.doc_target}: {e}")

    for victim_id, death_info in deaths.items():
        victim = death_info['victim']
        roles_involved = death_info['roles']
        victim_link = f"[{get_full_name(victim)}](tg://user?id={victim_id})"
        translated_roles = ", ".join(translate_role(r, lang) for r in roles_involved)

        if lang == 'kz':
            combined_message += f"Түнде *{translate_role(victim['role'], lang)}* {victim_link} аяусыз өлтірілген болды...\n"
            combined_message += f"Оған *{translated_roles}* кіріп шықты деседі\n\n"
        if lang == 'ru':
            combined_message += f"Сегодня был жестоко убит *{translate_role(victim['role'], lang)}* {victim_link}...\n"
            combined_message += f"ходят слухи, что у него был визит от *{translated_roles}*\n\n"

        chat.remove_player(victim_id, killed_by='night')

    if combined_message:
        send_message(chat.chat_id, combined_message, parse_mode="Markdown")
    else:
        if lang == 'kz':
            send_message(chat.chat_id, "_🤷 Неткен ғажап! Бұл түнде ешкім көз жұмбады…_", parse_mode="Markdown")
        if lang == 'ru':
            send_message(chat.chat_id, "_🤷 Как ни странно, этой ночью никто не погиб…_", parse_mode="Markdown")

    check_and_transfer_don_role(chat)
    check_and_transfer_sheriff_role(chat)



def process_night_actions(chat):
    for player_id, player in chat.players.items():
        if player['role'] != 'dead' and not player_made_action(player_id):
            # Если игрок не сделал действия, увеличиваем счетчик пропущенных
            player_profiles[player_id]['skipped_actions'] += 1
        else:
            # Если игрок сделал действия, сбрасываем счетчик
            player_profiles[player_id]['skipped_actions'] = 0

        # Дополнительная логика для Бомжа и Адвоката
        if player['role'] == '🧙‍♂️ Қаңғыбас':
            # Бомж не может выбрать ту же цель дважды подряд
            if chat.previous_hobo_target == player_id:
                # Если цель та же, нужно исключить её из доступных для выбора
                # Пример: создаём сообщение или сообщение об ошибке
                send_message(player_id, 'Ты не можешь выбрать эту цель снова. Выберите другую.')

        elif player['role'] == '👨🏼‍💼 Қорғаушы':
            # Адвокат не может выбрать ту же цель дважды подряд
            if chat.previous_lawyer_target == player_id:
                # Если цель та же, нужно исключить её из доступных для выбора
                send_message(player_id, 'Ты не можешь защищать того же игрока дважды подряд. Выберите другого игрока.')


def get_or_create_profile(user_id, user_name, user_last_name=None):
    # Проверяем, существует ли профиль в словаре
    profile = player_profiles.get(user_id)
    
    if not profile:
        # Если профиля нет, создаем новый
        profile = {
            'id': user_id,
            'name': user_name,
            'last_name': user_last_name,  # Сохраняем фамилию
            'euro': 0,  # Стартовый баланс
            'coins': 0,
            'shield': 0,
            'hanging_shield': 0,  # Щит от повешения
            'fake_docs': 0,
            'vip_until': '',        # Инициализация поля VIP
            'shield_active': True,  # Флаг активности обычного щита
            'hanging_shield_active': True,
            'gun': 0,
            'gun_used': False,
            'language': 'ru',  # Язык по умолчанию
            'docs_active': True  # Флаг активности фальшивых документов
        }
        # Сохраняем профиль в словаре
        player_profiles[user_id] = profile
    else:
        # Обновляем имя и фамилию, если они изменились
        profile['name'] = user_name
        profile['last_name'] = user_last_name

        # Добавляем недостающие ключи
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

def update_profile(user_id, profile):
    player_profiles[user_id] = profile

def process_mafia_action(chat):
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")
    mafia_victim = None

    # Нет голосов или уже есть жертва — нет смысла продолжать
    if not chat.mafia_votes or chat.dead:
        return None

    vote_counts = {}
    for voter_id, victim_id in chat.mafia_votes.items():
        weight = 3 if voter_id == chat.don_id else 1
        vote_counts[victim_id] = vote_counts.get(victim_id, 0) + weight

    max_votes = max(vote_counts.values(), default=0)
    possible_victims = [victim for victim, votes in vote_counts.items() if votes == max_votes]

    # Ничья
    if len(possible_victims) > 1:
        if chat.don_id in chat.mafia_votes:
            mafia_victim = chat.mafia_votes[chat.don_id]
        else:
            try:
                if lang == 'kz':
                    send_message_to_mafia(chat, "*Дауыс беру аяқталды.*\nОтбасы ортақ шешімге келе алмай, ешкімде құрбан етпеді")
                if lang == 'ru':
                    send_message_to_mafia(chat, "*Голосование завершено.*\nСемья не пришла к единому мнению и никого не убила")
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение о ничейном голосовании: {e}")
            chat.mafia_votes.clear()
            return None

    # Один кандидат — выбираем
    if len(possible_victims) == 1:
        mafia_victim = possible_victims[0]

    # Если жертва найдена и она ещё в игре
    if mafia_victim and mafia_victim in chat.players:
        victim_profile = chat.players[mafia_victim]
        mafia_victim_name = f"{victim_profile['name']} {victim_profile.get('last_name', '')}".replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').strip()

        try:
            if lang == 'kz':
                send_message_to_mafia(chat, f"*Дауыс беру аяқталды*\nМафия {mafia_victim_name} дегенді құрбан етті")
                send_message(chat.chat_id, "🤵🏻 *Мафия* құрбанын таңдады...", parse_mode="Markdown")
            if lang == 'ru':
                send_message_to_mafia(chat, f"*Голосование завершено*\nМафия выбрала жертвой {mafia_victim_name}")
                send_message(chat.chat_id, "🤵🏻 *Мафия* выбрала жертву...", parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение о выборе жертвы: {e}")

        # Проверка на блокировку дона
        if chat.don_id and chat.don_id in chat.players:
            if chat.players[chat.don_id].get('voting_blocked', False):
                mafia_victim = None  # Дон не может проголосовать — откатываем

        # Если всё в порядке — устанавливаем жертву
        if mafia_victim:
            chat.dead = (mafia_victim, victim_profile)

    # Если в итоге так и не выбрали жертву
    if not mafia_victim or mafia_victim not in chat.players:
        try:
            if lang == 'kz':
                send_message_to_mafia(chat, "*Дауыс беру аяқталды.*\nОтбасы ортақ шешімге келе алмай, ешкімде құрбан етпеді")
            if lang == 'ru':
                send_message_to_mafia(chat, "*Голосование завершено.*\nСемья не смогла выбрать жертву")
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение о провале голосования: {e}")

    chat.mafia_votes.clear()
    return mafia_victim

@bot.message_handler(commands=['stats'])
def show_stats(message):
    # Проверяем, что команда вызвана администратором
    if message.from_user.id != ADMIN_ID:
        return

    # Получаем количество профилей
    num_profiles = len(player_profiles)
    
    # Получаем количество чатов с настройками
    num_chats = len(chat_settings)
    
    # Получаем количество активных игр
    active_games = sum(1 for chat in chat_list.values() if chat.game_running)
    
    # Формируем сообщение
    stats_message = (
        f"📊 *Статистика бота:*\n\n"
        f"👤 Профилей игроков: *{num_profiles}*\n"
        f"💬 Чатов с настройками: *{num_chats}*\n"
        f"🎲 Активных игр: *{active_games}*"
    )
    
    # Отправляем сообщение
    send_message(message.chat.id, stats_message, parse_mode="Markdown")

    # Пытаемся удалить исходное сообщение с командой
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass


@bot.message_handler(commands=['chaek'])
def send_message_to_all_chats(message):
    # Убедимся, что команда выполняется только администратором бота
    admin_user_id = 6265990443  # Замените на ваш ID
    if message.from_user.id != admin_user_id:
        bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды.")
        return

    # Текст сообщения, который будет отправлен
    broadcast_message = "*Ойын уақытша тоқтатылды.*\n*🛠️ Бот жаңартылу үстінде!*\nӨтінемін, бірнеше минут күтіп, ойынды қайта бастаңыз.\n\n_Еш уайымдамаңыз — сіздің барлық қорғанысыңыз, құжатыңыз және қалған ресурстарыңыз толық сақталады!_"
    # Отправляем сообщение во все чаты, где бот активен
    success_count = 0
    error_count = 0
    for chat_id in chat_list.keys():
        try:
            send_message(chat_id, broadcast_message, parse_mode="Markdown")
            success_count += 1
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
            error_count += 1

    # Уведомляем администратора о результатах
    bot.reply_to(
        message,
        f"📤 Сообщение отправлено в {success_count} чатов.\n❌ Ошибки при отправке в {error_count} чатов."
    )
def parse_active_status(status):
    """Преобразует строку в булевое значение для активных статусов."""
    return status == '🟢 ON'
    
@bot.message_handler(commands=['send_zip'])
def send_zip_command(message):
    if message.from_user.id == ADMIN_ID:
        send_zip_to_channel()
        bot.reply_to(message, "✅ ZIP-архив с данными отправлен в канал.")
    else:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")

@bot.message_handler(commands=['export_data'])
def export_data_command(message):
    if message.from_user.id == ADMIN_ID:
        # Отправляем как ZIP, так и отдельные файлы для совместимости
        send_zip_to_channel()
        send_profiles_as_file()  # Старая функция для профилей
        export_chat_settings()   # Старая функция для настроек
        bot.reply_to(message, "✅ Все данные экспортированы.")
    else:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")

def handle_zip_upload(message):
    """Обрабатывает загруженный ZIP-архив и извлекает данные."""
    file_id = message.document.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    with zipfile.ZipFile(io.BytesIO(downloaded_file), 'r') as zip_file:
        # Обрабатываем player_profiles.csv
        if 'player_profiles.csv' in zip_file.namelist():
            with zip_file.open('player_profiles.csv') as f:
                csv_data = io.StringIO(f.read().decode('utf-8'))
                reader = csv.DictReader(csv_data)
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

        # Обрабатываем player_scores.csv
        if 'player_scores.csv' in zip_file.namelist():
            with zip_file.open('player_scores.csv') as f:
                csv_data = io.StringIO(f.read().decode('utf-8'))
                reader = csv.DictReader(csv_data)
                for row in reader:
                    entity_id = int(row['ID'])
                    value = int(row['Значение'])
                    if row['Тип'] == 'player':
                        player_scores[entity_id] = value
                    elif row['Тип'] == 'timer':
                        game_timers[entity_id] = value

        # Обрабатываем chat_settings.csv
        if 'chat_settings.csv' in zip_file.namelist():
            with zip_file.open('chat_settings.csv') as f:
                csv_data = io.StringIO(f.read().decode('utf-8'))
                reader = csv.DictReader(csv_data)
                for row in reader:
                    chat_id = int(row['Chat ID'])
                    reg_time_parts = row['Registration Time'].split('/')
                    
                    # Создаем настройки чата с учетом языка
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
                        'language': row.get('Language', 'kz')  # Добавляем язык чата
                    }

    bot.reply_to(message, "✅ Данные успешно загружены из архива!")

@bot.channel_post_handler(content_types=['document'])
def handle_document(message):
    channel_id = message.chat.id

    if channel_id == SETTINGS_CHANNEL_ID:
        if message.from_user and message.from_user.id == ADMIN_ID:
            if message.document.file_name.endswith('.zip'):
                handle_zip_upload(message)  # Обработка ZIP-архива
            else:
                import_chat_settings(message)  # Старая обработка отдельных файлов
        return

    # Обработка для других каналов (если нужно)
    if message.document:
        file_id = message.document.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        if message.document.file_name.endswith('.zip'):
            handle_zip_upload(message)  # Обработка ZIP-архива
        else:
            # Старая логика для отдельных файлов
            try:
                with io.StringIO(downloaded_file.decode('utf-8')) as csv_file:
                    reader = csv.DictReader(csv_file)
                    if 'Тип' in reader.fieldnames:  # Это файл с очками/таймерами
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
                        global player_scores, game_timers
                        player_scores = new_scores
                        game_timers = new_timers
                        send_message(channel_id, "✅ Данные игры успешно загружены.")
                    elif 'Chat ID' in reader.fieldnames:  # Это настройки чатов
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
                                    'mafia_ratio': int(row['Mafia Ratio'])
                                }
                            except Exception as e:
                                send_message(channel_id, f"❌ Ошибка в строке настроек: {e}")
                        send_message(channel_id, "✅ Настройки чатов успешно загружены!")
                        
                    else:  # Это профили игроков
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
    """Отправляет все данные (профили, очки, настройки) в виде ZIP-архива в канал."""
    channel_id = -1002598471111  # ID канала для загрузки данных

    # Создаем ZIP-архив в памяти
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Добавляем профили игроков
        profiles_csv = io.StringIO()
        writer = csv.writer(profiles_csv)
        writer.writerow(['ID', 'Имя', 'Фамилия', 'Евро', 'Монета', 'Щит', 'Щит от повешения', 
                         'Поддельные документы', 'VIP до', 'Щит активен', 
                         'Щит от повешения активен', 'Документы активны', 'Тапанша', 'Язык'])
        for user_id, profile in player_profiles.items():
            writer.writerow([
                user_id,
                profile.get('name', 'Неизвестно'),
                profile.get('last_name', ''),
                profile.get('euro', 0),
                profile.get('coins', 0),
                profile.get('shield', 0),
                profile.get('hanging_shield', 0),
                profile.get('fake_docs', 0),
                profile.get('vip_until', ''),
                '🟢 ON' if profile.get('shield_active', False) else '🔴 OFF',
                '🟢 ON' if profile.get('hanging_shield_active', False) else '🔴 OFF',
                '🟢 ON' if profile.get('docs_active', False) else '🔴 OFF',
                profile.get('gun', 0),
                profile.get('language', 'kz')  # Добавляем язык профиля
            ])
        profiles_csv.seek(0)
        zip_file.writestr('player_profiles.csv', profiles_csv.getvalue())

        # Добавляем настройки чатов (обновленная версия с языком)
        settings_csv = io.StringIO()
        writer = csv.writer(settings_csv)
        writer.writerow(['Chat ID', 'Pin Registration', 'Allow Registration', 
                        'Allow Leave', 'Registration Time', 'Night Time',
                        'Day Time', 'Voting Time', 'Confirmation Time',
                        'Mafia Ratio', 'Language'])  # Добавляем колонку Language
        for chat_id, settings in chat_settings.items():
            reg_time = f"{settings['registration_time'][0]}/{settings['registration_time'][1]}"
            writer.writerow([
                chat_id,
                'Yes' if settings['pin_registration'] else 'No',
                'Yes' if settings['allow_registration'] else 'No',
                'Yes' if settings['allow_leave_game'] else 'No',
                reg_time,
                settings['night_time'],
                settings['day_time'],
                settings['voting_time'],
                settings['confirmation_time'],
                settings['mafia_ratio'],
                settings.get('language', 'ru')  # Добавляем язык чата
            ])
        settings_csv.seek(0)
        zip_file.writestr('chat_settings.csv', settings_csv.getvalue())

    zip_buffer.seek(0)
    zip_buffer.name = 'game_data.zip'

    try:
        bot.send_document(channel_id, zip_buffer, caption="Архив с данными игры")
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
        lang = profile.get('language', 'ru')  # Язык только для приветствия

        full_name = f"{user_name} {user_last_name}".strip()
        words_count = len(full_name.split())
        symbols_count = len(full_name)

        if words_count + symbols_count > 45:
            msg = "❗ Ваш ник слишком длинный. Пожалуйста, сделайте его короче (сумма слов и символов не должна превышать 45)."
            bot.send_message(user_id, msg)
            return

        start_content = {
            'kz': {
                'text': '*Сэлем!*\nМен 🤵🏻 *Мафия* ойнынын жургізуші-ботымын.\nМені чатқа қосып, әкімші етіңіз және тегін ойнай бастаңыз',
                'add_to_group': '🤵🏽 Ботты өз чатыңа қосу',
                'join_chat': 'Чатка кіру',
                'news': '📰 Жаңалықтар'
            },
            'ru': {
                'text': '*Привет!*\nЯ 🤵🏻 *Мафия* бот-ведущий.\nДобавьте меня в чат, сделайте администратором и начните играть бесплатно',
                'add_to_group': '🤵🏽 Добавить бота в свой чат',
                'join_chat': 'Войти в чат',
                'news': '📰 Новости'
            }
        }
        content = start_content[lang]
        text = message.text

        if len(text.split()) > 1:
            param = text.split()[1]
            if param.startswith("join_"):
                game_chat_id = int(param.split('_')[1])
                lang = chat_settings.get(game_chat_id, {}).get("language", "kz")  # Язык чата

                if user_id in user_game_registration:
                    if user_game_registration[user_id] != game_chat_id:
                        if lang == 'kz':
                            bot.send_message(user_id, "🚫 Басқа ойынға қосылып қойғансыз")
                        if lang == 'ru':
                            bot.send_message(user_id, "🚫 Вы уже зарегистрированы в другой игре")
                        return

                chat = chat_list.get(game_chat_id)
                if chat:
                    try:
                        chat_member = bot.get_chat_member(game_chat_id, user_id)
                        if chat_member.status in ['member', 'administrator', 'creator'] and (chat_member.can_send_messages is None or chat_member.can_send_messages):
                            if chat.game_running:
                                if lang == 'kz':
                                    bot.send_message(user_id, "🚫 Қосылу мүмкін болмады, ойын басталып кетті!")
                                if lang == 'ru':
                                    bot.send_message(user_id, "🚫 Не удалось присоединиться — игра уже началась!")
                            elif not chat.button_id:
                                if lang == 'kz':
                                    bot.send_message(user_id, "🚫 Қосылу мүмкін болмады, ойын әлі басталмаған!")
                                if lang == 'ru':
                                    bot.send_message(user_id, "🚫 Не удалось присоединиться — игра ещё не началась!")
                            elif user_id not in chat.players:
                                full_name = f"{user_name} {user_last_name}".strip()
                                chat.players[user_id] = {'name': full_name, 'role': 'ждет', 'skipped_actions': 0}
                                user_game_registration[user_id] = game_chat_id

                                if lang == 'kz':
                                    bot.send_message(user_id, f"🎲 {bot.get_chat(game_chat_id).title} чатындағы ойынға қосылдыңыз!")
                                if lang == 'ru':
                                    bot.send_message(user_id, f"🎲 Вы присоединились к игре в чате {bot.get_chat(game_chat_id).title}!")

                                new_text = players_alive(chat.players, "registration", game_chat_id)
                                new_markup = types.InlineKeyboardMarkup(
                                    [[types.InlineKeyboardButton(
                                        '🤵🏻 Қосылу' if lang == 'kz' else '🤵🏻 Присоединиться',
                                        url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}'
                                    )]]
                                )

                                try:
                                    schedule_update(game_chat_id, chat)
                                except Exception as e:
                                    logging.error(f"Ошибка обновления сообщения: {e}")

                                with game_start_lock:
                                    if len(chat.players) >= 20 and not chat.game_running and chat.button_id:
                                       _start_game(game_chat_id)

                            else:
                                if lang == 'kz':
                                    bot.send_message(user_id, "✅ Ойынға қосылдыңыз! :)")
                                if lang == 'ru':
                                    bot.send_message(user_id, "✅ Вы уже присоединились к игре! :)")
                        else:
                            if lang == 'kz':
                                bot.send_message(user_id, "🚫 Ойынға қосыла алмайсыз, себебі топта хабарлама жіберуге рұқсатыңыз жоқ.")
                            if lang == 'ru':
                                bot.send_message(user_id, "🚫 Не удалось присоединиться — у вас нет прав на отправку сообщений в группе.")
                    except Exception as e:
                        logging.error(f"Ошибка при проверке прав доступа: {e}")
                        if lang == 'kz':
                            bot.send_message(user_id, "🚫 Қосылу мүмкін болмады")
                        if lang == 'ru':
                            bot.send_message(user_id, "🚫 Не удалось присоединиться")
                return

        bot_username = bot.get_me().username
        add_to_group_url = f'https://t.me/{bot_username}?startgroup=bot_command'

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton(content['add_to_group'], url=add_to_group_url))
        keyboard.add(types.InlineKeyboardButton(content['join_chat'], callback_data='join_chat'))
        keyboard.add(types.InlineKeyboardButton(content['news'], url='t.me/CityMafiaNews'))

        bot.send_message(chat_id, content['text'], reply_markup=keyboard, parse_mode="Markdown")

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
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    # Получаем язык из профиля для callback
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    lang = profile.get('language', 'ru')
    
    # Тексты для кнопок в зависимости от языка
    chat_list_text = {
        'kz': {
            'title': '*Чат тізімі*',
            'city_mafia': 'City Mafia Kazakhstan 🇰🇿',
            'golden_mafia': 'Golden Mafia KZ 🇰🇿'
        },
        'ru': {
            'title': '*Список чатов*',
            'city_mafia': 'City Mafia Kazakhstan 🇰🇿',
            'golden_mafia': 'Golden Mafia KZ 🇰🇿'
        }
    }
    content = chat_list_text[lang]

    bot.answer_callback_query(call.id, "Чатты таңдаңыз" if lang == 'kz' else "Выберите чат")
    
    keyboard = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton(content['city_mafia'], url='https://t.me/CityMafiaKZ')
    btn2 = types.InlineKeyboardButton(content['golden_mafia'], url='https://t.me/GMafiaKZ')
    keyboard.add(btn1)
    keyboard.add(btn2)

    send_message(chat_id, content['title'], reply_markup=keyboard, parse_mode="Markdown")


def update_registration_message(game_chat_id, chat):
    with lock:  # Гарантируем, что только один поток обновляет сообщение
        new_text = players_alive(chat.players, "registration", game_chat_id)

        lang = chat_settings.get(game_chat_id, {}).get("language", "kz")

        # Текст кнопки на нужном языке
        join_text = "🤵🏻 Қосылу" if lang == 'kz' else "🤵🏻 Присоединиться"

        new_markup = types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(join_text, url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}')]
        ])

        try:
            bot.edit_message_text(
                chat_id=game_chat_id,
                message_id=chat.button_id,
                text=new_text,
                reply_markup=new_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Ошибка обновления сообщения: {e}")

        # Удаляем таймер после обновления
        update_timers.pop(game_chat_id, None)

def schedule_update(game_chat_id, chat):
    if game_chat_id in update_timers:  
        # Если таймер уже запущен, отменяем его и создаем новый
        update_timers[game_chat_id].cancel()

    # Запускаем новый таймер на 1 секунду
    update_timers[game_chat_id] = threading.Timer(1.0, update_registration_message, args=(game_chat_id, chat))
    update_timers[game_chat_id].start()

@bot.message_handler(commands=['getstats'])
def get_stats(message):
    if message.from_user.id == admin_id:
        report = generate_stats_report()
        bot.send_message(admin_id, report, parse_mode="Markdown")
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
        
# Словари с переводами
TEXTS = {
    'kz': {
        'settings_title': "Чат баптаулары",
        'pin_reg': "📌 Тіркелуді бекіту",
        'admin_start': "👑 Ойынды тек әкімші бастайды",
        'leave_cmd': "🚪 /leave командасын қосу/өшіру",
        'mafia_count': "🤵 Мафия саны",
        'times': "⏱️ Уақыттар",
        'language': "🌐 Тілді өзгерту",
        'close': "❌ Жабу",
        'choose_lang': "Чат тілін таңдаңыз",
        'kazakh': "🇰🇿 Қазақша",
        'russian': "🇷🇺 Русский",
        'back': "🔙 Артқа",
        'group_only': "Бұл команданы тек топта қолдануға болады.",
        'pm_error': "Баптауларды жеке хабарламаға жіберу мүмкін емес. Бот сізге хабар жібере алатынын тексеріңіз.",
        'lang_changed': "Чат тілі өзгертілді!",
        'no_rights': "Баптауларды өзгерту құқығыңыз жоқ.",
        'time_reg': "⏰ Тіркелу уақыты",
        'time_night': "🌙 Түн уақыты",
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
        'yes': "✅ Иә",
        'no': "❌ Жоқ",
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
        'mafia_ratio_changed': "Мафия саны өзгертілді"
    },
    'ru': {
        'settings_title': "Настройки чата",
        'pin_reg': "📌 Закреплять регистрацию",
        'admin_start': "👑 Только админ запускает игру",
        'leave_cmd': "🚪 Включить/выключить /leave",
        'mafia_count': "🤵 Количество мафии",
        'times': "⏱️ Времена",
        'language': "🌐 Сменить язык",
        'close': "❌ Закрыть",
        'choose_lang': "Выберите язык чата",
        'kazakh': "🇰🇿 Қазақша",
        'russian': "🇷🇺 Русский",
        'back': "🔙 Назад",
        'group_only': "Эту команду можно использовать только в групповом чате.",
        'pm_error': "Не удалось отправить настройки в личные сообщения. Проверьте, что бот может писать вам.",
        'lang_changed': "Язык чата изменен!",
        'no_rights': "У вас нет прав для изменения настроек.",
        'time_reg': "⏰ Время регистрации",
        'time_night': "🌙 Ночное время",
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
        'yes': "✅ Да",
        'no': "❌ Нет",
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
        'mafia_ratio_changed': "Количество мафии изменено"
    }
}

def get_text(chat_id, key):
    """Получает текст на нужном языке"""
    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    return TEXTS[lang].get(key, key)

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
            "confirmation_time": 30,
            "mafia_ratio": 4
        }

    main_menu_kb = types.InlineKeyboardMarkup()
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'pin_reg'), callback_data=f"menu_pin_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'admin_start'), callback_data=f"menu_commands_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'leave_cmd'), callback_data=f"menu_leave_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'mafia_count'), callback_data=f"menu_mafia_ratio_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'times'), callback_data=f"menu_time_{chat_id}"))
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'language'), callback_data=f"menu_language_{chat_id}"))
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
    markup.add(
        types.InlineKeyboardButton(f"{'▪️' if lang == 'kz' else '▫️'} {get_text(chat_id, 'kazakh')}",
                                 callback_data=f"set_chat_lang_kz_{chat_id}"),
        types.InlineKeyboardButton(f"{'▪️' if lang == 'ru' else '▫️'} {get_text(chat_id, 'russian')}",
                                 callback_data=f"set_chat_lang_ru_{chat_id}")
    )
    markup.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
    
    bot.edit_message_text(get_text(chat_id, 'choose_lang'),
                         call.message.chat.id,
                         call.message.message_id,
                         reply_markup=markup)

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
    main_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'close'), callback_data=f"close_settings_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'),
                         chat_id=user_id,
                         message_id=call.message.message_id,
                         reply_markup=main_menu_kb)
    bot.answer_callback_query(call.id)

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

    bot.edit_message_text(get_text(chat_id, 'select_time'),
                         chat_id=user_id,
                         message_id=call.message.message_id,
                         reply_markup=time_menu_kb)
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
        confirmation_time_kb.add(
            types.InlineKeyboardButton(
                f"{selected} {option} {get_text(chat_id, 'sec')}",
                callback_data=f"set_confirmation_time_{option}_{chat_id}"
            )
        )
    confirmation_time_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'),
                         chat_id=user_id,
                         message_id=call.message.message_id,
                         reply_markup=confirmation_time_kb)
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
        voting_time_kb.add(
            types.InlineKeyboardButton(
                f"{selected} {option} {get_text(chat_id, 'sec')}",
                callback_data=f"set_voting_time_{option}_{chat_id}"
            )
        )
    voting_time_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'),
                         chat_id=user_id,
                         message_id=call.message.message_id,
                         reply_markup=voting_time_kb)
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
        day_time_kb.add(
            types.InlineKeyboardButton(
                f"{selected} {option} {get_text(chat_id, 'sec')}",
                callback_data=f"set_day_time_{option}_{chat_id}"
            )
        )
    day_time_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'),
                         chat_id=user_id,
                         message_id=call.message.message_id,
                         reply_markup=day_time_kb)
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

    time_options = [
        (120, 60), (180, 120), (240, 180), (300, 240),
        (360, 300), (420, 360), (480, 420), (540, 480), (600, 540)
    ]
    current_time = chat_settings[chat_id].get("registration_time", (120, 60))

    registration_kb = types.InlineKeyboardMarkup()
    for option in time_options:
        selected = "▪️" if option == current_time else "▫️"
        registration_kb.add(
            types.InlineKeyboardButton(
                f"{selected} {option[0]} / {option[1]} {get_text(chat_id, 'sec')}",
                callback_data=f"set_registration_time_{option[0]}_{option[1]}_{chat_id}"
            )
        )
    registration_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'),
                         chat_id=user_id,
                         message_id=call.message.message_id,
                         reply_markup=registration_kb)
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
        night_kb.add(
            types.InlineKeyboardButton(
                f"{selected} {option} {get_text(chat_id, 'sec')}",
                callback_data=f"set_night_time_{option}_{chat_id}"
            )
        )
    night_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"menu_time_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'select_option'),
                         chat_id=user_id,
                         message_id=call.message.message_id,
                         reply_markup=night_kb)
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

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_menu(call):
    user_id = call.from_user.id
    data = call.data
    chat_id = int(data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    if data.startswith("menu_pin_"):
        pin_status = get_text(chat_id, 'yes') if chat_settings[chat_id]['pin_registration'] else get_text(chat_id, 'no')
        pin_menu_kb = types.InlineKeyboardMarkup()
        pin_menu_kb.add(types.InlineKeyboardButton(pin_status, callback_data=f"toggle_pin_{chat_id}"))
        pin_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'pin_question'),
                            chat_id=user_id,
                            message_id=call.message.message_id,
                            reply_markup=pin_menu_kb)

    elif data.startswith("menu_leave_"):
        leave_status = get_text(chat_id, 'yes') if chat_settings[chat_id]['allow_leave_game'] else get_text(chat_id, 'no')
        leave_menu_kb = types.InlineKeyboardMarkup()
        leave_menu_kb.add(types.InlineKeyboardButton(leave_status, callback_data=f"toggle_leave_{chat_id}"))
        leave_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'leave_question'),
                            chat_id=user_id,
                            message_id=call.message.message_id,
                            reply_markup=leave_menu_kb)

    elif data.startswith("menu_commands_"):
        reg_status = get_text(chat_id, 'yes') if chat_settings[chat_id]['allow_registration'] else get_text(chat_id, 'no')
        commands_menu_kb = types.InlineKeyboardMarkup()
        commands_menu_kb.add(types.InlineKeyboardButton(reg_status, callback_data=f"toggle_reg_{chat_id}"))
        commands_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'admin_question'),
                            chat_id=user_id,
                            message_id=call.message.message_id,
                            reply_markup=commands_menu_kb)

    elif data.startswith("menu_mafia_ratio_"):
        current_ratio = chat_settings[chat_id]["mafia_ratio"]
        mafia_ratio_kb = types.InlineKeyboardMarkup()
        mafia_ratio_kb.add(
            types.InlineKeyboardButton(
                f"{'▪️' if current_ratio == 3 else '▫️'} {get_text(chat_id, 'more_mafia')}",
                callback_data=f"set_mafia_ratio_3_{chat_id}"
            )
        )
        mafia_ratio_kb.add(
            types.InlineKeyboardButton(
                f"{'▪️' if current_ratio == 4 else '▫️'} {get_text(chat_id, 'less_mafia')}",
                callback_data=f"set_mafia_ratio_4_{chat_id}"
            )
        )
        mafia_ratio_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'mafia_ratio_desc'),
                            chat_id=user_id,
                            message_id=call.message.message_id,
                            reply_markup=mafia_ratio_kb)

    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_pin_") or 
                                            call.data.startswith("toggle_leave_") or 
                                            call.data.startswith("toggle_reg_"))
def handle_admin_toggle(call):
    user_id = call.from_user.id
    data = call.data
    chat_id = int(data.split("_")[-1])

    if not is_admin_or_me(bot, chat_id, user_id):
        bot.answer_callback_query(call.id, get_text(chat_id, 'no_rights'))
        return

    if data.startswith("toggle_pin_"):
        chat_settings[chat_id]["pin_registration"] = not chat_settings[chat_id]["pin_registration"]
        new_state = get_text(chat_id, 'pin_enabled') if chat_settings[chat_id]["pin_registration"] else get_text(chat_id, 'pin_disabled')

        pin_menu_kb = types.InlineKeyboardMarkup()
        pin_menu_kb.add(
            types.InlineKeyboardButton(
                get_text(chat_id, 'yes') if chat_settings[chat_id]["pin_registration"] else get_text(chat_id, 'no'),
                callback_data=f"toggle_pin_{chat_id}"
            )
        )
        pin_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'pin_question'),
                            chat_id=user_id,
                            message_id=call.message.message_id,
                            reply_markup=pin_menu_kb)
        bot.answer_callback_query(call.id, new_state)

    elif data.startswith("toggle_leave_"):
        chat_settings[chat_id]["allow_leave_game"] = not chat_settings[chat_id]["allow_leave_game"]
        new_state = get_text(chat_id, 'leave_enabled') if chat_settings[chat_id]["allow_leave_game"] else get_text(chat_id, 'leave_disabled')

        leave_menu_kb = types.InlineKeyboardMarkup()
        leave_menu_kb.add(
            types.InlineKeyboardButton(
                get_text(chat_id, 'yes') if chat_settings[chat_id]["allow_leave_game"] else get_text(chat_id, 'no'),
                callback_data=f"toggle_leave_{chat_id}"
            )
        )
        leave_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'leave_question'),
                            chat_id=user_id,
                            message_id=call.message.message_id,
                            reply_markup=leave_menu_kb)
        bot.answer_callback_query(call.id, new_state)

    elif data.startswith("toggle_reg_"):
        chat_settings[chat_id]["allow_registration"] = not chat_settings[chat_id]["allow_registration"]
        new_state = get_text(chat_id, 'admin_only_enabled') if chat_settings[chat_id]["allow_registration"] else get_text(chat_id, 'admin_only_disabled')

        commands_menu_kb = types.InlineKeyboardMarkup()
        commands_menu_kb.add(
            types.InlineKeyboardButton(
                get_text(chat_id, 'yes') if chat_settings[chat_id]["allow_registration"] else get_text(chat_id, 'no'),
                callback_data=f"toggle_reg_{chat_id}"
            )
        )
        commands_menu_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))
        bot.edit_message_text(get_text(chat_id, 'admin_question'),
                            chat_id=user_id,
                            message_id=call.message.message_id,
                            reply_markup=commands_menu_kb)
        bot.answer_callback_query(call.id, new_state)

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
    mafia_ratio_kb.add(
        types.InlineKeyboardButton(
            f"{'▪️' if ratio == 3 else '▫️'} {get_text(chat_id, 'more_mafia')}",
            callback_data=f"set_mafia_ratio_3_{chat_id}"
        )
    )
    mafia_ratio_kb.add(
        types.InlineKeyboardButton(
            f"{'▪️' if ratio == 4 else '▫️'} {get_text(chat_id, 'less_mafia')}",
            callback_data=f"set_mafia_ratio_4_{chat_id}"
        )
    )
    mafia_ratio_kb.add(types.InlineKeyboardButton(get_text(chat_id, 'back'), callback_data=f"main_menu_{chat_id}"))

    bot.edit_message_text(get_text(chat_id, 'mafia_ratio_desc'),
                        chat_id=user_id,
                        message_id=call.message.message_id,
                        reply_markup=mafia_ratio_kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("close_settings_"))
def handle_close_settings(call):
    chat_id = int(call.data.split("_")[-1])
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.answer_callback_query(call.id, get_text(chat_id, 'menu_closed'))

@bot.message_handler(commands=['game'])
def create_game(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверяем, что команда вызвана в групповом чате
    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, "Эту команду можно использовать только в групповом чате.")
        return

    # Пытаемся удалить сообщение
    try:
        bot.delete_message(chat_id, message.message_id)
    except telebot.apihelper.ApiTelegramException as e:
        if "message to delete not found" in str(e):
            print(f"Сообщение не найдено для удаления: chat_id={chat_id}, message_id={message.message_id}")
        else:
            raise

    # Получаем список админов
    chat_admins = bot.get_chat_administrators(chat_id)
    admin_ids = [admin.user.id for admin in chat_admins]

    # Инициализация настроек чата
    if chat_id not in chat_settings:
        chat_settings[chat_id] = {
            "language": "ru",
            "allow_registration": True,
            "pin_registration": True,
            "allow_leave_game": True,
            "registration_time": (120, 60),
            "night_time": 45,
            "day_time": 60,
            "voting_time": 45,
            "confirmation_time": 30,
            "mafia_ratio": 4
        }

    chat_settings[chat_id].setdefault("allow_registration", True)
    chat_settings[chat_id].setdefault("pin_registration", False)
    chat_settings[chat_id].setdefault("allow_leave_game", True)

    # Проверка разрешения на регистрацию
    if not chat_settings[chat_id]["allow_registration"] and user_id not in admin_ids:
        return

    # Создание игры, если её ещё нет
    if chat_id not in chat_list:
        chat_list[chat_id] = Game(chat_id)

    chat = chat_list[chat_id]

    if chat.game_running or chat.button_id:
        return

    with registration_lock:
        if chat.button_id:
            return

        # Получаем язык чата
        lang = chat_settings.get(chat_id, {}).get("language", "ru")

        # Текст кнопки на нужном языке
        join_text = "🤵🏻 Қосылу" if lang == 'kz' else "🤵🏻 Присоединиться"

        # Создание кнопки и отправка сообщения
        join_btn = types.InlineKeyboardMarkup()
        bot_username = bot.get_me().username
        join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
        item1 = types.InlineKeyboardButton(join_text, url=join_url)
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

        # Настройка таймеров
        registration_time = chat_settings[chat_id]["registration_time"]
        total_time = registration_time[0]

        if chat_id not in notification_timers:
            notification_timers[chat_id] = {}

        notification_timers[chat_id]['59_seconds'] = threading.Timer(
            total_time - 59,
            lambda: notify_at_59_seconds(chat_id)
        )
        notification_timers[chat_id]['59_seconds'].start()

        notification_timers[chat_id]['29_seconds'] = threading.Timer(
            total_time - 29,
            lambda: notify_at_29_seconds(chat_id)
        )
        notification_timers[chat_id]['29_seconds'].start()

        game_start_timers[chat_id] = threading.Timer(
            total_time, lambda: start_game_with_delay(chat_id)
        )
        game_start_timers[chat_id].start()

        
def escape_markdown(text):
    # Экранируем специальные символы Markdown
    specials = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in specials else char for char in text)

@bot.message_handler(commands=['profile'])
def handle_profile(message):
    if message.chat.type == 'private':
        user_id = message.from_user.id
        user_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
        show_profile(message, user_id=user_id, user_name=user_name)

# В функции show_profile изменим клавиатуру:
def show_profile(message, user_id, message_id=None, user_name=None):
    if not user_name:
        user_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()

    profile = get_or_create_profile(user_id, user_name)
    check_vip_expiry(profile)
    
    # Получаем текущий язык из профиля (по умолчанию казахский)
    lang = profile.get('language', 'ru')

    if profile.get('vip_until'):
        vip_expiry = datetime.strptime(profile['vip_until'], '%Y-%m-%d %H:%M:%S')
        formatted_date = vip_expiry.strftime('%d.%m.%Y')
        vip_status = f"{formatted_date}"
    else:
        vip_status = "❌"

    # Тексты на разных языках
    texts = {
        'kz': {
            'profile': f"*Бейініңіз*\n\n"
                       f"👤 {escape_markdown(user_name)}\n"
                       f"🪪 ID: `{user_id}`\n\n"
                       f"💶 Еуро: {escape_markdown(str(profile['euro']))}\n"
                       f"🪙 Тиын: {escape_markdown(str(profile['coins']))}\n\n"
                       f"⚔️ Қорғаныс: {escape_markdown(str(profile['shield']))}\n"
                       f"📁 Құжат: {escape_markdown(str(profile['fake_docs']))}\n"
                       f"🔫 Тапанша: {escape_markdown(str(profile['gun']))}\n"
                       f"⚖️ Дарға қарсы қорғаныс: {escape_markdown(str(profile.get('hanging_shield', 0)))}\n\n"
                       f"👑 VIP-дәреже: {vip_status}",
            'buttons': {
                'shop': "🛒 Дүкен",
                'buy_coins': "Сатып алу 🪙",
                'exchange': "💰 Алмастыру",
                'settings': "⚙️ Баптаулар",
                'djekpot': "🎰 Джекпот"
            }
        },
        'ru': {
            'profile': f"*Ваш профиль*\n\n"
                       f"👤 {escape_markdown(user_name)}\n"
                       f"🪪 ID: `{user_id}`\n\n"
                       f"💶 Евро: {escape_markdown(str(profile['euro']))}\n"
                       f"🪙 Монеты: {escape_markdown(str(profile['coins']))}\n\n"
                       f"⚔️ Защита: {escape_markdown(str(profile['shield']))}\n"
                       f"📁 Документы: {escape_markdown(str(profile['fake_docs']))}\n"
                       f"🔫 Пистолет: {escape_markdown(str(profile['gun']))}\n"
                       f"⚖️ Защита от повешения: {escape_markdown(str(profile.get('hanging_shield', 0)))}\n\n"
                       f"👑 VIP-статус: {vip_status}",
            'buttons': {
                'shop': "🛒 Магазин",
                'buy_coins': "Купить 🪙",
                'exchange': "💰 Обмен",
                'settings': "⚙️ Настройки",
                'djekpot': "🎰 Джекпот"
            }
        }
    }

    # Создаем клавиатуру
    markup = types.InlineKeyboardMarkup(row_width=2)
    shop_btn = types.InlineKeyboardButton(texts[lang]['buttons']['shop'], callback_data="shop")
    buy_coins_btn = types.InlineKeyboardButton(texts[lang]['buttons']['buy_coins'], callback_data="buy_coins")
    exchange_btn = types.InlineKeyboardButton(texts[lang]['buttons']['exchange'], callback_data="exchange")
    settings_btn = types.InlineKeyboardButton(texts[lang]['buttons']['settings'], callback_data="settings")
    djekpot_btn = types.InlineKeyboardButton(texts[lang]['buttons']['djekpot'], callback_data="djekpot")
    
    markup.add(shop_btn, buy_coins_btn)
    markup.add(exchange_btn, settings_btn)
    markup.add(djekpot_btn)

    # Отправляем или редактируем сообщение
    if message_id:
        bot.edit_message_text(chat_id=message.chat.id, message_id=message_id, 
                             text=texts[lang]['profile'], reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, texts[lang]['profile'], reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == 'djekpot')
def handle_djekpot_info(call):
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
    profile = get_or_create_profile(user_id, user_name)
    lang = profile.get('language', 'ru')

    texts = {
        'ru': {
            'info': "🎰 *Джекпот*\n\n"
                    "Заплати 2 монеты и выиграй случайный приз:\n"
                    "- 👑 VIP\n"
                    "- 🪙 Монеты\n"
                    "- 💶 Евро\n"
                    "- ⚔️ Защита\n"
                    "- 📁 Документы\n"
                    "- 🔫 Пистолет\n"
                    "- ⚖️ Защита от повешения",
            'spin': "Крутить за 2 🪙",
            'back': "🔙 Назад"
        },
        'kz': {
            'info': "🎰 *Джекпот*\n\n"
                    "2 монета төлеп, кездейсоқ сыйлықты ұтып алыңыз:\n"
                    "- 👑 VIP\n"
                    "- 🪙 Монета\n"
                    "- 💶 Еуро\n"
                    "- ⚔️ Қорғаныс\n"
                    "- 📁 Құжат\n"
                    "- 🔫 Тапанша\n"
                    "- ⚖️ Дардан қорғаныс",
            'spin': "2🪙 Айналдыру",
            'back': "🔙 Артқа"
        }
    }

    new_text = texts[lang]['info']

    markup = types.InlineKeyboardMarkup()
    spin_btn = types.InlineKeyboardButton(texts[lang]['spin'], callback_data='spin_jackpot')
    back_btn = types.InlineKeyboardButton(texts[lang]['back'], callback_data='back_to_profile')
    markup.add(spin_btn)
    markup.add(back_btn)

    try:
        if call.message.text != new_text or call.message.reply_markup != markup:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=new_text,
                reply_markup=markup,
                parse_mode="Markdown"
            )
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e):
            raise


def roll_jackpot(profile, lang):
    prizes = [
        'vip',
        'coins',
        'euro',
        'shield',
        'fake_docs',
        'gun',
        'hanging_shield'
    ]

    weights = [10, 10, 25, 25, 25, 25, 25]  # редкие: vip и coins

    prize = random.choices(prizes, weights=weights, k=1)[0]

    labels = {
        'ru': {
            'vip': '👑 VIP',
            'coins': '🪙 Монеты',
            'euro': '💶 Евро',
            'shield': '⚔️ Защита',
            'fake_docs': '📁 Документы',
            'gun': '🔫 Пистолет',
            'hanging_shield': '⚖️ Защита от повешения'
        },
        'kz': {
            'vip': '👑 VIP',
            'coins': '🪙 Монета',
            'euro': '💶 Еуро',
            'shield': '⚔️ Қорғаныс',
            'fake_docs': '📁 Құжат',
            'gun': '🔫 Тапанша',
            'hanging_shield': '⚖️ Дардан қорғаныс'
        }
    }

    prize_text = labels[lang].get(prize, prize)

    if prize == 'vip':
        days = random.randint(1, 4)
        profile['vip_until'] = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        prize_text += f' на {days} д.' if lang == 'ru' else f' {days} күнге'
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
    lang = profile.get('language', 'ru')

    texts = {
        'ru': {
            'no_coins': "❌ У вас недостаточно монет",
            'win': "🎰 Вы выиграли: {}!"
        },
        'kz': {
            'no_coins': "❌ Монета жеткіліксіз",
            'win': "🎰 Сіз ұтып алдыңыз: {}!"
        }
    }

    if profile['coins'] < 2:
        bot.answer_callback_query(call.id, texts[lang]['no_coins'], show_alert=True)
        return

    profile['coins'] -= 2
    prize, prize_text = roll_jackpot(profile, lang)
    update_profile(user_id, profile)

    win_message = texts[lang]['win'].format(prize_text)
    bot.answer_callback_query(call.id, win_message, show_alert=True)

    # Обновить меню (опционально, или можно не вызывать если не хочешь менять экран)
    handle_djekpot_info(call)


# Добавим новый обработчик для меню настроек
@bot.callback_query_handler(func=lambda call: call.data == 'settings')
def handle_settings(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    lang = profile.get('language', 'ru')
    
    texts = {
        'kz': {
            'title': "⚙️ *Баптаулар*",
            'shield': f"⚔️ Қорғаныс {'🟢 ON' if profile.get('shield_active', True) else '🔴 OFF'}",
            'docs': f"📁 Құжат {'🟢 ON' if profile.get('docs_active', True) else '🔴 OFF'}",
            'hanging': f"⚖️ Дарға қарсы {'🟢 ON' if profile.get('hanging_shield_active', True) else '🔴 OFF'}",
            'language': f"🌐 Тіл: {'🇰🇿 Қазақша' if lang == 'kz' else '🇷🇺 Орысша'}",
            'back': "🔙 Артқа"
        },
        'ru': {
            'title': "⚙️ *Настройки*",
            'shield': f"⚔️ Защита {'🟢 ON' if profile.get('shield_active', True) else '🔴 OFF'}",
            'docs': f"📁 Документы {'🟢 ON' if profile.get('docs_active', True) else '🔴 OFF'}",
            'hanging': f"⚖️ Защита от повешения {'🟢 ON' if profile.get('hanging_shield_active', True) else '🔴 OFF'}",
            'language': f"🌐 Язык: {'🇰🇿 Казахский' if lang == 'kz' else '🇷🇺 Русский'}",
            'back': "🔙 Назад"
        }
    }

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(texts[lang]['shield'], callback_data="toggle_shield"))
    markup.add(types.InlineKeyboardButton(texts[lang]['docs'], callback_data="toggle_docs"))
    markup.add(types.InlineKeyboardButton(texts[lang]['hanging'], callback_data="toggle_hanging"))
    markup.add(types.InlineKeyboardButton(texts[lang]['language'], callback_data="change_language"))
    markup.add(types.InlineKeyboardButton(texts[lang]['back'], callback_data="back_to_profile"))

    bot.edit_message_text(texts[lang]['title'], chat_id=call.message.chat.id, 
                         message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")


# Добавим обработчик для смены языка
@bot.callback_query_handler(func=lambda call: call.data == 'change_language')
def handle_change_language(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    lang = profile.get('language', 'ru')

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="set_lang_ru"),
        types.InlineKeyboardButton("🇰🇿 Қазақша", callback_data="set_lang_kz")
    )
    markup.add(types.InlineKeyboardButton("🔙 Назад" if lang == 'ru' else "🔙 Артқа", callback_data="back_to_settings"))

    bot.edit_message_text("🌐 Тілді таңдаңыз / Выберите язык", 
                          chat_id=call.message.chat.id, 
                          message_id=call.message.message_id,
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data in ['set_lang_ru', 'set_lang_kz'])
def handle_set_language(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)

    new_lang = 'ru' if call.data == 'set_lang_ru' else 'kz'
    profile['language'] = new_lang

    bot.answer_callback_query(call.id, f"Язык изменен на {'русский' if new_lang == 'ru' else 'қазақша'}")

    # Возвращаемся в настройки
    handle_settings(call)

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_settings')
def back_to_settings(call):
    handle_settings(call)

# Обновим обработчики переключателей защиты
@bot.callback_query_handler(func=lambda call: call.data in ['toggle_shield', 'toggle_docs', 'toggle_hanging'])
def handle_toggle_protections(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    
    toggle_map = {
        "toggle_shield": "shield_active",
        "toggle_docs": "docs_active",
        "toggle_hanging": "hanging_shield_active"
    }

    if call.data in toggle_map:
        key = toggle_map[call.data]
        profile[key] = not profile.get(key, True)
        
        # Возвращаемся в меню настроек
        handle_settings(call)
        
        lang = profile.get('language', 'ru')
        status_text = {
            'kz': {
                'shield': "Қорғаныс",
                'docs': "Құжат",
                'hanging': "Дарға қарсы қорғаныс"
            },
            'ru': {
                'shield': "Защита",
                'docs': "Документы",
                'hanging': "Защита от повешения"
            }
        }
        
        item = call.data.split('_')[1]
        state = "✅" if profile[key] else "❌" if lang == 'kz' else "✅" if profile[key] else "❌"
        bot.answer_callback_query(call.id, f"{status_text[lang][item]} {state}")




@bot.callback_query_handler(
    func=lambda call: call.data in [
        'shop', 
        'buy_shield', 
        'buy_fake_docs', 
        'buy_gun', 
        'buy_hanging_shield', 
        'back_to_profile', 
        'renew_vip', 
        'buy_vip'
    ]
)
def handle_shop_actions(call):
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
    profile = get_or_create_profile(user_id, user_name)
    lang = profile.get('language', 'ru')

    texts = {
        'kz': {
            'shop_title': "🛒 *Дүкен*",
            'balance': f"💶 _Еуро_: {escape_markdown(str(profile['euro']))}\n🪙 _Тиын_: {escape_markdown(str(profile['coins']))}",
            'shield_desc': "⚔️ *Қорғаныс*\nбіреу-міреу сізді өлтіреміз деп шабуылдаса, қалқан сізді бір мәрте құтқарып қала алады.",
            'docs_desc': "📁 *Құжат*\nкомиссарға қарсы рөлдерге арналған (Дон, Мафия ж/е т. б.). Комиссар сізді тексерем десе, сізді ол бейбіт тұрғын ретінде көреді.",
            'hanging_desc': "⚖️ *Дарға қарсы қорғаныс*\nДарға асылып қалудан сақтап қалады.\nОсы дүниені сатып алсаңыз, тіпті барлығы сізге қарсы келген кезде де, ешкім сізді асып өлтіре алмайды!",
            'gun_desc': "🔫 *Тапанша*\nТүн жамылып, кез келген ойыншыны өлтіруге мүмкіндік береді.",
            'vip_desc': "👑 *7 күндік VIP-дәреже*\nVIP-дәрежені алған соң:\n- Жеңген сайын 💶 15 алып отырасыз\n- Жеңіліп қалсаңыз 💶 10 бонус аласыз\n- Тірі ойыншылар тізімінде атыңыздың жанында осындай 👑 белгі тұрады\n- Зат сатып алу 🔫 Тапанша аласыз\n- 🪽Қалқанды ойын барысында екі рет пайдалана аласыз",
            'buttons': {
                'shield': "⚔️ Қорғаныс - 💶 100",
                'docs': "📁 Құжат - 💶 150",
                'gun': "🔫 Тапанша - 💶 600",
                'hanging': "⚖️ Дарға қарсы қорғаныс - 🪙 1",
                'buy_vip': "👑 VIP сатып алy - 7 🪙",
                'renew_vip': "👑 VIP жаңарту - 4 🪙",
                'back': "🔙 Артқа"
            },
            'purchase': {
                'success': "✅ Сатып алу сәтті аяқталды",
                'no_money': "❌ Сатып алуға ақшаңыз жетпейді",
                'vip_only': "❌ Тек VIP-терге ғана қолжетімді!",
                'shield': "✅ Сатып алу сәтті аяқталды",
                'docs': "✅ Сатып алу сәтті аяқталды",
                'hanging': "✅ Сатып алу сәтті аяқталды",
                'vip_bought': "👑 VIP дәрежесі 7 күнге іске қосылды!",
                'vip_renewed': "👑 VIP мәртебеңіз 7 күнге ұзартылды!"
            }
        },
        'ru': {
            'shop_title': "🛒 *Магазин*",
            'balance': f"💶 _Евро_: {escape_markdown(str(profile['euro']))}\n🪙 _Монеты_: {escape_markdown(str(profile['coins']))}",
            'shield_desc': "⚔️ *Защита*\nЕсли кто-то нападет на вас, щит может один раз спасти вас.",
            'docs_desc': "📁 *Документы*\nДля ролей против комиссара (Дон, Мафия и т.д.). Если комиссар проверит вас, он увидит вас как мирного жителя.",
            'hanging_desc': "⚖️ *Защита от повешения*\nСпасет вас от повешения",
            'gun_desc': "🔫 *Пистолет*\nПозволяет ночью убить любого игрока.",
            'vip_desc': "👑 *7-дневный VIP-статус*\nС VIP-статусом:\n– За победу получаете 💶 15\n– За поражение получаете 💶 10 бонус\n– Рядом с вашим именем в списке живых игроков будет отображаться такой знак 👑\n– При VIP вы можете купить 🔫 Пистолет\n– 🪽 Щит можно использовать дважды в течение игры",
            'buttons': {
                'shield': "⚔️ Защита - 💶 100",
                'docs': "📁 Документы - 💶 150",
                'gun': "🔫 Пистолет - 💶 600",
                'hanging': "⚖️ Защита от повешения - 🪙 1",
                'buy_vip': "👑 Купить VIP - 7 🪙",
                'renew_vip': "👑 Продлить VIP - 4 🪙",
                'back': "🔙 Назад"
            },
            'purchase': {
                'success': "✅ Покупка успешно завершена",
                'no_money': "❌ Недостаточно средств для покупки",
                'vip_only': "❌ Доступно только для VIP!",
                'shield': "✅ Покупка успешно завершена",
                'docs': "✅ Покупка успешно завершена",
                'hanging': "✅ Покупка успешно завершена",
                'vip_bought': "👑 VIP-статус активирован на 7 дней!",
                'vip_renewed': "👑 Ваш VIP-статус продлен на 7 дней!"
            }
        }
    }

    t = texts[lang]

    if call.data == "shop":
        shop_text = f"{t['shop_title']}\n\n{t['balance']}\n\n{t['shield_desc']}\n\n{t['docs_desc']}\n\n{t['hanging_desc']}\n\n{t['gun_desc']}\n\n{t['vip_desc']}"

        markup = types.InlineKeyboardMarkup()
        buy_shield_btn = types.InlineKeyboardButton(t['buttons']['shield'], callback_data="buy_shield")
        buy_docs_btn = types.InlineKeyboardButton(t['buttons']['docs'], callback_data="buy_fake_docs")
        buy_gun_btn = types.InlineKeyboardButton(t['buttons']['gun'], callback_data="buy_gun")
        buy_hanging_shield_btn = types.InlineKeyboardButton(t['buttons']['hanging'], callback_data="buy_hanging_shield")

        if profile.get('vip_until'):
            buy_vip_btn = types.InlineKeyboardButton(t['buttons']['renew_vip'], callback_data="renew_vip")
        else:
            buy_vip_btn = types.InlineKeyboardButton(t['buttons']['buy_vip'], callback_data="buy_vip")

        back_btn = types.InlineKeyboardButton(t['buttons']['back'], callback_data="back_to_profile")
        markup.add(buy_shield_btn)
        markup.add(buy_docs_btn)
        markup.add(buy_hanging_shield_btn)
        markup.add(buy_vip_btn)
        markup.add(buy_gun_btn)
        markup.add(back_btn)

        bot.edit_message_text(shop_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "buy_gun":
        if not profile.get('vip_until'):
            bot.answer_callback_query(call.id, t['purchase']['vip_only'], show_alert=True)
            return
            
        if profile['euro'] >= 600:
            profile['euro'] -= 600
            profile['gun'] += 1
            
            bot.answer_callback_query(call.id, t['purchase']['success'], show_alert=True)
            
        else:
            bot.answer_callback_query(call.id, t['purchase']['no_money'], show_alert=True)

    elif call.data == "buy_shield":
        if profile['euro'] >= 100:
            profile['euro'] -= 100
            profile['shield'] += 1

            bot.answer_callback_query(call.id, t['purchase']['shield'], show_alert=True)
        else:
            bot.answer_callback_query(call.id, t['purchase']['no_money'], show_alert=True)

    elif call.data == "buy_fake_docs":
        if profile['euro'] >= 150:
            profile['euro'] -= 150
            profile['fake_docs'] += 1

            bot.answer_callback_query(call.id, t['purchase']['docs'], show_alert=True)
        else:
            bot.answer_callback_query(call.id, t['purchase']['no_money'], show_alert=True)

    elif call.data == "buy_vip":
        if profile['coins'] >= 7:
            profile['coins'] -= 7
            profile['vip_until'] = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

            bot.answer_callback_query(call.id, t['purchase']['vip_bought'], show_alert=True)
            
        else:
            bot.answer_callback_query(call.id, t['purchase']['no_money'], show_alert=True)

    elif call.data == "renew_vip":
        if profile['coins'] >= 4:
            profile['coins'] -= 4
            current_vip = datetime.strptime(profile['vip_until'], '%Y-%m-%d %H:%M:%S')
            new_vip_until = current_vip + timedelta(days=7)
            profile['vip_until'] = new_vip_until.strftime('%Y-%m-%d %H:%M:%S')

            bot.answer_callback_query(call.id, t['purchase']['vip_renewed'], show_alert=True)
        else:
            bot.answer_callback_query(call.id, t['purchase']['no_money'], show_alert=True)

    elif call.data == "buy_hanging_shield":
        if profile['coins'] >= 1:
            profile['coins'] -= 1
            profile['hanging_shield'] += 1

            bot.answer_callback_query(call.id, t['purchase']['hanging'], show_alert=True)
        else:
            bot.answer_callback_query(call.id, t['purchase']['no_money'], show_alert=True)

    elif call.data == "back_to_profile":
        show_profile(call.message, message_id=call.message.message_id, user_id=user_id, user_name=user_name)

def notify_vip_expiry():
    for user_id, profile in player_profiles.items():
        vip_until = profile.get('vip_until')
        if vip_until:
            vip_expiry = datetime.strptime(vip_until, '%Y-%m-%d %H:%M:%S')
            days_left = (vip_expiry - datetime.now()).days
            if days_left == 1:
                send_message(user_id, "⚠️ Сіздің VIP-статусыңыз ертең аяқталады. Оны дүкеннен ұзартуды ұмытпаңыз!")


@bot.callback_query_handler(func=lambda call: call.data in ['exchange', 'exchange_1', 'exchange_2', 'exchange_5', 'exchange_10'])
def handle_exchange(call):
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
    profile = get_or_create_profile(user_id, user_name)
    lang = profile.get('language', 'ru')

    texts = {
        'kz': {
            'title': "💰 *Алмастыру*",
            'balance': f"💶 _Еуро_: {profile['euro']}\n🪙 _Тиын_: {profile['coins']}",
            'choose': "Алмастыру опциясын таңдаңыз:",
            'success': "✅ Алмастыру сәтті өтті!",
            'no_coins': "❌ Тиын жеткіліксіз!",
            'rates': [
                ("1🪙 → 150💶", "exchange_1"),
                ("2🪙 → 300💶", "exchange_2"),
                ("5🪙 → 750💶", "exchange_5"),
                ("10🪙 → 1500💶", "exchange_10")
            ],
            'back': "🔙 Артқа"
        },
        'ru': {
            'title': "💰 *Обмен*",
            'balance': f"💶 _Евро_: {profile['euro']}\n🪙 _Монеты_: {profile['coins']}",
            'choose': "Выберите вариант обмена:",
            'success': "✅ Обмен успешно завершен!",
            'no_coins': "❌ Недостаточно монет!",
            'rates': [
                ("1🪙 → 150💶", "exchange_1"),
                ("2🪙 → 300💶", "exchange_2"),
                ("5🪙 → 750💶", "exchange_5"),
                ("10🪙 → 1500💶", "exchange_10")
            ],
            'back': "🔙 Назад"
        }
    }

    t = texts[lang]
    exchange_rates = {
        'exchange_1': (1, 150),
        'exchange_2': (2, 300),
        'exchange_5': (5, 750),
        'exchange_10': (10, 1500)
    }

    if call.data == 'exchange':
        exchange_text = f"{t['title']}\n{t['balance']}\n\n{t['choose']}"

        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [types.InlineKeyboardButton(text, callback_data=data) for text, data in t['rates']]
        markup.add(*buttons[:2])
        markup.add(*buttons[2:])
        markup.add(types.InlineKeyboardButton(t['back'], callback_data="back_to_profile"))

        bot.edit_message_text(exchange_text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=markup, parse_mode="Markdown")

    elif call.data in exchange_rates:
        coins_needed, euros_received = exchange_rates[call.data]

        if profile['coins'] >= coins_needed:
            profile['coins'] -= coins_needed
            profile['euro'] += euros_received

            bot.answer_callback_query(call.id, t['success'], show_alert=True)
        else:
            bot.answer_callback_query(call.id, t['no_coins'], show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == 'buy_coins')
def handle_buy_coins(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    lang = profile.get('language', 'ru')

    texts = {
        'kz': {
            'title': "💰 *Тиын сатып алу*",
            'choose': "Төлем әдісін таңдаңыз:",
            'card': "💳 Қартымен төлеу",
            'stars': "⭐️ Telegram Stars",
            'back': "🔙 Артқа"
        },
        'ru': {
            'title': "💰 *Покупка монет*",
            'choose': "Выберите способ оплаты:",
            'card': "💳 Оплата картой",
            'stars': "⭐️ Telegram Stars",
            'back': "🔙 Назад"
        }
    }

    t = texts[lang]

    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(t['card'], callback_data="pay_with_card")
    )
    markup.add(
        types.InlineKeyboardButton(t['stars'], callback_data="pay_with_stars")
    )
    markup.add(
        types.InlineKeyboardButton(t['back'], callback_data="back_to_profile")
    )

    bot.edit_message_text(
        f"{t['title']}\n{t['choose']}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'pay_with_card')
def handle_card_payment(call):
    user_id = call.from_user.id
    profile = get_or_create_profile(user_id, call.from_user.first_name)
    lang = profile.get('language', 'ru')

    texts = {
        'kz': {
            'title': "💳 *Қартымен төлеу*",
            'text': "🌍 *Төлемдерді қолмен қабылдаймыз*\nҚазір біз қолдау чаты арқылы төлемді қабылдай аламыз.",
            'pay': "Төлем жасау",
            'back': "🔙 Артқа"
        },
        'ru': {
            'title': "💳 *Оплата картой*",
            'text': "🌍 *Принимаем платежи вручную*\nСейчас мы можем принимать платежи через чат поддержки.",
            'pay': "Сделать платеж",
            'back': "🔙 Назад"
        }
    }

    t = texts[lang]

    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(t['pay'], url="https://t.me/CityMafiaSupport")
    )
    markup.add(
        types.InlineKeyboardButton(t['back'], callback_data="buy_coins")
    )

    bot.edit_message_text(
        text=f"{t['title']}\n\n{t['text']}",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )



@bot.callback_query_handler(func=lambda call: call.data == 'pay_with_stars')
def show_stars_options(call):
    bot.answer_callback_query(call.id)
    rates = [
        ("1 🪙 → 20 ⭐️", 1, 20),
        ("2 🪙 → 40 ⭐️", 2, 40),
        ("5 🪙 → 90 ⭐️", 5, 90),
        ("10 🪙 → 165 ⭐️", 10, 165),
        ("20 🪙 → 305 ⭐️", 20, 305),
        ("50 🪙 → 703 ⭐️", 50, 703),
        ("100 🪙 → 1344 ⭐️", 100, 1344),
        ("200 🪙 → 2688 ⭐️", 200, 2688)
    ]
    
    # Получаем язык пользователя (по умолчанию казахский)
    lang = call.from_user.language_code
    texts = {
        'kz': "🪙 Telegram Stars арқылы төлеу:",
        'ru': "🪙 Оплата через Telegram Stars:"
    }

    markup = types.InlineKeyboardMarkup(row_width=2)
    for text, coins, stars in rates:
        markup.add(types.InlineKeyboardButton(text, callback_data=f"stars:{coins}:{stars}"))
    markup.add(types.InlineKeyboardButton("🔙 Артқа" if lang == 'kz' else "🔙 Назад", callback_data="buy_coins"))

    bot.edit_message_text(
        texts.get(lang, texts['ru']),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('stars:'))
def process_stars_payment(call):
    bot.answer_callback_query(call.id)
    try:
        _, coins, stars = call.data.split(':')
        coins = int(coins)
        stars = int(stars)
        
        # Валидация данных
        valid_rates = {1: 20, 2: 40, 5: 90, 10: 165, 20: 305, 50: 703, 100: 1344, 200: 2688}
        if coins not in valid_rates or stars != valid_rates[coins]:
            raise ValueError("Invalid rate")

        # Преобразование в копейки
        total_amount = stars * 1  # (1 звезда = 1 единица валюты)

        # Создание платежа
        bot.send_invoice(
            call.message.chat.id,
            title=f"🪙 coins",
            description=f"Покупка — {coins} 🪙",
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency='XTR',
            prices=[LabeledPrice(label=f"{coins} Тиын", amount=total_amount)],
            invoice_payload=f"stars_{coins}_{stars}"
        )
        
    except Exception as e:
        logging.error(f"Payment error: {e}")
        lang = call.from_user.language_code
        texts = {
            'kz': "⚠️ Платеж временно недоступен",
            'ru': "⚠️ Платеж временно недоступен"
        }
        bot.answer_callback_query(call.id, text=texts.get(lang, texts['kz']), show_alert=True)


@bot.message_handler(content_types=['successful_payment'])
def handle_payment(message):
    try:
        payload = message.successful_payment.invoice_payload
        if payload.startswith("stars_"):
            _, coins, stars = payload.split('_')
            coins = int(coins)
            
            profile = get_or_create_profile(message.from_user.id, message.from_user.first_name)
            profile['coins'] += coins
            
            # Получаем язык пользователя (по умолчанию казахский)
            lang = message.from_user.language_code
            texts = {
                'kz': f"✅ Төлем сәтті аяқталды!\nҚосылды: {coins} 🪙\nЖаңа баланс: {profile['coins']}",
                'ru': f"✅ Платеж успешно завершен!\nДобавлено: {coins} 🪙\nНовый баланс: {profile['coins']}"
            }

            bot.send_message(
                message.chat.id,
                texts.get(lang, texts['kz']),
                parse_mode="Markdown"
            )
            
            # Уведомление админу
            admin_msg = f"💰 Жаңа төлем:\n@{message.from_user.username}\n{coins} тиын ({stars} Stars)"
            bot.send_message(ADMIN_ID, admin_msg)
    except Exception as e:
        logging.error(f"Payment processing error: {e}")


@bot.message_handler(commands=['help'])
def send_help(message):
    if message.chat.type == 'private':
        user_id = message.from_user.id
        profile = get_or_create_profile(user_id, message.from_user.first_name)
        lang = profile.get('language', 'kz')  # Получаем язык из профиля

        # Тексты на разных языках
        texts = {
            'kz': {
                'title': '🗂️ *Сілтемелер*',
                'support': '🛠️ Техникалық көмек',
                'how_to_play': 'Қалай ойнау керек?',
                'roles': '🤵🏻 Рөлдер'
            },
            'ru': {
                'title': '🗂️ *Ссылки*',
                'support': '🛠️ Техническая помощь',
                'how_to_play': 'Как играть?',
                'roles': '🤵🏻 Роли'
            }
        }

        t = texts[lang]

        keyboard = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton(text=t['support'], url="https://t.me/CityMafiaSupport")
        button2 = types.InlineKeyboardButton(text=t['how_to_play'], url="https://t.me/+_ljFO5TH39wxZTRi")
        button3 = types.InlineKeyboardButton(text=t['roles'], url="https://telegra.ph/maf-02-17")

        keyboard.add(button1, button2)
        keyboard.add(button3)

        send_message(
            message.chat.id,
            t['title'],
            parse_mode="Markdown",
            reply_markup=keyboard
        )

@bot.message_handler(commands=['coins'])
def transfer_coins(message):
    chat_id = message.chat.id
    sender_id = message.from_user.id

    lang = chat_settings.get(chat_id, {}).get("language", "ru")  # Определяем язык чата

    texts = {
        'kz': {
            'only_group': "🔸 Бұл команда тек топтарда қолжетімді!",
            'reply_required': "🔸 Монет жіберу үшін адамның хабарламасына жауап ретінде жаз!\nМысалы: /coins 10",
            'self_transfer': "🔸 Өзіңізге монет жібере алмайсыз!",
            'invalid_amount': "🔸 Қате сан! Мысалы: /coins 10",
            'profile_error': "🔸 Қате! Профильдерді алу мүмкін болмады.",
            'not_enough_coins': "🔸 Монет жеткіліксіз! Сізде: {coins} 🪙",
            'confirmation': "*{sender}* жіберді *{amount}* 🪙 *{recipient}*"
        },
        'ru': {
            'only_group': "🔸 Эта команда доступна только в группах!",
            'reply_required': "🔸 Чтобы отправить монеты, ответь на сообщение пользователя!\nНапример: /coins 10",
            'self_transfer': "🔸 Нельзя отправить монеты самому себе!",
            'invalid_amount': "🔸 Неверное количество! Пример: /coins 10",
            'profile_error': "🔸 Ошибка! Не удалось получить профили.",
            'not_enough_coins': "🔸 Недостаточно монет! У вас: {coins} 🪙",
            'confirmation': "*{sender}* отправил *{amount}* 🪙 *{recipient}*"
        }
    }[lang]

    # Удаляем сообщение с командой
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение: {e}")

    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, texts['only_group'])
        return

    if not message.reply_to_message:
        bot.reply_to(message, texts['reply_required'])
        return

    recipient = message.reply_to_message.from_user
    recipient_id = recipient.id

    if sender_id == recipient_id:
        bot.reply_to(message, texts['self_transfer'])
        return

    try:
        amount = int(message.text.split()[1])
        if amount <= 0:
            raise ValueError
    except (IndexError, ValueError):
        bot.reply_to(message, texts['invalid_amount'])
        return

    try:
        sender_profile = get_or_create_profile(sender_id, message.from_user.first_name, message.from_user.last_name)
        recipient_profile = get_or_create_profile(recipient_id, recipient.first_name, recipient.last_name)
    except Exception as e:
        logging.error(f"Ошибка при получении профилей: {e}")
        bot.reply_to(message, texts['profile_error'])
        return

    if sender_profile['coins'] < amount:
        bot.reply_to(message, texts['not_enough_coins'].format(coins=sender_profile['coins']))
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
        bot.send_message(chat_id,
            texts['confirmation'].format(sender=sender_name, amount=amount, recipient=recipient_name),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения: {e}")

MY_USER_ID = 6265990443  # замени на свой ID

@bot.message_handler(commands=['stop'])
def stop_game(message):
    global game_tasks, registration_timers, game_start_timers

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    lang = chat_settings.get(chat_id, {}).get("language", "ru")

    texts = {
        "kz": {
            "game_stopped": "🚫 *Ойынды әкімші тоқтатты!*",
            "registration_stopped": "🚫 *Тіркеуді әкімші тоқтатты*"
        },
        "ru": {
            "game_stopped": "🚫 *Игру остановил администратор!*",
            "registration_stopped": "🚫 *Регистрацию остановил администратор*"
        }
    }[lang]

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    is_admin = False

    # Разрешить суперпользователю
    if user_id == MY_USER_ID:
        is_admin = True
    # Обычный админ
    elif user_id:
        try:
            chat_member = bot.get_chat_member(chat_id, user_id)
            if chat_member.status in ['administrator', 'creator']:
                is_admin = True
        except Exception as e:
            print(f"Ошибка при получении члена чата: {e}")
    # Анонимный админ
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
        send_message(chat_id, texts['game_stopped'], parse_mode="Markdown")
        reset_game(chat)
        reset_roles(chat)
    else:
        reset_registration(chat_id)
        send_message(chat_id, texts['registration_stopped'], parse_mode="Markdown")

@bot.message_handler(commands=['time'])
def stop_registration_timer(message):
    global notification_timers, game_start_timers

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    lang = chat_settings.get(chat_id, {}).get("language", "ru")

    texts = {
        "kz": "*Ойынның автоматты бастау таймері өшірулі тұр. Сол үшін *\nОйынды /start пәрменін пайдаланып қолмен бастаңыз.",
        "ru": "*Таймер автоматического запуска игры был отключён. *\nЗапустите игру вручную с помощью команды /start."
    }

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    is_admin = False

    # Проверка обычного пользователя
    if user_id:
        try:
            chat_member = bot.get_chat_member(chat_id, user_id)
            if chat_member.status in ['administrator', 'creator']:
                is_admin = True
        except Exception as e:
            print(f"Ошибка при получении члена чата: {e}")

    # Проверка анонимного администратора
    elif message.sender_chat and message.sender_chat.id == chat_id:
        # Сообщение пришло от имени группы — скорее всего, от анонимного админа
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
        send_message(chat_id, texts[lang], parse_mode="Markdown")

@bot.message_handler(commands=['add_chat'])
def add_chat(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "У тебя нет прав для этой команды.")
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
        return bot.reply_to(message, "⛔️ У тебя нет прав для этой команды.")

    user_data[message.chat.id] = {}
    msg = bot.reply_to(message, "✍️ Отправь текст для рассылки (Markdown или HTML поддерживается):")
    bot.register_next_step_handler(msg, handle_text)

def handle_text(message):
    chat_id = message.chat.id
    user_data[chat_id]['text'] = message.text
    user_data[chat_id]['parse_mode'] = 'HTML' if '<b>' in message.text or '<i>' in message.text else 'Markdown'

    msg = bot.reply_to(message, "📎 Теперь отправь медиа (фото, видео, гиф и т.д.) или напиши «нет»:")
    bot.register_next_step_handler(msg, handle_media)

def handle_media(message):
    chat_id = message.chat.id
    if message.text and message.text.lower() == 'нет':
        user_data[chat_id]['media'] = None
    else:
        user_data[chat_id]['media'] = message

    msg = bot.reply_to(message, "🔘 Введи кнопку и ссылку в формате:\n\n`Текст кнопки - https://example.com`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, handle_button)

def handle_button(message):
    chat_id = message.chat.id
    keyboard = None

    match = re.match(r'^(.+?)\s*-\s*(https?://[^\s]+)$', message.text.strip())
    if match:
        button_text, url = match.groups()
        keyboard = types.InlineKeyboardMarkup()
        button = types.InlineKeyboardButton(text=button_text.strip(), url=url.strip())
        keyboard.add(button)

    user_data[chat_id]['keyboard'] = keyboard
    preview(chat_id, message)

def preview(chat_id, message):
    data = user_data[chat_id]
    text = data['text']
    keyboard = data.get('keyboard')
    parse_mode = data['parse_mode']

    try:
        if data.get('media'):
            bot.copy_message(chat_id, data['media'].chat.id, data['media'].message_id, caption=text, parse_mode=parse_mode, reply_markup=keyboard)
        else:
            bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=keyboard)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка предпросмотра: {e}")

    confirm_markup = types.InlineKeyboardMarkup()
    confirm_markup.add(
        types.InlineKeyboardButton("✅ Рассылать", callback_data='start_broadcast'),
        types.InlineKeyboardButton("♻️ Сбросить", callback_data='cancel_broadcast')
    )
    bot.send_message(chat_id, "Все готово. Начать рассылку?", reply_markup=confirm_markup)

@bot.callback_query_handler(func=lambda call: call.data in ['start_broadcast', 'cancel_broadcast'])
def callback_decision(call):
    chat_id = call.message.chat.id

    if call.data == 'cancel_broadcast':
        user_data.pop(chat_id, None)
        bot.edit_message_text("❌ Рассылка отменена.", chat_id, call.message.message_id)
        return

    broadcast_status['is_paused'] = False
    broadcast_status['is_stopped'] = False

    bot.edit_message_text("🚀 Начинаем рассылку...", chat_id, call.message.message_id)

    thread = threading.Thread(target=send_broadcast, args=(chat_id,))
    thread.start()

def control_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("⏸ Пауза", callback_data="pause_broadcast"),
        types.InlineKeyboardButton("▶️ Продолжить", callback_data="resume_broadcast"),
        types.InlineKeyboardButton("🛑 Остановить", callback_data="stop_broadcast")
    )
    return markup

@bot.callback_query_handler(func=lambda call: call.data in ['pause_broadcast', 'resume_broadcast', 'stop_broadcast'])
def handle_broadcast_controls(call):
    chat_id = call.message.chat.id

    if call.data == 'pause_broadcast':
        broadcast_status['is_paused'] = True
        bot.answer_callback_query(call.id, "⏸ Рассылка приостановлена.")

    elif call.data == 'resume_broadcast':
        broadcast_status['is_paused'] = False
        bot.answer_callback_query(call.id, "▶️ Рассылка возобновлена.")

    elif call.data == 'stop_broadcast':
        broadcast_status['is_stopped'] = True
        bot.answer_callback_query(call.id, "🛑 Рассылка остановлена.")

def send_broadcast(chat_id):
    data = user_data.get(chat_id)
    if not data:
        return

    text = data['text']
    media = data.get('media')
    keyboard = data.get('keyboard')
    parse_mode = data.get('parse_mode')

    players = list(player_profiles)
    random.shuffle(players)

    success = 0
    failed = 0

    status_msg = bot.send_message(chat_id, f"📤 Рассылка началась...\n✅ Отправлено: 0\n⌛ Осталось: {len(players)}", reply_markup=control_buttons())

    for idx, player_id in enumerate(players):
        if broadcast_status['is_stopped']:
            bot.edit_message_text("🛑 Рассылка остановлена.", chat_id, status_msg.message_id)
            return

        while broadcast_status['is_paused']:
            time.sleep(1)

        try:
            if media:
                bot.copy_message(player_id, media.chat.id, media.message_id, caption=text, parse_mode=parse_mode, reply_markup=keyboard)
            else:
                bot.send_message(player_id, text, parse_mode=parse_mode, reply_markup=keyboard)
            success += 1
        except Exception as e:
            logging.error(f"Ошибка отправки {player_id}: {e}")
            failed += 1

        if idx % 5 == 0 or idx == len(players) - 1:
            try:
                bot.edit_message_text(f"📤 Рассылка продолжается...\n✅ Отправлено: {success}\n⌛ Осталось: {len(players) - success}",
                                      chat_id, status_msg.message_id, reply_markup=control_buttons())
            except:
                pass

        time.sleep(2)

    bot.edit_message_text(f"✅ Рассылка завершена.\n📬 Отправлено: {success}\n❌ Ошибок: {failed}", chat_id, status_msg.message_id)
    user_data.pop(chat_id, None)


# Команда /next для отправки уведомления о новой регистрации в чате
@bot.message_handler(commands=['next'])
def next_message(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    chat_title = bot.get_chat(chat_id).title

    # Определяем язык чата
    lang = chat_settings.get(chat_id, {}).get("language", "ru")

    # Тексты на разных языках
    texts = {
        "kz": f"🔔 Сізге {chat_title} чатына жаңа ойынға тіркелу туралы хат келеді.",
        "ru": f"🔔 Вам придет уведомление о регистрации на новую игру в чате {chat_title}."
    }

    # Удаляем сообщение команды
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.error(f"Ошибка при удалении сообщения команды 'next' в чате {chat_id}: {e}")

    if chat_id not in next_players:
        next_players[chat_id] = []

    if user_id not in next_players[chat_id]:
        next_players[chat_id].append(user_id)

    try:
        send_message(user_id, texts[lang], parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка при отправке личного уведомления игроку {user_id}: {e}")


@bot.message_handler(commands=['leave'])
def leave_command(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Сначала удаляем сообщение с командой
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    # Проверяем, идет ли игра в данном чате
    if chat_id in chat_list:
        game = chat_list[chat_id]

        # Проверяем, есть ли настройки для этого чата, если нет — создаем с настройками по умолчанию
        if chat_id not in chat_settings:
            chat_settings[chat_id] = {"allow_leave_game": True}  # или другой дефолтный набор настроек

        # Если игра уже началась и настройка запрещает выход — блокируем
        if game.game_running and not chat_settings[chat_id]["allow_leave_game"]:
            return

    # Если игра не началась или выход разрешен — выполняем выход
    leave_game(user_id, chat_id, send_private_message=True)


def notify_game_start(chat):
    chat_title = bot.get_chat(chat.chat_id).title
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    # Сообщения и кнопки на разных языках
    texts = {
        "kz": {
            "message": f"👑 {chat_title} чатында жаңа ойынға тіркелу басталды!",
            "button": "🤵🏻 Қосылу"
        },
        "ru": {
            "message": f"👑 В чате {chat_title} началась регистрация на новую игру!",
            "button": "🤵🏻 Присоединиться"
        }
    }

    if chat.chat_id in next_players:
        for player_id in next_players[chat.chat_id]:
            try:
                join_btn = types.InlineKeyboardMarkup()
                bot_username = bot.get_me().username
                join_url = f'https://t.me/{bot_username}?start=join_{chat.chat_id}'
                button_text = texts[lang]["button"]
                item1 = types.InlineKeyboardButton(button_text, url=join_url)
                join_btn.add(item1)

                send_message(
                    player_id,
                    texts[lang]["message"],
                    reply_markup=join_btn,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Ошибка при отправке уведомления о старте игры игроку {player_id}: {e}")

        next_players[chat.chat_id] = []

def leave_game(user_id, game_chat_id, send_private_message=True):
    chat = chat_list.get(game_chat_id)
    lang = chat_settings.get(game_chat_id, {}).get("language", "kz")  # Язык по умолчанию — казахский

    # Сообщения
    texts = {
        'kz': {
            'left_game': "🚫 Сіз ойыннан шықтыңыз",
            'left_registration': "🚫 Сіз ойынға тіркелуден бас тарттыңыз.",
            'death_msg': "⚰️ {} бұл қаланың ауыр атмосферасына шыдай алмай асылып кетті. Ол *{}* болған еді.",
            'join_button': "🤵🏻 Қосылу"
        },
        'ru': {
            'left_game': "🚫 Вы вышли из игры",
            'left_registration': "🚫 Вы отказались от участия в игре.",
            'death_msg': "⚰️ {} не выдержал гнетущую атмосферу этого города и повесился. Он был *{}*.",
            'join_button': "🤵🏻 Присоединиться"
        }
    }

    if chat:
        if chat.game_running:
            if user_id in chat.players:
                player = chat.players.pop(user_id)

                if user_id in user_game_registration and user_game_registration[user_id] == game_chat_id:
                    del user_game_registration[user_id]

                full_name = f"{player['name']} {player.get('last_name', '')}".strip()
                clickable_name = f"[{full_name}](tg://user?id={user_id})"
                
                # Перевод роли по языку
                translated_role = translate_role(player['role'], lang)

                chat.all_dead_players.append(f"{clickable_name} - {translated_role}")

                try:
                    msg = texts[lang]['death_msg'].format(clickable_name, translated_role)
                    send_message(game_chat_id, msg, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение о выходе игрока в общий чат: {e}")

                if send_private_message:
                    try:
                        send_message(user_id, texts[lang]['left_game'])
                    except Exception as e:
                        logging.error(f"Не удалось отправить личное сообщение игроку {user_id}: {e}")

                if player['role'] == '🧔🏻‍♂️ Дон':
                    check_and_transfer_don_role(chat)

                if player['role'] == '🕵🏼 Комиссар':
                    check_and_transfer_sheriff_role(chat)

        elif user_id in chat.players:
            chat.players.pop(user_id)

            if user_id in user_game_registration and user_game_registration[user_id] == game_chat_id:
                del user_game_registration[user_id]

            if send_private_message:
                try:
                    send_message(user_id, texts[lang]['left_registration'])
                except Exception as e:
                    logging.error(f"Не удалось отправить личное сообщение игроку {user_id}: {e}")

            new_msg_text = registration_message(chat.players, chat.chat_id)
            join_text = texts[lang]['join_button']
            new_markup = types.InlineKeyboardMarkup([[
                types.InlineKeyboardButton(join_text, url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}')
            ]])

            try:
                bot.edit_message_text(
                    chat_id=game_chat_id,
                    message_id=chat.button_id,
                    text=new_msg_text,
                    reply_markup=new_markup,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения о регистрации: {e}")


@bot.message_handler(commands=['give'])
def give_items(message):
    allowed_user_id = 6265990443  # Замените на ваш user_id

    if message.from_user.id != allowed_user_id:
        bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды.")
        return

    command_args = message.text.split()

    if len(command_args) < 4 or (len(command_args) - 2) % 2 != 0:
        bot.reply_to(message, "❌ Неправильный формат команды. Используйте: /give <user_id> <item1> <amount1> [<item2> <amount2> ...]")
        return

    try:
        target_user_id = int(command_args[1])

        # Проверяем, существует ли профиль игрока
        if target_user_id not in player_profiles:
            try:
                user_info = bot.get_chat(target_user_id)
                username = f"{user_info.first_name} {user_info.last_name}".strip()  # Добавляем фамилию, если есть
            except Exception:
                username = "Неизвестный"

            player_profiles[target_user_id] = {
                'id': target_user_id,
                'name': username,
                'euro': 0,
                'shield': 0,
                'fake_docs': 0,
                'coins': 0
            }
            bot.reply_to(message, f"🆕 Профиль пользователя с именем {username} и ID {target_user_id} создан.")

        response = []
        for i in range(2, len(command_args), 2):
            item_type = command_args[i].lower()
            try:
                amount = int(command_args[i + 1])
            except ValueError:
                bot.reply_to(message, f"❌ Неправильный формат количества для {item_type}. Используйте целое число.")
                return

            if item_type in player_profiles[target_user_id]:
                player_profiles[target_user_id][item_type] += amount
                response.append(f"✅ {item_type.capitalize()}: {amount}")
            else:
                response.append(f"❌ Неправильный тип предмета: {item_type}")

        bot.reply_to(message, f"Результаты для игрока {target_user_id}:\n" + "\n".join(response))

    except ValueError:
        bot.reply_to(message, "❌ Неправильный формат user_id. Используйте числовое значение.")


@bot.message_handler(commands=['top'])
def top_players_command(message):
    if message.chat.type == 'private':
        return  # Игнорируем команду в личных сообщениях

    user_id = message.from_user.id
    current_time = time.time()

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    if user_id in last_top_usage and current_time - last_top_usage[user_id] < 15:
        return

    last_top_usage[user_id] = current_time

    lang = chat_settings.get(message.chat.id, {}).get("language", "ru")

    if not player_scores:
        if lang == 'kz':
            send_message(
                message.chat.id,
                "🏆 *Аптаның 15 үздік ойыншысы:*\n\n❌ Қазіргі уақытта рейтингте ешқандай ойыншы жоқ. Үздіктер тізіміне ену үшін, ойынды ойнаңыз!",
                parse_mode="Markdown"
            )
        if lang == 'ru':
            send_message(
                message.chat.id,
                "🏆 *15 лучших игроков недели:*\n\n❌ В настоящее время в рейтинге нет игроков. Играй, чтобы попасть в список лучших!",
                parse_mode="Markdown"
            )
        return

    sorted_scores = sorted(player_scores.items(), key=lambda x: x[1], reverse=True)[:15]

    if lang == 'kz':
        top_message = "🏆 *Аптаның 15 үздік ойыншысы:*\n\n"
    if lang == 'ru':
        top_message = "🏆 *15 лучших игроков недели:*\n\n"

    for index, (user_id, score) in enumerate(sorted_scores, start=1):
        try:
            user = bot.get_chat_member(message.chat.id, user_id)
            player_name = f"{user.user.first_name} {user.user.last_name}" if user.user.last_name else user.user.first_name
        except Exception:
            if lang == 'kz':
                player_name = "Белгісіз ойыншы"
            if lang == 'ru':
                player_name = "Неизвестный игрок"

        top_message += f"{index}. {player_name}\n"

    send_message(message.chat.id, top_message, parse_mode="Markdown")


@bot.message_handler(commands=['reset_scores'])
def reset_scores_command(message):
    # Проверяем права (только владелец)
    if message.from_user.id != OWNER_ID:  # OWNER_ID = 7025585720
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        send_message(message.chat.id, "❌ У вас нет прав на эту команду.")
        return

    # Очищаем очки и таймеры
    global player_scores, game_timers
    player_scores = {}
    game_timers = {}

    # Сохраняем изменения (2 варианта)
    try:
        # Вариант 1: Сохраняем через ZIP (рекомендуется)
        send_zip_to_channel()  # Отправит актуальные (пустые) данные
        
        # Вариант 2: Альтернативно можно сохранить отдельный файл с очками
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Тип', 'ID', 'Значение'])  # Пустой файл с заголовком
        
        file_data = io.BytesIO(output.getvalue().encode('utf-8'))
        file_data.name = 'player_scores_reset.csv'
        bot.send_document(SETTINGS_CHANNEL_ID, file_data, caption="Очки сброшены")
    except Exception as e:
        logging.error(f"Ошибка при сохранении сброшенных очков: {e}")

    # Уведомление
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
        
    send_message(message.chat.id, "✅ Все очки и таймеры успешно сброшены!")
    logging.info(f"Администратор {message.from_user.id} сбросил все очки игроков")


def all_night_actions_taken(chat):
    for player in chat.players.values():
        # Проверяем только живых игроков с активными ролями
        if player['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон', '🕵🏼 Комиссар', '👨🏼‍⚕️ Дәрігер', '🧙‍♂️ Қаңғыбас', '💃🏼 Көңілдес', '👨🏼‍💼 Қорғаушы', '🔪 Жауыз'] and player['role'] != 'dead':
            # Если игрок заблокирован или не выполнил действие, возвращаем False
            if player.get('voting_blocked', False) or not player.get('action_taken', False):
                return False
    # Если все действия выполнены, ждем 5 секунд
    time.sleep(5)
    return True


def get_full_name(player):
    # Используем .get() для безопасного получения имени и фамилии
    first_name = player.get('name', '')  # Если нет имени, будет 'Неизвестно'
    last_name = player.get('last_name', '')  # Если фамилия отсутствует, будет пустая строка
    return f"{first_name} {last_name}".strip()  # Убираем лишние пробелы, если фамилия пустая


def process_sheriff_actions(chat):
    """Обработка действий комиссара с учётом языка чата."""
    lang = chat_settings.get(chat.chat_id, {}).get("language", "ru")

    if chat.lawyer_target and chat.sheriff_check and chat.lawyer_target == chat.sheriff_check:
        checked_player = chat.players[chat.sheriff_check]

        if checked_player['role'] in {'🧔🏻‍♂️ Дон', '🤵🏻 Мафия'}:
            try:
                if lang == 'kz':
                    send_message(chat.sheriff_id, f"Сен {get_full_name(checked_player)} дегенді тексеріп, оның рөлі - 👨🏼 Тату тұрғын екенін анықтадың.")
                if lang == 'ru':
                    send_message(chat.sheriff_id, f"Ты проверил игрока {get_full_name(checked_player)}, и его роль — 👨🏼 Мирный житель.")
            except Exception:
                pass

            try:
                if lang == 'kz':
                    send_message(chat.sheriff_check, "🕵🏼 Комиссар сені іздеп келді, бірақ қорғаушы саған тату тұрғын рөлін берді.")
                if lang == 'ru':
                    send_message(chat.sheriff_check, "🕵🏼 Комиссар пришёл к тебе, но адвокат показал, что ты мирный житель.")
            except Exception:
                pass

            if chat.sergeant_id and chat.sergeant_id in chat.players:
                try:
                    if lang == 'kz':
                        msg = f"🕵🏼 Комиссар {get_full_name(checked_player)} дегенді тексеріп, оның рөлі - 👨🏼 Тату тұрғын екенін анықтады."
                    if lang == 'ru':
                        msg = f"🕵🏼 Комиссар проверил {get_full_name(checked_player)}, и его роль — 👨🏼 Мирный житель."
                    send_message(chat.sergeant_id, msg)
                except Exception:
                    pass
            return

    if chat.sheriff_check and chat.sheriff_check in chat.players:
        checked_player = chat.players[chat.sheriff_check]
        player_profile = player_profiles.get(chat.sheriff_check, {})
        allowed_roles = {'🧔🏻‍♂️ Дон', '🔪 Жауыз', '🤵🏻 Мафия'}

        if (player_profile.get('fake_docs', 0) > 0 and 
            not player_profile.get('fake_docs_used', False) and 
            player_profile.get('docs_active', False) and 
            checked_player['role'] in allowed_roles):

            try:
                if lang == 'kz':
                    send_message(chat.sheriff_id, f"Сен {get_full_name(checked_player)} дегенді тексеріп, оның рөлі - 👨🏼 Тату тұрғын екенін анықтадың.")
                if lang == 'ru':
                    send_message(chat.sheriff_id, f"Ты проверил игрока {get_full_name(checked_player)}, и его роль — 👨🏼 Мирный житель.")
            except Exception:
                pass

            try:
                if lang == 'kz':
                    send_message(chat.sheriff_check, "🕵🏼 *Комиссар* сені іздеп келді, бірақ сен жалған құжаттарды көрсеттің.", parse_mode="Markdown")
                if lang == 'ru':
                    send_message(chat.sheriff_check, "🕵🏼 *Комиссар* пришёл к тебе, но ты показал фальшивые документы.", parse_mode="Markdown")
            except Exception:
                pass

            if chat.sergeant_id and chat.sergeant_id in chat.players:
                try:
                    if lang == 'kz':
                        msg = f"🕵🏼 Комиссар {get_full_name(checked_player)} дегенді тексеріп, оның рөлі - 👨🏼 Тату тұрғын екенін анықтады."
                    if lang == 'ru':
                        msg = f"🕵🏼 Комиссар проверил {get_full_name(checked_player)}, и его роль — 👨🏼 Мирный житель."
                    send_message(chat.sergeant_id, msg)
                except Exception:
                    pass

            player_profile['fake_docs'] -= 1
            player_profile['fake_docs_used'] = True
            player_profiles[chat.sheriff_check] = player_profile
        else:
            try:
                if lang == 'kz':
                    send_message(chat.sheriff_id, f"Сен {get_full_name(checked_player)} дегенді тексеріп, оның рөлі - {checked_player['role']} екенін анықтадың.")
                if lang == 'ru':
                    send_message(chat.sheriff_id, f"Ты проверил игрока {get_full_name(checked_player)}, и его роль — {checked_player['role']}.")
            except Exception:
                pass

            try:
                if lang == 'kz':
                    send_message(chat.sheriff_check, "🕵🏼 *Комиссар* саған қонаққа баруды шешті.", parse_mode="Markdown")
                if lang == 'ru':
                    send_message(chat.sheriff_check, "🕵🏼 *Комиссар* решил заглянуть к тебе.", parse_mode="Markdown")
            except Exception:
                pass

            if chat.sergeant_id and chat.sergeant_id in chat.players:
                try:
                    if lang == 'kz':
                        msg = f"🕵🏼 Комиссар {get_full_name(checked_player)} дегенді тексеріп, оның рөлі - {checked_player['role']} екенін анықтады."
                    if lang == 'ru':
                        msg = f"🕵🏼 Комиссар проверил {get_full_name(checked_player)}, и его роль — {checked_player['role']}."
                    send_message(chat.sergeant_id, msg)
                except Exception:
                    pass


def handle_voting(chat):
    """Обработка голосования."""
    chat.is_voting_time = True
    chat.vote_counts.clear()

    lang = chat_settings.get(chat.chat_id, {}).get("language", "ru")
    voting_time = chat_settings.get(chat.chat_id, {}).get("voting_time", 45)

    # Заголовок голосования
    if lang == 'kz':
        title = f'*Айыптыларды табу және жазалау уақыты келді.*\nДауыс беру {voting_time} секундқа созылады'
        vote_button_text = '🗳 Дауыс беру'
        pm_text = '*Айыптыларды іздеу уақыты келді!*\nКімді асқың келеді?'
        skip_text = '🚷 Өткізіп жіберу'
    if lang == 'ru':
        title = f'*Время найти и наказать виновных.*\nГолосование продлится {voting_time} секунд'
        vote_button_text = '🗳 Проголосовать'
        pm_text = '*Время искать виновных!*\nКого хочешь повесить?'
        skip_text = '🚷 Пропустить голосование'

    vote_msg = send_message(
        chat.chat_id,
        title,
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(vote_button_text, url=f'https://t.me/{bot.get_me().username}')]
        ]),
        parse_mode="Markdown"
    )
    chat.vote_message_id = vote_msg.message_id

    lover_target_healed = chat.doc_target == chat.lover_target_id

    for voter_id in chat.players:
        if voter_id != chat.lover_target_id or lover_target_healed:
            try:
                voter_role = chat.players[voter_id]['role']
                buttons = []

                # Сортируем игроков по их номеру
                sorted_players = sorted(chat.players.items(), key=lambda item: item[1]['number'])

                for pid, target in sorted_players:
                    if pid == voter_id:
                        continue  # Игрок не может голосовать сам за себя

                    name = get_full_name(target)

                    # Для мафии/дона
                    if voter_role in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон'] and target['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон']:
                        name = f"🤵🏻 {name}"

                    # Для полицейских
                    if voter_role in ['🕵🏼 Комиссар', '👮🏼 Сержант']:
                        if target['role'] == '🕵🏼 Комиссар':
                            name = f"🕵🏼 {name}"
                        if target['role'] == '👮🏼 Сержант':
                            name = f"👮🏼 {name}"

                    buttons.append([types.InlineKeyboardButton(name, callback_data=f"{pid}_vote")])

                # Кнопка для пропуска голосования
                buttons.append([types.InlineKeyboardButton(skip_text, callback_data='skip_vote')])

                send_message(
                    voter_id,
                    pm_text,
                    reply_markup=types.InlineKeyboardMarkup(buttons),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Ошибка отправки голосования {voter_id}: {e}")

    time.sleep(voting_time)
    chat.is_voting_time = False
    return end_day_voting(chat)


def notify_night_start(chat_id, players_alive_text):
    """Отправляет уведомление о начале ночи."""
    lang = chat_settings.get(chat_id, {}).get("language", "ru")

    bot_username = bot.get_me().username
    private_message_url = f'https://t.me/{bot_username}'
    private_message_btn = types.InlineKeyboardMarkup()
    
    if lang == 'kz':
        btn_text = 'Ботқа өту'
        night_caption = '🌙 *Түн болды*\nДалаға тек ең батыл және қорықпайтын адамдар шығады. Күндіз олардың тірісін санаймыз...'
    if lang == 'ru':
        btn_text = 'Перейти к боту'
        night_caption = '🌙 *Наступила ночь*\nТолько самые смелые и бесстрашные выходят на улицу. Днём мы пересчитаем, кто остался...'

    private_message_btn.add(types.InlineKeyboardButton(btn_text, url=private_message_url))

    # Отправляем изображение с сообщением о начале ночи
    bot.send_photo(chat_id, 'https://t.me/ProfileChaekBot/7', caption=night_caption, parse_mode="Markdown", reply_markup=private_message_btn)

    time.sleep(1.5)

    send_message(chat_id=chat_id, message=players_alive_text, parse_mode="Markdown", reply_markup=private_message_btn)

def reset_night_state(chat):
    """Сбрасывает состояние игры перед началом ночи."""
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
            # Бота добавили в группу
            setup_new_chat(message.chat.id)
            break

def setup_new_chat(chat_id):
    # Инициализируем настройки по умолчанию
    chat_settings[chat_id] = {
        "language": "ru",  # По умолчанию казахский
        "pin_registration": True,
        "allow_registration": True,
        "allow_leave_game": True,
        "registration_time": (120, 60),
        "night_time": 45,
        "day_time": 60,
        "voting_time": 45,
        "confirmation_time": 30,
        "mafia_ratio": 4
    }
    
    # Отправляем приветственное сообщение с выбором языка
    welcome_markup = types.InlineKeyboardMarkup()
    welcome_markup.add(
        types.InlineKeyboardButton("🇰🇿 Қазақша", callback_data=f"init_lang_kz_{chat_id}"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data=f"init_lang_ru_{chat_id}")
    )
    
    welcome_text = (
        "Выберите язык"
    )
    
    send_message(chat_id, welcome_text, reply_markup=welcome_markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("init_lang_"))
def handle_init_language(call):
    lang = call.data.split("_")[2]
    chat_id = int(call.data.split("_")[3])
    
    if chat_id not in chat_settings:
        chat_settings[chat_id] = {}
    
    chat_settings[chat_id]["language"] = lang
    
    # Удаляем сообщение с выбором языка
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass
    
    # Отправляем инструкции на выбранном языке
    instructions = {
        "kz": (
            "Сәлем! :)\n"
            "Мен 🤵🏻 Мафия ойынын жүргізетін ботпын\n"
            "Ойынды бастау үшін маған төмендегі әкімші құқықтарын беріңіз:\n🛑 Хат жою\n🛑 Пайдаланушы бұғаттау\n🛑 Хат бекіту\n⚙️ Баптауларды өзгерту үшін /settings пәрменін пайдаланыңыз"
        ),
        "ru": (
            "Привет! :)\n"
            "Я бот ведущий для игры в 🤵🏻 Мафию\n"
            "Чтобы начать игру, для начала выдайте мне права админстратора:\n🛑 Удалять сообщение\n🛑 Закреплять сообщение\n🛑 Блокировать пользывателей\n⚙️ Используйте команду /settings для изменения настроек."
        )
    }
    
    send_message(chat_id, instructions[lang])
    
    # Предлагаем сразу настроить параметры
    if is_admin_or_me(bot, chat_id, call.from_user.id):
        settings_handler_by_chat(chat_id)

def settings_handler_by_chat(chat_id):
    # Аналогично вашей функции settings_handler, но для конкретного чата
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
            "confirmation_time": 30,
            "mafia_ratio": 4
        }

    # Получаем администраторов чата
    try:
        chat_admins = bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in chat_admins]
        
        # Отправляем меню настроек каждому администратору
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
    """Обрабатывает действия Любовницы."""
    don_blocked = False
    lover_target_healed = False

    lang = chat_settings.get(chat.chat_id, {}).get("language", "ru")

    if chat.lover_target_id and chat.lover_target_id in chat.players:
        lover_target = chat.players[chat.lover_target_id]

        # Уведомление цели Любовницы
        try:
            if lang == 'kz':
                send_message(chat.lover_target_id, '💃🏼 Көңілдес "Маған кел, бәрін ұмыт...", - деп ән салды', parse_mode="Markdown")
            if lang == 'ru':
                send_message(chat.lover_target_id, '💃🏼 Любовница напела: "Иди ко мне, забудь обо всём..."', parse_mode="Markdown")
        except Exception:
            pass

        # Проверяем, лечит ли Доктор цель Любовницы
        if chat.doc_target == chat.lover_target_id:
            try:
                if lang == 'kz':
                    send_message(chat.lover_target_id, "💃🏼 *Көңілдес* сені тыныштандырғысы келді, бірақ 👨🏼‍⚕️ *Дәрігердің* сенімен екенін көріп, кетіп қалды!", parse_mode="Markdown")
                if lang == 'ru':
                    send_message(chat.lover_target_id, "💃🏼 *Любовница* хотела тебя соблазнить, но увидела, что ты с 👨🏼‍⚕️ *Доктором*, и ушла.", parse_mode="Markdown")
            except Exception:
                pass
            lover_target_healed = True
        else:
            # Блокируем голосование и действия цели
            lover_target['voting_blocked'] = True

            if lover_target['role'] == '🧔🏻‍♂️ Дон':
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
    """Обрабатывает действия Бомжа с учетом языка."""
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    if chat.hobo_id and chat.hobo_target:
        hobo_target = chat.hobo_target
        if hobo_target in chat.players:
            hobo_target_name = get_full_name(chat.players[hobo_target])
            hobo_visitors = []

            try:
                if lang == 'kz':
                    send_message(hobo_target, f'🧙🏼‍♂️ *Қаңғыбас* түнде сенен бір бөтелке сұрауға кетті.', parse_mode="Markdown")
                if lang == 'ru':
                    send_message(hobo_target, f'🧙🏼‍♂️ *Бомж* пришёл к тебе ночью попросить бутылку.', parse_mode="Markdown")
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
                if lang == 'kz':
                    if hobo_visitors:
                        visitors_names = ', '.join(hobo_visitors)
                        send_message(chat.hobo_id, f'Түнде сен {hobo_target_name} деген бөтелке алуға барып, {visitors_names} дегенді көрдің.')
                    if not hobo_visitors:
                        send_message(chat.hobo_id, f'Сен {hobo_target_name} дегенге бөтелке іздеуге барғанда, күдікті ештеңе байқаған жоқсың.')
                if lang == 'ru':
                    if hobo_visitors:
                        visitors_names = ', '.join(hobo_visitors)
                        send_message(chat.hobo_id, f'Ты пришёл ночью к {hobo_target_name} за бутылкой и увидел: {visitors_names}.')
                    if not hobo_visitors:
                        send_message(chat.hobo_id, f'Ты пришёл ночью к {hobo_target_name} за бутылкой, но ничего подозрительного не заметил.')
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение бомжу {chat.hobo_id}: {e}")
        try:
            if hobo_target not in chat.players:
                if lang == 'kz':
                    send_message(chat.hobo_id, 'Сен бұл түні ешкімді жолықтырмадың.')
                if lang == 'ru':
                    send_message(chat.hobo_id, 'Ты никого не встретил этой ночью.')
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение бомжу {chat.hobo_id} о пустой встрече: {e}")

def send_night_actions(chat):
    """Отправляет кнопки для выполнения ночных действий в зависимости от роли игрока с учетом языка."""
    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    for player_id, player in chat.players.items():
        if not chat.game_running:
            break

        try:
            if player['role'] in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон']:
                if lang == 'kz':
                    list_btn(chat.players, player_id, 'мафия', 'Кімді құрбан етеміз?', 'м')
                if lang == 'ru':
                    list_btn(chat.players, player_id, 'мафия', 'Кого сделаем жертвой?', 'м')

            if player['role'] == '🕵🏼 Комиссар':
                send_sheriff_menu(chat, player_id)

            if player['role'] == '👨🏼‍⚕️ Дәрігер':
                if lang == 'kz':
                    list_btn(chat.players, player_id, 'доктор', 'Кімді емдейміз?', 'д')
                if lang == 'ru':
                    list_btn(chat.players, player_id, 'доктор', 'Кого будем лечить?', 'д')

            if player['role'] == '🧙‍♂️ Қаңғыбас':
                players_btn = types.InlineKeyboardMarkup()
                for key, val in chat.players.items():
                    if key != player_id and val['role'] != 'dead' and key != chat.previous_hobo_target:
                        players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_б'))

                if lang == 'kz':
                    send_message(player_id, "Кімге бөтелке іздеп барамыз?", reply_markup=players_btn)
                if lang == 'ru':
                    send_message(player_id, "К кому пойдём искать бутылку?", reply_markup=players_btn)

            if player['role'] == '💃🏼 Көңілдес':
                players_btn = types.InlineKeyboardMarkup()
                for key, val in chat.players.items():
                    if key != player_id and val['role'] != 'dead' and (chat.previous_lover_target_id is None or key != chat.previous_lover_target_id):
                        players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_л'))

                if lang == 'kz':
                    send_message(player_id, "Кімге ләззат береміз?", reply_markup=players_btn)
                if lang == 'ru':
                    send_message(player_id, "Кому доставим удовольствие?", reply_markup=players_btn)

            if player['role'] == '👨🏼‍💼 Қорғаушы':
                players_btn = types.InlineKeyboardMarkup()
                for key, val in chat.players.items():
                    if key != player_id and val['role'] != 'dead' and key != chat.previous_lawyer_target:
                        players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_а'))

                if lang == 'kz':
                    send_message(player_id, "Кімді қорғаймыз?", reply_markup=players_btn)
                if lang == 'ru':
                    send_message(player_id, "Кого защитим?", reply_markup=players_btn)

            if player['role'] == '🔪 Жауыз':
                if lang == 'kz':
                    list_btn(chat.players, player_id, 'маньяк', 'Кімді атасың?', 'мк')
                if lang == 'ru':
                    list_btn(chat.players, player_id, 'маньяк', 'Кого убьём?', 'мк')

            profile = get_or_create_profile(player_id, player['name'])
            if profile['gun'] > 0 and not profile['gun_used'] and player['role'] != 'dead':
                players_btn = types.InlineKeyboardMarkup()
                for key, val in chat.players.items():
                    if key != player_id and val['role'] != 'dead':
                        players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_gun'))

                if lang == 'kz':
                    send_message(player_id, "🔫 Кімді көздейсің?", reply_markup=players_btn)
                if lang == 'ru':
                    send_message(player_id, "🔫 В кого целишься?", reply_markup=players_btn)

        except Exception as e:
            logging.error(f"Не удалось отправить сообщение игроку {player_id}: {e}")



# Обновленный код для функции game_cycle
async def game_cycle(chat_id):
    global chat_list, game_tasks
    chat = chat_list[chat_id]
    game_start_time = time.time()

    day_count = 1

    try:
        while chat.game_running:  # Основной цикл игры
            if not chat.game_running:
                break
            await asyncio.sleep(3)

            if not chat.game_running:
                break

            # Начало ночи
            chat.is_night = True
            chat.is_voting_time = False  # Убедимся, что голосование неактивно ночью

            # Сохраняем предыдущую цель любовницы перед сбросом
            reset_night_state(chat)

            dead_id = None

            if not chat.game_running:
                break

            players_alive_text = night_message(chat.players, chat.chat_id)

            notify_night_start(chat_id, players_alive_text)
            notify_mafia_and_don(chat)
            notify_police(chat)  # Уведомляем полицейских о составе

            if not chat.game_running:
                break

            # Отправляем новые кнопки выбора для ночных ролей
            send_night_actions(chat)

            start_time = time.time()
            night_time = chat_settings.get(chat_id, {}).get("night_time", 45)  # По умолчанию 45

            while time.time() - start_time < night_time:
                if all_night_actions_taken(chat):
                    break
                await asyncio.sleep(2)

            if not chat.game_running:
                break

            chat.is_night = False

            # Обработка действий любовницы
            process_lover_action(chat)

            # Пример обработки действия мафии
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

            # Вызов функции обработки действий комиссара
            process_sheriff_actions(chat)

            # Удаление игроков, пропустивших действия
            to_remove = []
            for player_id, player in chat.players.items():
                if not chat.game_running:
                    break
                if player['role'] not in ['👨🏼 Тату тұрғын', '🤞 Жолы болғыш', '💣 Камикадзе', '👮🏼 Сержант'] and not player.get('action_taken', False):
                    player['skipped_actions'] += 1
                    if player['skipped_actions'] >= 2:
                        to_remove.append(player_id)
                else:
                    player['action_taken'] = False
                    player['skipped_actions'] = 0

            lang = chat_settings.get(chat_id, {}).get("language", "kz")

            if lang == 'kz':
                caption = f'🌤️ *{day_count}-ші күн*\nКүн шығып, өткен түнде төгілген қанды қатыртады...'
            if lang == 'ru':
                caption = f'🌤️ *День {day_count}*\nВосход солнца подсвечивает кровь, пролитую прошлой ночью...'

            bot.send_photo(
                chat_id,
                'https://t.me/ProfileChaekBot/8',
                caption=caption,
                parse_mode="Markdown"
            )

            await asyncio.sleep(1.5)

            if not chat.game_running:
                break

            # Обработка убийств
            killed_by_mafia = chat.dead  # Жертва мафии
            killed_by_sheriff = None
            killed_by_bomber = None  # Жертва Комиссара

            if chat.sheriff_shoot and chat.sheriff_shoot in chat.players:
               shooted_player = chat.players[chat.sheriff_shoot]
               killed_by_sheriff = (chat.sheriff_shoot, chat.players[chat.sheriff_shoot])
               chat.sheriff_shoot = None

            process_deaths(chat, killed_by_mafia, killed_by_sheriff, killed_by_bomber, killed_by_maniac)

            if not chat.game_running:
                break

            if check_game_end(chat, game_start_time):
                break  # Если игра закончена, выходим из цикла

            players_alive_text = players_alive(chat.players, "day", chat.chat_id)
            msg = send_message(chat_id=chat_id, message=players_alive_text, parse_mode="Markdown")
            chat.button_id = msg.message_id

            chat.dead = None
            chat.sheriff_check = None

            day_time = chat_settings.get(chat_id, {}).get("day_time", 60)  # По умолчанию 60 секунд
            await asyncio.sleep(day_time)

            if not chat.game_running:
                break

            # Начало голосования днем
            should_continue = handle_voting(chat)

            if not chat.game_running:
                break

            # Обрабатываем результат голосования
            if not chat.voting_finished:
                should_continue = end_day_voting(chat)

            await asyncio.sleep(2)

            # Если игра не должна продолжаться после голосования
            if not should_continue:
                reset_voting(chat)
                day_count += 1
                continue

            chat.is_voting_time = False  # Отключаем время голосования

            if check_game_end(chat, game_start_time):
                break  # Если игра закончена, выходим из цикла

            confirmation_time = chat_settings.get(chat_id, {}).get("confirmation_time", 30)
            await asyncio.sleep(confirmation_time)

            if not chat.game_running:
                break

            # Вызываем обработку подтверждающего голосования
            handle_confirm_vote(chat)

            chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
            await asyncio.sleep(2)

            chat.vote_counts.clear()
            for player in chat.players.values():
                if not chat.game_running:
                    break
                player['has_voted'] = False

            # Сброс блокировки голосования в конце дня
            for player in chat.players.values():
                player['voting_blocked'] = False  # Разблокируем голосование для всех игроков

            if check_game_end(chat, game_start_time):
                break  # Если игра закончена, выходим из цикла

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
    full_name = f"{first_name} {last_name}".strip()  # Формируем полное имя

    if chat and not chat.game_running and chat.button_id:
        if user_id not in chat.players:
            add_player(chat, user_id, full_name)  # Передаем полное имя в add_player
            bot.answer_callback_query(call.id, text="Вы присоединились к игре!")

            # Обновляем сообщение о наборе
            new_msg_text = registration_message(chat.players, chat.chat_id)
            
            # Проверяем, изменился ли текст перед обновлением сообщения
            if new_msg_text != call.message.text:
                try:
                    bot.edit_message_text(chat_id=chat_id, message_id=chat.button_id, text=new_msg_text, reply_markup=call.message.reply_markup, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Ошибка обновления сообщения: {e}")
            
            # Проверяем количество игроков
            if len(chat.players) >= 20:
                _start_game(chat_id)  # Запускаем игру, если зарегистрировалось достаточное количество игроков
        else:
            bot.answer_callback_query(call.id, text="Вы уже зарегистрированы в этой игре.")
    else:
        bot.answer_callback_query(call.id, text="Ошибка: игра уже началась или регистрация не открыта.")

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
        bot.answer_callback_query(call.id, text="⛔️ сен ойында жоқсың.")
        return

    lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

    if not chat.is_voting_time:  
        if lang == 'kz':
            bot.answer_callback_query(call.id, text="Дауыс беру қазір мүмкін емес.")
        if lang == 'ru':
            bot.answer_callback_query(call.id, text="Голосование сейчас недоступно.")
        return

    if 'vote_counts' not in chat.__dict__:
        chat.vote_counts = {}

    player = chat.players.get(from_id)

    # Блокировка от Көңілдес
    if player.get('voting_blocked', False) and not player.get('healed_from_lover', False):
        if lang == 'kz':
            bot.answer_callback_query(call.id, text="💃🏼 Көңілдес «Маған кел, бәрін ұмыт...» – деп ән салды")
        if lang == 'ru':
            bot.answer_callback_query(call.id, text="💃🏼 Любовница поёт: «Иди ко мне, забудь всё...»")
        return

    if not player.get('has_voted', False):
        chat.vote_counts['skip'] = chat.vote_counts.get('skip', 0) + 1
        player['has_voted'] = True

        if lang == 'kz':
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="🚷 Сіз дауыс беруді өткізіп жіберуді шештіңіз")
        if lang == 'ru':
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="🚷 Вы решили пропустить голосование")

        full_name = get_full_name(player)
        voter_link = f"[{full_name}](tg://user?id={from_id})"

        if lang == 'kz':
            send_message(chat_id, f"🚷 {voter_link} ешкімді аспауды ұсынады", parse_mode="Markdown")
        if lang == 'ru':
            send_message(chat_id, f"🚷 {voter_link} предлагает никого не вешать", parse_mode="Markdown")


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
        lang = 'ru'  # Default language if chat not found
        bot.answer_callback_query(call.id, text="⛔️ Сіз ойында жоқсыз." if lang == 'kz' else "⛔️ Вы не в игре.")
        return

    # Get chat language
    lang = chat_settings.get(chat_id, {}).get("language", "kz")
    
    player = chat.players.get(from_id)

    if player['role'] == 'dead':
        bot.answer_callback_query(call.id, text="⛔️ Сен өлдің!" if lang == 'kz' else "⛔️ Вы мертвы!")
        return

    if chat.confirm_votes.get('player_id') == from_id:
        return

    # Проверка блокировки голосования, если игрока выбрала любовница
    if player.get('voting_blocked', False) and not player.get('healed_from_lover', False):
        bot.answer_callback_query(call.id, text="💃🏼 Менімен бірге бәрін ұмыт..." if lang == 'kz' else "💃🏼 Со мной все забывается...")
        return

    # Проверка, нажимал ли игрок кнопку недавно
    if from_id in vote_timestamps:
        last_vote_time = vote_timestamps[from_id]
        if current_time - last_vote_time < 1:
            bot.answer_callback_query(call.id, text="Дауыс қабылданды!" if lang == 'kz' else "Голос принят!")
            return

    vote_timestamps[from_id] = current_time

    try:
        logging.info(f"Получены данные: {call.data}")
        data_parts = call.data.split('_')

        if len(data_parts) < 2:
            logging.error(f"Недостаточно данных в callback_data: {call.data}")
            return

        action = data_parts[0]
        role = data_parts[1]

        if action in ['yes', 'no']:
            if from_id == chat.confirm_votes['player_id']:
                bot.answer_callback_query(call.id, text="Сіз дауыс бере алмайсыз." if lang == 'kz' else "Вы не можете голосовать.")
                return
            time.sleep(1.5)

        if len(data_parts) == 2 and data_parts[1] == 'gun':
            if not chat.is_night:
                bot.answer_callback_query(call.id, text="🔫 Пистолетті тек түнде қолдануға болады!" if lang == 'kz' else "🔫 Пистолет можно использовать только ночью!")
                return
                
            profile = get_or_create_profile(from_id, player['name'])
            if profile['gun'] <= 0 or profile['gun_used']:
                bot.answer_callback_query(call.id, text="❌ Сізде қолданатын пистолет жоқ!" if lang == 'kz' else "❌ У вас нет доступного пистолета!")
                return
                
            target_id = int(data_parts[0])
            if target_id not in chat.players or chat.players[target_id]['role'] == 'dead':
                bot.answer_callback_query(call.id, text="❌ Мақсат қолжетімсіз!" if lang == 'kz' else "❌ Цель недоступна!")
                return
                
            profile['gun'] -= 1
            chat.gun_kill = (target_id, chat.players[target_id])
            
            target_name = chat.players[target_id]['name']
            bot.edit_message_text(chat_id=call.message.chat.id, 
                                message_id=call.message.message_id, 
                                text=f"🔫 {target_name} дегенді көздедің" if lang == 'kz' else f"🔫 Вы прицелились в {target_name}")
            
            send_message(chat.chat_id, "🔫 Біреу түнде қаруын қолданды..." if lang == 'kz' else "🔫 Кто-то использовал оружие ночью...", parse_mode="Markdown")
            
            bot.answer_callback_query(call.id, text="✅ Таңдауыңыз қабылданды!" if lang == 'kz' else "✅ Ваш выбор принят!")
            return

        # Проверка, что действия Комиссара доступны только ночью
        if role == '🕵🏼 Комиссар':
            if not chat.is_night:
                bot.answer_callback_query(call.id, text="Әрекеттер тек түнде қол жетімді." if lang == 'kz' else "Действия доступны только ночью.")
                return

            if chat.players[from_id].get('action_taken', False):
                bot.answer_callback_query(call.id, text="Сіз бүгін кешке өз таңдауыңызды жасадыңыз." if lang == 'kz' else "Вы уже сделали свой выбор сегодня вечером.")
                return

        # В callback_handler, внутри условия if call.data.startswith('confirm'):
        if call.data.startswith('confirm'):
            data_parts = call.data.split('_')
            player_id = int(data_parts[1])
            vote_confirmation = data_parts[2]
            from_id = call.from_user.id
            chat_id = call.message.chat.id
            chat = chat_list.get(chat_id)
            lang = chat_settings.get(chat_id, {}).get("language", "kz")

            if chat.chat_id != chat_id:
                bot.answer_callback_query(call.id,
                    text="Сіз бұл дауыс беруге қатыса алмайсыз" if lang == 'kz'
                    else "Вы не можете участвовать в этом голосовании")
                return

            if not getattr(chat, 'confirm_votes_active', True):
                bot.answer_callback_query(call.id,
                    text="Дауыс беру аяқталды" if lang == 'kz'
                    else "Голосование завершено")
                return

    # Защита от повторного нажатия на ту же кнопку
            previous_vote = chat.confirm_votes['voted'].get(from_id)
            if previous_vote == vote_confirmation:
                bot.answer_callback_query(call.id,
                    text="Сіз бұл таңдау жасадыңыз" if lang == 'kz'
                    else "Вы уже выбрали это")
                return

    # Убираем предыдущий голос
            if previous_vote == 'yes':
                chat.confirm_votes['yes'] -= 1
            elif previous_vote == 'no':
                chat.confirm_votes['no'] -= 1

    # Учитываем новый голос
            chat.confirm_votes['voted'][from_id] = vote_confirmation
            if vote_confirmation == 'yes':
                chat.confirm_votes['yes'] += 1
            elif vote_confirmation == 'no':
                chat.confirm_votes['no'] += 1

    # Формируем клавиатуру
            confirm_markup = types.InlineKeyboardMarkup()
            confirm_markup.add(
                types.InlineKeyboardButton(f"👍🏼 {chat.confirm_votes['yes']}", callback_data=f"confirm_{player_id}_yes"),
                types.InlineKeyboardButton(f"👎🏼 {chat.confirm_votes['no']}", callback_data=f"confirm_{player_id}_no")
            )

    # Обновляем клавиатуру, если прошло >= 1 секунда
            can_edit = time.time() - confirm_vote_timestamps.get(chat.chat_id, 0) >= 1

            try:
                if can_edit:
                    bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        reply_markup=confirm_markup
                    )
                    confirm_vote_timestamps[chat.chat_id] = time.time()

                bot.answer_callback_query(call.id,
                    text="Дауыс қабылданды!" if lang == 'kz'
                    else "Голос принят!")
            except Exception as e:
                logging.error(f"Ошибка при обновлении клавиатуры голосования: {e}")

    # Проверка завершения голосования
            alive_players_count = len([
                p for pid, p in chat.players.items()
                if p['role'] != 'dead' and p['status'] == 'alive' and pid != chat.confirm_votes['player_id']
            ])

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
                        bot.answer_callback_query(call.id, text="Әрекеттер тек түнде қол жетімді." if lang == 'kz' else "Действия доступны только ночью.")
                        return
                    if chat.players[from_id].get('action_taken', False):
                        bot.answer_callback_query(call.id, text="Сіз бүгін кешке өз таңдауыңызды жасадыңыз." if lang == 'kz' else "Вы уже сделали свой выбор сегодня вечером.")
                        return

                    chat.sheriff_check = target_id
                    chat.players[from_id]['action_taken'] = True
                    if chat.last_sheriff_menu_id:
                        try:
                            bot.edit_message_text(chat_id=from_id, message_id=chat.last_sheriff_menu_id, 
                                                 text=f"Сен тексеруге бардың {chat.players[target_id]['name']}" if lang == 'kz' 
                                                 else f"Вы пошли проверять {chat.players[target_id]['name']}")
                        except Exception as e:
                            logging.error(f"Ошибка при обновлении последнего меню Комиссара: {e}")

                    send_message(chat.chat_id, "🕵🏼 *Комиссар* бұзақыларды іздеуге кетті..." if lang == 'kz' else "🕵🏼 *Комиссар* отправился искать преступников...", parse_mode="Markdown")

                    bot.edit_message_reply_markup(chat_id=from_id, message_id=chat.last_sheriff_menu_id, reply_markup=None)

                    if chat.sergeant_id and chat.sergeant_id in chat.players:
                        sergeant_message = (f"🕵🏼 Комиссар {chat.players[from_id]['name']} дегенді тексеруге кеттің. {chat.players[target_id]['name']}." if lang == 'kz' 
                                         else f"🕵🏼 Комиссар {chat.players[from_id]['name']} пошел проверять {chat.players[target_id]['name']}.")
                        send_message(chat.sergeant_id, sergeant_message)

                elif player_role == '🕵🏼 Комиссар' and action == 'с':
                    if not chat.is_night:
                        bot.answer_callback_query(call.id, text="Комиссарлардың әрекеттері тек түнде болады." if lang == 'kz' else "Действия комиссара доступны только ночью.")
                        return
                    if chat.players[from_id].get('action_taken', False):
                        bot.answer_callback_query(call.id, text="Сіз бүгін кешке өз таңдауыңызды жасадыңыз." if lang == 'kz' else "Вы уже сделали свой выбор сегодня вечером.")
                        return

                    chat.sheriff_shoot = target_id
                    chat.players[from_id]['action_taken'] = True
                    if chat.last_sheriff_menu_id:
                        try:
                            bot.edit_message_text(chat_id=from_id, message_id=chat.last_sheriff_menu_id, 
                                               text=f"Сіз өлтіруге бардыңыз {chat.players[target_id]['name']}" if lang == 'kz' 
                                               else f"Вы пошли стрелять в {chat.players[target_id]['name']}")
                        except Exception as e:
                            logging.error(f"Ошибка при обновлении последнего меню Комиссара: {e}")

                    send_message(chat.chat_id, "🕵🏼 *Комиссар* тапаншасын оқтай бастады..." if lang == 'kz' else "🕵🏼 *Комиссар* начал стрелять...", parse_mode="Markdown")
                    bot.edit_message_reply_markup(chat_id=from_id, message_id=chat.last_sheriff_menu_id, reply_markup=None)

                    if chat.sergeant_id and chat.sergeant_id in chat.players:
                        sergeant_message = (f"🕵🏼 Комиссар {chat.players[from_id]['name']} оқ атады {chat.players[target_id]['name']}." if lang == 'kz' 
                                         else f"🕵🏼 Комиссар {chat.players[from_id]['name']} выстрелил в {chat.players[target_id]['name']}.")
                        send_message(chat.sergeant_id, sergeant_message)

                elif player_role in ['🤵🏻 Мафия', '🧔🏻‍♂️ Дон'] and action == 'м':
                    if not handle_night_action(call, chat, player_role):
                        return

                    if target_id not in chat.players or chat.players[target_id]['role'] == 'dead':
                        bot.answer_callback_query(call.id, "Мақсат қолжетімсіз." if lang == 'kz' else "Цель недоступна.")
                        return

                    victim_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                        text=f"Сіз дауыс бердіңіз {victim_name}" if lang == 'kz' 
                                        else f"Вы проголосовали за {victim_name}")

                    if from_id not in chat.mafia_votes:
                        chat.mafia_votes[from_id] = target_id
                        voter_name = f"{chat.players[from_id]['name']} {chat.players[from_id].get('last_name', '')}".strip()
        
                        if player_role == '🧔🏻‍♂️ Дон':
                            send_message_to_mafia(chat, f"🧔🏻‍♂️ *Дон* [{voter_name}](tg://user?id={from_id}) дауыс берді {victim_name}" if lang == 'kz' 
                                              else f"🧔🏻‍♂️ *Дон* [{voter_name}](tg://user?id={from_id}) проголосовал за {victim_name}")
                            for player_id, player in chat.players.items():
                                if player['role'] == '👨🏼‍💼 Қорғаушы':
                                    send_message(player_id, f"🧔🏻‍♂️ Дон ??? дауыс берді {victim_name}" if lang == 'kz' 
                                              else f"🧔🏻‍♂️ Дон ??? проголосовал за {victim_name}")
                        else:
                            send_message_to_mafia(chat, f"🤵🏻 Мафия [{voter_name}](tg://user?id={from_id}) дауыс берді {victim_name}" if lang == 'kz' 
                                              else f"🤵🏻 Мафия [{voter_name}](tg://user?id={from_id}) проголосовал за {victim_name}")
                            for player_id, player in chat.players.items():
                                if player['role'] == '👨🏼‍💼 Қорғаушы':
                                    send_message(player_id, f"🤵🏻 Мафия ??? дауыс берді {victim_name}" if lang == 'kz' 
                                              else f"🤵🏻 Мафия ??? проголосовал за {victim_name}")
                    else:
                        bot.answer_callback_query(call.id, "Сіз дауыс беріп қойғансыз." if lang == 'kz' else "Вы уже голосовали.")

                elif player_role == '👨🏼‍⚕️ Дәрігер' and action == 'д':
                    if not handle_night_action(call, chat, player_role):
                        return

                    victim_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                       text=f"Сіз емдеуді таңдадыңыз {victim_name}" if lang == 'kz' 
                                       else f"Вы выбрали лечение для {victim_name}")
    
                    if target_id == from_id:
                        if player.get('self_healed', False):  
                            bot.answer_callback_query(call.id, text="Сіз өзіңізді емдедіңіз, басқа ойыншыны таңдаңыз." if lang == 'kz' 
                                                    else "Вы уже лечили себя, выберите другого игрока.")
                            return
                        else:
                            player['self_healed'] = True  
    
                    chat.doc_target = target_id
                    send_message(chat.chat_id, "👨🏼‍⚕️ *Дәрігер* біреудің өмірін құтқаруға үшін шықты…" if lang == 'kz' 
                                  else "👨🏼‍⚕️ *Доктор* отправился спасать чью-то жизнь…", parse_mode="Markdown")

                elif player_role == '🧙‍♂️ Қаңғыбас' and action == 'б':
                    if not handle_night_action(call, chat, player_role):
                        return
                    target_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                    chat.hobo_target = target_id
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                       text=f"Сіз бөтелке алуға бардыңыз {target_name}" if lang == 'kz' 
                                       else f"Вы пошли за бутылкой к {target_name}")
                    send_message(chat.chat_id, "🧙‍♂️ *Қаңғыбас* бөтелке іздеп, біреудің үйіне кетті…" if lang == 'kz' 
                                  else "🧙‍♂️ *Бомж* отправился искать бутылку в чужом доме…", parse_mode="Markdown")

                elif player_role == '💃🏼 Көңілдес' and action == 'л':
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.previous_lover_target_id = chat.lover_target_id
                    chat.lover_target_id = target_id
                    target_name = f"{chat.players[chat.lover_target_id]['name']} {chat.players[chat.lover_target_id].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                       text=f"Сен ләззат сыйлауға кеттің {target_name}" if lang == 'kz' 
                                       else f"Вы отправились доставлять удовольствие {target_name}")
                    send_message(chat.chat_id, "💃🏼 *Көңілдес* өз таңдауына қонаққа кетті..." if lang == 'kz' 
                                  else "💃🏼 *Любовница* отправилась к своему выбору...", parse_mode="Markdown")
                    logging.info(f"Предыдущая цель любовницы обновлена: {chat.previous_lover_target_id}")
                    logging.info(f"Текущая цель любовницы: {chat.lover_target_id}")
                
                elif player_role == '👨🏼‍💼 Қорғаушы' and action == 'а':
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.lawyer_target = target_id
                    target_name = f"{chat.players[chat.lawyer_target]['name']} {chat.players[chat.lawyer_target].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                       text=f"Сіз қорғауды таңдадыңыз {target_name}" if lang == 'kz' 
                                       else f"Вы выбрали защиту для {target_name}")
                    send_message(chat.chat_id, "👨🏼‍💼 *Қорғаушы* қорғау үшін клиент іздейді..." if lang == 'kz' 
                                  else "👨🏼‍💼 *Адвокат* ищет клиента для защиты...", parse_mode="Markdown")

                elif player_role == '🔪 Жауыз' and action == 'мк':
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.maniac_target = target_id
                    target_name = f"{chat.players[chat.maniac_target]['name']} {chat.players[chat.maniac_target].get('last_name', '')}".strip()
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                       text=f"Сіз өлтіруді таңдадыңыз {target_name}" if lang == 'kz' 
                                       else f"Вы выбрали убийство для {target_name}")
                    send_message(chat.chat_id, "🔪 *Жауыз* түнгі аңшылыққа шықты..." if lang == 'kz' 
                                  else "🔪 *Маньяк* отправился на ночную охоту...", parse_mode="Markdown")

                elif action == 'vote':
                    if not chat.is_voting_time:  
                        bot.answer_callback_query(call.id, text="Қазіргі уақытта дауыс беру мүмкін емес." if lang == 'kz' 
                                                else "Сейчас нельзя голосовать.")
                        return

                    if 'vote_counts' not in chat.__dict__:
                        chat.vote_counts = {}

                    if player.get('voting_blocked', False) and not player.get('healed_from_lover', False):
                        bot.answer_callback_query(call.id, text="💃🏼 Менімен бірге бәрін ұмыт..." if lang == 'kz' 
                                                else "💃🏼 Со мной все забывается...")
                        return

                    if not chat.players[from_id].get('has_voted', False):
                        victim_name = f"{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}".strip()
                        chat.vote_counts[target_id] = chat.vote_counts.get(target_id, 0) + 1
                        chat.players[from_id]['has_voted'] = True
                        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                           text=f"Сіз таңдадыңыз {victim_name}" if lang == 'kz' 
                                           else f"Вы выбрали {victim_name}")
                        voter_name = f"[{chat.players[from_id]['name']} {chat.players[from_id].get('last_name', '')}](tg://user?id={from_id})".strip()
                        target_name = f"[{chat.players[target_id]['name']} {chat.players[target_id].get('last_name', '')}](tg://user?id={target_id})".strip()

                        send_message(chat_id, f"{voter_name} өз дауысын {target_name} үшін берді" if lang == 'kz' 
                                      else f"{voter_name} проголосовал за {target_name}", parse_mode="Markdown")

            elif action == 'check':
                if not chat.is_night:
                    bot.answer_callback_query(call.id, text="Әрекеттер тек түнде қол жетімді." if lang == 'kz' 
                                            else "Действия доступны только ночью.")
                    return
                if chat.players[from_id].get('action_taken', False):
                    bot.answer_callback_query(call.id, text="Сіз бүгін кешке өз таңдауыңызды жасадыңыз." if lang == 'kz' 
                                            else "Вы уже сделали свой выбор сегодня вечером.")
                    return
                list_btn(chat.players, from_id, '🕵🏼 Комиссар', 'Кімді тексереміз?' if lang == 'kz' else 'Кого проверить?', 'ш', message_id=chat.last_sheriff_menu_id)

            elif action == 'shoot':
                if not chat.is_night:
                    bot.answer_callback_query(call.id, text="Әрекеттер тек түнде қол жетімді." if lang == 'kz' 
                                            else "Действия доступны только ночью.")
                    return
                if chat.players[from_id].get('action_taken', False):
                    bot.answer_callback_query(call.id, text="Сіз бүгін кешке өз таңдауыңызды жасадыңыз." if lang == 'kz' 
                                            else "Вы уже сделали свой выбор сегодня вечером.")
                    return
                list_btn(chat.players, from_id, '🕵🏼 Комиссар', 'Кімді атамыз?' if lang == 'kz' else 'Кого застрелить?', 'с', message_id=chat.last_sheriff_menu_id)

    except Exception as e:
        logging.error(f"Ошибка в callback_handler: {e}")


def check_player_status(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status in ["kicked", "left", "restricted"]:  # Бан, выход или мут
            leave_game(user_id, chat_id, send_private_message=False)  # Личное сообщение не отправляем
            return False  # Игрок удалён
        return True  # Игрок может продолжать играть
    except Exception as e:
        logging.error(f"Ошибка проверки статуса игрока {user_id}: {e}")
        return True

def monitor_players():
    while True:
        for chat_id, game in chat_list.items():
            for user_id in list(game.players.keys()):  # Копия ключей, чтобы не было ошибок при удалении
                check_player_status(chat_id, user_id)
        time.sleep(0.3)  # Проверяем каждые 15 секунд

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
        lang = chat_settings.get(chat.chat_id, {}).get("language", "kz")

        if not chat.game_running:
            logging.info(f"Игра завершена, игнорируем сообщение от {user_id}")
            return

        # Последние слова мертвого игрока
        if user_id in chat.dead_last_words:
            player_name = f"{chat.dead_last_words.pop(user_id)} {message.from_user.last_name or ''}".strip()
            last_words = message.text
            if last_words:
                player_link = f"[{player_name}](tg://user?id={user_id})"
                try:
                    if lang == 'kz':
                        send_message(chat.chat_id, f"Тұрғындардың біреуі {player_link} өлер алдында айғайлағанын есітіпті:\n_{last_words}_", parse_mode="Markdown")
                    if lang == 'ru':
                        send_message(chat.chat_id, f"Кто-то из жителей услышал предсмертный крик {player_link}:\n_{last_words}_", parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Не удалось отправить последние слова игрока {user_id} в чат: {e}")
                
                try:
                    if lang == 'kz':
                        send_message(user_id, "*Хабарлама қабылданып, чатқа жіберілді.*", parse_mode='Markdown')
                    if lang == 'ru':
                        send_message(user_id, "*Сообщение получено и отправлено в чат.*", parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Не удалось отправить подтверждение игроку {user_id}: {e}")
            return

        # Пересылка сообщений между Комиссаром и Сержантом только ночью
        if chat.is_night:
            if user_id == chat.sheriff_id and chat.sergeant_id in chat.players:
                sheriff_name = f"{chat.players[user_id]['name']} {chat.players[user_id].get('last_name', '')}".strip()
                try:
                    if lang == 'kz':
                        send_message(chat.sergeant_id, f"🕵🏼 *Комиссар {sheriff_name}*:\n{message.text}", parse_mode='Markdown')
                    if lang == 'ru':
                        send_message(chat.sergeant_id, f"🕵🏼 *Комиссар {sheriff_name}*:\n{message.text}", parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение от Комиссара {user_id} к Сержанту {chat.sergeant_id}: {e}")

            elif user_id == chat.sergeant_id and chat.sheriff_id in chat.players:
                sergeant_name = f"{chat.players[user_id]['name']} {chat.players[user_id].get('last_name', '')}".strip()
                try:
                    if lang == 'kz':
                        send_message(chat.sheriff_id, f"👮🏼 *Сержант {sergeant_name}*:\n{message.text}", parse_mode='Markdown')
                    if lang == 'ru':
                        send_message(chat.sheriff_id, f"👮🏼 *Сержант {sergeant_name}*:\n{message.text}", parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение от Сержанта {user_id} к Комиссару {chat.sheriff_id}: {e}")

            elif chat.players[user_id]['role'] in ['🧔🏻‍♂️ Дон', '🤵🏻 Мафия']:
                mafia_name = f"{chat.players[user_id]['name']}"
                mafia_last_name = chat.players[user_id].get('last_name', '')
                try:
                    notify_mafia(chat, mafia_name, mafia_last_name, message.text, user_id)
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение от мафии/Дона {user_id}: {e}")

executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)  # Ограничиваем до 3 потоков

def delete_message_in_thread(chat_id, message_id):
    def delete():
        try:
            bot.delete_message(chat_id, message_id)
            logging.info(f"Сообщение {message_id} удалено в чате {chat_id}")
        except Exception as e:
            logging.warning(f"Ошибка при удалении сообщения {message_id} в чате {chat_id}: {e}")

    executor.submit(delete)  # Запускаем удаление в пуле потоков

@bot.message_handler(content_types=['text', 'sticker', 'photo', 'video', 'document', 'audio', 'voice', 'animation'])
def handle_message(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    chat = chat_list.get(chat_id)
    if chat and chat.game_running:
        # Определение, является ли отправитель админом
        is_admin = False
        if message.sender_chat:
            # Анонимный админ
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
            if ((user_id not in chat.players or player.get('role') == 'dead') or 
                (chat.lover_target_id is not None and user_id == chat.lover_target_id and not player.get('healed_from_lover', False))) and \
                not (is_admin and message_type == 'text' and message.text.startswith('!')):
                logging.info(f"Удаление сообщения днём от {user_id}: {message_type}")
                delete_message_in_thread(chat_id, message.message_id)

bot.skip_pending = True

bot.infinity_polling()
