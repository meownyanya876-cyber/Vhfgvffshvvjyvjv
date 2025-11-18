import asyncio
import logging
import json
import aiofiles
import os
import random
from enum import Enum
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)

API_TOKEN = '8451280584:AAEjtbULV6VqyaOdEgMTwCbn0IgNyQrgKCI'

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

NIGHT_DURATION = 40
DAY_DISCUSSION_DURATION = 45
VOTING_DURATION = 40

class PlayerRole(Enum):
    CIVILIAN = "civilian"
    MAFIA = "mafia"
    SHERIFF = "sheriff"
    DON = "don"
    ADVOCATE = "advocate"
    DOCTOR = "doctor"
    MANIAC = "maniac"
    STUKACH = "stukach"
    LOVER = "lover"
    VAMPIRE = "vampire"
    BUM = "bum"

NIGHT_PHOTO = "AgACAgIAAyEFAATBcV3tAAPZaRm1aRjlRQVXtWD1XAYaN8kPek0AAhsOaxslJtBIR7xaizzvFVIBAAMCAAN5AAM2BA"
MORNING_PHOTO = "AgACAgIAAyEFAATBcV3tAAPbaRm1r76uNAxxVChQnJZ6H0C-8tIAAh0OaxslJtBIiLzDshPRKs4BAAMCAAN5AAM2BA"

class Player:
    def __init__(self, user_id: int, username: str, first_name: str, chat_id: int):
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.chat_id = chat_id
        self.role: Optional[PlayerRole] = None
        self.is_alive: bool = True
        self.votes_against: int = 0

        self.last_guarded_player: Optional[int] = None
        self.action_message_id: Optional[int] = None

        self.advocate_alibi_given_to_self: bool = False
        self.advocate_alibi_history: Dict[int, int] = {}
        self.advocate_alibi_current: Optional[int] = None

        self.vampire_bitten: Optional[int] = None
        self.vampire_can_control: bool = False
        self.lover_blocked: bool = False
        self.stukach_target: Optional[int] = None

        self.mafia_chat_messages: List[Dict] = []
        self.doctor_self_healed: bool = False

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "first_name": self.first_name,
            "chat_id": self.chat_id,
            "role": self.role.value if self.role else None,
            "is_alive": self.is_alive,
            "votes_against": self.votes_against,
            "last_guarded_player": self.last_guarded_player,
            "action_message_id": self.action_message_id,
            "advocate_alibi_given_to_self": self.advocate_alibi_given_to_self,
            "advocate_alibi_history": self.advocate_alibi_history,
            "advocate_alibi_current": self.advocate_alibi_current,
            "vampire_bitten": self.vampire_bitten,
            "vampire_can_control": self.vampire_can_control,
            "lover_blocked": self.lover_blocked,
            "stukach_target": self.stukach_target,
            "mafia_chat_messages": self.mafia_chat_messages,
            "doctor_self_healed": self.doctor_self_healed
        }

    @classmethod
    def from_dict(cls, data):
        player = cls(data['user_id'], data['username'], data.get('first_name', data['username']), data['chat_id'])
        player.role = PlayerRole(data['role']) if data['role'] else None
        player.is_alive = data['is_alive']
        player.votes_against = data['votes_against']

        player.last_guarded_player = data.get('last_guarded_player', None)
        player.action_message_id = data.get('action_message_id', None)
        player.advocate_alibi_given_to_self = data.get('advocate_alibi_given_to_self', False)
        player.advocate_alibi_history = data.get('advocate_alibi_history', {})
        player.advocate_alibi_current = data.get('advocate_alibi_current', None)
        player.vampire_bitten = data.get('vampire_bitten', None)
        player.vampire_can_control = data.get('vampire_can_control', False)
        player.lover_blocked = data.get('lover_blocked', False)
        player.stukach_target = data.get('stukach_target', None)
        player.mafia_chat_messages = data.get('mafia_chat_messages', [])
        player.doctor_self_healed = data.get('doctor_self_healed', False)

        return player

class Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.players: List[Player] = []
        self.is_active: bool = False
        self.day_number: int = 0
        self.night_actions: Dict = {}
        self.votes: Dict = {}
        self.night_kills: List[str] = []

        self.registration_message_id: Optional[int] = None

        self.final_vote_message_id: Optional[int] = None
        self.final_votes: Dict = {"execute": set(), "pardon": set()}
        self.candidate_for_execution: Optional[int] = None

        self.night_timer: Optional[asyncio.Task] = None
        self.day_timer: Optional[asyncio.Task] = None
        self.voting_timer: Optional[asyncio.Task] = None
        self.final_voting_timer: Optional[asyncio.Task] = None

        self.current_phase: str = "waiting"

        self.death_note_message: Dict[int, str] = {}

        self.night_visits: Dict[int, List[PlayerRole]] = {}

        self.sheriff_check_target: Optional[int] = None
        self.lover_blocked_players: List[int] = []
        self.vampire_bite_target: Optional[int] = None
        self.vampire_last_bite_target: Optional[int] = None
        self.bum_visit_target: Optional[int] = None

        self.mafia_chat_active: bool = False
        self.group_invite_link: Optional[str] = None

    def to_dict(self):
        return {
            "chat_id": self.chat_id,
            "players": [player.to_dict() for player in self.players],
            "is_active": self.is_active,
            "day_number": self.day_number,
            "night_actions": self.night_actions,
            "votes": self.votes,
            "night_kills": self.night_kills,
            "registration_message_id": self.registration_message_id,
            "final_vote_message_id": self.final_vote_message_id,
            "final_votes": {"execute": list(self.final_votes["execute"]), "pardon": list(self.final_votes["pardon"])},
            "candidate_for_execution": self.candidate_for_execution,
            "current_phase": self.current_phase,
            "death_note_message": self.death_note_message,
            "night_visits": {str(k): [r.value for r in v] for k, v in self.night_visits.items()},
            "sheriff_check_target": self.sheriff_check_target,
            "lover_blocked_players": self.lover_blocked_players,
            "vampire_bite_target": self.vampire_bite_target,
            "vampire_last_bite_target": self.vampire_last_bite_target,
            "bum_visit_target": self.bum_visit_target,
            "mafia_chat_active": self.mafia_chat_active,
            "group_invite_link": self.group_invite_link
        }

    @classmethod
    def from_dict(cls, data):
        game = cls(data['chat_id'])
        game.players = [Player.from_dict(player_data) for player_data in data['players']]
        game.is_active = data['is_active']
        game.day_number = data['day_number']
        game.night_actions = data['night_actions']
        game.votes = data.get('votes', {})
        game.night_kills = data.get('night_kills', [])
        game.registration_message_id = data.get('registration_message_id', None)
        game.final_vote_message_id = data.get('final_vote_message_id', None)
        game.candidate_for_execution = data.get('candidate_for_execution', None)

        final_votes_data = data.get('final_votes', {"execute": [], "pardon": []})
        game.final_votes = {
            "execute": set(final_votes_data.get("execute", [])),
            "pardon": set(final_votes_data.get("pardon", []))
        }
        game.current_phase = data.get('current_phase', 'waiting')
        game.death_note_message = data.get('death_note_message', {})
        night_visits_data = data.get('night_visits', {})
        game.night_visits = {}
        for user_id_str, roles_list in night_visits_data.items():
            user_id = int(user_id_str)
            game.night_visits[user_id] = [PlayerRole(role_value) for role_value in roles_list]

        game.sheriff_check_target = data.get('sheriff_check_target', None)
        game.lover_blocked_players = data.get('lover_blocked_players', [])
        game.vampire_bite_target = data.get('vampire_bite_target', None)
        game.vampire_last_bite_target = data.get('vampire_last_bite_target', None)
        game.bum_visit_target = data.get('bum_visit_target', None)
        game.mafia_chat_active = data.get('mafia_chat_active', False)
        game.group_invite_link = data.get('group_invite_link', None)

        return game

DATA_FILE = "data/games.json"

async def safe_callback_answer(callback: CallbackQuery, text: str = "", show_alert: bool = False):
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as e:
        error_str = str(e).lower()
        if "query is too old" in error_str or "query id is invalid" in error_str or "response timeout expired" in error_str:
            logging.debug(f"Ignoring expired callback query: {e}")
        else:
            logging.error(f"Error answering callback query: {e}")

async def save_games(games: Dict[int, Game]):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)

    async with aiofiles.open(DATA_FILE, 'w', encoding='utf-8') as f:
        games_dict = {str(chat_id): game.to_dict() for chat_id, game in games.items()}
        await f.write(json.dumps(games_dict, indent=4, ensure_ascii=False))

async def load_games() -> Dict[int, Game]:
    try:
        async with aiofiles.open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            if not content:
                return {}
            games_dict = json.loads(content)
            games = {}
            for chat_id_str, game_data in games_dict.items():
                games[int(chat_id_str)] = Game.from_dict(game_data)
            return games
    except FileNotFoundError:
        return {}

active_games = {}

async def get_group_invite_link(game: Game) -> str:
    if game.group_invite_link:
        return game.group_invite_link
    
    try:
        chat = await bot.get_chat(game.chat_id)
        invite_link = await chat.export_invite_link()
        game.group_invite_link = invite_link
        await save_games(active_games)
        return invite_link
    except Exception as e:
        logging.error(f"Не удалось получить ссылку на группу: {e}")
        return f"https://t.me/{(await bot.get_me()).username}"

@router.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type == "private":
        await handle_private_start(message)
    else:
        await message.answer(
            "🎮 Добро пожаловать в Мафию!\n\n"
            "Для настройки игры используйте команду /menu",
            reply_markup=ReplyKeyboardRemove()
        )

async def handle_private_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    first_name = message.from_user.first_name

    target_game = None
    target_chat_id = None

    for chat_id, game in active_games.items():
        if not game.is_active:
            player_exists = any(p.user_id == user_id for p in game.players)
            if not player_exists:
                target_game = game
                target_chat_id = chat_id
                break

    if not target_game:
        await message.answer(
            "❌ В данный момент нет открытой регистрации в мафию.\n\n"
            "Попросите администратора создать игру в групповом чате!",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    new_player = Player(user_id, username, first_name, target_chat_id)
    target_game.players.append(new_player)
    await save_games(active_games)

    try:
        invite_link = await get_group_invite_link(target_game)
        
        group_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎮 Перейти в группу",
                        url=invite_link
                    )
                ]
            ]
        )
    except Exception as e:
        logging.error(f"Не удалось получить ссылку на группу: {e}")
        group_keyboard = None

    await message.answer(
        "✅ Ты присоединился к игре!",
        reply_markup=group_keyboard
    )

    await update_registration_message(target_game)

