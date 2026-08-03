# EngLearning v2

Oddelený projekt od **v1** (`kotlas6667/English_learning_with_AI`).

Voice-based English tutor (CEFR A2–B2) — FastAPI + web UI v Dockeri (HAOS ako host).

## Čo je nové vo v2

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

## Deploy na HAOS (vedľa v1)

Odporúčané cesty **oddelené od v1**:

| | v1 | v2 |
|---|---|---|
| kód | `/share/English_learning_with_AI` | `/share/English_learning_with_AI_v2` |
| data | `.../English_learning_with_AI/data` | `.../English_learning_with_AI_v2/data` |
| kontajner | `englearning` | `englearning-v2` |
| port | `8080` | `8081` (alebo iný voľný) |

```bash
cd /tmp
curl -fsSL -o haos-full-deploy.sh \
  "https://raw.githubusercontent.com/kotlas6667/English_learning_with_AI_v2/master/scripts/haos-full-deploy.sh"
chmod +x haos-full-deploy.sh
bash ./haos-full-deploy.sh
```

Skript defaultne sťahuje **tento** repo (`master`) do `/share/English_learning_with_AI_v2` a spustí kontajner `englearning-v2` na porte **8081**.

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

## V1 vs V2

- **v1** ostáva v `https://github.com/kotlas6667/English_learning_with_AI` (bez zmien tohto oddelenia).
- **v2** je tento repozitár — ďalší vývoj ide sem.
