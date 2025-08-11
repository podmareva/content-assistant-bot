# db_check.py — проверка подключения к БД (psycopg v3)
import os
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

load_dotenv()
url = os.getenv("DATABASE_URL")
print("DATABASE_URL loaded:", bool(url))

try:
    # row_factory=dict_row -> получать словари, как раньше с RealDictCursor
    with psycopg.connect(url, sslmode="require", row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("select version() as v")
            print("Postgres version:", cur.fetchone()["v"])

            cur.execute("select current_user as u, current_database() as d")
            print("User/DB:", cur.fetchone())

    print("✅ OK — подключение работает")
except Exception as e:
    print("❌ Ошибка подключения:", e)