async def update_registration_message(game: Game):
    if not game.registration_message_id:
        return

    players_text = "📋 Зарегистрированные игроки:\n" + "\n".join(
        [f"• {player.first_name}" for player in game.players]
    )

    can_start = can_start_game(len(game.players))

    try:
        invite_link = await get_group_invite_link(game)
        keyboard_buttons = [
            [InlineKeyboardButton(text="🎮 Присоединиться к игре", url=f"https://t.me/{(await bot.get_me()).username}?start=join_{game.chat_id}")]
        ]

        if can_start["can_start"]:
            keyboard_buttons.append([InlineKeyboardButton(text="🚀 ▶️ Начать игру", callback_data=f"start_game_{game.chat_id}")])
        else:
            keyboard_buttons.append([InlineKeyboardButton(text=f"⏳ Нужно {can_start['required']} игроков", callback_data="no_action")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        status_text = "✅ Можно начинать!" if can_start["can_start"] else f"⏳ Нужно {can_start['required']} игроков"

        try:
            await bot.edit_message_text(
                chat_id=game.chat_id,
                message_id=game.registration_message_id,
                text=f"🎯 <b>Регистрация на игру открыта!</b>\n\n"
                     f"{players_text}\n\n"
                     f"📊 <b>Всего игроков:</b> {len(game.players)}\n"
                     f"{status_text}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось обновить сообщение с регистрацией: {e}")
    except Exception as e:
        logging.error(f"Ошибка при обновлении сообщения регистрации: {e}")

def can_start_game(player_count: int) -> Dict:
    valid_counts = [4, 5, 6, 7, 8, 9, 10]
    if player_count in valid_counts:
        return {"can_start": True, "required": player_count}
    else:
        for count in valid_counts:
            if player_count < count:
                return {"can_start": False, "required": count}
        return {"can_start": False, "required": 10}

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах!")
        return

    chat_id = message.chat.id

    if chat_id in active_games and active_games[chat_id].is_active:
        await message.answer("❌ В этом чате уже идет активная игра! Дождитесь её окончания.")
        return

    await start_registration(message)

@router.message(Command("startgame"))
async def cmd_startgame(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах!")
        return

    chat_id = message.chat.id

    if chat_id not in active_games:
        active_games[chat_id] = Game(chat_id)

    await start_registration(message)

async def start_registration(message: Message):
    chat_id = message.chat.id

    if chat_id not in active_games:
        active_games[chat_id] = Game(chat_id)

    if active_games[chat_id].is_active:
        await message.answer("❌ В этом чате уже идет активная игра!")
        return

    active_games[chat_id].players = []

    players_text = "📋 Зарегистрированные игроки:\n• Пока никого"

    try:
        invite_link = await get_group_invite_link(active_games[chat_id])
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Присоединиться к игре", url=f"https://t.me/{(await bot.get_me()).username}?start=join_{chat_id}")],
                [InlineKeyboardButton(text="⏳ Нужно 4 игрока", callback_data="no_action")]
            ]
        )
    except Exception as e:
        logging.error(f"Ошибка при создании клавиатуры: {e}")
        keyboard = None

    registration_message = await message.answer(
        f"🎯 <b>Регистрация на игру открыта!</b>\n\n"
        f"{players_text}\n\n"
        f"📊 <b>Всего игроков:</b> 0\n"
        f"⏳ Нужно 4 игрока",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    active_games[chat_id].registration_message_id = registration_message.message_id
    await save_games(active_games)

@router.callback_query(F.data.startswith("start_game_"))
async def start_game_callback(callback: CallbackQuery):
    chat_id = int(callback.data.split("_")[2])

    if chat_id not in active_games:
        await safe_callback_answer(callback, "❌ Игра не найдена!")
        return

    game = active_games[chat_id]

    if game.is_active:
        await safe_callback_answer(callback, "❌ Игра уже начата!")
        return

    start_check = can_start_game(len(game.players))
    if not start_check["can_start"]:
        await safe_callback_answer(callback, f"❌ Нельзя начать с {len(game.players)} игроками! Нужно {start_check['required']}")
        return

    if len(game.players) == 0:
        await safe_callback_answer(callback, "❌ Нет зарегистрированных игроков!")
        return

    try:
        member = await bot.get_chat_member(chat_id, callback.from_user.id)
        if member.status not in ["administrator", "creator"]:
            await safe_callback_answer(callback, "❌ Только администратор может начать игру!")
            return
    except Exception as e:
        logging.error(f"Не удалось проверить права администратора: {e}")
        await safe_callback_answer(callback, "❌ Не удалось проверить права администратора!")
        return

    logging.info(f"Начинаем игру в чате {chat_id} с {len(game.players)} игроками")

    game.is_active = True
    game.day_number = 1
    await save_games(active_games)

    try:
        await bot.delete_message(chat_id=chat_id, message_id=game.registration_message_id)
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение с регистрацией: {e}")

    logging.info("Распределяем роли для классической мафии")
    await assign_classic_roles(game)

    try:
        invite_link = await get_group_invite_link(game)
        
        night_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎮 Перейти в бота",
                        url=f"https://t.me/{(await bot.get_me()).username}"
                    )
                ]
            ]
        )
    except Exception as e:
        logging.error(f"Не удалось создать клавиатуру: {e}")
        night_keyboard = None

    try:
        await bot.send_photo(
            game.chat_id,
            photo=NIGHT_PHOTO,
            caption="🌙 Наступает ночь ❄️\n"
                   "На улицы города выходят лишь самые отважные и бесстрашные.\n"
                   "Утром попробуем сосчитать их головы...",
            reply_markup=night_keyboard
        )
    except Exception as e:
        logging.error(f"Не удалось отправить ночное фото: {e}")
        await bot.send_message(
            game.chat_id,
            "🌙 Наступает ночь ❄️\n"
            "На улицы города выходят лишь самые отважные и бесстрашные.\n"
            "Утром попробуем сосчитать их головы...",
            reply_markup=night_keyboard
        )

    await asyncio.sleep(1)

    await send_players_list(game)

    await send_roles_to_players(game)

    await reveal_advocate_and_mafia(game)

    await send_night_actions_to_players(game)

    game.night_timer = asyncio.create_task(night_timer(game))
    game.current_phase = "night"
    await save_games(active_games)

    await safe_callback_answer(callback, "🎮 Игра началась!")

async def assign_classic_roles(game: Game):
    players = game.players.copy()
    random.shuffle(players)

    player_count = len(players)

    if player_count == 4:
        players[0].role = PlayerRole.SHERIFF
        players[1].role = PlayerRole.VAMPIRE
        players[2].role = PlayerRole.DOCTOR
        players[3].role = PlayerRole.LOVER
    elif player_count == 5:
        players[0].role = PlayerRole.SHERIFF
        players[1].role = PlayerRole.ADVOCATE
        players[2].role = PlayerRole.DOCTOR
        players[3].role = PlayerRole.STUKACH
        players[4].role = PlayerRole.CIVILIAN
    elif player_count == 6:
        players[0].role = PlayerRole.SHERIFF
        players[1].role = PlayerRole.DON
        players[2].role = PlayerRole.DOCTOR
        players[3].role = PlayerRole.ADVOCATE
        players[4].role = PlayerRole.LOVER
        players[5].role = PlayerRole.CIVILIAN
    elif player_count == 7:
        players[0].role = PlayerRole.SHERIFF
        players[1].role = PlayerRole.VAMPIRE
        players[2].role = PlayerRole.DOCTOR
        players[3].role = PlayerRole.ADVOCATE
        players[4].role = PlayerRole.LOVER
        players[5].role = PlayerRole.BUM
        players[6].role = PlayerRole.CIVILIAN
    else:
        mafia_count = 1
        sheriff_count = 1

        for i in range(mafia_count):
            if i < len(players):
                players[i].role = PlayerRole.MAFIA

        if mafia_count < len(players):
            players[mafia_count].role = PlayerRole.SHERIFF

        for i in range(mafia_count + sheriff_count, len(players)):
            players[i].role = PlayerRole.CIVILIAN

async def reveal_advocate_and_mafia(game: Game):
    advocate_player = next((p for p in game.players if p.role == PlayerRole.ADVOCATE), None)
    don_player = next((p for p in game.players if p.role == PlayerRole.DON), None)
    vampire_player = next((p for p in game.players if p.role == PlayerRole.VAMPIRE), None)
    mafia_players = [p for p in game.players if p.role == PlayerRole.MAFIA]

    if advocate_player and don_player:
        allies_text = f"🤵🏻 <b>{don_player.first_name}</b> - это Дон (ваш союзник)"
        if vampire_player:
            allies_text += f"\n🧛 <b>{vampire_player.first_name}</b> - это Вампир (ваш союзник)"

        try:
            await bot.send_message(
                advocate_player.user_id,
                f"⚖️ Вы знаете своих союзников!\n\n{allies_text}\n\nВы работаете вместе и стреляете вместе!",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение адвокату о союзниках: {e}")

        allies_text_don = f"👨🏼‍💼 <b>{advocate_player.first_name}</b> - это Адвокат (ваш союзник)"
        if vampire_player:
            allies_text_don += f"\n🧛 <b>{vampire_player.first_name}</b> - это Вампир (ваш союзник)"

        try:
            await bot.send_message(
                don_player.user_id,
                f"⚖️ Вы знаете своих союзников!\n\n{allies_text_don}\n\nВы работаете вместе и стреляете вместе!",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение дону об адвокате: {e}")

        if vampire_player:
            allies_text_vampire = f"🤵🏻 <b>{don_player.first_name}</b> - это Дон (ваш союзник)\n👨🏼‍💼 <b>{advocate_player.first_name}</b> - это Адвокат (ваш союзник)"
            try:
                await bot.send_message(
                    vampire_player.user_id,
                    f"🧛 Вы знаете своих союзников!\n\n{allies_text_vampire}\n\nВы работаете вместе и стреляете вместе!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение вампиру о союзниках: {e}")

    elif advocate_player and mafia_players:
        mafia_names = ", ".join([f"<b>{p.first_name}</b>" for p in mafia_players])
        try:
            await bot.send_message(
                advocate_player.user_id,
                f"⚖️ Вы знаете своих союзников!\n\n"
                f"🔫 Ваши союзники: {mafia_names}\n\n"
                f"Вы работаете вместе и стреляете вместе!",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение адвокату о мафии: {e}")

        for mafia_player in mafia_players:
            try:
                await bot.send_message(
                    mafia_player.user_id,
                    f"⚖️ Вы знаете своего союзника!\n\n"
                    f"👥 <b>{advocate_player.first_name}</b> - это Адвокат (ваш союзник)\n\n"
                    f"Вы работаете вместе и стреляете вместе!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение мафии об адвокате: {e}")

async def send_players_list(game: Game):
    alive_players = [p for p in game.players if p.is_alive]

    players_list = []
    for i, p in enumerate(alive_players):
        player_link = f'<a href="tg://user?id={p.user_id}">{p.first_name}</a>'
        players_list.append(f"{i+1}. {player_link}")

    players_text = "👥 <b>Живые игроки:</b>\n" + "\n".join(players_list)

    role_counts = {}
    for p in alive_players:
        role_name = get_role_name(p.role)
        if role_name in role_counts:
            role_counts[role_name] += 1
        else:
            role_counts[role_name] = 1

    roles_hint = f"\n\n<b>Кто-то из них:</b>\n"
    role_lines = []
    for role_name, count in role_counts.items():
        role_emoji = get_role_emoji_by_name(role_name)
        if count > 1:
            role_lines.append(f"{role_emoji} <b>{role_name}</b> - {count}")
        else:
            role_lines.append(f"{role_emoji} <b>{role_name}</b>")
    
    roles_hint += " | ".join(role_lines)
    roles_hint += f"\n\n<b>Всего:</b> {len(alive_players)} чел."

    final_text = players_text + roles_hint

    await bot.send_message(game.chat_id, final_text, parse_mode="HTML")

def get_role_emoji_by_name(role_name: str) -> str:
    emoji_map = {
        "Мирный житель": "👨🏼",
        "Мафия": "🔫",
        "Комиссар Каттани": "🕵🏼",
        "Дон": "🤵🏻",
        "Адвокат": "👨🏼‍💼",
        "Доктор": "👨🏼‍⚕️️",
        "Маньяк": "🔪",
        "Стукач": "🤓",
        "Любовница": "💃",
        "Вампир": "🧛",
        "Бомж": "🧙🏻"
    }
    return emoji_map.get(role_name, "❓")

async def send_roles_to_players(game: Game):
    role_assignments = []

    logging.info(f"Начинаем отправку ролей для {len(game.players)} игроков")

    for player in game.players:
        if not player.role:
            logging.error(f"У игрока {player.first_name} нет роли!")
            continue

        role_text = get_role_description(player.role)
        role_emoji = get_role_emoji(player.role)
        role_name = get_role_name(player.role)

        try:
            await bot.send_chat_action(player.user_id, "typing")

            try:
                invite_link = await get_group_invite_link(game)
                
                group_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🎮 Перейти в группу",
                                url=invite_link
                            )
                        ]
                    ]
                )
            except Exception as e:
                logging.error(f"Не удалось создать клавиатуру: {e}")
                group_keyboard = None

            await bot.send_message(
                player.user_id,
                role_text,
                reply_markup=group_keyboard,
                parse_mode="HTML"
            )

            role_assignments.append(f"• {player.first_name} - {role_name}")
            logging.info(f"✅ Роль отправлена игроку {player.first_name}: {player.role}")

            await asyncio.sleep(0.3)

        except Exception as e:
            error_msg = f"❌ Не удалось отправить сообщение игроку {player.first_name}: {e}"
            logging.error(error_msg)
            role_assignments.append(f"• {player.first_name} - ❌ Ошибка отправки")

    logging.info("=== РАСПРЕДЕЛЕНИЕ РОЛЕЙ ===")
    for assignment in role_assignments:
        logging.info(assignment)
    logging.info("=== КОНЕЦ РАСПРЕДЕЛЕНИЯ ===")

    await save_games(active_games)

async def send_night_actions_to_players(game: Game):
    active_players = 0
    for player in game.players:
        if player.is_alive:
            try:
                sent = await send_classic_night_actions(player, game)
                if sent:
                    active_players += 1
            except Exception as e:
                logging.error(f"Не удалось отправить ночное действие игроку {player.first_name}: {e}")

    await activate_mafia_chat(game)

    logging.info(f"Ночные действия отправлены {active_players} игрокам")

