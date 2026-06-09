♻️ EcoScaner Bot
Telegram бот для поощрения раздельного сбора мусора.
Пользователи фотографируют перерабатываемые отходы, получают баллы и соревнуются в рейтинге.

🚀 Возможности
📸 Двойной AI-анализ (GPT-4o-mini + Gemini 2.0 Flash)
Два AI анализируют фото параллельно через OpenRouter

Консенсус двух моделей → принято; разногласие → очередь ручной проверки

Определяет: тип отходов, бренд, объём, цвет, пустая/полная тара

Отклоняет: скриншоты, стоковые фото, косметику, несколько предметов в кадре

💎 Система баллов
Тип	Пустая	Полная
🧴 Пластик	+5	+2
🥫 Металл	+6	+3
🍶 Стекло	+8	+4
📦 Картон	+3	+1
🛡️ Многоуровневая защита от читов
Rate limiter — не более 5 фото в минуту

SHA-256 hash — одно фото принимается только 1 раз глобально

Perceptual hash — визуально похожие фото отклоняются (dHash + aHash)

File ID — один Telegram file_id не принимается дважды

Fingerprint — одна упаковка (бренд + объём) не принимается дважды в день

Категорийный лимит — не более 4 шт. одной категории в день

Дневной лимит — не более 10 фото в день

Fraud Score — взвешенная оценка по 4 сигналам (использованность 30%, доверие 35%, геососедство 20%, file_id 15%)

🌍 GPS-бонус
Фото рядом с пунктом приёма (<500 м) → ×1.2 к баллам

🌳 Уровни (по total_earned_points, никогда не понижаются)
Уровень	Порог
🌰 Начинающий	0+
🌱 Эко-новичок	50+
🌿 Эко-активист	200+
🌳 Эко-мастер	500+
🏆 Рейтинг
/top — топ-10 за всё время

/top week — топ-10 за последние 7 дней

🛍️ Магазин наград
/store — список наград (сортировка по цене, ✅/🔒 по балансу)

/buy <id> — купить награду (баллы списываются с баланса, уровень не меняется)

Купленные награды отображаются в /profile

🔎 Очередь ручной проверки
При разногласии AI фото попадает в очередь

Уведомление с фото и кнопками выбора категории отправляется в Telegram-группу администраторов

Администратор принимает решение прямо в Telegram или через веб-панель

После решения пользователю автоматически приходит уведомление + баллы

📁 Структура проекта
text
ecoscaner-mvp/
├── admin/
│   ├── app.py                  # Flask admin панель (логин, дашборд, пользователи, reviews)
│   └── templates/
│       ├── base.html           # Общий layout, sidebar
│       ├── dashboard.html      # Статистика + график активности
│       ├── users.html          # Список пользователей + поиск
│       ├── activity.html       # Последние 50 записей
│       ├── reviews.html        # Фото + кнопки категорий + решение
│       └── login.html          # Страница входа
├── config/
│   ├── settings.py             # Все настройки и переменные окружения
│   └── bonus_brands.py         # Бренды с бонусными баллами
├── database/
│   └── db.py                   # get_connection(), init_db(), миграции, индексы
├── handlers/
│   ├── start.py                # /start
│   ├── profile.py              # /profile (баланс, уровень, награды)
│   ├── top.py                  # /top, /top week
│   ├── help.py                 # /help
│   ├── photo.py                # Обработка фото: AI + fraud + баллы
│   ├── store.py                # /store, /buy
│   ├── admin_review.py         # Review queue: уведомления в группу + callback-кнопки
│   └── start_task.py           # Система заданий
├── services/
│   ├── user_service.py         # Пользователи, баллы, рейтинг
│   ├── waste_service.py        # WasteRecord, hash, fingerprint, дубликаты
│   ├── store_service.py        # Магазин, покупки, сток
│   ├── fingerprint.py          # ProductAnalyzer, pHash, консенсус AI
│   ├── fraud_scorer.py         # compute_fraud_score(), GPS множитель
│   └── task_service.py         # Логика заданий
├── run.py                      # Единая точка запуска (бот + admin)
├── .env                        # Секреты (не коммитить!)
├── requirements.txt
├── check_db.py                 # Проверка таблиц БД
├── check_syntax.py             # Проверка синтаксиса всех .py файлов
└── cleanup.py                  # Сброс store_items и purchases
🗄️ База данных (SQLite + WAL)
Таблица	Назначение
users	Профили, баланс, уровень
wastes	История сдачи, hash, GPS, fraud_score
store_items	Награды в магазине
purchases	История покупок
review_queue	Фото с разногласием двух AI (хранит file_id)
fraud_flags	Подозрительные действия
recycling_points	Координаты пунктов приёма для GPS-бонуса
⚙️ Установка
bash
git clone https://github.com/yourname/ecoscaner-mvp.git
cd ecoscaner-mvp
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
Создать .env:

text
BOT_TOKEN=your_telegram_bot_token
OPENROUTER_API_KEY=your_openrouter_api_key
ADMIN_SECRET=your_flask_secret
ADMIN_PASSWORD=your_admin_password
ADMIN_GROUP_ID=-1001234567890   # ID Telegram-группы администраторов
DATABASE_PATH=                  # оставить пустым — путь определится автоматически
DAILY_LIMIT=10
CATEGORY_DAY_LIMIT=4
ACCOUNT_MIN_AGE_DAYS=0
FRAUD_SCORE_THRESHOLD=0.65
Как получить ADMIN_GROUP_ID: добавь @userinfobot в группу, напиши любое сообщение — бот ответит ID группы (начинается с -100).

bash
python run.py
# 🤖 Бот активен
# 🌐 Admin → http://127.0.0.1:5000
📱 Команды
Команда	Описание
/start	Приветствие и инструкция
/profile	Баланс, уровень, статистика, награды
/top	Топ-10 за всё время
/top week	Топ-10 за неделю
/store	Магазин наград
/buy <id>	Купить награду
/help	Помощь
🛠️ Tech Stack
Компонент	Технология
Bot	python-telegram-bot 21.x
AI	OpenRouter (GPT-4o-mini + Gemini 2.0 Flash)
Database	SQLite (WAL mode)
Admin	Flask
Language	Python 3.12+
📌 Roadmap
Двойной AI анализ (GPT + Gemini)

Fraud Score (4 сигнала)

Perceptual hash дедупликация

GPS-бонус

Рейтинг + недельный топ

Магазин наград (сортировка по цене, ✅/🔒 статус)

Награды в профиле

Очередь ручной проверки с фото

Admin веб-панель

Telegram-уведомления в группу (фото + кнопки)

Уведомление пользователю после решения

/lottery — розыгрыш призов

Ежедневные напоминания

VPS деплой

Партнёрские купоны