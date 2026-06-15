# 📦 Инструкция по деплою бота

## 🚀 Шаг 1: Загрузка на GitHub

### Вариант A: Через GitHub Desktop (проще)
1. Скачайте и установите [GitHub Desktop](https://desktop.github.com/)
2. Откройте GitHub Desktop
3. File → Add Local Repository
4. Выберите папку `bot`
5. Нажмите "Publish repository"
6. Снимите галочку "Keep this code private" (если хотите публичный репозиторий)
7. Нажмите "Publish repository"

### Вариант B: Через командную строку
1. Создайте новый репозиторий на [GitHub.com](https://github.com/new)
2. Выполните команды:

```bash
cd c:\Users\ivant\OneDrive\Desktop\funpay\bot
git remote add origin https://github.com/ВАШ_USERNAME/ВАШ_REPO.git
git branch -M main
git push -u origin main
```

## ☁️ Шаг 2: Деплой на Apply.build

1. Перейдите на [apply.build](https://apply.build)
2. Войдите через GitHub
3. Нажмите "New Project"
4. Выберите ваш репозиторий из списка
5. Настройте проект:
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
6. Добавьте переменные окружения (Environment Variables):
   - `BOT_TOKEN` = ваш токен от @BotFather
   - `ADMIN_IDS` = ваши ID через запятую (например: 1818423656,7380810090)
7. Нажмите "Deploy"

## ⚙️ Шаг 3: Получение токена бота

Если у вас еще нет токена:
1. Откройте Telegram
2. Найдите @BotFather
3. Отправьте команду `/newbot`
4. Следуйте инструкциям
5. Скопируйте полученный токен

## 🆔 Шаг 4: Получение вашего Telegram ID

1. Найдите в Telegram бота @userinfobot
2. Отправьте ему команду `/start`
3. Он отправит вам ваш ID

## ✅ Проверка работы

1. Дождитесь завершения деплоя на Apply.build
2. Проверьте логи (Logs) на наличие ошибок
3. Откройте вашего бота в Telegram
4. Отправьте команду `/start`
5. Если бот ответил - всё работает! 🎉

## ⚠️ ВАЖНО: Безопасность

**НИКОГДА не публикуйте токен бота в коде!**
- ✅ Используйте переменные окружения
- ✅ Добавьте `.env` в `.gitignore`
- ❌ Не коммитьте файлы с токенами
- ❌ Не публикуйте токены в README

## 🔧 Обновление бота

Когда вы вносите изменения в код:

1. Внесите изменения в файлы
2. Закоммитьте изменения:
```bash
git add .
git commit -m "Описание изменений"
git push
```
3. Apply.build автоматически задеплоит новую версию

## 📝 Альтернативные платформы

Если Apply.build не подходит, можете использовать:
- **Heroku** (требует кредитную карту)
- **Railway.app** (бесплатный tier)
- **Render.com** (бесплатный tier)
- **Fly.io** (бесплатный tier)

Процесс деплоя везде похож!