async def activate_mafia_chat(game: Game):
    mafia_players = [p for p in game.players if p.is_alive and p.role in [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.ADVOCATE, PlayerRole.VAMPIRE]]
    
    if len(mafia_players) > 1:
        game.mafia_chat_active = True
        await save_games(active_games)
        
        for player in mafia_players:
            try:
                try:
                    invite_link = await get_group_invite_link(game)
                    
                    group_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🎮 Перейти в группу",
                                    url=invite_link
                                )
                            ]
                        ]
                    )
                except Exception as e:
                    logging.error(f"Не удалось создать клавиатуру: {e}")
                    group_keyboard = None

                await bot.send_message(
                    player.user_id,
                    "<b>Вы можете общаться с другими членами мафии в этом чате.!</b>",
                    reply_markup=group_keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение о чате мафии игроку {player.first_name}: {e}")

def get_role_emoji(role: PlayerRole) -> str:
    emojis = {
        PlayerRole.CIVILIAN: "👨🏼",
        PlayerRole.MAFIA: "🔫", 
        PlayerRole.SHERIFF: "🕵🏼",
        PlayerRole.DON: "🤵🏻",
        PlayerRole.ADVOCATE: "👨🏼‍💼",
        PlayerRole.DOCTOR: "👨🏼‍⚕️️",
        PlayerRole.MANIAC: "🔪",
        PlayerRole.STUKACH: "🤓",
        PlayerRole.LOVER: "💃",
        PlayerRole.VAMPIRE: "🧛",
        PlayerRole.BUM: "🧙🏻"
    }
    return emojis.get(role, "❓")

def get_role_name(role: PlayerRole) -> str:
    names = {
        PlayerRole.CIVILIAN: "Мирный житель",
        PlayerRole.MAFIA: "Мафия",
        PlayerRole.SHERIFF: "Комиссар Каттани",
        PlayerRole.DON: "Дон",
        PlayerRole.ADVOCATE: "Адвокат",
        PlayerRole.DOCTOR: "Доктор",
        PlayerRole.MANIAC: "Маньяк",
        PlayerRole.STUKACH: "Стукач",
        PlayerRole.LOVER: "Любовница",
        PlayerRole.VAMPIRE: "Вампир",
        PlayerRole.BUM: "Бомж"
    }
    return names.get(role, "Неизвестная роль")

def get_role_description(role: PlayerRole) -> str:
    descriptions = {
        PlayerRole.CIVILIAN: "Твоя роль - <b>👨🏼 Мирный житель!</b>\n\nТвоя задача: вычислить и проголосовать против мафии днем.",

        PlayerRole.MAFIA: "Твоя роль - <b>🔫 Мафия!</b>\n\nТвоя задача: устранять мирных жителей ночью.",

        PlayerRole.DON: "Твоя роль - <b>🤵🏻 Дон!</b>\n\nТебе решать кто не проснётся этой ночью...",

        PlayerRole.ADVOCATE: "Твоя роль - <b>👨🏼‍💼 Адвокат!</b>\n\nТвоя задача защитить группировку мафии. Игрок, выбранный ночью адвокатом будет защищен от линчевания на людском собрании. Твоя задача, чтобы Мафия победила. Адвокат может защитить себя при необходимости от линчевания только один раз.",

        PlayerRole.SHERIFF: "Твоя роль - <b>🕵🏼 Комиссар Каттани!</b>\n\nГлавный городской защитник и гроза мафии. Твоя задача - находить мафию и исключать во время голосования.",

        PlayerRole.DOCTOR: "Твоя роль - <b>👨🏼‍⚕️️ Доктор!</b>\n\nТвоя задача - лечить игроков ночью. Ты можешь вылечить себя только один раз за игру.",

        PlayerRole.MANIAC: "Твоя роль - <b>🔪 Маньяк!</b>\n\nТвоя задача: убивать игроков ночью.\n\nОсобенности:\n• Ты играешь сам за себя\n• Можешь убивать одного игрока каждую ночь",

        PlayerRole.STUKACH: "Твоя роль - <b>🤓 Стукач!</b>\n\nТы играешь за мирных. Твоя цель - проверить того же игрока, что и комиссар в ту же ночь. Роль проверенного будет раскрыта в общий чат.",

        PlayerRole.LOVER: "Твоя роль - <b>💃 Любовница!</b>\n\nТот, кого ты навестишь ночью, не сможет сделать ночную активность (она будет отменена), также игрок не сможет голосовать.",

        PlayerRole.VAMPIRE: "Твоя роль - <b>🧛 Вампир!</b>\n\nТы играешь за мафию, ты видишь друг друга. Первым делом ты можешь укусить игрока. Если этот игрок не комиссар каттани или доктор, ты сможешь управлять его голосом на дневном голосовании. Также после укуса ты можешь стрелять как мафия (если дон жив, то приоритет у дона).",

        PlayerRole.BUM: "Твоя роль - <b>🧙🏻 Бомж!</b>\n\nТвоя задача - зайти за бутылкой к любому игроку и стать свидетелем убийства."
    }

    return descriptions.get(role, "Роль не определена")

async def night_timer(game: Game):
    try:
        await asyncio.sleep(NIGHT_DURATION)
        if game.chat_id in active_games and game.current_phase == "night":
            await process_night_actions(game)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Ошибка в таймере ночи: {e}")

async def check_all_night_actions_complete(game: Game):
    if game.current_phase != "night":
        return

    active_roles_players = []
    for player in game.players:
        if not player.is_alive:
            continue

        if player.role in [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.MANIAC]:
            active_roles_players.append((player.user_id, "kill"))
        elif player.role == PlayerRole.ADVOCATE:
            don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
            if don_alive:
                active_roles_players.append((player.user_id, "alibi"))
                active_roles_players.append((player.user_id, "kill"))
            else:
                active_roles_players.append((player.user_id, "kill"))
        elif player.role == PlayerRole.SHERIFF:
            active_roles_players.append((player.user_id, "sheriff_action"))
        elif player.role == PlayerRole.DOCTOR:
            active_roles_players.append((player.user_id, "guard"))
        elif player.role == PlayerRole.STUKACH:
            active_roles_players.append((player.user_id, "stukach_check"))
        elif player.role == PlayerRole.LOVER:
            active_roles_players.append((player.user_id, "lover_visit"))
        elif player.role == PlayerRole.VAMPIRE:
            active_roles_players.append((player.user_id, "vampire_bite"))
        elif player.role == PlayerRole.BUM:
            active_roles_players.append((player.user_id, "bum_visit"))

    all_complete = True
    for player_id, action_type in active_roles_players:
        found = False
        player_str = str(player_id)

        for action_key in game.night_actions.keys():
            if action_key.startswith(player_str + "_"):
                if action_type == "kill":
                    if "убийство" in action_key or action_key.endswith("_kill_skip"):
                        found = True
                        break
                elif action_type == "check":
                    if "проверка" in action_key:
                        found = True
                        break
                elif action_type == "sheriff_action":
                    if "проверка" in action_key or "убийство_шериф" in action_key:
                        found = True
                        break
                elif action_type == "guard":
                    if "охрана" in action_key:
                        found = True
                        break
                elif action_type == "alibi":
                    if "алиби" in action_key or action_key.endswith("_alibi_skip"):
                        found = True
                        break
                elif action_type == "stukach_check":
                    if "проверка_стукач" in action_key:
                        found = True
                        break
                elif action_type == "lover_visit":
                    if "любовница" in action_key:
                        found = True
                        break
                elif action_type == "vampire_bite":
                    if "укус_вампир" in action_key:
                        found = True
                        break
                elif action_type == "bum_visit":
                    if "бомж" in action_key:
                        found = True
                        break

        if not found:
            all_complete = False
            break

    if all_complete:
        if game.night_timer and not game.night_timer.done():
            game.night_timer.cancel()

        await process_night_actions(game)

async def process_night_actions(game: Game):
    if game.current_phase != "night":
        return

    game.current_phase = "processing"
    await save_games(active_games)

    for blocked_user_id in game.lover_blocked_players:
        keys_to_remove = [key for key in game.night_actions.keys() if key.startswith(str(blocked_user_id) + "_")]
        for key in keys_to_remove:
            del game.night_actions[key]

    killed_players = []

    don_kill = None
    advocate_kill = None
    sheriff_kill = None
    other_kills = []

    for action_key, target_username in game.night_actions.items():
        if "убийство" in action_key:
            player_id_str = action_key.split("_")[0]
            try:
                player_id = int(player_id_str)
                if player_id in game.lover_blocked_players:
                    continue
            except ValueError:
                pass

            target_player = next((p for p in game.players if p.first_name == target_username and p.is_alive), None)
            if target_player:
                if "убийство_дон" in action_key:
                    don_kill = target_player
                elif "убийство_адвокат" in action_key:
                    advocate_kill = target_player
                elif "убийство_шериф" in action_key:
                    sheriff_kill = target_player
                elif "убийство_вампир" in action_key:
                    pass
                elif "убийство" in action_key:
                    other_kills.append(target_player)

    target_player = None
    sheriff_target = None

    if don_kill:
        don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
        if don_alive:
            target_player = don_kill
    elif advocate_kill:
        don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
        if not don_alive:
            target_player = advocate_kill

    if not target_player and other_kills:
        don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
        if not don_alive:
            target_player = random.choice(other_kills)
        else:
            target_player = other_kills[0]

    if sheriff_kill:
        sheriff_target = sheriff_kill

    if target_player:
        killer_role = None
        for action_key, target_username in game.night_actions.items():
            if "убийство" in action_key and target_username == target_player.first_name:
                if "убийство_шериф" in action_key:
                    killer_role = PlayerRole.SHERIFF
                elif "убийство_дон" in action_key:
                    killer_role = PlayerRole.DON
                elif "убийство_адвокат" in action_key:
                    killer_role = PlayerRole.ADVOCATE
                elif "убийство_маньяк" in action_key:
                    killer_role = PlayerRole.MANIAC
                elif "убийство_вампир" in action_key:
                    killer_role = PlayerRole.VAMPIRE
                elif "убийство" in action_key:
                    killer_role = PlayerRole.MAFIA
                break

        guarded_player = next((p for p in game.players if p.last_guarded_player == target_player.user_id and p.role == PlayerRole.DOCTOR), None)
        has_doctor_visit = target_player.user_id in game.night_visits and PlayerRole.DOCTOR in game.night_visits[target_player.user_id]

        if guarded_player or has_doctor_visit:
            if killer_role == PlayerRole.SHERIFF:
                pass
            else:
                pass
            target_player = None

        if target_player:
            target_player.is_alive = False
            killed_players.append((target_player.user_id, target_player.first_name, target_player.role))

            try:
                await bot.send_message(
                    target_player.user_id,
                    "💀 Вы умерли...\n\n"
                    "📜 У вас есть последний шанс оставить предсмертную записку.\n\n"
                    "Напишите ваши последние слова (бот отправит их в группу):"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение умершему игроку: {e}")

    vampire_kill = None
    vampire = next((p for p in game.players if p.role == PlayerRole.VAMPIRE and p.is_alive), None)
    if vampire:
        vampire_action_key = f"{vampire.user_id}_убийство_вампир"
        if vampire_action_key in game.night_actions:
            vampire_kill = next((p for p in game.players if p.first_name == game.night_actions[vampire_action_key] and p.is_alive), None)

    don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
    if vampire_kill and not target_player:
        if not don_alive or not don_kill:
            target_player = vampire_kill
            killer_role = PlayerRole.VAMPIRE

            guarded_player = next((p for p in game.players if p.last_guarded_player == target_player.user_id and p.role == PlayerRole.DOCTOR), None)
            has_doctor_visit = target_player.user_id in game.night_visits and PlayerRole.DOCTOR in game.night_visits[target_player.user_id]

            if guarded_player or has_doctor_visit:
                pass
                target_player = None
            else:
                target_player.is_alive = False
                killed_players.append((target_player.user_id, target_player.first_name, target_player.role))

                try:
                    await bot.send_message(
                        target_player.user_id,
                        "💀 Вы умерли...\n\n"
                        "📜 У вас есть последний шанс оставить предсмертную записку.\n\n"
                        "Напишите ваши последние слова (бот отправит их в группу):"
                    )
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение умершему игроку: {e}")

    if sheriff_target and sheriff_target.is_alive:
        guarded_player = next((p for p in game.players if p.last_guarded_player == sheriff_target.user_id and p.role == PlayerRole.DOCTOR), None)
        has_doctor_visit = sheriff_target.user_id in game.night_visits and PlayerRole.DOCTOR in game.night_visits[sheriff_target.user_id]

        if guarded_player or has_doctor_visit:
            pass
        else:
            already_killed = any(user_id == sheriff_target.user_id for user_id, _, _ in killed_players)
            if not already_killed:
                sheriff_target.is_alive = False
                killed_players.append((sheriff_target.user_id, sheriff_target.first_name, sheriff_target.role))

                try:
                    await bot.send_message(
                        sheriff_target.user_id,
                        "💀 Вы умерли...\n\n"
                        "📜 У вас есть последний шанс оставить предсмертную записку.\n\n"
                        "Напишите ваши последние слова (бот отправит их в группу):"
                    )
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение умершему игроку: {e}")

    await asyncio.sleep(2)
    try:
        await bot.send_photo(
            game.chat_id,
            photo=MORNING_PHOTO,
            caption=f"🌝 <b>Утро: {game.day_number}</b>\n"
                   f"Солнце восходит, подсушивая на тротуарах пролитую ночью кровь...",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить утреннее фото: {e}")
        await bot.send_message(game.chat_id, f"🌝 <b>Утро: {game.day_number}</b>\nСолнце восходит, подсушивая на тротуарах пролитую ночью кровь...", parse_mode="HTML")

    await asyncio.sleep(1)

    if killed_players:
        death_messages = []
        bum_witnesses = []

        for user_id, player_name, role in killed_players:
            player_link = f'<a href="tg://user?id={user_id}">{player_name}</a>'
            role_emoji = get_role_emoji(role)
            role_name_bold = f"<b>{get_role_name(role)}</b>"

            visitors = []
            if user_id in game.night_visits:
                for visitor_role in game.night_visits[user_id]:
                    if visitor_role != PlayerRole.DOCTOR and visitor_role != PlayerRole.BUM:
                        visitors.append(visitor_role)

            death_text = f"Сегодня был жестоко убит {role_emoji} {role_name_bold} {player_link}..."

            if visitors:
                visitor_names = []
                for visitor_role in visitors:
                    visitor_emoji = get_role_emoji(visitor_role)
                    visitor_name = get_role_name(visitor_role)
                    visitor_names.append(f"{visitor_emoji} <b>{visitor_name}</b>")

                if len(visitor_names) == 1:
                    death_text += f"\n\nГоворят, у него в гостях был {visitor_names[0]}"
                else:
                    visitors_str = ", ".join(visitor_names[:-1]) + f" и {visitor_names[-1]}"
                    death_text += f"\n\nГоворят, у него в гостях были {visitors_str}"

            death_messages.append(death_text)

            if game.bum_visit_target == user_id:
                bum = next((p for p in game.players if p.role == PlayerRole.BUM and p.is_alive), None)
                if bum:
                    bum_witnesses.append((bum.user_id, bum.first_name, user_id, player_name))

        if death_messages:
            final_death_text = "\n\n".join(death_messages)
            await bot.send_message(game.chat_id, final_death_text, parse_mode="HTML")

        for bum_user_id, bum_name, killed_user_id, killed_name in bum_witnesses:
            killed_player = next((p for p in game.players if p.user_id == killed_user_id), None)
            killed_link = f'<a href="tg://user?id={killed_user_id}">{killed_name}</a>' if killed_player else killed_name

            killer_role = None
            killer_name = None
            killer_player = None

            don_kill = None
            advocate_kill = None
            vampire_kill = None

            for action_key, target_username in game.night_actions.items():
                if "убийство" in action_key and target_username == killed_name:
                    try:
                        killer_id = int(action_key.split("_")[0])
                        killer = next((p for p in game.players if p.user_id == killer_id), None)
                        if killer:
                            if "убийство_дон" in action_key:
                                don_kill = (killer.role, killer.first_name, killer)
                            elif "убийство_адвокат" in action_key:
                                advocate_kill = (killer.role, killer.first_name, killer)
                            elif "убийство_вампир" in action_key:
                                vampire_kill = (killer.role, killer.first_name, killer)
                            elif not killer_role:
                                killer_role = killer.role
                                killer_name = killer.first_name
                                killer_player = killer
                    except ValueError:
                        pass

            don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
            if don_kill and don_alive:
                killer_role, killer_name, killer_player = don_kill
            elif advocate_kill and not don_alive:
                killer_role, killer_name, killer_player = advocate_kill
            elif vampire_kill:
                don_alive_check = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
                if not don_alive_check:
                    killer_role, killer_name, killer_player = vampire_kill

            if killer_role and killer_name:
                killer_role_emoji = get_role_emoji(killer_role)
                killer_role_name = get_role_name(killer_role)
                killer_role_name_bold = f"<b>{killer_role_name}</b>"
                killer_name_bold = f"<b>{killer_name}</b>"
                try:
                    await bot.send_message(
                        bum_user_id,
                        f"Ночью ты пришёл за бутылкой к ныне покойному {killed_link} и увидел там {killer_name_bold} - {killer_role_emoji} {killer_role_name_bold}.",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение бомжу {bum_name}: {e}")

    stukach = next((p for p in game.players if p.role == PlayerRole.STUKACH and p.is_alive), None)
    if stukach and stukach.stukach_target and game.sheriff_check_target:
        checked_player = next((p for p in game.players if p.user_id == stukach.stukach_target), None)
        if checked_player and game.sheriff_check_target == checked_player.user_id:
            checked_link = f'<a href="tg://user?id={checked_player.user_id}">{checked_player.first_name}</a>'
            checked_role_emoji = get_role_emoji(checked_player.role)
            checked_role_name = f"<b>{get_role_name(checked_player.role)}</b>"
            await bot.send_message(
                game.chat_id,
                f"🤓 <b>Стукач</b> раскрыл роль игрока {checked_link}!\n\n"
                f"🎭 Роль: {checked_role_emoji} {checked_role_name}",
                parse_mode="HTML"
            )

    if not killed_players:
        await bot.send_message(
            game.chat_id,
            "✨ Сегодня никто не погиб! Город вздохнул с облегчением."
        )

    await send_morning_messages_to_players(game, killed_players)

    await asyncio.sleep(2)
    await send_players_list(game)

    if check_game_end_condition(game):
        await end_game(game)
        return

    await asyncio.sleep(2)
    await start_day_phase(game)

async def send_morning_messages_to_players(game: Game, killed_players: List):
    killed_user_ids = {user_id for user_id, _, _ in killed_players}

    killer_by_target = {}
    saved_by_doctor = set()

    for action_key, target_username in game.night_actions.items():
        if "убийство" in action_key:
            target = next((p for p in game.players if p.first_name == target_username), None)
            if target:
                try:
                    killer_id = int(action_key.split("_")[0])
                    killer = next((p for p in game.players if p.user_id == killer_id), None)
                    if killer:
                        killer_by_target[target.user_id] = killer.role
                        if target.user_id not in killed_user_ids:
                            if target.user_id in game.night_visits and PlayerRole.DOCTOR in game.night_visits[target.user_id]:
                                saved_by_doctor.add(target.user_id)
                except ValueError:
                    pass

    for player in game.players:
        if not player.is_alive:
            continue

        if player.user_id not in game.night_visits:
            continue

        visitors = game.night_visits[player.user_id]
        messages_to_send = []

        has_doctor = PlayerRole.DOCTOR in visitors
        was_saved_by_doctor = player.user_id in saved_by_doctor

        has_lover = PlayerRole.LOVER in visitors
        has_vampire = PlayerRole.VAMPIRE in visitors

        if has_doctor and has_lover:
            try:
                await bot.send_message(
                    player.user_id,
                    "💃 <b>Любовница</b> хотела замолкнуть тебя, но увидела, что <b>👨🏼‍⚕️️ Доктор</b> у тебя и ушла!"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение игроку {player.first_name}: {e}")
            visitors = [v for v in visitors if v != PlayerRole.LOVER]

        for visitor_role in visitors:
            if visitor_role == PlayerRole.SHERIFF:
                messages_to_send.append("Кто-то очень сильно заинтересовался вашей ролью.")

            elif visitor_role == PlayerRole.DOCTOR:
                if was_saved_by_doctor:
                    messages_to_send.append("<b>👨🏼‍⚕️️ Доктор</b> вылечил тебя.")
                else:
                    messages_to_send.append("<b>👨🏼‍⚕️️ Доктор</b> приходил к тебе сегодня.")

            elif visitor_role == PlayerRole.DON:
                if player.user_id in killed_user_ids and player.user_id in killer_by_target:
                    if killer_by_target[player.user_id] == PlayerRole.DON:
                        messages_to_send.append("Вы были убиты.")

            elif visitor_role == PlayerRole.VAMPIRE:
                vampire = next((p for p in game.players if p.role == PlayerRole.VAMPIRE and p.is_alive), None)
                if vampire and vampire.vampire_bitten == player.user_id:
                    if has_doctor:
                        messages_to_send.append("Вас пытался укусить <b>🧛 Вампир</b>, но <b>👨🏼‍⚕️️ Доктор</b> прибыл вовремя.")
                    else:
                        messages_to_send.append("Вы были укушены.")
                else:
                    if game.vampire_bite_target == player.user_id:
                        if has_doctor:
                            messages_to_send.append("Вас пытался укусить <b>🧛 Вампир</b>, но <b>👨🏼‍⚕️️ Доктор</b> прибыл вовремя.")
                        else:
                            messages_to_send.append("Вас пытался укусить <b>🧛 Вампир</b>.")

            elif visitor_role == PlayerRole.LOVER:
                messages_to_send.append("К тебе сегодня пришла любовница.")

        if messages_to_send:
            try:
                await bot.send_message(
                    player.user_id,
                    "\n".join(messages_to_send),
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение игроку {player.first_name}: {e}")

    for doctor in game.players:
        if doctor.role == PlayerRole.DOCTOR and doctor.is_alive and doctor.last_guarded_player:
            guarded_player = next((p for p in game.players if p.user_id == doctor.last_guarded_player), None)
            if guarded_player and guarded_player.user_id in saved_by_doctor:
                visitors_to_doctor = []
                if guarded_player.user_id in game.night_visits:
                    for visitor_role in game.night_visits[guarded_player.user_id]:
                        if visitor_role in [PlayerRole.VAMPIRE, PlayerRole.LOVER]:
                            visitors_to_doctor.append(visitor_role)
                
                if visitors_to_doctor:
                    for visitor_role in visitors_to_doctor:
                        if visitor_role == PlayerRole.VAMPIRE:
                            try:
                                guarded_link = f'<a href="tg://user?id={guarded_player.user_id}">{guarded_player.first_name}</a>'
                                await bot.send_message(
                                    doctor.user_id,
                                    f"Сегодня вылечили {guarded_link}! Его гости: <b>🧛 Вампир</b>!",
                                    parse_mode="HTML"
                                )
                            except Exception as e:
                                logging.error(f"Не удалось отправить сообщение доктору {doctor.first_name}: {e}")
                        elif visitor_role == PlayerRole.LOVER:
                            try:
                                guarded_link = f'<a href="tg://user?id={guarded_player.user_id}">{guarded_player.first_name}</a>'
                                await bot.send_message(
                                    doctor.user_id,
                                    f"Сегодня вылечили {guarded_link}! Его гости: <b>💃 Любовница</b>!",
                                    parse_mode="HTML"
                                )
                            except Exception as e:
                                logging.error(f"Не удалось отправить сообщение доктору {doctor.first_name}: {e}")
            else:
                if guarded_player and guarded_player.user_id in game.night_visits:
                    has_important_visitors = any(visitor in [PlayerRole.VAMPIRE, PlayerRole.LOVER] for visitor in game.night_visits[guarded_player.user_id])
                    if not has_important_visitors:
                        try:
                            await bot.send_message(
                                doctor.user_id,
                                f"Помощь врача не понадобилась...",
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logging.error(f"Не удалось отправить сообщение доктору {doctor.first_name}: {e}")

async def start_day_phase(game: Game):
    game.current_phase = "day"
    game.mafia_chat_active = False

    for player in game.players:
        player.lover_blocked = False

    await save_games(active_games)

    game.day_timer = asyncio.create_task(day_timer(game))

async def day_timer(game: Game):
    try:
        await asyncio.sleep(DAY_DISCUSSION_DURATION)
        await start_voting_phase(game)
    except Exception as e:
        logging.error(f"Ошибка в таймере дня: {e}")

async def start_voting_phase(game: Game):
    game.current_phase = "voting"
    await save_games(active_games)

    alive_players = [p for p in game.players if p.is_alive]

    if len(alive_players) <= 1:
        await end_game(game)
        return

    try:
        voting_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎮 Перейти в бота",
                        url=f"https://t.me/{(await bot.get_me()).username}"
                    )
                ]
            ]
        )
    except Exception as e:
        logging.error(f"Не удалось создать клавиатуру: {e}")
        voting_keyboard = None

    await bot.send_message(
        game.chat_id,
        f"Пришло время определить и наказать виновных.\n"
        f"Голосование продлится {VOTING_DURATION} секунд.",
        reply_markup=voting_keyboard,
        parse_mode="HTML"
    )

    for player in alive_players:
        await send_voting_menu(player, game)

    game.voting_timer = asyncio.create_task(voting_timer(game))

async def send_voting_menu(player: Player, game: Game):
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id]

    if not targets:
        return

    if player.vampire_bitten:
        vampire = next((p for p in game.players if p.user_id == player.vampire_bitten and p.role == PlayerRole.VAMPIRE and p.is_alive), None)
        if vampire and vampire.vampire_can_control:
            logging.info(f"Игрок {player.first_name} укушен вампиром {vampire.first_name}, блокируем голосование")
            try:
                try:
                    invite_link = await get_group_invite_link(game)
                    
                    group_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🎮 Перейти в группу",
                                    url=invite_link
                                )
                            ]
                        ]
                    )
                except Exception as e:
                    logging.error(f"Не удалось создать клавиатуру: {e}")
                    group_keyboard = None

                await bot.send_message(
                    player.user_id,
                    "🧛 <b>Вы укушены вампиром!</b>\n\n"
                    "Вампир будет управлять вашим голосом на этом голосовании.\n"
                    "Вы не можете голосовать самостоятельно.",
                    reply_markup=group_keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение укушенному игроку {player.first_name}: {e}")
            return

    if player.role == PlayerRole.VAMPIRE and player.vampire_bitten:
        bitten_player = next((p for p in game.players if p.user_id == player.vampire_bitten and p.is_alive), None)
        logging.info(f"Вампир {player.first_name} пытается голосовать, укушенный: {bitten_player.first_name if bitten_player else 'не найден'}, can_control: {player.vampire_can_control}")
        if bitten_player and player.vampire_can_control:
            try:
                invite_link = await get_group_invite_link(game)
                
                group_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🎮 Перейти в группу",
                                url=invite_link
                            )
                        ]
                    ]
                )
            except Exception as e:
                logging.error(f"Не удалось создать клавиатуру: {e}")
                group_keyboard = None

            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=f"🧛 Проголосовать от имени {bitten_player.first_name}",
                    callback_data=f"vampire_vote_bitten_{game.chat_id}"
                )],
                [InlineKeyboardButton(
                    text=f"🧛 Проголосовать от своего имени",
                    callback_data=f"vampire_vote_self_{game.chat_id}"
                )]
            ]
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            try:
                await bot.send_message(
                    player.user_id,
                    "🧛 <b>Вампир, голосование!</b>\n\n"
                    "Вы можете проголосовать:\n"
                    f"• От имени укушенного игрока ({bitten_player.first_name})\n"
                    "• От своего имени\n\n"
                    "Выберите вариант:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить меню голосования вампиру {player.first_name}: {e}")
            return

    keyboard_buttons = []
    for target in targets:
        button_text = f"{target.first_name}"
        if is_mafia_ally(player, target):
            ally_emoji = get_role_emoji(target.role)
            button_text = f"{ally_emoji} {button_text}"
        
        keyboard_buttons.append([InlineKeyboardButton(
            text=button_text, 
            callback_data=f"vote_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        await bot.send_message(
            player.user_id,
            "<b>Голосование!</b>\n\n"
            "Выберите игрока, против которого хотите проголосовать:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить меню голосования игроку {player.first_name}: {e}")

def is_mafia_ally(player: Player, target: Player) -> bool:
    mafia_roles = [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.ADVOCATE, PlayerRole.VAMPIRE]
    
    if player.role in mafia_roles and target.role in mafia_roles:
        return True
    return False

@router.callback_query(F.data.startswith("vote_"))
async def process_vote_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        voter_id = callback.from_user.id

        voter = next((p for p in game.players if p.user_id == voter_id), None)
        target_player = next((p for p in game.players if p.user_id == target_user_id), None)

        if voter and voter.lover_blocked:
            await safe_callback_answer(callback, "❌ Вы заблокированы любовницей и не можете голосовать!")
            return

        if voter and voter.vampire_bitten:
            vampire = next((p for p in game.players if p.user_id == voter.vampire_bitten and p.role == PlayerRole.VAMPIRE and p.is_alive), None)
            if vampire and vampire.vampire_can_control:
                await safe_callback_answer(callback, "❌ Вы укушены вампиром! Вампир управляет вашим голосом, вы не можете голосовать самостоятельно.")
                return

        if not voter or not target_player or not target_player.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        game.votes[voter_id] = target_user_id
        await save_games(active_games)

        voter_link = f'<a href="tg://user?id={voter.user_id}">{voter.first_name}</a>'
        target_link = f'<a href="tg://user?id={target_player.user_id}">{target_player.first_name}</a>'
        await bot.send_message(
            game.chat_id,
            f"<b>{voter_link}</b> проголосовал против <b>{target_link}</b>",
            parse_mode="HTML"
        )

        await safe_callback_answer(callback, f"✅ Вы проголосовали против {target_player.first_name}")

        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        except:
            pass

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        await bot.send_message(
            callback.message.chat.id,
            f"✅ Вы проголосовали против {target_player.first_name}",
            reply_markup=group_keyboard
        )

    except Exception as e:
        logging.error(f"Ошибка в обработке голоса: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("vampire_vote_"))
async def process_vampire_vote_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")

        if len(data_parts) >= 5:
            try:
                target_user_id = int(data_parts[3])
                chat_id = int(data_parts[4])
            except (ValueError, IndexError):
                await safe_callback_answer(callback, "❌ Ошибка в данных!")
                return

            if chat_id not in active_games:
                await safe_callback_answer(callback, "❌ Игра не найдена!")
                return

            game = active_games[chat_id]
            vampire_id = callback.from_user.id
            vampire = next((p for p in game.players if p.user_id == vampire_id), None)
            target_player = next((p for p in game.players if p.user_id == target_user_id), None)

            if not vampire or vampire.role != PlayerRole.VAMPIRE or not target_player or not target_player.is_alive:
                await safe_callback_answer(callback, "❌ Игрок не найден!")
                return

            vote_type = data_parts[2]

            bitten_player = next((p for p in game.players if p.user_id == vampire.vampire_bitten and p.is_alive), None)

            if vote_type == "bitten" and bitten_player:
                voter_id = bitten_player.user_id
                voter_name = bitten_player.first_name
            else:
                voter_id = vampire.user_id
                voter_name = vampire.first_name

            game.votes[voter_id] = target_user_id
            await save_games(active_games)

            voter_link = f'<a href="tg://user?id={voter_id}">{voter_name}</a>'
            target_link = f'<a href="tg://user?id={target_player.user_id}">{target_player.first_name}</a>'
            await bot.send_message(
                game.chat_id,
                f"<b>{voter_link}</b> проголосовал против <b>{target_link}</b>",
                parse_mode="HTML"
            )

            await safe_callback_answer(callback, f"✅ Вы проголосовали против {target_player.first_name}")

            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
            except:
                pass

            if vote_type == "bitten" and bitten_player:
                confirm_text = f"✅ Вы проголосовали от имени {bitten_player.first_name} против {target_player.first_name}"
            else:
                confirm_text = f"✅ Вы проголосовали от своего имени против {target_player.first_name}"

            try:
                invite_link = await get_group_invite_link(game)
                
                group_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🎮 Перейти в группу",
                                url=invite_link
                            )
                        ]
                    ]
                )
            except Exception as e:
                logging.error(f"Не удалось создать клавиатуру: {e}")
                group_keyboard = None

            await bot.send_message(callback.message.chat.id, confirm_text, reply_markup=group_keyboard)

            if vote_type == "bitten" and vampire.user_id not in game.votes:
                targets_self = [p for p in game.players if p.is_alive and p.user_id != vampire.user_id]
                keyboard_buttons = []
                for target in targets_self:
                    button_text = f"{target.first_name}"
                    if is_mafia_ally(vampire, target):
                        ally_emoji = get_role_emoji(target.role)
                        button_text = f"{ally_emoji} {button_text}"
                    
                    keyboard_buttons.append([InlineKeyboardButton(
                        text=button_text,
                        callback_data=f"vampire_vote_self_{target.user_id}_{chat_id}"
                    )])
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
                await bot.send_message(
                    vampire.user_id,
                    "🧛 Теперь вы можете проголосовать от своего имени:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            elif vote_type == "self" and bitten_player and bitten_player.user_id not in game.votes:
                targets_bitten = [p for p in game.players if p.is_alive and p.user_id != vampire.user_id and p.user_id != bitten_player.user_id]
                keyboard_buttons = []
                for target in targets_bitten:
                    button_text = f"{target.first_name}"
                    if is_mafia_ally(vampire, target):
                        ally_emoji = get_role_emoji(target.role)
                        button_text = f"{ally_emoji} {button_text}"
                    
                    keyboard_buttons.append([InlineKeyboardButton(
                        text=button_text,
                        callback_data=f"vampire_vote_bitten_{target.user_id}_{chat_id}"
                    )])
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
                await bot.send_message(
                    vampire.user_id,
                    f"🧛 Теперь вы можете проголосовать от имени {bitten_player.first_name}:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            return

        if len(data_parts) != 4:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        vote_type = data_parts[2]
        try:
            chat_id = int(data_parts[3])
        except (ValueError, IndexError):
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        vampire_id = callback.from_user.id
        vampire = next((p for p in game.players if p.user_id == vampire_id), None)

        if not vampire or vampire.role != PlayerRole.VAMPIRE:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        bitten_player = next((p for p in game.players if p.user_id == vampire.vampire_bitten and p.is_alive), None)
        if not bitten_player and vote_type == "bitten":
            await safe_callback_answer(callback, "❌ Укушенный игрок не найден!")
            return

        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        except:
            pass

        targets = [p for p in game.players if p.is_alive and p.user_id != vampire.user_id]
        if vote_type == "bitten" and bitten_player:
            targets = [p for p in targets if p.user_id != bitten_player.user_id]

        if not targets:
            await callback.message.answer("❌ Нет доступных целей для голосования!")
            await safe_callback_answer(callback, "❌ Нет доступных целей!")
            return

        keyboard_buttons = []
        for target in targets:
            button_text = f"{target.first_name}"
            if is_mafia_ally(vampire, target):
                ally_emoji = get_role_emoji(target.role)
                button_text = f"{ally_emoji} {button_text}"
            
            keyboard_buttons.append([InlineKeyboardButton(
                text=button_text,
                callback_data=f"vampire_vote_{vote_type}_{target.user_id}_{chat_id}"
            )])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        if vote_type == "bitten" and bitten_player:
            message_text = f"🧛 <b>Голосование от имени {bitten_player.first_name}</b>\n\nВыберите игрока, против которого хотите проголосовать:"
        else:
            message_text = "🧛 <b>Голосование от своего имени</b>\n\nВыберите игрока, против которого хотите проголосовать:"

        await callback.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await safe_callback_answer(callback, "✅ Выберите цель для голосования")

    except Exception as e:
        logging.error(f"Ошибка в обработке голосования вампира: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

async def voting_timer(game: Game):
    try:
        await asyncio.sleep(VOTING_DURATION)
        await process_voting_results(game)
    except Exception as e:
        logging.error(f"Ошибка в таймере голосования: {e}")

async def process_voting_results(game: Game):
    vote_count = {}
    for target_id in game.votes.values():
        vote_count[target_id] = vote_count.get(target_id, 0) + 1

    if not vote_count:
        await bot.send_message(
            game.chat_id,
            "Голосование окончено. Мнения жителей разошлись... Разошлись и сами жители, так никого и не повесив...",
            parse_mode="HTML"
        )
        if check_game_end_condition(game):
            await end_game(game)
            return
        await asyncio.sleep(3)
        await start_night_phase(game)
        return

    max_votes = max(vote_count.values())
    candidates = [player_id for player_id, votes in vote_count.items() if votes == max_votes]

    if len(candidates) > 1:
        await bot.send_message(
            game.chat_id,
            "Мнения жителей разошлись... Разошлись и сами жители, так никого и не повесив..",
            parse_mode="HTML"
        )
        if check_game_end_condition(game):
            await end_game(game)
            return
        await asyncio.sleep(3)
        await start_night_phase(game)
        return

    executed_id = candidates[0]
    executed_player = next(p for p in game.players if p.user_id == executed_id)
    game.candidate_for_execution = executed_id

    execute_count = sum(1 for v in game.votes.values() if v == executed_id)
    pardon_count = len(game.votes) - execute_count

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"👍 ({execute_count})", callback_data=f"final_execute_{executed_id}_{game.chat_id}"),
            InlineKeyboardButton(text=f"👎 ({pardon_count})", callback_data=f"final_pardon_{executed_id}_{game.chat_id}")
        ]
    ])

    message = await bot.send_message(
        game.chat_id,
        f"Уверены что хотите линчевать {executed_player.first_name} ?",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    game.final_vote_message_id = message.message_id
    game.final_votes = {"execute": set(), "pardon": set()}
    await save_games(active_games)

    game.final_voting_timer = asyncio.create_task(final_voting_timer(game))

async def final_voting_timer(game: Game):
    try:
        await asyncio.sleep(25)
        await process_final_voting_results(game)
    except Exception as e:
        logging.error(f"Ошибка в таймере финального голосования: {e}")

@router.callback_query(F.data.startswith("final_"))
async def process_final_vote_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 4:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        action = data_parts[1]
        target_user_id = int(data_parts[2])
        chat_id = int(data_parts[3])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        voter_id = callback.from_user.id

        voter = next((p for p in game.players if p.user_id == voter_id), None)
        if not voter or not voter.is_alive:
            await safe_callback_answer(callback, "❌ Вы не можете голосовать!")
            return

        if voter.vampire_bitten:
            vampire = next((p for p in game.players if p.user_id == voter.vampire_bitten and p.role == PlayerRole.VAMPIRE and p.is_alive), None)
            if vampire and vampire.vampire_can_control:
                await safe_callback_answer(callback, "❌ Вы укушены вампиром! Вампир управляет вашим голосом, вы не можете голосовать самостоятельно.")
                return

        if voter.user_id == game.candidate_for_execution:
            await safe_callback_answer(callback, "❌ Вы не можете голосовать за свою казнь или помилование!")
            return

        if voter_id in game.final_votes["execute"]:
            game.final_votes["execute"].remove(voter_id)
        if voter_id in game.final_votes["pardon"]:
            game.final_votes["pardon"].remove(voter_id)

        game.final_votes[action].add(voter_id)
        await save_games(active_games)

        execute_count = len(game.final_votes["execute"])
        pardon_count = len(game.final_votes["pardon"])

        target_player = next(p for p in game.players if p.user_id == target_user_id)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"👍 ({execute_count})", callback_data=f"final_execute_{target_user_id}_{chat_id}"),
                InlineKeyboardButton(text=f"👎 ({pardon_count})", callback_data=f"final_pardon_{target_user_id}_{chat_id}")
            ]
        ])

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=game.final_vote_message_id,
                text=f"Уверены что хотите линчевать {target_player.first_name} ?",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось обновить сообщение голосования: {e}")

        await safe_callback_answer(callback, f"✅ Ваш голос учтен!")

    except Exception as e:
        logging.error(f"Ошибка в обработке финального голоса: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

async def process_final_voting_results(game: Game):
    execute_count = len(game.final_votes["execute"])
    pardon_count = len(game.final_votes["pardon"])

    if game.candidate_for_execution:
        executed_player = next((p for p in game.players if p.user_id == game.candidate_for_execution), None)
    else:
        executed_player = None

    if executed_player and execute_count > pardon_count:
        advocate = next((p for p in game.players if p.role == PlayerRole.ADVOCATE and p.is_alive), None)
        if advocate and advocate.advocate_alibi_current == executed_player.user_id:
            player_link = f'<a href="tg://user?id={executed_player.user_id}">{executed_player.first_name}</a>'
            await bot.send_message(
                game.chat_id,
                f"⚖️ {player_link} имеет алиби от адвоката и не может быть казнен!",
                parse_mode="HTML"
            )
            advocate.advocate_alibi_current = None
            await save_games(active_games)
            await bot.send_message(
                game.chat_id,
                f"✨ {player_link} был помилован благодаря алиби адвоката!",
                parse_mode="HTML"
            )
        else:
            executed_player.is_alive = False

            try:
                await bot.send_message(
                    executed_player.user_id,
                    "💀 Вы были казнены...\n\n"
                    "📜 У вас есть последний шанс оставить предсмертную записку.\n\n"
                    "Напишите ваши последние слова (бот отправит их в группу):"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение казненному игроку: {e}")

            player_link = f'<a href="tg://user?id={executed_player.user_id}">{executed_player.first_name}</a>'
            role_emoji = get_role_emoji(executed_player.role)
            role_name_bold = f"<b>{get_role_name(executed_player.role)}</b>"
            
            await bot.send_message(
                game.chat_id,
                f"{player_link} линчевали на дневном собрании!\n"
                f"Он был {role_emoji}{role_name_bold}..",
                parse_mode="HTML"
            )
    else:
        if executed_player:
            player_link = f'<a href="tg://user?id={executed_player.user_id}">{executed_player.first_name}</a>'
            await bot.send_message(
                game.chat_id,
                f"✨ <b>{player_link}</b> был помилован и возвращается к жизни!",
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                game.chat_id,
                "✨ <b>Никто не был казнен!</b> Город решил дать шанс всем подозреваемым.",
                parse_mode="HTML"
            )
            if check_game_end_condition(game):
                await end_game(game)
                return

    if check_game_end_condition(game):
        await end_game(game)
    else:
        await asyncio.sleep(3)
        await start_night_phase(game)

async def start_night_phase(game: Game):
    game.day_number += 1
    game.night_actions = {}
    game.votes = {}
    game.night_kills = []
    game.candidate_for_execution = None
    game.current_phase = "night"
    game.night_visits = {}
    game.sheriff_check_target = None
    game.lover_blocked_players = []
    game.vampire_last_bite_target = game.vampire_bite_target
    game.vampire_bite_target = None
    game.bum_visit_target = None
    game.mafia_chat_active = False

    for player in game.players:
        if player.role == PlayerRole.ADVOCATE:
            player.advocate_alibi_current = None
        player.lover_blocked = False

    await save_games(active_games)

    try:
        night_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎮 Перейти в бота",
                        url=f"https://t.me/{(await bot.get_me()).username}"
                    )
                ]
            ]
        )
    except Exception as e:
        logging.error(f"Не удалось создать клавиатуру: {e}")
        night_keyboard = None

    try:
        await bot.send_photo(
            game.chat_id,
            photo=NIGHT_PHOTO,
            caption="🌙 Наступает ночь ❄️\n"
                   "На улицы города выходят лишь самые отважные и бесстрашные.\n"
                   "Утром попробуем сосчитать их головы...",
            reply_markup=night_keyboard
        )
    except Exception as e:
        logging.error(f"Не удалось отправить ночное фото: {e}")
        await bot.send_message(
            game.chat_id,
            "🌙 Наступает ночь ❄️\n"
            "На улицы города выходят лишь самые отважные и бесстрашные.\n"
            "Утром попробуем сосчитать их головы...",
            reply_markup=night_keyboard
        )

    await asyncio.sleep(2)

    await send_players_list(game)

    await asyncio.sleep(2)

    await send_night_actions_to_players(game)

    game.night_timer = asyncio.create_task(night_timer(game))

