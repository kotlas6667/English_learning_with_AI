# English Learning with AI

Voice-based English tutor (CEFR A2–B2). Runs as FastAPI + web UI in Docker — e.g. on **HAOS** only as a container host (Home Assistant has no role inside the app).

## Features

- **Conversation** — immersive role-play by topic (you are in the situation; AI is the other side, e.g. IT support)
- **Free debate** — open chat guided by profile/history; push-to-talk microphone (hold to speak)
- **Reading** — AI generates a text, you read aloud, errors are highlighted; then explanation / debate
- **LLM** — OpenAI / Gemini / Mistral (model selectable in the UI)
- **TTS** — Edge-TTS (no API key) or ElevenLabs; speech rate in settings
- **STT** — Whisper (requires `OPENAI_API_KEY`)
- **Learning store** — vocabulary / reading errors, spaced repetition, practice mode
- **Users** — password accounts, profile + history; deleting an account removes all related data

## Quick start (Docker)

```bash
cp .env.example .env
# add at least one LLM key; OPENAI_API_KEY is also needed for Whisper STT

docker compose up -d --build
```

UI:
- LAN: `http://<IP>:8080` (e.g. `http://192.168.1.109:8080`)
- Tailscale HTTP: `http://100.82.143.35:8080/`
- Tailscale HTTPS (odporúčané, mikrofón): `https://tomaspi.tail7d1cba.ts.net:8443/`

### Required in `.env`

- at least one of: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`
- `OPENAI_API_KEY` is also required for Whisper STT

### TTS

- default `TTS_PROVIDER=edge` (Microsoft neural voices, no key)
- ElevenLabs: `TTS_PROVIDER=elevenlabs` + `ELEVENLABS_API_KEY`

## Local run (without Docker)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8080
```

## Deploy on HAOS

1. Copy the project (git clone / Samba / SCP) onto HAOS.
2. Create `.env` with API keys (do not commit it).
3. `docker compose up -d --build`
4. Open on your LAN: `http://192.168.1.109:8080`
5. Or via Tailscale HTTPS (odporúčané): `https://tomaspi.tail7d1cba.ts.net:8443/`
6. Or via Tailscale HTTP: `http://100.82.143.35:8080/`

### Access via Tailscale

**HTTPS (odporúčané — mikrofón v prehliadači):**

`https://tomaspi.tail7d1cba.ts.net:8443/`

- Client must be on the same Tailscale tailnet.
- Uses Tailscale Serve (tailnet only, not Funnel / public internet).
- Proxies to host EngLearning on `http://192.168.1.109:8080`.

**HTTP (bez TLS, mikrofón často nefunguje):**

`http://100.82.143.35:8080/`

#### How Serve was enabled on HAOS

In Tailscale admin ([DNS](https://login.tailscale.com/admin/dns)): enable **MagicDNS** and **HTTPS Certificates**.

On HAOS, `tailscale` is not in the host SSH PATH — enter the add-on container first:

```bash
docker exec -it $(docker ps -q -f name=tailscale) /bin/bash
/opt/tailscale serve --bg --https=8443 --set-path=/ http://192.168.1.109:8080
/opt/tailscale serve status
```

If Share Home Assistant already uses HTTPS port `443`, EngLearning must use another port (`8443`). Status should show:

```text
https://tomaspi.tail7d1cba.ts.net:8443 (tailnet only)
|-- / proxy http://192.168.1.109:8080
```

Disable with: `/opt/tailscale serve --https=8443 off`

### Microphone note

Browsers often require **HTTPS** or `localhost` for the microphone. Prefer Tailscale Serve HTTPS above; plain LAN / Tailscale HTTP may force text input only.

## Data (`./data`)

- `users.json` — user index
- `users/<id>/` — `profile.md`, `history.md`, `vocabulary.md`, `reading_errors.md`, `comprehension.md`, `topics.json`
- `sessions.json` — auth session tokens

Volume in `docker-compose.yml`: `./data:/app/data`.

## API (short)

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | API key status |
| `GET /api/meta` | topics, levels, LLM, TTS |
| `POST /api/session/start` | start conversation / reading / free_debate |
| `POST /api/conversation/turn` | text turn |
| `POST /api/conversation/utterance` | voice turn |
| `POST /api/reading/evaluate` | reading evaluation |
| `GET /api/learning` | learning store |

## Privacy

This repository is **private**. Do **not** commit `.env` or personal `data/users/*` (`.env` and user data paths are in `.gitignore`).
