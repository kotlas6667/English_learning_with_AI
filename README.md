# EngLearning v2

Voice-based English tutor (CEFR A2–B2) — FastAPI + web UI v Dockeri (HAOS ako host).

Toto je **aktuálna produkčná vetva**. Starý projekt `English_learning_with_AI` (v1) je nahradený týmto repom.

## Čo je vo v2

- Domov + bottom navigácia (Domov / Cvičenie / Pokrok / Profil)
- Denný cieľ (minúty) + cieľ učenia (cestovanie / práca / bežný život)
- Knižnica scenárov + denný mix (~8 otázok)
- Turn feedback: Povedal si / Lepšie / Tip / Skóre (bez dopĺňania kontextu do STT)
- Pri neistote STT: zopakovať odpoveď; po 2× zlyhaní zápis do progresu
- Skill skóre, recap lekcie, PWA

## Quick start (Docker)

```bash
cp .env.example .env
# aspoň jeden LLM kľúč; OPENAI_API_KEY aj pre Whisper STT

docker compose up -d --build
```

UI: `http://<IP>:8080`

## Deploy na HAOS (nahradí v1)

Skript **zastaví starý kontajner `englearning`**, nahradí kód v `/share/English_learning_with_AI` a spustí v2 na porte **8080**.  
Volume s dátami (`settings`, štatistiky, learning store) **ostáva**.

```bash
cd /tmp
curl -fsSL -o haos-full-deploy.sh \
  "https://raw.githubusercontent.com/kotlas6667/English_learning_with_AI_v2/main/scripts/haos-full-deploy.sh"
chmod +x haos-full-deploy.sh
bash ./haos-full-deploy.sh
```

Po nasadení: **Ctrl+Shift+R** v prehliadači.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8080
```

## Data (`./data`)

Per-user: settings, stats, learning store, profil. Pri Dockeri mapuj volume — rebuild kódu dáta nemení.
