import os, psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
print("DATABASE_URL loaded:", url)

try:
    conn = psycopg2.connect(url, sslmode="require", cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute("select version() as v;")
    print("Postgres version:", cur.fetchone()["v"])
    cur.execute("select current_user as u, current_database() as d;")
    print(cur.fetchone())
    conn.close()
    print("✅ OK — подключение работает")
except Exception as e:
    print("❌ Ошибка подключения:", e)
