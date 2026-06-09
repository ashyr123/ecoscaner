from database.db import get_connection

with get_connection() as conn:
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM purchases")
    conn.execute("DELETE FROM store_items")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='store_items'")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='purchases'")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

print("Temizlendi")