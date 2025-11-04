import os, time, json, hashlib, re, sys, subprocess
import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://sede.inap.gob.es/secretaria-intervencion-acceso-libre-2023-2024"
STATE_FILE = "state_inap.json"

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN","")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

def fetch_html(url: str) -> str:
    r = requests.get(url, timeout=25, headers={"User-Agent":"INAP-monitor/1.0"})
    r.raise_for_status()
    return r.text

def extract_summary(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("article") or soup.find("main") or soup
    text = re.sub(r"\n{2,}", "\n", main.get_text(separator="\n")).strip()
    links = []
    for a in main.find_all("a", href=True):
        t = " ".join(a.get_text(" ", strip=True).split())
        if t and not t.lower().startswith(("escuchar","mapa web")):
            links.append(f"{t} -> {a['href']}")
    lines = [L for L in text.split("\n") if L.strip()]
    head = "\n".join(lines[:200])
    tail = "\n".join(links[:200])
    return f"TEXT:\n{head}\n\nLINKS:\n{tail}"

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"hash": None, "last_changed": None}
    with open(STATE_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE,"w",encoding="utf-8") as f:
        json.dump(state,f,ensure_ascii=False,indent=2)

def sha256(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def notify_telegram(message: str):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("[INFO] Telegram no configurado.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id":TELEGRAM_CHAT_ID,"text":message}, timeout=15)
        print("[OK] Telegram enviado.")
    except Exception as e:
        print("[ERR] Telegram:", e)

def commit_changes():
    # Commit del state_inap.json al repo para persistir estado
    subprocess.run(["git","config","user.name","inap-bot"], check=True)
    subprocess.run(["git","config","user.email","bot@users.noreply.github.com"], check=True)
    subprocess.run(["git","add",STATE_FILE], check=True)
    # Si no hay cambios, no hacer commit
    diff = subprocess.run(["git","diff","--cached","--quiet"])
    if diff.returncode != 0:
        subprocess.run(["git","commit","-m","update state_inap.json"], check=True)
        # El push lo hace el workflow con GITHUB_TOKEN
        return True
    return False

def main():
    html = fetch_html(URL)
    snap = extract_summary(html)
    h = sha256(snap)
    state = load_state()
    if h != state.get("hash"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["hash"] = h
        state["last_changed"] = ts
        save_state(state)
        excerpt = snap[:1500]
        msg = (
            f"🔔 INAP — Cambio detectado (Secretaría-Intervención OEP 2023/24)\n"
            f"URL: {URL}\n"
            f"Fecha: {ts}\n\n"
            f"Extracto:\n{excerpt}\n"
            f"\n(Estado guardado en {STATE_FILE})"
        )
        notify_telegram(msg)
        changed = commit_changes()
        print("[CHANGE] Detectado y notificado. Commit:", changed)
    else:
        print("[OK] Sin cambios.")

if __name__ == "__main__":
    main()
