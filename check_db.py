# check_db.py
import sqlite3, os

# Scriptin kendi klasöründeki DB'yi bul
BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "ecoscaner.db")

print(f"DB yolu: {DB}")
print(f"Dosya var mı: {os.path.exists(DB)}")

conn = sqlite3.connect(DB)
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print(f"Tablo sayısı: {len(rows)}")
for r in rows:
    print(" →", r[0])
conn.close()