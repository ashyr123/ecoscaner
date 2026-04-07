# ♻️ EcoScaner Bot

Telegram бот для поощрения раздельного сбора мусора.
Пользователи фотографируют перерабатываемые отходы, получают баллы и соревнуются в рейтинге.

---

## 🚀 Возможности

### 📸 Двойной AI-анализ (GPT-4o-mini + Gemini 2.0 Flash)
- Два AI анализируют фото параллельно через OpenRouter
- Консенсус двух моделей → принято; разногласие → очередь ручной проверки
- Определяет: тип отходов, бренд, объём, цвет, пустая/полная тара
- Отклоняет: скриншоты, стоковые фото, косметику, несколько предметов в кадре

### 💎 Система баллов
| Тип | Пустая | Полная |
|-----|--------|--------|
| 🧴 Пластик | +5 | +2 |
| 🥫 Металл | +6 | +3 |
| 🍶 Стекло | +8 | +4 |
| 📦 Картон | +3 | +1 |

### 🛡️ Многоуровневая защита от читов
- **Rate limiter** — не более 5 фото в минуту
- **SHA-256 hash** — одно фото принимается только 1 раз глобально
- **Perceptual hash** — визуально похожие фото отклоняются (dHash + aHash)
- **File ID** — один Telegram file_id не принимается дважды
- **Fingerprint** — одна упаковка (бренд + объём) не принимается дважды в день
- **Категорийный лимит** — не более 4 шт. одной категории в день
- **Дневной лимит** — не более 10 фото в день
- **Fraud Score** — взвешенная оценка по 4 сигналам (использованность 30%, доверие 35%, геососедство 20%, file_id 15%)

### 🌍 GPS-бонус
Фото рядом с пунктом приёма (<500 м) → **×1.2** к баллам

### 🌳 Уровни (по `total_earned_points`, никогда не понижаются)
| Уровень | Порог |
|---------|-------|
| 🌰 Начинающий | 0+ |
| 🌱 Эко-новичок | 50+ |
| 🌿 Эко-активист | 200+ |
| 🌳 Эко-мастер | 500+ |

### 🏆 Рейтинг
- `/top` — топ-10 за всё время
- `/top week` — топ-10 за последние 7 дней

### 🛍️ Магазин наград
- `/store` — список наград
- `/buy <id>` — купить награду (баллы списываются с баланса, уровень не меняется)

---

## 📁 Структура проекта
ecoscaner-mvp/
├── admin/
│ └── app.py # Flask admin панель (логин, дашборд, пользователи)
├── config/
│ └── settings.py # Все настройки и переменные окружения
├── database/
│ └── db.py # get_connection(), init_db(), миграции, индексы
├── handlers/
│ ├── start.py # /start
│ ├── profile.py # /profile
│ ├── top.py # /top, /top week
│ ├── help.py # /help
│ ├── photo.py # Обработка фото: AI + fraud + баллы
│ └── store.py # /store, /buy
├── services/
│ ├── user_service.py # Пользователи, баллы, рейтинг
│ ├── waste_service.py # WasteRecord, hash, fingerprint, дубликаты
│ ├── store_service.py # Магазин, покупки, сток
│ ├── fingerprint.py # ProductAnalyzer, pHash, консенсус AI
│ └── fraud_scorer.py # compute_fraud_score(), GPS множитель
├── run.py # Единая точка запуска (бот + admin)
├── .env # Секреты (не коммитить!)
└── requirements.txt

text

---

## 🗄️ База данных (SQLite + WAL)

| Таблица | Назначение |
|---------|-----------|
| `users` | Профили, баланс, уровень |
| `wastes` | История сдачи, hash, GPS, fraud_score |
| `store_items` | Награды в магазине |
| `purchases` | История покупок |
| `review_queue` | Фото с разногласием двух AI |
| `fraud_flags` | Подозрительные действия |
| `recycling_points` | Координаты пунктов приёма для GPS-бонуса |

---

## ⚙️ Установка

```bash
git clone https://github.com/yourname/ecoscaner-mvp.git
cd ecoscaner-mvp
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Создать `.env`:
```env
BOT_TOKEN=your_telegram_bot_token
OPENROUTER_API_KEY=your_openrouter_api_key
ADMIN_SECRET=your_flask_secret
ADMIN_PASSWORD=your_admin_password
ADMIN_TELEGRAM_IDS=123456789
DATABASE_PATH=        # оставить пустым — путь определится автоматически
DAILY_LIMIT=10
CATEGORY_DAY_LIMIT=4
ACCOUNT_MIN_AGE_DAYS=0
FRAUD_SCORE_THRESHOLD=0.65
```

```bash
python run.py
# 🤖 Бот активен
# 🌐 Admin → http://127.0.0.1:5000
```

---

## 📱 Команды

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и инструкция |
| `/profile` | Баланс, уровень, статистика |
| `/top` | Топ-10 за всё время |
| `/top week` | Топ-10 за неделю |
| `/store` | Магазин наград |
| `/buy <id>` | Купить награду |
| `/help` | Помощь |

---

## 🛠️ Tech Stack

| Компонент | Технология |
|-----------|------------|
| Bot | python-telegram-bot 21.x |
| AI | OpenRouter (GPT-4o-mini + Gemini 2.0 Flash) |
| Database | SQLite (WAL mode) |
| Admin | Flask |
| Language | Python 3.12+ |

---

## 📌 Roadmap

- [x] Двойной AI анализ (GPT + Gemini)
- [x] Fraud Score (4 сигнала)
- [x] Perceptual hash дедупликация
- [x] GPS-бонус
- [x] Рейтинг + недельный топ
- [x] Магазин наград
- [x] Очередь ручной проверки
- [x] Admin панель
- [ ] Автоуведомления из review queue
- [ ] /lottery — розыгрыш призов
- [ ] Ежедневные напоминания
- [ ] VPS деплой
- [ ] Партнёрские купоны