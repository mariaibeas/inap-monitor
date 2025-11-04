# monitor_inap.py
import os, json, re, subprocess
from datetime import datetime
import hashlib
import requests
from bs4 import BeautifulSoup

# ========= Config por variables de entorno =========
# URL vigilada (si no se pasa, usa INAP)
URL = os.getenv("URL_TO_WATCH", "https://sede.inap.gob.es/secretaria-intervencion-acceso-libre-2023-2024")

# Modo de snapshot:
#  - "text": extrae texto (article/main o body) y genera hash
#  - "links": extrae SOLO enlaces <a> como "texto || href" y genera hash
MODE = os.getenv("MODE", "text").strip().lower()  # "text" | "links"

# Selector opcional para acotar el área (ej. "article", "ul", "#contenedor .lista")
CSS_SELECTOR = os.getenv("CSS_SELECTOR", "").strip()

STATE_FILE = "state_inap.json"
LOG_FILE   = "hashes.log"

# Telegram: 1 o varios destinos
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "").strip()   # opcional (uno)
TELEGRAM_CHAT_IDS = os.getenv("TELEGRAM_CHAT_IDS", "").strip()  # coma-separada (varios)

# Para pruebas controladas: cambiar este secret hace que cambie el hash
SNAPSHOT_SALT = os.getenv("SNAPSHOT_SALT", "")

# ========= Utilidades =========
def log(line: str):
    line2 = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {line}"
    print(line2)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line2 + "\n")
    except Exception:
        pass

def fetch_html(url: str) -> str:
    r = requests.get(url, timeout=25, headers={"User-Agent":"INAP-monitor/1.0"})
    r.raise_for_status()
    return r.text

def extract_summary(html: str) -> str:
    soup  = BeautifulSoup(html, "html.parser")
    scope = soup.select_one(CSS_SELECTOR) if CSS_SELECTOR else (soup.find("article") or soup.find("main") or soup)
    text  = re.sub(r"\n{2,}", "\n", scope.get_text(separator="\n")).strip()
    lines = [L for L in text.split("\n") if L.strip()]
    head  = "\n".join(lines[:200])  # limitar para estabilidad
    return head

def extract_links_snapshot(html: str) -> str:
    soup  = BeautifulSoup(html, "html.parser")
    scope = soup.select_one(CSS_SELECTOR) if CSS_SELECTOR else soup
    pairs = []
    for a in scope.find_all("a", href=True):
        t = " ".join(a.get_text(" ", strip=True).split())
        h = a["href"].strip()
        pairs.append(f"{t} || {h}")
    return "\n".join(pairs[:500])  # limitar por si hay muchos

def load_state():
    base = {"hash": None, "last_changed": None, "known_chats": []}
    if not os.path.exists(STATE_FILE):
        return base
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if "known_chats" not in data:
                data["known_chats"] = []
            return {**base, **data}
        except Exception:
            return base

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def parse_chat_ids():
    ids = []
    if TELEGRAM_CHAT_IDS:
        ids += [x.strip() for x in TELEGRAM_CHAT_IDS.split(",") if x.strip()]
    if TELEGRAM_CHAT_ID:
        ids.append(TELEGRAM_CHAT_ID)
    # quitar duplicados preservando orden
    seen = set(); out = []
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    return out

def notify_telegram_one(chat_id: str, message: str):
    if not (TELEGRAM_TOKEN and chat_id):
        log(f"[INFO] Telegram no configurado para chat {chat_id}.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=15)
        log(f"[OK] Telegram enviado a {chat_id}")
    except Exception as e:
        log(f"[ERR] Telegram {chat_id}: {e}")

def notify_all(chat_ids, message: str):
    for cid in chat_ids:
        notify_telegram_one(cid, message)

def commit_changes():
    subprocess.run(["git","config","user.name","inap-bot"], check=True)
    subprocess.run(["git","config","user.email","bot@users.noreply.github.com"], check=True)
    subprocess.run(["git","add", STATE_FILE, LOG_FILE], check=True)
    diff = subprocess.run(["git","diff","--cached","--quiet"])
    if diff.returncode != 0:
        subprocess.run(["git","commit","-m","update state/log"], check=True)
        return True
    return False

# ========= Main =========
def main():
    log(f"Inicio run | URL={URL} | MODE={MODE} | CSS_SELECTOR='{CSS_SELECTOR or '(none)'}'")
    html = fetch_html(URL)
    snap = extract_links_snapshot(html) if MODE == "links" else extract_summary(html)
    h    = sha256(snap + SNAPSHOT_SALT)

    state = load_state()
    log(f"Hash actual={h} | salt={'(set)' if SNAPSHOT_SALT else '(empty)'}")

    # 1) Bienvenida a chats nuevos (cuando añadas IDs o el chico pulse START y lo metas)
    incoming  = parse_chat_ids()
    new_chats = [c for c in incoming if c not in state["known_chats"]]
    if new_chats:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        notify_all(new_chats,
            "✅ Bot activado.\n"
            "A partir de ahora recibirás un mensaje cuando cambie la página:\n"
            f"{URL}\n"
            f"🕒 Fecha de alta: {ts}"
        )
        state["known_chats"].extend(new_chats)
        # si es la primera vez absoluta, persistimos el hash también
        if state.get("hash") is None:
            state["hash"] = h
            state["last_changed"] = ts
        save_state(state)
        commit_changes()
        log(f"Bienvenida enviada a nuevos chats: {new_chats}")

    # 2) Primera vez absoluta sin hash (si no se cubrió arriba)
    if state.get("hash") is None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["hash"] = h
        state["last_changed"] = ts
        save_state(state)
        log("Estado inicial guardado (no hay notificación de cambio).")
        commit_changes()
        return

    # 3) Notificar cambios a todos los chats conocidos
    if h != state.get("hash"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log("Cambio detectado -> notifico por Telegram.")
        state["hash"] = h
        state["last_changed"] = ts
        save_state(state)
        notify_all(state["known_chats"],
            "🔔 Se ha detectado un cambio en la página vigilada.\n"
            f"👉 {URL}\n"
            f"🕒 {ts}"
        )
        commit_changes()
    else:
        log("Sin cambios.")

if __name__ == "__main__":
    main()
