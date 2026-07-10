# monitor_inap.py
import os, json, re, subprocess
from datetime import datetime
import hashlib
import requests
from bs4 import BeautifulSoup

URL = "https://sede.inap.gob.es/es/procedimientos-y-servicios/seleccion/escala-de-funcionarios-de-administracion-local-con-habilitacion-de-caracter-nacional/procesos-selectivos-vigentes/secretaria-categoria-de-entrada-acceso-libre-convocatoria-extraordinaria-oep-2023"
#URL = "https://sede.inap.gob.es/secretaria-intervencion-acceso-libre-2023-2024"
#URL = "http://smarlexgames.es/prueba/index.html"
STATE_FILE = "state_inap.json"
LOG_FILE   = "hashes.log"

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN","")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

# Para pruebas controladas: cambiar este secret hace que cambie el hash
SNAPSHOT_SALT = os.getenv("SNAPSHOT_SALT","")

def log(line: str):
    line2 = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {line}"
    print(line2)  # se verá en los logs de GitHub Actions
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line2 + "\n")
    except Exception:
        pass

def fetch_html(url: str):
    import time

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; INAP-monitor/1.0; +https://github.com/mariaibeas/inap-monitor)"
    }

    last_error = None

    for intento in range(1, 4):
        try:
            log(f"Intento {intento}/3 descargando página...")
            r = requests.get(url, timeout=45, headers=headers)
            r.raise_for_status()
            return r.text

        except requests.exceptions.RequestException as e:
            last_error = e
            log(f"[WARN] Error descargando página en intento {intento}/3: {e}")

            if intento < 3:
                time.sleep(10)

    log(f"[ERROR] No se pudo descargar la página tras 3 intentos: {last_error}")
    return None

def extract_summary(html: str) -> str:
    soup  = BeautifulSoup(html, "html.parser")
    main  = soup.find("article") or soup.find("main") or soup
    text  = re.sub(r"\n{2,}", "\n", main.get_text(separator="\n")).strip()
    lines = [L for L in text.split("\n") if L.strip()]
    head  = "\n".join(lines[:200])  # snapshot estable
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
        log("[INFO] Telegram no configurado.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)

def commit_changes():
    subprocess.run(["git","config","user.name","inap-bot"], check=True)
    subprocess.run(["git","config","user.email","bot@users.noreply.github.com"], check=True)
    subprocess.run(["git","add", STATE_FILE, LOG_FILE], check=True)
    diff = subprocess.run(["git","diff","--cached","--quiet"])
    if diff.returncode != 0:
        subprocess.run(["git","commit","-m","update state/log"], check=True)
        return True
    return False

def main():
    log(f"Inicio run | URL={URL}")
    html = fetch_html(URL)

    if html is None:
        log("[INFO] No se actualiza estado porque no se ha podido leer la web.")
        commit_changes()
        return

    snap = extract_summary(html)

    # Hash incluyendo sal (si existe) para pruebas
    h    = sha256(snap + SNAPSHOT_SALT)
    state = load_state()
    log(f"Hash actual={h} | salt={'(set)' if SNAPSHOT_SALT else '(empty)'}")

    # PRIMERA VEZ: avisito de “bot activado”, sin “cambio”
    if state.get("hash") is None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["hash"] = h
        state["last_changed"] = ts
        save_state(state)
        log("Estado inicial guardado (no hay notificación de cambio).")
        notify_telegram(
            "✅ Bot activado.\n"
            "A partir de ahora recibirás un mensaje cuando cambie la página:\n"
            f"{URL}\n"
            f"🕒 {ts}"
        )
        commit_changes()
        return

    # CAMBIO
    if h != state.get("hash"):
        #ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        #log("Cambio detectado -> notifico por Telegram.")
        #state["hash"] = h
        #state["last_changed"] = ts
        #save_state(state)
        #notify_telegram(
         #   "🔔 INAP — Ha habido un cambio en la página.\n"
          #  f"👉 {URL}\n"
           # f"🕒 {ts}"
        #)
        #commit_changes()
    else:
        log("Sin cambios.")

if __name__ == "__main__":
    main()