def check_game_end_condition(game: Game) -> bool:
    alive_players = [p for p in game.players if p.is_alive]

    if len(alive_players) < 2:
        return True

    mafia_roles = [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.ADVOCATE, PlayerRole.VAMPIRE]
    good_roles = [PlayerRole.SHERIFF, PlayerRole.DOCTOR, PlayerRole.CIVILIAN, PlayerRole.MANIAC, PlayerRole.STUKACH, PlayerRole.BUM, PlayerRole.LOVER]

    mafia_count = len([p for p in alive_players if p.role in mafia_roles])
    good_count = len([p for p in alive_players if p.role in good_roles])

    if mafia_count == 0:
        return True

    if mafia_count >= good_count:
        return True

    return False

async def end_game(game: Game):
    game.is_active = False

    alive_players = [p for p in game.players if p.is_alive]

    mafia_roles = [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.ADVOCATE, PlayerRole.VAMPIRE]
    good_roles = [PlayerRole.SHERIFF, PlayerRole.DOCTOR, PlayerRole.CIVILIAN, PlayerRole.MANIAC, PlayerRole.STUKACH, PlayerRole.BUM, PlayerRole.LOVER]

    mafia_count = len([p for p in alive_players if p.role in mafia_roles])
    good_count = len([p for p in alive_players if p.role in good_roles])

    winners = []
    others = []

    if mafia_count == 0:
        for p in alive_players:
            if p.role in good_roles:
                winners.append(p)
        for p in game.players:
            if p not in winners:
                others.append(p)
    elif mafia_count >= good_count:
        for p in alive_players:
            if p.role in mafia_roles:
                winners.append(p)
        for p in game.players:
            if p not in winners:
                others.append(p)
    else:
        if mafia_count > 0:
            for p in alive_players:
                if p.role in mafia_roles:
                    winners.append(p)
            for p in game.players:
                if p not in winners:
                    others.append(p)
        else:
            for p in alive_players:
                if p.role in good_roles:
                    winners.append(p)
            for p in game.players:
                if p not in winners:
                    others.append(p)

    message_parts = ["🎮 <b>Игра окончена!</b>\n"]

    if winners:
        message_parts.append("<b>Победители:</b>")
        for i, p in enumerate(winners, 1):
            role_emoji = get_role_emoji(p.role)
            role_name = get_role_name(p.role)
            player_link = f'<a href="tg://user?id={p.user_id}">{p.first_name}</a>'
            message_parts.append(f"    {i}. {player_link} - {role_emoji} {role_name}")

    if others:
        message_parts.append("\n<b>Другие пользователи:</b>")
        for i, p in enumerate(others, len(winners) + 1):
            role_emoji = get_role_emoji(p.role)
            role_name = get_role_name(p.role)
            player_link = f'<a href="tg://user?id={p.user_id}">{p.first_name}</a>'
            message_parts.append(f"    {i}. {player_link} - {role_emoji} {role_name}")

    final_message = "\n".join(message_parts)

    await bot.send_message(
        game.chat_id,
        final_message,
        parse_mode="HTML"
    )

    if game.chat_id in active_games:
        del active_games[game.chat_id]
        await save_games(active_games)

