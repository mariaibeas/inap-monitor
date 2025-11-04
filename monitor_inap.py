# monitor_inap.py
import os, json, re, subprocess
from datetime import datetime
import hashlib
import requests
from bs4 import BeautifulSoup

URL = "https://sede.inap.gob.es/secretaria-intervencion-acceso-libre-2023-2024"
STATE_FILE = "state_inap.json"

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN","")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

def fetch_html(url: str) -> str:
    r = requests.get(url, timeout=25, headers={"User-Agent":"INAP-monitor/1.0"})
    r.raise_for_status()
    return r.text

def extract_summary(html: str) -> str:
    """Snapshot estable del contenido principal para detectar cambios."""
    soup  = BeautifulSoup(html, "html.parser")
    main  = soup.find("article") or soup.find("main") or soup
    text  = re.sub(r"\n{2,}", "\n", main.get_text(separator="\n")).strip()
    lines = [L for L in text.split("\n") if L.strip()]
    head  = "\n".join(lines[:200])  # suficiente para detectar cambios
    return head

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"hash": None, "last_changed": None}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def notify_telegram(message: str):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("[INFO] Telegram no configurado.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)

def commit_changes():
    """Hace commit del state para persistir entre ejecuciones (lo empuja el workflow)."""
    subprocess.run(["git","config","user.name","inap-bot"], check=True)
    subprocess.run(["git","config","user.email","bot@users.noreply.github.com"], check=True)
    subprocess.run(["git","add", STATE_FILE], check=True)
    diff = subprocess.run(["git","diff","--cached","--quiet"])
    if diff.returncode != 0:
        subprocess.run(["git","commit","-m","update state_inap.json"], check=True)
        return True
    return False

def main():
    html = fetch_html(URL)
    snap = extract_summary(html)
    h    = sha256(snap)
    state = load_state()

    # --- PRIMERA EJECUCIÓN: NO NOTIFICAR ---
    if state.get("hash") is None:
        state["hash"] = h
        state["last_changed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
        commit_changes()
        print("[INIT] Estado inicial guardado. No se notifica.")
        return

    # --- CAMBIO DETECTADO ---
    if h != state.get("hash"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["hash"] = h
        state["last_changed"] = ts
        save_state(state)
        commit_changes()
        msg = (
            "🔔 INAP — Ha habido un cambio en la página de "
            "Secretaría-Intervención (OEP 2023/24).\n"
            f"👉 {URL}\n"
            f"🕒 {ts}"
        )
        notify_telegram(msg)
        print("[CHANGE] Detectado y notificado.")
    else:
        print("[OK] Sin cambios.")

if __name__ == "__main__":
    main()
