# EcoScaner — Geliştirme Yol Haritası / Development Roadmap

Mobil web arayüzü (`web/index.html`) ve Telegram botu birlikte büyüyecek. Her faz 3–5 somut adım içerir.

---

## Faz 1 — Statik UI (tamamlandı)

**Amaç:** Kullanıcı arayüzünü tarayıcıda görmek ve mock veriyle test etmek.

| # | Adım | Dosya |
|---|------|--------|
| 1 | HTML arayüzünü `web/index.html` olarak kaydet | `web/index.html` |
| 2 | Flask ile `/app` rotasında sun | `admin/app.py` → `mobile_app()` |
| 3 | `python run.py` ile sunucuyu başlat | `run.py` |
| 4 | Tarayıcıda aç: `http://127.0.0.1:5000/app` | — |
| 5 | (İsteğe bağlı) `.env` içine `GEMINI_API_KEY` ekle; tarama/sohbet dene | `.env`, `/api/app/config` |

**English:** Static mobile UI is served at `/app`; Gemini key is optional via `GEMINI_API_KEY`.

---

## Faz 2 — SQLite ve mevcut backend API’leri ✅ (tamamlandı)

**Amaç:** Mock Alexander / 450 puan yerine gerçek `users`, `wastes`, `store_items` verisi.

| # | Adım | Durum | Dosya |
|---|------|--------|--------|
| 1 | `GET /api/app/profile?user_id=` — profil, seviye, bakiye | ✅ | `api/app_routes.py`, `services/app_api_service.py` |
| 2 | `GET /api/app/activity` — son atıklar (`wastes`) | ✅ | `api/app_routes.py` |
| 3 | `GET /api/app/leaderboard` — sıralama + mevcut kullanıcı | ✅ | `services/app_api_service.py` |
| 4 | `GET /api/app/store` — mağaza + `canAfford` | ✅ | `services/store_service.py` |
| 5 | `web/index.html` — `fetch()` ile canlı veri | ✅ | `web/index.html` |
| 6 | `POST /api/app/scan` | ✅ Faz 4 | `services/scan_service.py` |

---

## Faz 3 — Telegram Web App ve kimlik doğrulama ✅

| # | Adım | Durum | Dosya |
|---|------|--------|--------|
| 1 | `telegram-web-app.js` + `initData` → `POST /api/app/auth` | ✅ | `web/index.html`, `services/telegram_webapp.py` |
| 2 | İmzalı cookie oturumu (`ecoscaner_sid`) | ✅ | `services/web_auth.py` |
| 3 | Korumalı API rotaları (`@login_required_api`) | ✅ | `api/app_routes.py` |
| 4 | Dev mod: `APP_ALLOW_DEV_AUTH` + `POST /api/app/auth/dev` | ✅ | `.env` |
| 5 | `/start` → Web App düğmesi | ✅ | `handlers/start.py` |
| 6 | `POST /api/app/store/buy` | ✅ | `api/app_routes.py`, `store_service.py` |
| 7 | `WEBAPP_URL` BotFather + `.env` | ✅ | `config/settings.py` |

**English:** Telegram HMAC auth + signed cookie; buy flow wired.

---

## Faz 4 — Sunucu taraması (OpenRouter çift-AI) ✅

| # | Adım | Durum | Dosya |
|---|------|--------|--------|
| 1 | `POST /api/app/scan` multipart upload | ✅ | `api/app_routes.py` |
| 2 | Paylaşılan pipeline (fraud, hash, AI) | ✅ | `services/scan_service.py` |
| 3 | İstemci Gemini tarama kaldırıldı | ✅ | `web/index.html` |
| 4 | Sohbet sunucu proxy (`POST /api/app/chat`) | ✅ | `api/app_routes.py` |
| 5 | Admin review kuyruğu (web kaynaklı) | ✅ | `review_queue` insert |

**English:** Web scan uses same dual-AI as bot; API keys stay server-side.

---

## Faz 5 — Deploy

**Amaç:** Üretimde HTTPS ile bot + web + admin.

| # | Adım | Dosya |
|---|------|--------|
| 1 | VPS (Ubuntu): Python 3.12, `pip install -r requirements.txt` | `requirements.txt` |
| 2 | `.env` üretim değerleri; `ecoscaner.db` yedekleme | `.env.example` |
| 3 | `systemd` unit: `WorkingDirectory=.../ecoscaner-mvp`, `ExecStart=.../python run.py` | yeni `deploy/ecoscaner.service` |
| 4 | Nginx: `/app` ve admin → `127.0.0.1:5000`, SSL (Let’s Encrypt) | — |
| 5 | Webhook veya polling; `ADMIN_GROUP_ID` ve log izleme | `main.py`, `run.py` |

**English:** systemd + reverse proxy; HTTPS required for Telegram Web App.

---

## Hızlı komutlar

```powershell
Set-Location "c:\Users\User\OneDrive\Desktop\ecoscaner_mvp_v2\ecoscaner-mvp"
& "c:\Users\User\OneDrive\Desktop\ecoscaner_mvp_v2\.venv\Scripts\python.exe" run.py
```

- Admin: http://127.0.0.1:5000  
- Mobil uygulama: http://127.0.0.1:5000/app  

Alternatif (sadece statik HTML, bot yok):

```powershell
Set-Location "c:\Users\User\OneDrive\Desktop\ecoscaner_mvp_v2\ecoscaner-mvp\web"
python -m http.server 8080
# http://127.0.0.1:8080/ — Gemini anahtarı için Flask /api/app/config gerekir
```