async def send_classic_night_actions(player: Player, game: Game) -> bool:
    try:
        if player.role == PlayerRole.MAFIA:
            return await send_kill_action_menu(player, game, "🔫 Убить")
        elif player.role == PlayerRole.DON:
            return await send_kill_action_menu(player, game, "🔫 Убить")
        elif player.role == PlayerRole.ADVOCATE:
            return await send_advocate_action_menu(player, game)
        elif player.role == PlayerRole.SHERIFF:
            return await send_sheriff_action_choice_menu(player, game)
        elif player.role == PlayerRole.DOCTOR:
            return await send_doctor_action_menu(player, game)
        elif player.role == PlayerRole.MANIAC:
            return await send_kill_action_menu(player, game, "🔫 Убить")
        elif player.role == PlayerRole.STUKACH:
            return await send_stukach_action_menu(player, game)
        elif player.role == PlayerRole.LOVER:
            return await send_lover_action_menu(player, game)
        elif player.role == PlayerRole.VAMPIRE:
            return await send_vampire_action_menu(player, game)
        elif player.role == PlayerRole.BUM:
            return await send_bum_action_menu(player, game)
        return False
    except Exception as e:
        logging.error(f"Не удалось отправить ночное действие игроку {player.first_name}: {e}")
        return False

async def send_kill_action_menu(player: Player, game: Game, action_text: str) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id and not is_mafia_ally(player, p)]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"🎯 {target.first_name}", 
            callback_data=f"kill_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    messages = [
        f"🔫 Кто станет жертвой мафии этой ночью?",
        f"🌑 Тени сходятся вокруг кого-то. Кого выберете вы?",
        f"🎭 Чья жизнь оборвется этой ночью?"
    ]

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            f"{random.choice(messages)}\n\n{action_text}:",
            reply_markup=keyboard
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню убийства игроку {player.first_name}: {e}")
        return False

