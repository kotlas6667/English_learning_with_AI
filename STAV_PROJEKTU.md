# EngLearning — stav projektu (handoff pre nový chat)

**Účel tohto súboru:** rýchly kontext bez prechádzania celého kódu.  
**Jazyk komunikácie s používateľom:** slovenčina.  
**Workspace:** `C:\PROGRAMING_SYNCHRO_DISK\PROGRAMOVANIE\11.PYTHON\EngLearning_HAOS`

Aktualizované: 2026-07-30.

---

## Čo to je

Hlasová webová app na výučbu angličtiny (A2–B2).

- **Backend:** FastAPI (`app/main.py`)
- **Frontend:** `app/static/` (`index.html`, `app.js`, `styles.css`)
- **Deploy:** Docker na HAOS (HAOS = len hostiteľ kontajnera; **žiadna funkčná väzba na Home Assistant**)
- **LLM** = len text (OpenAI / Gemini / Mistral)
- **TTS** = Edge-TTS (bez kľúča) alebo ElevenLabs
- **STT** = Whisper (potrebuje `OPENAI_API_KEY`)

Lokálny beh typicky:

```bash
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

UI: `http://127.0.0.1:8080`  
Docker: `docker compose up -d --build` → port `8080`, volume `./data:/app/data`

---

## Režimy lekcie

| Režim | UI | Správanie |
|-------|----|-----------|
| **Konverzácia** | chat + mikrofón | Roleplay podľa témy/podtémy; `[[unknown:…\|sk]]`, `[[ask]]` |
| **Čítanie + porozumenie** | text + tlačidlá | Pozri tok nižšie |
| **Voľná debata** | chat + mikrofón | AI navrhne tému z profilu/histórie/learning store; užívateľ môže hovoriť o čomkoľvek |

**Režim** je mimo panela Nastavenia (vždy viditeľný select).  
V nastaveniach: úroveň, téma, podtéma, min. otázky, **počet viet** (čítanie), LLM, TTS, hlas, rýchlosť.

### Tok čítania

1. **Vygeneruj text** → `POST /api/session/start` (`mode=reading`), TTS sa neprehráva automaticky  
2. **Prehrať vzor** (voliteľné) → `/api/speak`  
3. **Štart čítania** → `/api/reading/begin` + nahrávanie  
4. **Stop** → `/api/reading/evaluate` → chyby v texte + zoznam zle prečítaných slov  
5. **Vysvetlenie textu** → `/api/reading/explain` (AI hodnotí, či správne vysvetlil obsah)  
6. **Debata o texte** → `/api/reading/start-debate` + `/api/reading/debate` (otázky z textu)

### Voľná debata

- Tlačidlo **Voľná debata** alebo režim `free_debate`
- Tag `[[topic:…]]` = návrh témy
- Tag `[[learn:…]]` = nové fakty o používateľovi → sekcia **About the learner** v `profile.md`
- Tag `[[unknown:…\|sk]]` → learning store (vocabulary)

---

## Autentifikácia a práva

### Prihlásenie (úvodná obrazovka)

- Výber používateľa z **selectu** + heslo  
- Alebo **Vytvoriť nový účet** (meno + heslo + úroveň) → `/api/auth/register`  
- Session token v `localStorage` (`englearning_token`), header `X-Session-Token`  
- Zoznam na login: `GET /api/auth/users` (bez hesiel)

### Administrator

- Účet **Administrator** sa vytvorí automaticky (`UserManager._ensure_administrator`)
- Heslo zatiaľ: **`admin`**
- `role: "admin"` — najvyššie práva:
  - vytvárať používateľov
  - spravovať cudzie účty (select „Spravovať účet“)
  - mazať cudzie účty (s admin heslom)
  - vidieť všetkých v `GET /api/users`
- Bežný user spravuje len seba
- Posledného admina nejde zmazať; meno `Administrator` sa nedá premenovať

### Heslá

- PBKDF2 (`app/auth.py`), session store `data/sessions.json`
- Legacy účet bez `password_hash`: prvé prihlásenie nastaví heslo
- Zmazanie účtu vyžaduje heslo (vlastné alebo admin heslo pri mazaní cudzieho)

---

## Dáta (Markdown, per user)

