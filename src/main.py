import asyncio
import logging
import sys
import urllib.parse
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.config import BOT_TOKEN, INITIAL_PROXIES, get_proxy_link, ADMIN_IDS
from src import database as db

# Настройка логирования
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Rate Limit Config ---
RATE_LIMIT = 2.0 # seconds
user_last_action = {}

def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    last_time = user_last_action.get(user_id, 0)
    
    if now - last_time < RATE_LIMIT:
        return False # Too fast
        
    user_last_action[user_id] = now
    return True

# States
class AddProxyState(StatesGroup):
    waiting_for_link = State()
    waiting_for_location = State()
    confirm_notification = State()

# --- Middleware / Checks ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# --- User Handlers ---

@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    if not check_rate_limit(message.from_user.id):
        return # Ignore spam

    await db.add_user(message.from_user.id, message.from_user.username)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Получить лучший прокси", callback_data="get_best_proxy")
    kb.button(text="📋 Показать все прокси", callback_data="get_all_proxies")
    
    if is_admin(message.from_user.id):
        kb.button(text="⚙️ Админ панель", callback_data="admin_panel")
        
    kb.adjust(1)
    
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n\n"
        "Я помогу тебе получить быстрый MTProxy.\n"
        "Я автоматически выберу наименее нагруженный сервер для тебя.",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "get_best_proxy")
async def process_get_best_proxy(callback: types.CallbackQuery):
    if not check_rate_limit(callback.from_user.id):
        await callback.answer("⏳ Не спешите, подождите пару секунд...", show_alert=True)
        return

    proxy = await db.get_least_loaded_proxy(callback.from_user.id)
    
    if not proxy:
        await callback.message.answer("😓 Нет доступных активных прокси.")
        await callback.answer()
        return

    link = get_proxy_link(proxy['server'], proxy['port'], proxy['secret'])
    
    text = (
        f"<b>🚀 Рекомендуемый прокси:</b>\n"
        f"🌍 Локация: {proxy['location']}\n"
        f"👥 Сейчас пользуются: {proxy['usage_count']}\n\n"
        f"👇 Нажми кнопку ниже, чтобы подключиться"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Подключиться", url=link)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "get_all_proxies")
async def process_get_all_proxies(callback: types.CallbackQuery):
    if not check_rate_limit(callback.from_user.id):
        await callback.answer("⏳ Не спешите, подождите пару секунд...", show_alert=True)
        return

    proxies = await db.get_all_proxies(only_active=True)
    
    if not proxies:
        await callback.message.answer("Список активных прокси пуст.")
        await callback.answer()
        return

    text = "<b>📋 Все доступные прокси:</b>\n\n"
    kb = InlineKeyboardBuilder()
    
    for p in proxies:
        text += (
            f"🌍 <b>{p['location']}</b>\n"
            f"📊 Использований: {p['usage_count']}\n\n"
        )
        # Теперь кнопка ведет не на URL, а вызывает callback
        kb.button(text=f"Connect {p['location']}", callback_data=f"user_connect_{p['id']}")

    kb.button(text="🔙 Назад", callback_data="start_menu")
    kb.adjust(1)
    
    await callback.message.edit_text(
        text, 
        parse_mode="HTML", 
        reply_markup=kb.as_markup(),
        disable_web_page_preview=True
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("user_connect_"))
async def process_user_connect_proxy(callback: types.CallbackQuery):
    if not check_rate_limit(callback.from_user.id):
        await callback.answer("⏳ Не спешите, подождите пару секунд...", show_alert=True)
        return

    try:
        proxy_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    # Записываем использование
    await db.record_usage(callback.from_user.id, proxy_id)
    
    # Получаем данные
    proxy = await db.get_proxy_by_id(proxy_id)
    if not proxy or not proxy['is_active']:
        await callback.answer("Прокси больше не доступен", show_alert=True)
        return

    link = get_proxy_link(proxy['server'], proxy['port'], proxy['secret'])
    
    text = (
        f"<b>🌍 Выбран прокси: {proxy['location']}</b>\n"
        f"Вот ваша ссылка для подключения 👇"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Подключиться", url=link)],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="get_all_proxies")]
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "start_menu")
async def process_back_to_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Получить лучший прокси", callback_data="get_best_proxy")
    kb.button(text="📋 Показать все прокси", callback_data="get_all_proxies")
    
    if is_admin(callback.from_user.id):
        kb.button(text="⚙️ Админ панель", callback_data="admin_panel")
        
    kb.adjust(1)
    
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=kb.as_markup()
    )

# --- Admin Handlers ---

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await show_admin_panel(message)

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    await show_admin_panel(callback.message, is_edit=True)

async def show_admin_panel(message: types.Message, is_edit=False):
    users_count = await db.get_all_users_count()
    proxies = await db.get_all_proxies(only_active=False)
    active_count = sum(1 for p in proxies if p['is_active'])
    
    text = (
        f"<b>⚙️ Админ панель</b>\n\n"
        f"👥 Всего юзеров: {users_count}\n"
        f"🌍 Прокси всего: {len(proxies)} (Активных: {active_count})"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить прокси", callback_data="admin_add_proxy")
    kb.button(text="📋 Управление прокси", callback_data="admin_manage_proxies")
    kb.button(text="🔙 Назад в меню", callback_data="start_menu")
    kb.adjust(1)
    
    if is_edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())

# --- Add Proxy Logic ---