async def send_sheriff_action_choice_menu(player: Player, game: Game) -> bool:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Проверить игрока",
                callback_data=f"sheriff_check_{game.chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Убить игрока",
                callback_data=f"sheriff_kill_{game.chat_id}"
            )
        ]
    ])

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            "🕵🏼 <b>Комиссар Каттани</b>, что вы хотите сделать этой ночью?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню выбора действия шерифу {player.first_name}: {e}")
        return False

async def send_check_action_menu(player: Player, game: Game, action_text: str) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"{target.first_name}", 
            callback_data=f"check_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    messages = [
        f"🕵🏼 <b>Комиссар Каттани</b>, кого вы проверите этой ночью?",
        f"🔍 Чьи намерения вы хотите раскрыть?",
        f"🕵️ Кто скрывает темную душу за маской невинности?"
    ]

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            f"{random.choice(messages)}\n\n{action_text}:",
            reply_markup=keyboard
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню проверки игроку {player.first_name}: {e}")
        return False

async def send_doctor_action_menu(player: Player, game: Game) -> bool:
    targets = [p for p in game.players if p.is_alive]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        if target.user_id == player.user_id and player.doctor_self_healed:
            continue
            
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"{target.first_name}", 
            callback_data=f"guard_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            "👨🏼‍⚕️️ <b>Доктор</b>, кого лечить будете сегодня?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню лечения игроку {player.first_name}: {e}")
        return False