```
data/
  users.json              # index používateľov + active_user_id
  sessions.json           # session tokeny
  users/<id>/
    profile.md            # profil pre AI (Weak areas, About the learner, …)
    history.md            # história lekcií
    vocabulary.md
    reading_errors.md
    comprehension.md
    question_gaps.md
    topics.json           # témy/podtémy daného používateľa
    settings.json         # nastavenia lekcie (UI) — prežijú refresh aj rebuild
```

**Poznámka Docker:** `DATA_DIR` v `.env` často `/app/data` (volume). Lokálne môže byť `data/`. Pri debugovaní vždy skontroluj `get_settings().data_dir`.

**HAOS deploy:** `docker cp` je dočasné. Trvalo: `scripts/haos-full-deploy.sh` (sync kódu do `/share`, `docker build`, volume na host `.../data`). Nastavenia = JSON vo volume, **SQLite netreba**.

---

## Kľúčové súbory

| Súbor | Úloha |
|-------|--------|
| `app/main.py` | FastAPI routes, auth, session start, reading/conversation endpoints |
| `app/users.py` | UserManager, role admin/user, profil, história |
| `app/auth.py` | hash hesla, SessionStore |
| `app/modes/conversation.py` | konverzácia + free_debate |
| `app/modes/reading.py` | generovanie textu, evaluate, explain, debate |
| `app/modes/comprehension.py` | hodnotenie odpovedí v debate |
| `app/prompts.py` | systémové / generation / judge prompty |
| `app/learning_store.py` | MD store + parsovanie `[[unknown:]]`, `[[learn:]]`, `[[topic:]]` |
| `app/user_topics.py` | témy per user + detekcia duplicít |
| `app/user_settings.py` | `settings.json` — preferencie lekcie |
| `app/voice/` | Edge / ElevenLabs TTS, Whisper STT, rýchlosť |
| `app/static/*` | UI |
| `scripts/haos-full-deploy.sh` | plný rebuild na HAOS so zachovaním data/ |
| `docker-compose.yml`, `Dockerfile`, `.env.example` | deploy |

---

## API (dôležité)

### Auth
- `GET /api/auth/users` — login directory  
- `POST /api/auth/login` — `{user_id, password}` alebo `{name, password}`  
- `POST /api/auth/register` — verejná registrácia + token  
- `POST /api/auth/logout`, `GET /api/auth/me`

### Lekcie
- `POST /api/session/start` — `mode`: `conversation` \| `reading` \| `free_debate`  
  Body okrem iného: `sentence_count`, `min_questions`, `user_id`, TTS/LLM polia  
- Conversation: `/api/conversation/turn`, `/api/conversation/utterance`  
- Reading: `/begin`, `/evaluate`, `/explain`, `/start-debate`, `/debate` (+ aliasy comprehension)

### Users / topics / learning
- CRUD users s auth; admin môže `user_id` ≠ self  
- Topics: check / add topic / add subtopic (duplicity lokálne + LLM)  
- `GET /api/learning?user_id=`

Väčšina endpointov vyžaduje session; výnimky: health, auth users/login/register, static, index.

---

## UI poznámky

- Auth gate + modály majú vlastný dizajn (pruh, tiene, animácie)  
- Select používateľov: **nepoužívať `appearance: none`** na Windowse (inak čierny prázdny dropdown)  
- Cache-bust: `styles.css?v=…`, `app.js?v=…` v `index.html`  
- Admin badge + „Nový používateľ“ + „Spravovať účet“ len pre admina  
- Static assets: `app/static/`

---

## Čo ešte nie je / zámery

- Learning store je Markdown; neskôr možné DB  
- Heslo admina `admin` je dočasné (produkčne zmeniť)  
- README.md je čiastočne zastaraný (ešte popisuje starší flow čítania a users bez auth) — **tento súbor je aktuálnejší**

---

## Rýchly checklist pre nového agenta

1. Čítaj tento súbor najprv.  
2. Potom podľa úlohy otvor relevantný súbor z tabuľky vyššie.  
3. Komunikuj s používateľom **po slovensky**.  
4. Nemeň git config; commity len na vyžiadanie.  
5. Pri UI drž existujúci vizuálny jazyk (Fraunces + Source Sans, zelená `#1f6f5b`, papierové pozadie).  
6. Po zmene static súborov bumpni `?v=` v `index.html`.
