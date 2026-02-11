import aiosqlite
import asyncio
import os
from src.config import get_proxy_link

# Если задана переменная окружения DB_PATH, используем её, иначе файл в корне
DB_NAME = os.getenv("DB_PATH", "bot_database.db")

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Таблица прокси
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT,
                server TEXT,
                port INTEGER,
                secret TEXT,
                usage_count INTEGER DEFAULT 0,
                unique_identifier TEXT UNIQUE,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        
        # Миграция: добавляем столбец is_active, если его нет (для старых баз)
        try:
            await db.execute("ALTER TABLE proxies ADD COLUMN is_active BOOLEAN DEFAULT 1")
        except Exception:
            pass 

        # Таблица связей (кто какой прокси взял)
        # Хранит историю, чтобы не накручивать счетчик одним юзером
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_proxy_relations (
                user_id INTEGER,
                proxy_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, proxy_id)
            )
        """)

        await db.commit()

async def add_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_all_users_count():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_proxy_if_new(location, server, port, secret):
    unique_id = f"{server}:{port}"
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            # Пытаемся добавить новый прокси
            cursor = await db.execute(
                """
                INSERT INTO proxies (location, server, port, secret, usage_count, unique_identifier, is_active)
                VALUES (?, ?, ?, ?, 0, ?, 1)
                """,
                (location, server, port, secret, unique_id)
            )
            await db.commit()
            return True # Успешно добавлен (новый)
        except aiosqlite.IntegrityError:
            return False # Уже существует

async def get_all_proxies(only_active=True):
    query = "SELECT * FROM proxies"
    if only_active:
        query += " WHERE is_active = 1"
    query += " ORDER BY location"
    
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query) as cursor:
            return await cursor.fetchall()

async def get_least_loaded_proxy(user_id: int):
    """
    Возвращает прокси с наименьшим количеством использований.
    Если этот пользователь еще не брал этот прокси -> записываем и увеличиваем счетчик.
    Если брал -> просто возвращаем прокси, не увеличивая счетчик.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        # Выбираем прокси, сортируем по usage_count (возрастание), берем первый активный
        async with db.execute("SELECT * FROM proxies WHERE is_active = 1 ORDER BY usage_count ASC LIMIT 1") as cursor:
            proxy = await cursor.fetchone()
            
            if proxy:
                # Пытаемся записать использование
                try:
                    await db.execute(
                        "INSERT INTO user_proxy_relations (user_id, proxy_id) VALUES (?, ?)",
                        (user_id, proxy["id"])
                    )
                    # Если вставка прошла успешно (значит связи не было), увеличиваем счетчик
                    await db.execute(
                        "UPDATE proxies SET usage_count = usage_count + 1 WHERE id = ?",
                        (proxy["id"],)
                    )
                    await db.commit()
                except aiosqlite.IntegrityError:
                    pass # Юзер уже получал этот прокси, счетчик не увеличиваем

            return proxy

async def record_usage(user_id: int, proxy_id: int):
    """
    Пытается зафиксировать факт использования прокси пользователем.
    Увеличивает общий счетчик прокси ТОЛЬКО если пользователь берет его впервые.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO user_proxy_relations (user_id, proxy_id) VALUES (?, ?)",
                (user_id, proxy_id)
            )
            # Если запись уникальна - увеличиваем счетчик
            await db.execute(
                "UPDATE proxies SET usage_count = usage_count + 1 WHERE id = ?",
                (proxy_id,)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            pass # Связка уже существует

async def get_proxy_by_id(proxy_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)) as cursor:
            return await cursor.fetchone()

async def toggle_proxy_status(proxy_id: int):
    """Переключает статус активности прокси"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Сначала получаем текущий статус
        async with db.execute("SELECT is_active FROM proxies WHERE id = ?", (proxy_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            current_status = row[0]
        
        new_status = 0 if current_status else 1
        await db.execute("UPDATE proxies SET is_active = ? WHERE id = ?", (new_status, proxy_id))
        await db.commit()
        return new_status

async def delete_proxy(proxy_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        await db.execute("DELETE FROM user_proxy_relations WHERE proxy_id = ?", (proxy_id,))
        await db.commit()

async def reset_proxy_usage(proxy_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        # Сбрасываем счетчик в таблице proxies
        await db.execute("UPDATE proxies SET usage_count = 0 WHERE id = ?", (proxy_id,))
        # Удаляем историю использования этим прокси
        await db.execute("DELETE FROM user_proxy_relations WHERE proxy_id = ?", (proxy_id,))
        await db.commit()

async def update_proxy(proxy_id: int, location: str, server: str, port: int, secret: str):
    unique_id = f"{server}:{port}"
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                """
                UPDATE proxies 
                SET location = ?, server = ?, port = ?, secret = ?, unique_identifier = ?
                WHERE id = ?
                """,
                (location, server, port, secret, unique_id, proxy_id)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False