async def send_advocate_action_menu(player: Player, game: Game) -> bool:
    all_players = [p for p in game.players if p.is_alive]

    if not all_players:
        return False

    available_for_alibi = []
    current_night = game.day_number

    for target in all_players:
        if target.user_id == player.user_id:
            if not player.advocate_alibi_given_to_self:
                available_for_alibi.append(target)
        else:
            last_given_night = player.advocate_alibi_history.get(target.user_id, -10)
            if last_given_night < current_night - 1:
                available_for_alibi.append(target)

    if not available_for_alibi:
        return await send_advocate_kill_menu(player, game)

    keyboard_buttons = []
    for target in available_for_alibi:
        button_text = f"⚖️ {target.first_name}"
        if is_mafia_ally(player, target):
            ally_emoji = get_role_emoji(target.role)
            button_text = f"⚖️ {ally_emoji} {target.first_name}"
        
        keyboard_buttons.append([InlineKeyboardButton(
            text=button_text, 
            callback_data=f"alibi_{target.user_id}_{game.chat_id}"
        )])

    keyboard_buttons.append([InlineKeyboardButton(
        text="⏭️ Пропустить",
        callback_data=f"alibi_skip_{game.chat_id}"
    )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    messages = [
        f"⚖️ Адвокат, кому вы хотите дать алиби этой ночью?",
        f"🛡️ Чью защиту вы обеспечите?",
        f"⚖️ Кого вы защитите от дневного голосования?"
    ]

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            f"{random.choice(messages)}\n\n⚖️ Дать алиби:",
            reply_markup=keyboard
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню адвоката игроку {player.first_name}: {e}")
        return False

async def send_stukach_action_menu(player: Player, game: Game) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"🤓 {target.first_name}",
            callback_data=f"stukach_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            "🤓 <b>Стукач</b>, к какому игроку вы хотите пойти этой ночью?\n\n"
            "Если вы выберете того же игрока, что и комиссар, его роль будет публично раскрыта!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню стукача игроку {player.first_name}: {e}")
        return False

async def send_lover_action_menu(player: Player, game: Game) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"💃 {target.first_name}",
            callback_data=f"lover_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            "💃 <b>Любовница</b>, кого вы хотите навестить этой ночью?\n\n"
            "Тот, кого вы навестите, не сможет сделать ночную активность и не сможет голосовать.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню любовницы игроку {player.first_name}: {e}")
        return False

async def send_vampire_action_menu(player: Player, game: Game) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id]

    targets = [p for p in targets if not is_mafia_ally(player, p)]
    if game.vampire_last_bite_target:
        targets = [p for p in targets if p.user_id != game.vampire_last_bite_target]

    if not targets:
        return await send_vampire_kill_menu(player, game)

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"🧛 {target.first_name}",
            callback_data=f"vampire_bite_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            "🧛 <b>Вампир</b>, кого вы хотите укусить этой ночью?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню вампира игроку {player.first_name}: {e}")
        return False

async def send_vampire_kill_menu(player: Player, game: Game) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id and not is_mafia_ally(player, p)]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f" {target.first_name}",
            callback_data=f"kill_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            "🧛 <b>Вампир</b>, кого вы хотите убить этой ночью?\n\n"
            "Убить:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню убийства вампира игроку {player.first_name}: {e}")
        return False

async def send_bum_action_menu(player: Player, game: Game) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"{target.first_name}",
            callback_data=f"bum_{target.user_id}_{game.chat_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            "🧙🏻 <b>Бомж</b>, к кому вы хотите зайти за бутылкой этой ночью?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню бомжа игроку {player.first_name}: {e}")
        return False

