import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x) for x in admin_ids_str.split(",") if x.strip().isdigit()]

# Список начальных прокси. 
# Теперь прокси хранятся в базе данных. Вы можете добавлять новые через админку /admin
# Этот список можно оставить пустым.
INITIAL_PROXIES = []

def get_proxy_link(server, port, secret):
    return f"https://t.me/proxy?server={server}&port={port}&secret={secret}"
