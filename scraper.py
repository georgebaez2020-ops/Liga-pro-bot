import os, requests, json

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
STATE_FILE = "last.json"

def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/ecu_primera_a/scoreboard"

def main():
    r = requests.get(URL, timeout=20).json()
    state = load_state()
    new_state = {}

    for ev in r.get("events", []):
        comp = ev["competitions"][0]
        home = comp["competitors"][0]
        away = comp["competitors"][1]
        if home["homeAway"] != "home":
            home, away = away, home

        match_id = ev["id"]
        home_name = home["team"]["shortDisplayName"]
        away_name = away["team"]["shortDisplayName"]
        home_goals = int(home.get("score", 0))
        away_goals = int(away.get("score", 0))
        status = comp["status"]["type"]["state"]
        clock = comp["status"].get("displayClock", "")
        detail = comp["status"]["type"].get("detail", "")

        key = f"{home_goals}-{away_goals}"
        new_state[match_id] = key

        if status == "in" and state.get(match_id) != key:
            if not (state.get(match_id) is None and key == "0-0"):
                send(f"⚽ <b>GOOOL Liga Pro!</b>\n\n{home_name} {home_goals} - {away_goals} {away_name}\n🕐 {clock}' - {detail}")

    save_state(new_state)
    print(f"Revisados {len(new_state)} partidos")

if __name__ == "__main__":
    main()