async def send_advocate_kill_menu(player: Player, game: Game) -> bool:
    targets = [p for p in game.players if p.is_alive and p.user_id != player.user_id and not is_mafia_ally(player, p)]

    if not targets:
        return False

    keyboard_buttons = []
    for target in targets:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"🔫 {target.first_name}", 
            callback_data=f"kill_{target.user_id}_{game.chat_id}"
        )])

    keyboard_buttons.append([InlineKeyboardButton(
        text="⏭️ Пропустить",
        callback_data=f"kill_skip_{game.chat_id}"
    )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    messages = [
        f"🔫 Адвокат, кого вы хотите убить этой ночью?",
        f"⚖️ Чья судьба будет решена?",
        f"🔪 Кто станет жертвой?"
    ]

    try:
        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        message = await bot.send_message(
            player.user_id,
            f"{random.choice(messages)}\n\n🔫 Убить:",
            reply_markup=keyboard
        )
        player.action_message_id = message.message_id
        await save_games(active_games)
        return True
    except Exception as e:
        logging.error(f"Не удалось отправить меню убийства адвоката игроку {player.first_name}: {e}")
        return False

@router.callback_query(F.data.startswith("kill_"))
async def process_kill_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        if data_parts[1] == "skip":
            chat_id = int(data_parts[2])
            if chat_id not in active_games:
                await safe_callback_answer(callback, "❌ Игра не найдена!")
                return

            game = active_games[chat_id]
            killer_id = callback.from_user.id
            killer = next((p for p in game.players if p.user_id == killer_id), None)

            if not killer:
                await safe_callback_answer(callback, "❌ Игрок не найден!")
                return

            if killer.action_message_id:
                try:
                    await bot.delete_message(chat_id=callback.message.chat.id, message_id=killer.action_message_id)
                except Exception as e:
                    logging.error(f"Не удалось удалить сообщение: {e}")

            game.night_actions[f"{killer.user_id}_kill_skip"] = "skip"
            await save_games(active_games)

            await callback.message.answer("✅ Вы пропустили убийство")
            await safe_callback_answer(callback, "✅ Действие записано!")

            await check_all_night_actions_complete(game)
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        killer_id = callback.from_user.id

        killer = next((p for p in game.players if p.user_id == killer_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not killer or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if is_mafia_ally(killer, target):
            await safe_callback_answer(callback, "❌ Вы не можете атаковать союзника мафии!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза! Время для действий истекло.")
            return

        if killer.role == PlayerRole.MAFIA:
            action_type = "убийство"
        elif killer.role == PlayerRole.DON:
            action_type = "убийство_дон"
        elif killer.role == PlayerRole.ADVOCATE:
            action_type = "убийство_адвокат"
        elif killer.role == PlayerRole.MANIAC:
            action_type = "убийство_маньяк"
        elif killer.role == PlayerRole.SHERIFF:
            action_type = "убийство_шериф"
        elif killer.role == PlayerRole.VAMPIRE:
            action_type = "убийство_вампир"
        else:
            action_type = "убийство"

        game.night_actions[f"{killer.user_id}_{action_type}"] = target.first_name

        if target.user_id not in game.night_visits:
            game.night_visits[target.user_id] = []
        if killer.role not in game.night_visits[target.user_id]:
            game.night_visits[target.user_id].append(killer.role)

        await save_games(active_games)

        if killer.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=killer.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        await callback.message.answer(
            f"Ваш выбор: <b>{target.first_name}</b>",
            reply_markup=group_keyboard,
            parse_mode="HTML"
        )
        await safe_callback_answer(callback, "✅ Действие записано!")

        if killer.role == PlayerRole.ADVOCATE:
            don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
            if don_alive:
                messages = [
                    f"⚖️ Адвокат дает кому-то алиби...",
                    f"🛡️ Кто-то получил защиту адвоката..."
                ]
            else:
                messages = [
                    f"🔫 Адвокат выбрал жертву...",
                    f"⚖️ Адвокат стреляет..."
                ]
        elif killer.role == PlayerRole.DON:
            await bot.send_message(
                game.chat_id,
                "🤵🏻 <b>Дон</b> выбрал жертву...",
                parse_mode="HTML"
            )
            await check_all_night_actions_complete(game)
            return
        elif killer.role == PlayerRole.MANIAC:
            messages = [
                f"🔪 Маньяк выбрал жертву...",
                f"🌑 Маньяк не дремлет..."
            ]
        elif killer.role == PlayerRole.SHERIFF:
            await bot.send_message(
                game.chat_id,
                "🕵🏼 <b>Комиссар Каттани</b> уже зарядил свой пистолет...",
                parse_mode="HTML"
            )
            await check_all_night_actions_complete(game)
            return
        elif killer.role == PlayerRole.VAMPIRE:
            await bot.send_message(
                game.chat_id,
                "🧛 <b>Вампир</b> выбрал жертву...",
                parse_mode="HTML"
            )
            await check_all_night_actions_complete(game)
            return
        else:
            messages = [
                f"🔪 Тени сходятся вокруг одного из жителей... Мафия не дремлет!",
                f"🌑 В темноте слышится шепот... Кто-то обречен...",
                f"🎭 Мафия выбрала свою жертву... Смерть бродит по городу..."
            ]

        await bot.send_message(game.chat_id, random.choice(messages))

        await check_all_night_actions_complete(game)

    except Exception as e:
        logging.error(f"Ошибка в обработке убийства: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("alibi_"))
async def process_alibi_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        if data_parts[1] == "skip":
            chat_id = int(data_parts[2])
            if chat_id not in active_games:
                await safe_callback_answer(callback, "❌ Игра не найдена!")
                return

            game = active_games[chat_id]
            advocate_id = callback.from_user.id
            advocate = next((p for p in game.players if p.user_id == advocate_id), None)

            if not advocate or advocate.role != PlayerRole.ADVOCATE:
                await safe_callback_answer(callback, "❌ Игрок не найден!")
                return

            if advocate.action_message_id:
                try:
                    await bot.delete_message(chat_id=callback.message.chat.id, message_id=advocate.action_message_id)
                except Exception as e:
                    logging.error(f"Не удалось удалить сообщение: {e}")

            game.night_actions[f"{advocate.user_id}_alibi_skip"] = "skip"
            await save_games(active_games)

            await send_advocate_kill_menu(advocate, game)
            await safe_callback_answer(callback, "✅ Алиби пропущено")
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        advocate_id = callback.from_user.id

        advocate = next((p for p in game.players if p.user_id == advocate_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not advocate or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if advocate.role != PlayerRole.ADVOCATE:
            await safe_callback_answer(callback, "❌ У вас нет права выдавать алиби!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза! Время для действий истекло.")
            return

        current_night = game.day_number
        if target.user_id == advocate.user_id:
            if advocate.advocate_alibi_given_to_self:
                await safe_callback_answer(callback, "❌ Вы уже дали себе алиби один раз!")
                return
            advocate.advocate_alibi_given_to_self = True
        else:
            last_given_night = advocate.advocate_alibi_history.get(target.user_id, -10)
            if last_given_night >= current_night - 1:
                await safe_callback_answer(callback, "❌ Этому игроку нельзя дать алиби (нужно подождать 1 ночь)!")
                return

        advocate.advocate_alibi_current = target.user_id
        advocate.advocate_alibi_history[target.user_id] = current_night
        game.night_actions[f"{advocate.user_id}_алиби"] = target.first_name

        if target.user_id not in game.night_visits:
            game.night_visits[target.user_id] = []
        if advocate.role not in game.night_visits[target.user_id]:
            game.night_visits[target.user_id].append(advocate.role)

        await save_games(active_games)

        if advocate.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=advocate.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        target_name = "себе" if target.user_id == advocate.user_id else target.first_name
        await callback.message.answer(
            f"Ваш выбор: <b>{target_name}</b>",
            reply_markup=group_keyboard,
            parse_mode="HTML"
        )

        await send_advocate_kill_menu(advocate, game)
        await safe_callback_answer(callback, "✅ Алиби выдано!")

        don_alive = any(p for p in game.players if p.role == PlayerRole.DON and p.is_alive)
        if don_alive:
            messages = [
                f"⚖️ Адвокат дает кому-то алиби...",
                f"🛡️ Кто-то получил защиту адвоката..."
            ]
            await bot.send_message(game.chat_id, random.choice(messages))

    except Exception as e:
        logging.error(f"Ошибка в обработке алиби: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("sheriff_check_"))
async def process_sheriff_check_choice_callback(callback: CallbackQuery):
    try:
        chat_id = int(callback.data.split("_")[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        sheriff_id = callback.from_user.id
        sheriff = next((p for p in game.players if p.user_id == sheriff_id), None)

        if not sheriff or sheriff.role != PlayerRole.SHERIFF:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза! Время для действий истекло.")
            return

        if sheriff.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=sheriff.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        await send_check_action_menu(sheriff, game, "🔍 Проверить")
        await safe_callback_answer(callback, "✅ Выбрана проверка")

    except Exception as e:
        logging.error(f"Ошибка в обработке выбора проверки шерифа: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("sheriff_kill_"))
async def process_sheriff_kill_choice_callback(callback: CallbackQuery):
    try:
        chat_id = int(callback.data.split("_")[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        sheriff_id = callback.from_user.id
        sheriff = next((p for p in game.players if p.user_id == sheriff_id), None)

        if not sheriff or sheriff.role != PlayerRole.SHERIFF:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза! Время для действий истекло.")
            return

        if sheriff.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=sheriff.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        await send_kill_action_menu(sheriff, game, "🔫 Убить")
        await safe_callback_answer(callback, "✅ Выбрано убийство")

    except Exception as e:
        logging.error(f"Ошибка в обработке выбора убийства шерифа: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("check_"))
async def process_check_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        checker_id = callback.from_user.id

        checker = next((p for p in game.players if p.user_id == checker_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not checker or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза! Время для действий истекло.")
            return

        if checker.role == PlayerRole.SHERIFF:
            if target.role in [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.ADVOCATE]:
                result = "🔴 Этот игрок - Мафия!"
                role_info = "Мафия"
            else:
                result = "🟢 Этот игрок не Мафия"
                role_info = "Мирный житель"
            action_type = "проверка шерифа"

            game.night_actions[f"{checker.user_id}_{action_type}"] = target.first_name

            game.sheriff_check_target = target.user_id

            if target.user_id not in game.night_visits:
                game.night_visits[target.user_id] = []
            if checker.role not in game.night_visits[target.user_id]:
                game.night_visits[target.user_id].append(checker.role)

            await save_games(active_games)

            if checker.action_message_id:
                try:
                    await bot.delete_message(chat_id=callback.message.chat.id, message_id=checker.action_message_id)
                except Exception as e:
                    logging.error(f"Не удалось удалить сообщение: {e}")

            try:
                invite_link = await get_group_invite_link(game)
                
                group_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🎮 Перейти в группу",
                                url=invite_link
                            )
                        ]
                    ]
                )
            except Exception as e:
                logging.error(f"Не удалось создать клавиатуру: {e}")
                group_keyboard = None

            target_emoji = get_role_emoji(target.role)
            target_role_name = get_role_name(target.role)
            await callback.message.answer(
                f"Ваш выбор: <b>{target.first_name}</b>\n\n{target.first_name} - {target_emoji} {target_role_name}",
                reply_markup=group_keyboard,
                parse_mode="HTML"
            )
            await safe_callback_answer(callback, "✅ Проверка завершена!")

            await bot.send_message(
                game.chat_id,
                "🕵🏼 <b>Комиссар Каттани</b> ушёл искать злодеев...",
                parse_mode="HTML"
            )

            await check_all_night_actions_complete(game)
        else:
            await safe_callback_answer(callback, "❌ Неизвестная роль для проверки!")
            return

    except Exception as e:
        logging.error(f"Ошибка в обработке проверки: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("guard_"))
async def process_guard_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        doctor_id = callback.from_user.id

        doctor = next((p for p in game.players if p.user_id == doctor_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not doctor or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if doctor.role != PlayerRole.DOCTOR:
            await callback.answer("❌ У вас нет права охранять!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза! Время для действий истекло.")
            return

        if target.user_id == doctor.user_id:
            if doctor.doctor_self_healed:
                await safe_callback_answer(callback, "❌ Вы уже лечили себя один раз за игру!")
                return
            doctor.doctor_self_healed = True

        game.night_actions[f"{doctor.user_id}_охрана"] = target.first_name
        doctor.last_guarded_player = target.user_id

        if target.user_id not in game.night_visits:
            game.night_visits[target.user_id] = []
        if doctor.role not in game.night_visits[target.user_id]:
            game.night_visits[target.user_id].append(doctor.role)

        await save_games(active_games)

        if doctor.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=doctor.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        await callback.message.answer(
            f"Ваш выбор: <b>{target.first_name}</b>",
            reply_markup=group_keyboard,
            parse_mode="HTML"
        )
        await safe_callback_answer(callback, "✅ Охрана установлена!")

        await bot.send_message(
            game.chat_id,
            "👨🏼‍⚕️️<b>Доктор</b> вышел на ночную смену...",
            parse_mode="HTML"
        )

        await check_all_night_actions_complete(game)

    except Exception as e:
        logging.error(f"Ошибка в обработке охраны: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("lover_"))
async def process_lover_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        lover_id = callback.from_user.id
        lover = next((p for p in game.players if p.user_id == lover_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not lover or lover.role != PlayerRole.LOVER or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза!")
            return

        game.night_actions[f"{lover.user_id}_любовница"] = target.first_name
        game.lover_blocked_players.append(target.user_id)
        target.lover_blocked = True

        if target.user_id not in game.night_visits:
            game.night_visits[target.user_id] = []
        if lover.role not in game.night_visits[target.user_id]:
            game.night_visits[target.user_id].append(lover.role)

        await save_games(active_games)

        if lover.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=lover.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        await callback.message.answer(
            f"Ваш выбор: <b>{target.first_name}</b>",
            reply_markup=group_keyboard,
            parse_mode="HTML"
        )
        await safe_callback_answer(callback, "✅ Визит записан!")

        await bot.send_message(
            game.chat_id,
            f"💃 <b>Любовница</b> уже ждёт кого-то в гости...",
            parse_mode="HTML"
        )

        await check_all_night_actions_complete(game)

    except Exception as e:
        logging.error(f"Ошибка в обработке визита любовницы: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("vampire_bite_"))
async def process_vampire_bite_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 4:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        target_user_id = int(data_parts[2])
        chat_id = int(data_parts[3])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        vampire_id = callback.from_user.id
        vampire = next((p for p in game.players if p.user_id == vampire_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not vampire or vampire.role != PlayerRole.VAMPIRE or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза!")
            return

        if is_mafia_ally(vampire, target):
            await safe_callback_answer(callback, "❌ Вы не можете укусить союзника мафии!")
            return

        if target.role == PlayerRole.SHERIFF:
            await safe_callback_answer(callback, "❌ Укус не удался! Вы не можете укусить комиссара.")
            return

        game.night_actions[f"{vampire.user_id}_укус_вампир"] = target.first_name
        game.vampire_bite_target = target.user_id
        vampire.vampire_bitten = target.user_id

        vampire.vampire_can_control = True
        target.vampire_bitten = vampire.user_id
        logging.info(f"Вампир {vampire.first_name} укусил {target.first_name} и может управлять его голосом")

        if target.user_id not in game.night_visits:
            game.night_visits[target.user_id] = []
        if vampire.role not in game.night_visits[target.user_id]:
            game.night_visits[target.user_id].append(vampire.role)

        await save_games(active_games)

        if vampire.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=vampire.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        await callback.message.answer(
            f"Ваш выбор: <b>{target.first_name}</b>\n\n🧛 Вы сможете управлять его голосом на дневном голосовании.\n\nТеперь вы можете стрелять как мафия.",
            reply_markup=group_keyboard,
            parse_mode="HTML"
        )

        await safe_callback_answer(callback, "✅ Укус записан!")

        await send_vampire_kill_menu(vampire, game)

        await bot.send_message(
            game.chat_id,
            f"🧛 <b>Вампир</b> укусил кого-то...",
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Ошибка в обработке укуса вампира: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("bum_"))
async def process_bum_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        bum_id = callback.from_user.id
        bum = next((p for p in game.players if p.user_id == bum_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not bum or bum.role != PlayerRole.BUM or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза!")
            return

        game.night_actions[f"{bum.user_id}_бомж"] = target.first_name
        game.bum_visit_target = target.user_id

        if target.user_id not in game.night_visits:
            game.night_visits[target.user_id] = []
        if bum.role not in game.night_visits[target.user_id]:
            game.night_visits[target.user_id].append(bum.role)

        await save_games(active_games)

        if bum.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=bum.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        await callback.message.answer(
            f"Ваш выбор: <b>{target.first_name}</b>\n\n🧙🏻 Вы станете свидетелем убийства, если оно произойдет у этого игрока.",
            reply_markup=group_keyboard,
            parse_mode="HTML"
        )
        await safe_callback_answer(callback, "✅ Визит записан!")

        await bot.send_message(
            game.chat_id,
            f"🧙🏼 <b>Бомж</b> пошёл бухать...",
            parse_mode="HTML"
        )

        await check_all_night_actions_complete(game)

    except Exception as e:
        logging.error(f"Ошибка в обработке визита бомжа: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data.startswith("stukach_"))
async def process_stukach_callback(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        if len(data_parts) < 3:
            await safe_callback_answer(callback, "❌ Ошибка в данных!")
            return

        target_user_id = int(data_parts[1])
        chat_id = int(data_parts[2])

        if chat_id not in active_games:
            await safe_callback_answer(callback, "❌ Игра не найдена!")
            return

        game = active_games[chat_id]
        stukach_id = callback.from_user.id
        stukach = next((p for p in game.players if p.user_id == stukach_id), None)
        target = next((p for p in game.players if p.user_id == target_user_id), None)

        if not stukach or stukach.role != PlayerRole.STUKACH or not target or not target.is_alive:
            await safe_callback_answer(callback, "❌ Игрок не найден!")
            return

        if game.current_phase != "night":
            await safe_callback_answer(callback, "❌ Сейчас не ночная фаза!")
            return

        game.night_actions[f"{stukach.user_id}_проверка_стукач"] = target.first_name
        stukach.stukach_target = target.user_id

        if target.user_id not in game.night_visits:
            game.night_visits[target.user_id] = []
        if stukach.role not in game.night_visits[target.user_id]:
            game.night_visits[target.user_id].append(stukach.role)

        await save_games(active_games)

        if stukach.action_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=stukach.action_message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение: {e}")

        try:
            invite_link = await get_group_invite_link(game)
            
            group_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎮 Перейти в группу",
                            url=invite_link
                        )
                    ]
                ]
            )
        except Exception as e:
            logging.error(f"Не удалось создать клавиатуру: {e}")
            group_keyboard = None

        if game.sheriff_check_target == target.user_id:
            await callback.message.answer(
                f"Ваш выбор: <b>{target.first_name}</b>\n\n🤓 Вы выбрали того же игрока, что и комиссар! Его роль будет публично раскрыта утром.",
                reply_markup=group_keyboard,
                parse_mode="HTML"
            )
        else:
            await callback.message.answer(
                f"Ваш выбор: <b>{target.first_name}</b>\n\n🤓 Вы пошли к этому игроку. Если комиссар тоже проверит его, роль будет раскрыта.",
                reply_markup=group_keyboard,
                parse_mode="HTML"
            )

        await safe_callback_answer(callback, "✅ Выбор записан!")

        await bot.send_message(
            game.chat_id,
            f"🤓 <b>Стукач</b> начал собирать информацию для сплетен...",
            parse_mode="HTML"
        )

        await check_all_night_actions_complete(game)

    except Exception as e:
        logging.error(f"Ошибка в обработке выбора стукача: {e}")
        await safe_callback_answer(callback, "❌ Произошла ошибка!")

@router.callback_query(F.data == "no_action")
async def no_action_callback(callback: CallbackQuery):
    await safe_callback_answer(callback)

@router.message(F.chat.type == "private")
async def handle_private_message(message: Message):
    user_id = message.from_user.id

    if message.text and message.text.startswith("/"):
        return

    for game in active_games.values():
        if game.is_active and game.mafia_chat_active:
            player = next((p for p in game.players if p.user_id == user_id), None)
            if player and player.is_alive and player.role in [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.ADVOCATE, PlayerRole.VAMPIRE]:
                mafia_players = [p for p in game.players if p.is_alive and p.role in [PlayerRole.MAFIA, PlayerRole.DON, PlayerRole.ADVOCATE, PlayerRole.VAMPIRE] and p.user_id != user_id]
                
                for mafia_player in mafia_players:
                    try:
                        player_link = f'<a href="tg://user?id={player.user_id}">{player.first_name}</a>'
                        await bot.send_message(
                            mafia_player.user_id,
                            f"{player_link}: {message.text}",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logging.error(f"Не удалось отправить сообщение в чат мафии игроку {mafia_player.first_name}: {e}")
                return

    for game in active_games.values():
        if game.is_active:
            player = next((p for p in game.players if p.user_id == user_id), None)
            if player and not player.is_alive:
                if player.user_id not in game.death_note_message:
                    game.death_note_message[player.user_id] = message.text
                    await save_games(active_games)

                    player_link = f'<a href="tg://user?id={player.user_id}">{player.first_name}</a>'
                    await bot.send_message(
                        game.chat_id,
                        f"📜 Последние слова {player_link}: \"{message.text}\"",
                        parse_mode="HTML"
                    )

                    await message.answer("✅ Ваши последние слова отправлены в группу!")
                    return

    pass

@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_message_during_night(message: Message):
    if message.text and message.text.startswith("/"):
        return

    if message.from_user.is_bot:
        return

    chat_id = message.chat.id

    if chat_id not in active_games:
        return

    game = active_games[chat_id]

    if not game.is_active:
        return

    player = next((p for p in game.players if p.user_id == message.from_user.id), None)

    if player and not player.is_alive:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception as e:
            logging.debug(f"Не удалось удалить сообщение мертвого игрока: {e}")
        return

    if message.text and isinstance(message.text, str) and message.text.strip().startswith("!"):
        try:
            member = await bot.get_chat_member(chat_id, message.from_user.id)
            if member.status in ["administrator", "creator"]:
                return
        except Exception as e:
            logging.debug(f"Не удалось проверить права администратора: {e}")

    if not player:
        return

    if game.current_phase != "night":
        return

    if player.lover_blocked:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception as e:
            logging.debug(f"Не удалось удалить сообщение заблокированного игрока: {e}")
        return

    try:
        await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except Exception as e:
        logging.debug(f"Не удалось удалить сообщение во время ночи: {e}")

async def main():
    global active_games
    active_games = await load_games()
    logging.info("Games loaded from storage.")

    await dp.start_polling(bot)

if __name__ == '__main__':
    os.makedirs("data", exist_ok=True)

    asyncio.run(main())