@dp.callback_query(F.data == "admin_add_proxy")
async def start_add_proxy(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Отправьте мне ссылку на MTProxy.\n"
        "Формат: https://t.me/proxy?server=...&port=...&secret=..."
    )
    await state.set_state(AddProxyState.waiting_for_link)
    await callback.answer()

@dp.message(AddProxyState.waiting_for_link)
async def process_proxy_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    
    # Simple validation using urllib
    try:
        parsed = urllib.parse.urlparse(link)
        params = urllib.parse.parse_qs(parsed.query)
        
        server = params.get('server', [None])[0]
        port = params.get('port', [None])[0]
        secret = params.get('secret', [None])[0]
        
        if not (server and port and secret):
            raise ValueError("Missing params")
            
        await state.update_data(server=server, port=int(port), secret=secret)
        
        await message.answer("Отлично! Теперь введите название локации (например: Финляндия 🇫🇮):")
        await state.set_state(AddProxyState.waiting_for_location)
        
    except Exception as e:
        await message.answer("Неверный формат ссылки. Попробуйте еще раз или /cancel.")

@dp.message(AddProxyState.waiting_for_location)
async def process_proxy_location(message: types.Message, state: FSMContext):
    location = message.text.strip()
    data = await state.get_data()
    
    # Save to DB
    is_new = await db.add_proxy_if_new(
        location, data['server'], data['port'], data['secret']
    )
    
    if not is_new:
        await message.answer("Этот прокси уже существует в базе!")
        await state.clear()
        return

    # Ask for notification
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Разослать уведомление", callback_data="notify_yes")
    kb.button(text="🔕 Не рассылать", callback_data="notify_no")
    
    await state.update_data(location=location) # Save location for notification msg
    
    await message.answer(
        f"Прокси '{location}' добавлен!\nРазослать уведомление всем пользователям?",
        reply_markup=kb.as_markup()
    )
    await state.set_state(AddProxyState.confirm_notification)

@dp.callback_query(F.data.startswith("notify_"))
async def process_notification_choice(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1]
    data = await state.get_data()
    
    if action == "yes":
        await callback.message.edit_text("⏳ Рассылка уведомлений...")
        link = get_proxy_link(data['server'], data['port'], data['secret'])
        msg_text = (
            f"🎉 <b>Добавлен новый прокси!</b>\n\n"
            f"🌍 Локация: {data['location']}\n"
            f"🔗 <a href='{link}'>Подключиться сейчас</a>"
        )
        
        users = await db.get_all_users()
        count = 0
        for user_id in users:
            try:
                await bot.send_message(user_id, msg_text, parse_mode="HTML")
                count += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        
        await callback.message.answer(f"✅ Рассылка завершена. Отправлено: {count}.")
    else:
        await callback.message.edit_text("✅ Прокси добавлен без рассылки.")
        
    await state.clear()
    await show_admin_panel(callback.message)

# --- Manage Proxies Logic ---

@dp.callback_query(F.data == "admin_manage_proxies")
async def list_proxies_admin(callback: types.CallbackQuery):
    proxies = await db.get_all_proxies(only_active=False)
    
    if not proxies:
        await callback.message.answer("Прокси нет.")
        return

    text = "Управление прокси (нажмите, чтобы изменить статус):"
    kb = InlineKeyboardBuilder()
    
    for p in proxies:
        status_icon = "✅" if p['is_active'] else "❌"
        # Кнопка: "✅ Финляндия | 123 uses"
        label = f"{status_icon} {p['location']} | 👥 {p['usage_count']}"
        kb.button(text=label, callback_data=f"toggle_proxy_{p['id']}")
    
    kb.button(text="🔙 Назад", callback_data="admin_panel")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("toggle_proxy_"))
async def toggle_proxy(callback: types.CallbackQuery):
    proxy_id = int(callback.data.split("_")[2])
    new_status = await db.toggle_proxy_status(proxy_id)
    
    if new_status is None:
        await callback.answer("Прокси не найден", show_alert=True)
        return
        
    status_text = "Активен" if new_status else "Отключен"
    await callback.answer(f"Статус изменен на: {status_text}")
    
    # Обновляем список
    await list_proxies_admin(callback)


async def check_new_proxies_and_notify():
    """Проверяет конфиг и добавляет новые прокси, рассылая уведомления."""
    new_proxies_added = []
    
    for p in INITIAL_PROXIES:
        is_new = await db.add_proxy_if_new(
            p['location'], 
            p['server'], 
            p['port'], 
            p['secret']
        )
        if is_new:
            new_proxies_added.append(p)
            
    if new_proxies_added:
        users = await db.get_all_users()
        for p in new_proxies_added:
            link = get_proxy_link(p['server'], p['port'], p['secret'])
            msg_text = (
                f"🎉 <b>Добавлен новый прокси!</b>\n\n"
                f"🌍 Локация: {p['location']}\n"
                f"🔗 <a href='{link}'>Подключиться сейчас</a>"
            )
            print(f"Рассылка уведомления о {p['location']} для {len(users)} пользователей...")
            for user_id in users:
                try:
                    await bot.send_message(user_id, msg_text, parse_mode="HTML")
                    await asyncio.sleep(0.05) 
                except Exception as e:
                    print(f"Не удалось отправить пользователю {user_id}: {e}")

async def main():
    # Инициализируем БД
    await db.init_db()
    
    # Проверяем новые прокси из конфига (на всякий случай)
    await check_new_proxies_and_notify()
    
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        if not BOT_TOKEN:
            print("ОШИБКА: BOT_TOKEN не найден в .env файле!")
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
