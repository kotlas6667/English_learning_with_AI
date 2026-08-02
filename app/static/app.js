(() => {
  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "englearning_token";
  const SETTINGS_KEY = "englearning_lesson_settings";
  const MIC_KEY = "englearning_mic_permission";
  const SETTINGS_FIELDS = [
    "mode",
    "level",
    "topic",
    "subtopic",
    "minQuestions",
    "sentenceCount",
    "llm",
    "llmModel",
    "ttsProvider",
    "voice",
    "speechRate",
    "silenceTimeout",
  ];

  const state = {
    meta: null,
    sessionId: null,
    mode: null,
    voiceId: null,
    ttsProvider: "edge",
    userId: null,
    userName: null,
    isAdmin: false,
    managedUserId: null,
    token: localStorage.getItem(TOKEN_KEY) || null,
    lastStartPayload: null,
    passageText: "",
    passageAudio: null,
    mediaRecorder: null,
    chunks: [],
    readingPhase: null,
    authMode: "login",
    isPractice: false,
    startInFlight: false,
    currentAudio: null,
    currentAudioSource: null,
    audioUnlocked: false,
    audioContext: null,
    audioEl: null,
    audioKeepalive: null,
    micPermission: (() => {
      try {
        const v = localStorage.getItem("englearning_mic_permission");
        return v === "granted" || v === "denied" ? v : null;
      } catch (_) {
        return null;
      }
    })(),
    ptt: null,
  };

  function setStatus(msg, isError = false) {
    updateActivityBar(msg || "", isError);
  }

  function activityKindFromMessage(msg, isError) {
    const t = String(msg || "").toLowerCase();
    if (isError) return "error";
    if (!t.trim()) return "idle";
    if (t.includes("prerušen") || t.includes("pocujem") || t.includes("počujem") || t.includes("hovor ďalej") || t.includes("hovor dalej")) {
      return "hearing";
    }
    // Countdown po pustení holdu — nie ready text s „odošlem“.
    if (t.startsWith("pauza") || /\bpauza[…. ]/.test(t)) return "silence";
    if (t.includes("nahrávam") || t.includes("pokračujem v nahrávaní")) return "listening";
    // Pripravený PTT stav (toggle).
    if (t.includes("ťukni na mikrofón") || (t.includes("mikrofón") && t.includes("odošle"))) return "idle";
    if (t.includes("drž mikrofón") && t.includes("po pustení")) return "idle";
    if (
      t.includes("počúvam") || t.includes("pocuvam") || t.includes("počúvanie") || t.includes("live")
    ) {
      return "listening";
    }
    if (
      t.includes("spracúvam") || t.includes("generujem") || t.includes("pripravujem")
      || t.includes("čakám") || t.includes("cakam") || t.includes("porovnávam")
      || t.includes("hodnotím") || t.includes("spúšťam")
    ) {
      return "processing";
    }
    return "info";
  }

  function activityLabelFor(kind) {
    const map = {
      idle: "Pripravené",
      listening: "Počúvam",
      hearing: "Hovoríš",
      silence: "Pauza",
      speaking: "AI hovorí",
      processing: "Spracúvam",
      info: "Info",
      error: "Chyba",
    };
    return map[kind] || "Stav";
  }

  function updateActivityBar(msg, isError = false) {
    const bar = $("activityBar");
    const label = $("activityLabel");
    const text = $("activityText");
    if (!bar || !label || !text) return;
    const kind = activityKindFromMessage(msg, isError);
    const visible = !!String(msg || "").trim();
    const nextText = msg || "—";
    // Neprekresľuj DOM, ak sa nič nezmenilo (inak banner „bliká“).
    if (
      bar.hidden === !visible
      && bar.dataset.state === kind
      && text.textContent === nextText
      && label.textContent === activityLabelFor(kind)
    ) {
      return;
    }
    bar.hidden = !visible;
    bar.dataset.state = kind;
    label.textContent = activityLabelFor(kind);
    text.textContent = nextText;
    document.body.classList.toggle("has-activity-bar", visible);
  }

  function authHeaders(extra = {}) {
    const headers = { ...extra };
    if (state.token) headers["X-Session-Token"] = state.token;
    return headers;
  }

  function silenceTimeoutSec() {
    const n = Number($("silenceTimeout")?.value || state.meta?.default_silence_timeout || 3);
    return Math.max(1, Math.min(10, n || 3));
  }

  function currentSpeechRate() {
    const raw = $("speechRate")?.value;
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) return 1;
    return Math.max(0.7, Math.min(1.5, n));
  }

  function stopCurrentAudio() {
    const source = state.currentAudioSource;
    if (source) {
      try {
        source.stop(0);
      } catch (_) {}
      state.currentAudioSource = null;
    }
    const audio = state.currentAudio;
    if (!audio) return;
    try {
      audio.pause();
      const src = audio.src;
      if (audio !== state.audioEl) {
        audio.removeAttribute("src");
        audio.load();
      }
      if (src && src.startsWith("blob:")) URL.revokeObjectURL(src);
    } catch (_) {}
    state.currentAudio = null;
  }

  function base64ToUint8Array(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function base64ToMp3ObjectUrl(b64) {
    const bytes = base64ToUint8Array(b64);
    const blob = new Blob([bytes], { type: "audio/mpeg" });
    return URL.createObjectURL(blob);
  }

  async function ensureAudioContext() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!state.audioContext) state.audioContext = new Ctx();
    if (state.audioContext.state === "suspended") {
      try {
        await state.audioContext.resume();
      } catch (_) {}
    }
    return state.audioContext;
  }

  async function startAudioKeepalive() {
    // Keepalive loop removed — iOS Safari leakoval RAM pri Audio.loop = true.
  }

  function stopAudioKeepalive() {
    const warm = state.audioKeepalive;
    if (!warm) return;
    try {
      warm.pause();
      warm.removeAttribute("src");
      warm.load();
    } catch (_) {}
    state.audioKeepalive = null;
  }

  async function unlockAudioPlayback() {
    try {
      await Promise.race([
        ensureAudioContext(),
        new Promise((resolve) => setTimeout(resolve, 400)),
      ]);
      if (!state.audioEl) {
        state.audioEl = new Audio();
        state.audioEl.preload = "auto";
        state.audioEl.setAttribute("playsinline", "true");
        state.audioEl.playsInline = true;
      }
      // Jednorazový silent play (BEZ loop) — odomkne autoplay, nežíra RAM.
      const warm = state.audioEl;
      const prevVol = warm.volume;
      warm.loop = false;
      warm.volume = 0.01;
      warm.src =
        "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
      try {
        const playP = warm.play();
        if (playP && typeof playP.then === "function") {
          await Promise.race([
            playP,
            new Promise((resolve) => setTimeout(resolve, 400)),
          ]);
        }
        try {
          warm.pause();
        } catch (_) {}
      } catch (_) {}
      warm.volume = prevVol || 1;
      state.audioUnlocked = true;
    } catch (_) {
      // Best-effort; replay via 🔊 still works on tap.
    }
  }

  function pickRecorderMimeType() {
    const types = [
      "audio/mp4",
      "audio/aac",
      "audio/webm;codecs=opus",
      "audio/webm",
    ];
    for (const t of types) {
      try {
        if (window.MediaRecorder?.isTypeSupported?.(t)) return t;
      } catch (_) {}
    }
    return "";
  }

  function recorderBlobType(mime) {
    if (mime && mime.startsWith("audio/mp4")) return "audio/mp4";
    if (mime && mime.startsWith("audio/aac")) return "audio/aac";
    return "audio/webm";
  }

  async function playViaWebAudio(b64) {
    const ctx = await ensureAudioContext();
    if (!ctx) throw new Error("AudioContext unavailable");
    const bytes = base64ToUint8Array(b64);
    // decodeAudioData si ArrayBuffer „odznačí“ — treba kópiu.
    const copy = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const audioBuffer = await ctx.decodeAudioData(copy);
    stopCurrentAudio();
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    try {
      source.playbackRate.value = currentSpeechRate();
    } catch (_) {}
    source.connect(ctx.destination);
    state.currentAudioSource = source;
    return new Promise((resolve, reject) => {
      source.onended = () => {
        if (state.currentAudioSource === source) state.currentAudioSource = null;
        resolve();
      };
      try {
        source.start(0);
      } catch (err) {
        state.currentAudioSource = null;
        reject(err);
      }
    });
  }

  async function playViaHtmlAudio(b64) {
    stopCurrentAudio();
    const url = base64ToMp3ObjectUrl(b64);
    const audio = state.audioEl || new Audio();
    state.audioEl = audio;
    audio.preload = "auto";
    audio.setAttribute("playsinline", "true");
    audio.playsInline = true;
    audio.src = url;
    audio.playbackRate = currentSpeechRate();
    audio.preservesPitch = true;
    state.currentAudio = audio;
    try {
      await audio.play();
      await new Promise((resolve) => {
        const finish = () => {
          audio.removeEventListener("ended", finish);
          audio.removeEventListener("error", finish);
          resolve();
        };
        audio.addEventListener("ended", finish);
        audio.addEventListener("error", finish);
      });
    } finally {
      if (state.currentAudio === audio) state.currentAudio = null;
      try {
        URL.revokeObjectURL(url);
      } catch (_) {}
    }
  }

  async function playBase64Mp3(b64) {
    if (!b64) return true;
    stopCurrentAudio();
    await ensureAudioContext();
    // 1) Web Audio — spoľahlivejšie po async na iOS
    try {
      await playViaWebAudio(b64);
      return true;
    } catch (_) {
      /* fallback */
    }
    // 2) HTMLAudioElement (odomknutý element)
    try {
      await playViaHtmlAudio(b64);
      return true;
    } catch (_) {
      setStatus("Zvuk zablokovaný prehliadačom — ťukni na 🔊 pri odpovedi AI.", true);
      return false;
    }
  }

  async function blobToBase64(blob) {
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = "";
    for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  async function synthesizeSpeechBase64(text) {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        text,
        tts_provider: $("ttsProvider")?.value || state.ttsProvider || "edge",
        voice_id: $("voice")?.value || state.voiceId || null,
        speech_rate: currentSpeechRate(),
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || res.statusText || "TTS zlyhalo");
    }
    return blobToBase64(await res.blob());
  }

  async function replayAssistantSpeech(text, cachedB64) {
    const b64 = cachedB64 || (await synthesizeSpeechBase64(text));
    await playBase64Mp3(b64);
    return b64;
  }

  async function api(path, options = {}) {
    const opts = { ...options };
    opts.headers = authHeaders(opts.headers || {});
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      clearSession();
      showAuthGate();
    }
    if (!res.ok) {
      const detail = data.detail;
      let msg = res.statusText || "Request failed";
      if (typeof detail === "string") msg = detail;
      else if (detail && typeof detail === "object") {
        msg = detail.message || JSON.stringify(detail);
        const err = new Error(msg);
        err.detail = detail;
        err.status = res.status;
        throw err;
      }
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function clearSession() {
    state.token = null;
    state.userId = null;
    state.userName = null;
    state.isAdmin = false;
    state.managedUserId = null;
    localStorage.removeItem(TOKEN_KEY);
  }

  function effectiveUserId() {
    if (state.isAdmin && state.managedUserId) return state.managedUserId;
    return state.userId;
  }

  function saveToken(token, user) {
    state.token = token;
    state.userId = user.id;
    state.userName = user.name;
    state.isAdmin = !!(user.is_admin || user.role === "admin");
    state.managedUserId = user.id;
    localStorage.setItem(TOKEN_KEY, token);
    $("currentUserName").textContent = user.name;
    $("adminBadge").classList.toggle("hidden", !state.isAdmin);
    $("addUserBtn").classList.toggle("hidden", !state.isAdmin);
    $("manageUserWrap").classList.toggle("hidden", !state.isAdmin);
  }

  function showAuthGate() {
    $("authGate").classList.remove("hidden");
    $("appMain").classList.add("hidden");
    loadLoginUsers().catch(() => {});
  }

  function showApp() {
    $("authGate").classList.add("hidden");
    $("appMain").classList.remove("hidden");
    $("currentUserName").textContent = state.userName || "—";
    $("adminBadge").classList.toggle("hidden", !state.isAdmin);
    $("addUserBtn").classList.toggle("hidden", !state.isAdmin);
    $("manageUserWrap").classList.toggle("hidden", !state.isAdmin);
  }

  function setAuthMode(mode) {
    state.authMode = mode;
    const isReg = mode === "register";
    $("authTitle").textContent = isReg ? "Nový účet" : "Prihlásenie";
    $("authHint").textContent = isReg
      ? "Zvoľ unikátne meno a heslo (min. 4 znaky). Heslo budeš potrebovať aj na zmazanie účtu."
      : "Vyber účet a zadaj heslo. Administrator má najvyššie práva (heslo: admin).";
    $("authSubmit").textContent = isReg ? "Vytvoriť a prihlásiť" : "Prihlásiť";
    $("authToggle").textContent = isReg ? "Už mám účet" : "Vytvoriť nový účet";
    $("authLoginFields").classList.toggle("hidden", isReg);
    $("authRegisterFields").classList.toggle("hidden", !isReg);
    $("authPassword").autocomplete = isReg ? "new-password" : "current-password";
    $("authError").hidden = true;
    if (!isReg) loadLoginUsers().catch(() => {});
  }

  async function loadLoginUsers() {
    const err = $("authError");
    const sel = $("authUserSelect");
    try {
      const res = await fetch("/api/auth/users");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof data.detail === "string" ? data.detail : "Nepodarilo sa načítať používateľov"
        );
      }
      const list = Array.isArray(data.users) ? data.users : [];
      sel.innerHTML = "";
      if (!list.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "(žiadni používatelia)";
        sel.appendChild(opt);
        err.textContent = "Zoznam účtov je prázdny. Vytvor nový účet.";
        err.hidden = false;
        return;
      }
      let adminId = null;
      for (const u of list) {
        const opt = document.createElement("option");
        opt.value = String(u.id || "");
        const name = String(u.name || u.id || "Používateľ");
        opt.textContent = u.is_admin || u.role === "admin" ? `${name} (admin)` : name;
        if (u.is_admin || u.role === "admin" || name.toLowerCase() === "administrator") {
          adminId = opt.value;
        }
        sel.appendChild(opt);
      }
      sel.value = adminId || list[0].id;
      if (!sel.value && sel.options[0]) sel.selectedIndex = 0;
      err.hidden = true;
    } catch (e) {
      sel.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(načítanie zlyhalo)";
      sel.appendChild(opt);
      err.textContent = e.message || "Nepodarilo sa načítať používateľov.";
      err.hidden = false;
    }
  }

  async function submitAuth() {
    const password = $("authPassword").value;
    const err = $("authError");
    err.hidden = true;
    if (!password || (state.authMode === "register" && password.length < 4)) {
      err.textContent = state.authMode === "register"
        ? "Heslo musí mať aspoň 4 znaky."
        : "Zadaj heslo.";
      err.hidden = false;
      return;
    }

    $("authSubmit").disabled = true;
    try {
      let data;
      if (state.authMode === "register") {
        const name = $("authName").value.trim();
        if (!name) {
          err.textContent = "Zadaj meno.";
          err.hidden = false;
          return;
        }
        data = await api("/api/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            password,
            preferred_level: $("authLevel").value || "A2",
          }),
        });
      } else {
        const userId = $("authUserSelect").value;
        if (!userId) {
          err.textContent = "Vyber používateľa.";
          err.hidden = false;
          return;
        }
        data = await api("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: userId, password }),
        });
      }
      saveToken(data.token, data.user);
      $("authPassword").value = "";
      $("authName").value = "";
      setAuthMode("login");
      showApp();
      await bootApp();
      // Prompt len ak ešte nebolo udelené (localStorage / Permissions API).
      if (state.micPermission !== "granted") {
        await ensureMicPermission();
      }
      unlockAudioPlayback().catch(() => {});
      if (state.micPermission === "granted") {
        setStatus(`Prihlásený: ${data.user.name}${data.user.is_admin ? " (Administrator)" : ""} · mikrofón OK`);
      } else {
        setStatus(`Prihlásený: ${data.user.name}${data.user.is_admin ? " (Administrator)" : ""}`);
      }
    } catch (e) {
      err.textContent = e.message || "Akcia zlyhala.";
      err.hidden = false;
    } finally {
      $("authSubmit").disabled = false;
    }
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch (_) {
      /* ignore */
    }
    clearSession();
    showAuthGate();
  }

  let settingsPersistTimer = null;
  let settingsPersistInFlight = null;

  function settingsStorageKey(userId) {
    const uid = userId || effectiveUserId() || state.userId;
    return uid ? `${SETTINGS_KEY}:${uid}` : SETTINGS_KEY;
  }

  function readLessonSettings(userId) {
    try {
      const key = settingsStorageKey(userId);
      let raw = localStorage.getItem(key);
      if (!raw && key !== SETTINGS_KEY) {
        const legacy = localStorage.getItem(SETTINGS_KEY);
        if (legacy) {
          localStorage.setItem(key, legacy);
          localStorage.removeItem(SETTINGS_KEY);
          raw = legacy;
        }
      }
      if (!raw) return {};
      const data = JSON.parse(raw);
      return data && typeof data === "object" ? data : {};
    } catch (_) {
      return {};
    }
  }

  function writeLessonSettingsLocal(data, userId) {
    const uid = userId || effectiveUserId() || state.userId;
    if (!uid || !data) return;
    try {
      localStorage.setItem(settingsStorageKey(uid), JSON.stringify(data));
    } catch (_) {}
  }

  function collectLessonSettings() {
    const data = {};
    for (const id of SETTINGS_FIELDS) {
      const el = $(id);
      if (el && el.value != null && el.value !== "") data[id] = el.value;
    }
    return data;
  }

  function saveLessonSettings() {
    const uid = effectiveUserId() || state.userId;
    if (!uid) return;
    const data = collectLessonSettings();
    writeLessonSettingsLocal(data, uid);
    schedulePersistLessonSettings(data, uid);
  }

  function schedulePersistLessonSettings(data, userId) {
    const uid = userId || effectiveUserId() || state.userId;
    if (!uid || !state.token) return;
    if (settingsPersistTimer) clearTimeout(settingsPersistTimer);
    settingsPersistTimer = setTimeout(() => {
      settingsPersistTimer = null;
      persistLessonSettings(data, uid).catch(() => {});
    }, 350);
  }

  async function persistLessonSettings(data, userId) {
    const uid = userId || effectiveUserId() || state.userId;
    if (!uid || !state.token) return null;
    const payload = data || collectLessonSettings();
    const req = api("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: uid, settings: payload }),
    });
    settingsPersistInFlight = req;
    try {
      const res = await req;
      const saved = res?.settings && typeof res.settings === "object" ? res.settings : payload;
      writeLessonSettingsLocal(saved, uid);
      if (state.meta) state.meta.lesson_settings = saved;
      return saved;
    } finally {
      if (settingsPersistInFlight === req) settingsPersistInFlight = null;
    }
  }

  function clearLessonSettings(userId) {
    if (!userId) return;
    try {
      localStorage.removeItem(settingsStorageKey(userId));
    } catch (_) {}
  }

  function mergeLessonSettingsPrefs(serverPrefs, localPrefs) {
    const server = serverPrefs && typeof serverPrefs === "object" ? serverPrefs : {};
    const local = localPrefs && typeof localPrefs === "object" ? localPrefs : {};
    if (Object.keys(server).length) return { ...local, ...server };
    return { ...local };
  }

  function applySelectValue(id, value) {
    const el = $(id);
    if (!el || value == null || value === "") return false;
    const want = String(value);
    const has = Array.from(el.options || []).some((o) => o.value === want);
    if (!has) return false;
    el.value = want;
    return el.value === want;
  }

  function applyLessonSettings(prefs) {
    const saved = prefs || readLessonSettings();
    if (!saved || !Object.keys(saved).length) return;

    applySelectValue("mode", saved.mode);
    applySelectValue("level", saved.level);
    applySelectValue("topic", saved.topic);
    syncSubtopics(saved.subtopic || null);
    applySelectValue("subtopic", saved.subtopic);
    applySelectValue("minQuestions", saved.minQuestions);
    applySelectValue("sentenceCount", saved.sentenceCount);
    applySelectValue("llm", saved.llm === "gpt" ? "openai" : saved.llm);
    syncLlmModels(saved.llmModel || null);
    applySelectValue("llmModel", saved.llmModel);
    applySelectValue("ttsProvider", saved.ttsProvider);
    applySelectValue("speechRate", saved.speechRate === "1.0" ? "1" : saved.speechRate);
    applySelectValue("silenceTimeout", saved.silenceTimeout);
    if (saved.ttsProvider) state.ttsProvider = saved.ttsProvider;
    syncModeUi();
  }

  function fillSelect(el, items, valueKey = "id", labelKey = "label") {
    el.innerHTML = "";
    for (const item of items) {
      const opt = document.createElement("option");
      if (typeof item === "string" || typeof item === "number") {
        opt.value = String(item);
        opt.textContent = String(item);
      } else {
        opt.value = String(item[valueKey]);
        opt.textContent = item[labelKey];
      }
      el.appendChild(opt);
    }
  }

  function syncSubtopics(preferSubId = null) {
    const topicId = $("topic").value;
    const topic = (state.meta?.topics || []).find((t) => t.id === topicId);
    fillSelect($("subtopic"), topic ? topic.subtopics : []);
    if (preferSubId) applySelectValue("subtopic", preferSubId);
  }

  function applyTopics(topics, preferTopicId = null, preferSubId = null) {
    state.meta = state.meta || {};
    state.meta.topics = topics;
    fillSelect($("topic"), topics);
    if (preferTopicId) $("topic").value = preferTopicId;
    if (!$("topic").value && topics[0]) $("topic").value = topics[0].id;
    syncSubtopics();
    if (preferSubId) $("subtopic").value = preferSubId;
  }

  function syncLlmModels(preferModel = null) {
    const provider = ($("llm")?.value || "openai") === "gpt" ? "openai" : ($("llm")?.value || "openai");
    const byProvider = state.meta?.llm_model_options || {};
    const defaults = state.meta?.default_llm_models || {};
    let options = byProvider[provider] || [];
    const fallback = defaults[provider] || state.meta?.default_llm_model || "";
    if (!options.length && fallback) {
      options = [{ id: fallback, label: fallback }];
    }
    fillSelect($("llmModel"), options);
    const want = preferModel || defaults[provider] || state.meta?.default_llm_model || options[0]?.id;
    if (want) $("llmModel").value = String(want);
    if (!$("llmModel").value && options[0]) $("llmModel").value = options[0].id;
  }

  function syncModeUi() {
    const mode = $("mode").value;
    const reading = mode === "reading";
    const free = mode === "free_debate";
    $("startBtn").textContent = reading
      ? "Vygeneruj text"
      : free
        ? "Štart voľnej debaty"
        : "Štart lekcie";
    $("restartBtn").textContent = reading ? "Vygeneruj znova" : "Reštart lekcie";
    $("restartBtn").classList.toggle("hidden", free);
    $("freeDebateBtn").classList.toggle("hidden", free);
    $("sentenceCountWrap").classList.toggle("hidden", !reading);
    $("silenceTimeout")?.closest("label")?.classList.toggle("dimmed", false);
    $("topic").closest("label")?.classList.toggle("dimmed", free);
    $("subtopic").closest("label")?.classList.toggle("dimmed", free);
  }

  function isPttMode() {
    return state.mode === "free_debate" || state.mode === "conversation";
  }

  function syncPttUi() {
    const pttOn = isPttMode();
    const btn = $("pttMicBtn");
    btn?.classList.toggle("hidden", !pttOn);
    $("recordConv")?.classList.toggle("hidden", pttOn);
    $("stopConv")?.classList.toggle("hidden", true);
    if (!btn) return;
    const holding = !!state.ptt?.holding;
    const busy = !!state.ptt?.processing || !!state.ptt?.finalizing;
    btn.classList.toggle("is-holding", holding);
    btn.classList.toggle("is-busy", busy && !holding);
    btn.setAttribute("aria-pressed", holding ? "true" : "false");
    const label = btn.querySelector(".ptt-label");
    if (label) {
      if (holding) label.textContent = "Stop / odošli";
      else if (state.ptt?.finalizing) label.textContent = "Odosielam…";
      else if (state.ptt?.processing) label.textContent = "Spracúvam…";
      else label.textContent = "Ťukni a hovor";
    }
  }

  async function loadManagedUsers() {
    if (!state.isAdmin) return;
    const data = await api("/api/users");
    fillSelect(
      $("manageUserSelect"),
      (data.users || []).map((u) => ({
        id: u.id,
        label: u.is_admin ? `${u.name} (admin)` : u.name,
      }))
    );
    $("manageUserSelect").value = state.managedUserId || state.userId;
  }

  async function loadMeta() {
    const uid = effectiveUserId() || "";
    const q = uid ? `?user_id=${encodeURIComponent(uid)}` : "";
    state.meta = await api(`/api/meta${q}`);
    fillSelect($("level"), state.meta.levels);
    $("level").value = state.meta.default_level || "A2";
    applyTopics(state.meta.topics || []);
    fillSelect($("minQuestions"), state.meta.min_questions_options || [20, 50, 80]);
    $("minQuestions").value = String(state.meta.default_min_questions || 20);
    fillSelect($("sentenceCount"), state.meta.sentence_count_options || [20, 50, 100]);
    $("sentenceCount").value = String(state.meta.default_sentence_count || 20);

    const providers = state.meta.llm_options?.length
      ? state.meta.llm_options
      : (state.meta.llm_providers || []).map((id) => ({ id, label: id }));
    fillSelect($("llm"), providers.length ? providers : [
      { id: "openai", label: "GPT (OpenAI)" },
      { id: "gemini", label: "Gemini" },
      { id: "mistral", label: "Mistral" },
    ]);
    if (state.meta.default_llm) {
      $("llm").value = state.meta.default_llm === "gpt" ? "openai" : state.meta.default_llm;
    }
    syncLlmModels(state.meta.default_llm_model);
    const ttsOptions = state.meta.tts_options?.length
      ? state.meta.tts_options
      : [
          { id: "edge", label: "Edge-TTS (Microsoft)" },
          { id: "elevenlabs", label: "ElevenLabs" },
        ];
    fillSelect($("ttsProvider"), ttsOptions);
    $("ttsProvider").value = state.meta.default_tts_provider || "edge";
    state.ttsProvider = $("ttsProvider").value;

    const rateOptions = (state.meta.speech_rate_options || []).map((o) => ({
      id: String(o.id ?? o.value),
      label: o.label,
    }));
    fillSelect(
      $("speechRate"),
      rateOptions.length
        ? rateOptions
        : [
            { id: "0.75", label: "Veľmi pomaly" },
            { id: "0.85", label: "Pomaly" },
            { id: "1", label: "Normálne" },
            { id: "1.15", label: "Rýchlo" },
            { id: "1.3", label: "Veľmi rýchlo" },
          ]
    );
    const defaultRate = state.meta.default_speech_rate ?? 1;
    const defaultId = String(defaultRate === 1 || defaultRate === 1.0 ? "1" : defaultRate);
    if (!applySelectValue("speechRate", defaultId)) {
      applySelectValue("speechRate", String(defaultRate));
    }
    if (!$("speechRate").value) $("speechRate").value = "1";

    const silenceOpts = (state.meta.silence_timeout_options || [2, 3, 4, 5]).map((s) => ({
      id: String(s),
      label: `${s} s`,
    }));
    fillSelect($("silenceTimeout"), silenceOpts);
    $("silenceTimeout").value = String(state.meta.default_silence_timeout || 3);
    if (!$("silenceTimeout").value) $("silenceTimeout").value = "3";

    const localPrefs = readLessonSettings(uid || undefined);
    const serverPrefs = state.meta.lesson_settings || {};
    const prefs = mergeLessonSettingsPrefs(serverPrefs, localPrefs);
    applyLessonSettings(prefs);
    if (Object.keys(prefs).length) {
      writeLessonSettingsLocal(prefs, uid || undefined);
      // Migrate browser-only prefs to server when file is still empty.
      if (!Object.keys(serverPrefs).length && Object.keys(localPrefs).length) {
        schedulePersistLessonSettings(prefs, uid || undefined);
      }
    }
    syncModeUi();
  }

  async function loadVoices() {
    const provider = $("ttsProvider")?.value || state.meta?.default_tts_provider || "edge";
    state.ttsProvider = provider;
    try {
      const data = await api(`/api/voices?provider=${encodeURIComponent(provider)}`);
      // Edge vie vrátiť veľa hlasov — v selecte drž len preferované + max ~40.
      let voices = data.voices || [];
      if (provider === "edge" && voices.length > 40) {
        voices = voices.slice(0, 40);
      }
      $("voice").innerHTML = "";
      const frag = document.createDocumentFragment();
      for (const v of voices) {
        const opt = document.createElement("option");
        opt.value = v.voice_id;
        opt.textContent = `${v.name}${v.likely_english ? "" : " (other)"}`;
        frag.appendChild(opt);
      }
      $("voice").appendChild(frag);
      const preferred =
        provider === "edge"
          ? state.meta.default_tts_provider === "edge"
            ? state.meta.default_voice_id
            : "en-US-JennyNeural"
          : state.meta.default_voice_id;
      if (preferred) $("voice").value = preferred;
      if (!$("voice").value && voices[0]) $("voice").value = voices[0].voice_id;
      const voicePrefs = mergeLessonSettingsPrefs(state.meta?.lesson_settings, readLessonSettings());
      applySelectValue("voice", voicePrefs.voice);
    } catch (err) {
      $("voice").innerHTML = "";
      const opt = document.createElement("option");
      opt.value = state.meta.default_voice_id || "";
      opt.textContent = provider === "elevenlabs"
        ? "Default (nastav ELEVENLABS_API_KEY)"
        : "Default Edge voice";
      $("voice").appendChild(opt);
      const voicePrefs = mergeLessonSettingsPrefs(state.meta?.lesson_settings, readLessonSettings());
      applySelectValue("voice", voicePrefs.voice);
      setStatus(err.message, true);
    }
  }

  function learningKindLabel(kind) {
    const map = {
      vocabulary: "slovíčko",
      reading_error: "čítanie",
      comprehension: "zlá odpoveď",
      question_gap: "nerozumel otázke",
    };
    return map[kind] || kind;
  }

  async function loadLearning() {
    const data = await api(`/api/learning?user_id=${encodeURIComponent(effectiveUserId() || "")}`);
    const dueWords = (data.due || []).map((d) => (typeof d === "string" ? d : d.word)).filter(Boolean);
    $("dueLine").textContent = dueWords.length
      ? `Na opakovanie (podľa významu): ${dueWords.join(", ")}`
      : "Žiadne due položky.";
    const body = $("learningBody");
    body.innerHTML = "";
    for (const item of data.items || []) {
      const sig = Number(item.significance || 5);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span class="sig-badge sig-${Math.min(10, Math.max(1, sig))}">${sig}/10</span></td>
        <td>${escapeHtml(learningKindLabel(item.kind))}</td>
        <td>${escapeHtml(item.word)}</td>
        <td>${escapeHtml(item.tip || item.translation_sk || "")}</td>
        <td>${escapeHtml(item.status)}</td>
        <td>${escapeHtml(item.next_review)}</td>
        <td class="learning-actions">
          <button type="button" class="ghost danger-text learning-delete" title="Vymazať položku">Vymazať</button>
        </td>`;
      const btn = tr.querySelector(".learning-delete");
      btn.addEventListener("click", () => {
        deleteLearningItem(item.kind, item.word).catch((e) => setStatus(e.message, true));
      });
      body.appendChild(tr);
    }
  }

  async function deleteLearningItem(kind, word) {
    if (!kind || !word) return;
    if (!confirm(`Naozaj vymazať „${word}“?`)) return;
    await api("/api/learning", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        word,
        user_id: effectiveUserId() || undefined,
      }),
    });
    setStatus(`Vymazané: ${word}`);
    await loadLearning();
  }

  function openPracticePanel() {
    $("practicePanel").classList.remove("hidden");
    $("practiceKind").focus();
  }

  function closePracticePanel() {
    $("practicePanel").classList.add("hidden");
  }

  async function startPractice() {
    const kind = $("practiceKind").value || "reading_error";
    setStatus(`Pripravujem precvičovanie (${kind})…`);
    try {
      await stopPtt();
      const data = await api("/api/learning/practice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind,
          user_id: effectiveUserId() || undefined,
          level: $("level").value,
          llm_provider: $("llm").value,
          llm_model: $("llmModel")?.value || null,
          tts_provider: $("ttsProvider").value,
          voice_id: $("voice").value || null,
          speech_rate: currentSpeechRate(),
          sentence_count: Number($("sentenceCount").value || 20),
        }),
      });
      closePracticePanel();
      state.sessionId = data.session_id;
      state.mode = "reading";
      state.isPractice = true;
      state.voiceId = $("voice").value || null;
      state.ttsProvider = $("ttsProvider").value;
      state.userId = data.user_id || effectiveUserId();
      state.passageText = data.text || "";
      state.passageAudio = null;
      $("mode").value = "reading";
      syncModeUi();
      $("chat").innerHTML = "";
      $("lessonTitle").textContent = data.title
        ? `Precvičovanie — ${data.title}`
        : "Precvičovanie";
      showPanels("reading", data.phase || "ready");
      $("passage").innerHTML = data.highlighted_html || escapeHtml(data.text || "");
      $("readFeedback").textContent = "";
      showWrongWords([]);
      setReadingActionPhase("ready");
      const targets = (data.practice_targets || []).join(", ");
      setStatus(
        `Precvičovanie (${kind}): ${data.practice_targets?.length || 0} položiek. `
        + `Text ~${data.sentence_count || $("sentenceCount").value} viet. `
        + (targets ? `Ciele: ${targets}` : "")
      );
      $("lesson").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function showPanels(mode, phase) {
    $("lesson").classList.remove("hidden");
    const debate = phase === "debate" || phase === "comprehension";
    const chatMode = mode === "conversation" || mode === "free_debate";
    $("conversationPanel").classList.toggle("hidden", !chatMode);
    $("readingPanel").classList.toggle("hidden", mode !== "reading" || debate);
    $("comprehensionPanel").classList.toggle("hidden", !debate);
    $("phaseBadge").textContent = phase || mode;
    state.readingPhase = phase;
    syncPttUi();
  }

  function showWrongWords(words, errors) {
    const box = $("wrongWordsBox");
    const list = $("wrongWordsList");
    list.innerHTML = "";
    const rows = [];
    if (errors?.length) {
      const seen = new Set();
      for (const err of errors) {
        const expected = String(err.expected || "").trim();
        if (!expected || expected === "(missing)" || seen.has(expected)) continue;
        seen.add(expected);
        rows.push({
          word: expected,
          significance: Number(err.significance || 5),
        });
      }
      rows.sort((a, b) => b.significance - a.significance || a.word.localeCompare(b.word));
    } else if (words?.length) {
      for (const w of words) rows.push({ word: w, significance: null });
    }
    if (!rows.length) {
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");
    for (const row of rows) {
      const li = document.createElement("li");
      if (row.significance != null) {
        li.innerHTML = `<span class="sig-badge sig-${Math.min(10, Math.max(1, row.significance))}">${row.significance}/10</span> ${escapeHtml(row.word)}`;
      } else {
        li.textContent = row.word;
      }
      list.appendChild(li);
    }
  }

  function setReadingActionPhase(phase) {
    if (phase === "ready" || phase === "reading") {
      $("readingActionsReady").classList.remove("hidden");
      $("readingActionsAfter").classList.add("hidden");
      $("startReadingBtn").classList.toggle("hidden", phase === "reading");
      $("stopRead").classList.toggle("hidden", phase !== "reading");
    } else if (phase === "reading_done") {
      if (state.isPractice) {
        $("readingActionsReady").classList.remove("hidden");
        $("readingActionsAfter").classList.add("hidden");
        $("startReadingBtn").classList.remove("hidden");
        $("stopRead").classList.add("hidden");
      } else {
        $("readingActionsReady").classList.add("hidden");
        $("readingActionsAfter").classList.remove("hidden");
        $("explainBtn").classList.remove("hidden");
        $("stopExplain").classList.add("hidden");
        $("debateBtn").classList.remove("hidden");
      }
    } else if (phase === "explain") {
      $("readingActionsReady").classList.add("hidden");
      $("readingActionsAfter").classList.remove("hidden");
      $("explainBtn").classList.add("hidden");
      $("stopExplain").classList.remove("hidden");
      $("debateBtn").classList.remove("hidden");
    }
  }

  function appendChat(role, text, opts = {}) {
    const div = document.createElement("div");
    div.className = `bubble ${role}`;

    const body = document.createElement("div");
    body.className = "bubble-text";
    body.textContent = text;
    div.appendChild(body);

    if (role === "assistant" && text) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "bubble-replay";
      btn.title = "Prečítať znova";
      btn.setAttribute("aria-label", "Prečítať znova");
      btn.innerHTML =
        '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">'
        + '<path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>'
        + "</svg>";
      let audioB64 = opts.audioBase64 || null;
      btn.addEventListener("click", async () => {
        try {
          btn.disabled = true;
          btn.classList.add("is-playing");
          setStatus("Prehrávam text…");
          audioB64 = await replayAssistantSpeech(text, audioB64);
          setStatus("Hotovo.");
        } catch (err) {
          setStatus(err.message || "Prehratie zlyhalo", true);
        } finally {
          btn.disabled = false;
          btn.classList.remove("is-playing");
        }
      });
      div.appendChild(btn);
    }

    $("chat").appendChild(div);
    $("chat").scrollTop = $("chat").scrollHeight;
  }

  function buildStartPayload(restart = false) {
    return {
      mode: $("mode").value,
      level: $("level").value,
      topic: $("topic").value,
      subtopic: $("subtopic").value,
      llm_provider: $("llm").value,
      llm_model: $("llmModel")?.value || null,
      tts_provider: $("ttsProvider").value,
      voice_id: $("voice").value || null,
      speech_rate: currentSpeechRate(),
      min_questions: Number($("minQuestions").value || 20),
      sentence_count: Number($("sentenceCount").value || 20),
      user_id: effectiveUserId(),
      restart: !!restart,
    };
  }

  async function startLesson(restart = false, forceMode = null) {
    if (state.startInFlight) {
      setStatus("Už spúšťam lekciu — počkaj chvíľu…");
      return;
    }
    state.startInFlight = true;
    const startControls = ["startBtn", "freeDebateBtn", "restartBtn"];
    for (const id of startControls) {
      if ($(id)) $(id).disabled = true;
    }
    try {
    // Skôr než speech UI: mic prompt len ak ešte nie je zapamätaný grant.
    if (state.micPermission !== "granted") {
      await ensureMicPermission();
    }
    unlockAudioPlayback().catch(() => {});
    await stopPtt();
    if (forceMode) $("mode").value = forceMode;
    syncModeUi();
    const payload = buildStartPayload(restart);
    state.lastStartPayload = payload;
    state.isPractice = false;
    const reading = payload.mode === "reading";
    const free = payload.mode === "free_debate";
    setStatus(
      free
        ? "Pripravujem voľnú debatu podľa tvojej histórie a learning store…"
        : reading
          ? (restart ? "Generujem nový text…" : "Generujem text na čítanie…")
          : (restart ? "Reštart: opakovanie + história…" : "Spúšťam lekciu…")
    );
    $("chat").innerHTML = "";
    $("passage").innerHTML = "";
    $("readFeedback").textContent = "";
    $("compFeedback").textContent = "";
    showWrongWords([]);
    try {
      const data = await api("/api/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.sessionId = data.session_id;
      state.mode = data.mode;
      state.voiceId = payload.voice_id;
      state.ttsProvider = payload.tts_provider;
      state.userId = data.user_id || payload.user_id;
      state.passageText = data.text || "";
      state.passageAudio = data.audio_base64 || null;

      if (data.mode === "conversation" || data.mode === "free_debate") {
        $("lessonTitle").textContent = data.mode === "free_debate"
          ? (data.suggested_topic
            ? `Voľná debata — ${data.suggested_topic}`
            : "Voľná debata")
          : (restart ? "Reštart — konverzácia" : "Konverzácia");
        showPanels(data.mode, data.phase || data.mode);
        $("chat").innerHTML = "";
        appendChat("assistant", data.reply, { audioBase64: data.audio_base64 });
        const due = data.due_words?.length ? `Opakujeme: ${data.due_words.join(", ")}. ` : "";
        const topicHint = data.suggested_topic ? `Návrh témy: ${data.suggested_topic}. ` : "";
        const facts = data.learned_facts?.length
          ? `Nové fakty o tebe: ${data.learned_facts.join("; ")}. `
          : "";
        setStatus(
          data.mode === "free_debate"
            ? `${topicHint}${due}${facts}AI hovorí úvod…`
            : `${due}Otázky: ${data.questions_asked || 0}/${data.min_questions}`
        );
        if (data.mode === "free_debate" || data.mode === "conversation") {
          if (data.mode === "free_debate") setStatus("AI hovorí úvod…");
          await playBase64Mp3(data.audio_base64);
          ensurePtt();
          syncPttUi();
          pttReadyStatus();
        } else {
          await playBase64Mp3(data.audio_base64);
          syncPttUi();
        }
      } else {
        $("lessonTitle").textContent = data.title || "Čítanie";
        showPanels("reading", data.phase || "ready");
        $("passage").innerHTML = data.highlighted_html || escapeHtml(data.text || "");
        setReadingActionPhase("ready");
        syncPttUi();
        const due = data.due_words?.length ? `Opakujeme: ${data.due_words.join(", ")}. ` : "";
        setStatus(
          `${due}Text pripravený (~${data.sentence_count || payload.sentence_count} viet). `
          + `Stlač „Štart čítania“ a čítaj nahlas.`
        );
      }
      await loadLearning();
    } catch (err) {
      setStatus(err.message, true);
    }
    } finally {
      state.startInFlight = false;
      for (const id of startControls) {
        if ($(id)) $(id).disabled = false;
      }
    }
  }

  async function ensurePassageAudio() {
    if (state.passageAudio) return state.passageAudio;
    if (!state.passageText) return null;
    setStatus("Generujem hlasový vzor…");
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        text: state.passageText,
        tts_provider: $("ttsProvider").value,
        voice_id: $("voice").value,
        speech_rate: currentSpeechRate(),
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "TTS zlyhalo");
    }
    const blob = await res.blob();
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    state.passageAudio = btoa(binary);
    return state.passageAudio;
  }

  async function sendConversationText() {
    const text = $("textInput").value.trim();
    if (!text || !state.sessionId) return;
    $("textInput").value = "";
    clearPttPauseTimer();
    interruptAiSpeech();
    const ptt = ensurePtt();
    ptt.processing = true;
    syncPttUi();
    appendChat("user", text);
    setStatus("Čakám na odpoveď…");
    try {
      const data = await api("/api/conversation/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.sessionId,
          text,
          speech_rate: currentSpeechRate(),
        }),
      });
      appendChat("assistant", data.reply, { audioBase64: data.audio_base64 });
      const confusedNote = data.confused?.length
        ? `Zapísané: nerozumel otázke — ${data.confused.map((c) => c.summary).filter(Boolean).join("; ")}. `
        : "";
      const wrongNote = data.wrongs?.length
        ? `Zapísané zlá odpoveď — ${data.wrongs.map((w) => w.summary).filter(Boolean).join("; ")}. `
        : "";
      if (data.learned_facts?.length) {
        setStatus(`Zapísané o tebe: ${data.learned_facts.join("; ")}. Otázky: ${data.questions_asked}/${data.min_questions}`);
      } else if (wrongNote) {
        setStatus(`${wrongNote}Pozri learning store dole.`);
      } else if (confusedNote) {
        setStatus(`${confusedNote}AI to preformuluje.`);
      } else if (state.mode === "free_debate") {
        setStatus("AI odpovedá…");
      } else {
        setStatus(`Otázky: ${data.questions_asked}/${data.min_questions}`);
      }
      await loadLearning();
      ptt.processing = false;
      syncPttUi();
      await playBase64Mp3(data.audio_base64);
      if (isPttMode()) pttReadyStatus();
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      if (state.ptt) state.ptt.processing = false;
      syncPttUi();
    }
  }

  async function startRecording(kind) {
    if (!state.sessionId) {
      setStatus("Najprv spusti lekciu / vygeneruj text.", true);
      return;
    }
    if (isPttMode() && kind === "conversation") {
      setStatus("Ťukni na mikrofón (zelené tlačidlo).");
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: micAudioConstraints(),
    });
    state.chunks = [];
    const recorder = new MediaRecorder(stream);
    state.mediaRecorder = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) state.chunks.push(e.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(state.chunks, { type: "audio/webm" });
      if (kind === "conversation") await uploadConversation(blob);
      if (kind === "reading") await uploadReading(blob);
      if (kind === "comprehension") await uploadComprehension(blob);
      if (kind === "explain") await uploadExplain(blob);
    };
    recorder.start();
    toggleRecordButtons(kind, true);
    setStatus("Počúvam… hovor / čítaj.");
  }

  function stopRecording(kind) {
    if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
      state.mediaRecorder.stop();
    }
    toggleRecordButtons(kind, false);
  }

  function toggleRecordButtons(kind, recording) {
    const map = {
      conversation: ["recordConv", "stopConv"],
      reading: ["startReadingBtn", "stopRead"],
      comprehension: ["recordComp", "stopComp"],
      explain: ["explainBtn", "stopExplain"],
    };
    const [startId, stopId] = map[kind];
    if ($(startId)) $(startId).classList.toggle("hidden", recording);
    if ($(stopId)) $(stopId).classList.toggle("hidden", !recording);
  }

  function micAudioConstraints() {
    return {
      echoCancellation: { ideal: true },
      noiseSuppression: { ideal: true },
      autoGainControl: { ideal: true },
      channelCount: { ideal: 1 },
      sampleRate: { ideal: 16000 },
    };
  }

  async function ensureMicPermission(opts = {}) {
    const quiet = !!opts.quiet;
    const allowPrompt = opts.prompt !== false;
    if (!navigator.mediaDevices?.getUserMedia) {
      state.micPermission = "unsupported";
      if (!quiet) setStatus("Tento prehliadač nepodporuje mikrofón.", true);
      return false;
    }

    // 1) Už máme grant v pamäti / localStorage — nevolaj znova getUserMedia (Safari by sa znova pýtala).
    if (state.micPermission === "granted") return true;
    try {
      const stored = localStorage.getItem(MIC_KEY);
      if (stored === "granted") {
        state.micPermission = "granted";
        return true;
      }
      if (stored === "denied") state.micPermission = "denied";
    } catch (_) {}

    // 2) Permissions API (Chrome; Safari často nepodporuje)
    try {
      if (navigator.permissions?.query) {
        const status = await navigator.permissions.query({ name: "microphone" });
        if (status.state === "granted") {
          state.micPermission = "granted";
          try {
            localStorage.setItem(MIC_KEY, "granted");
          } catch (_) {}
          return true;
        }
        if (status.state === "denied") {
          state.micPermission = "denied";
          try {
            localStorage.setItem(MIC_KEY, "denied");
          } catch (_) {}
          if (!quiet) {
            setStatus(
              "Mikrofón je zablokovaný. V Safari: Aa → Webová stránka → Mikrofón → Povoliť.",
              true
            );
          }
          return false;
        }
        status.onchange = () => {
          if (status.state === "granted" || status.state === "denied") {
            state.micPermission = status.state;
            try {
              localStorage.setItem(MIC_KEY, status.state);
            } catch (_) {}
          }
        };
      }
    } catch (_) {
      /* ignore */
    }

    if (state.micPermission === "denied") {
      if (!quiet) {
        setStatus(
          "Mikrofón je zablokovaný. V Safari: Aa → Webová stránka → Mikrofón → Povoliť.",
          true
        );
      }
      return false;
    }

    // 3) Prompt len ak ešte nebolo udelené (a volajúci to chce — pri refreshi nie).
    if (!allowPrompt) return false;

    try {
      if (!quiet) setStatus("Vyžadujem prístup k mikrofónu…");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: micAudioConstraints(),
      });
      stream.getTracks().forEach((t) => {
        try {
          t.stop();
        } catch (_) {}
      });
      state.micPermission = "granted";
      try {
        localStorage.setItem(MIC_KEY, "granted");
      } catch (_) {}
      unlockAudioPlayback().catch(() => {});
      if (!quiet) setStatus("Mikrofón povolený — nabudúce sa už nebudem pýtať.");
      return true;
    } catch (err) {
      state.micPermission = "denied";
      try {
        localStorage.setItem(MIC_KEY, "denied");
      } catch (_) {}
      const msg = String(err?.message || err || "");
      if (!quiet) {
        setStatus(
          /denied|not allowed|permission/i.test(msg)
            ? "Mikrofón zamietnutý. Povoľ ho pre túto stránku a skús znova."
            : `Mikrofón: ${msg}`,
          true
        );
      }
      return false;
    }
  }

  function ensurePtt() {
    if (!state.ptt) {
      state.ptt = {
        holding: false,
        recording: false,
        processing: false,
        finalizing: false,
        stream: null,
        recorder: null,
        chunks: [],
        pendingSegments: [],
        pauseTimer: null,
        abortController: null,
        pointerId: null,
      };
    }
    if (!Array.isArray(state.ptt.pendingSegments)) state.ptt.pendingSegments = [];
    return state.ptt;
  }

  function interruptAiSpeech() {
    stopCurrentAudio();
    const ptt = state.ptt;
    if (ptt?.abortController) {
      try {
        ptt.abortController.abort();
      } catch (_) {}
      ptt.abortController = null;
    }
    if (ptt) ptt.processing = false;
  }

  function clearPttPauseTimer() {
    const ptt = state.ptt;
    if (!ptt?.pauseTimer) return;
    clearTimeout(ptt.pauseTimer);
    ptt.pauseTimer = null;
  }

  function recorderCanPause(recorder) {
    return !!(
      recorder
      && typeof recorder.pause === "function"
      && typeof recorder.resume === "function"
    );
  }

  function pttHasPendingUtterance(ptt) {
    if (!ptt) return false;
    if (ptt.pendingSegments?.length) return true;
    if (ptt.chunks?.length) return true;
    if (ptt.recorder && ptt.recorder.state === "paused") return true;
    return false;
  }

  function discardPttUtterance(ptt) {
    if (!ptt) return;
    clearPttPauseTimer();
    try {
      if (ptt.recorder && ptt.recorder.state !== "inactive") {
        ptt.recorder.ondataavailable = null;
        ptt.recorder.onstop = null;
        ptt.recorder.stop();
      }
    } catch (_) {}
    ptt.recorder = null;
    ptt.recording = false;
    ptt.chunks = [];
    ptt.pendingSegments = [];
  }

  function releasePttStream(ptt) {
    if (!ptt) return;
    try {
      ptt.stream?.getTracks?.().forEach((t) => {
        try {
          t.stop();
        } catch (_) {}
      });
    } catch (_) {}
    ptt.stream = null;
  }

  function stopAndCollectPttBlob(ptt) {
    return new Promise((resolve) => {
      const finish = () => {
        const parts = [...(ptt.pendingSegments || [])];
        if (ptt.chunks?.length) parts.push(...ptt.chunks);
        const mime = recorderBlobType(ptt.recorderMime || parts[0]?.type || "audio/webm");
        ptt.pendingSegments = [];
        ptt.chunks = [];
        ptt.recorder = null;
        ptt.recording = false;
        resolve(new Blob(parts, { type: mime }));
      };

      const recorder = ptt.recorder;
      if (!recorder || recorder.state === "inactive") {
        finish();
        return;
      }

      recorder.ondataavailable = (ev) => {
        if (ev.data?.size > 0) ptt.chunks.push(ev.data);
      };
      recorder.onstop = () => finish();
      try {
        if (recorder.state === "paused" || recorder.state === "recording") {
          try {
            recorder.requestData?.();
          } catch (_) {}
          recorder.stop();
        } else {
          finish();
        }
      } catch (_) {
        finish();
      }
    });
  }

  function schedulePttSend(ptt) {
    clearPttPauseTimer();
    const waitSec = silenceTimeoutSec();
    let left = waitSec;
    const tickPause = () => {
      if (!state.ptt || state.ptt !== ptt || ptt.holding || ptt.finalizing) return;
      if (left <= 0) {
        ptt.pauseTimer = null;
        flushPttAndUpload(ptt).catch((err) => setStatus(err.message, true));
        return;
      }
      setStatus(`Pauza… o ${left}s odošlem AI. (Ťukni znova = pokračuj v nahrávaní.)`);
      left -= 1;
      ptt.pauseTimer = setTimeout(tickPause, 1000);
    };
    setStatus(`Pauza ${waitSec} s… potom odošlem AI. (Ťukni znova = pokračuj v nahrávaní.)`);
    tickPause();
  }

  async function flushPttAndUpload(ptt) {
    if (!ptt || ptt.finalizing || ptt.holding) return;
    ptt.finalizing = true;
    clearPttPauseTimer();
    setStatus("Spracúvam hlas…");
    try {
      const blob = await stopAndCollectPttBlob(ptt);
      // Uvoľni mic hneď — inak iOS nechá oranžový indikátor zapnutý.
      releasePttStream(ptt);
      if (blob.size < 1200) {
        setStatus("Príliš krátky záznam / ticho — ťukni na mikrofón a hovor jasnejšie.");
        syncPttUi();
        return;
      }
      await uploadConversation(blob, { fromPtt: true });
    } finally {
      ptt.finalizing = false;
      releasePttStream(ptt);
      syncPttUi();
    }
  }

  async function stopPtt() {
    const ptt = state.ptt;
    if (!ptt) {
      syncPttUi();
      return;
    }
    clearPttPauseTimer();
    interruptAiSpeech();
    discardPttUtterance(ptt);
    releasePttStream(ptt);
    stopAudioKeepalive();
    state.ptt = null;
    syncPttUi();
  }

  function pttReadyStatus() {
    setStatus("Pripravené — ťukni na mikrofón (ďalšie ťuknutie zastaví a odošle).");
  }

  function resetStuckPtt(ptt) {
    if (!ptt) return;
    if (ptt.finalizing) ptt.finalizing = false;
    if (ptt.holding && !ptt.recording) {
      ptt.holding = false;
      ptt.pointerId = null;
    }
    if (ptt.recording && ptt.recorder && ptt.recorder.state !== "recording" && ptt.recorder.state !== "paused") {
      ptt.recording = false;
      ptt.recorder = null;
    }
  }

  async function pttToggleMic(e) {
    if (e?.button != null && e.button !== 0) return;
    if (!state.sessionId || !isPttMode()) {
      setStatus("Najprv spusti konverzáciu alebo voľnú debatu.", true);
      return;
    }
    const ptt = ensurePtt();
    resetStuckPtt(ptt);
    if (ptt.finalizing || ptt.processing) {
      // Preruš AI / odosielanie a začni novú nahrávku.
      interruptAiSpeech();
      ptt.finalizing = false;
    }
    if (ptt.holding || ptt.recording) {
      await pttStopRecordingAndSend();
      return;
    }
    await pttStartRecording();
  }

  async function pttStartRecording() {
    if (!window.MediaRecorder) {
      setStatus("Tento prehliadač nepodporuje nahrávanie hlasu (MediaRecorder).", true);
      return;
    }
    const ptt = ensurePtt();
    if (ptt.holding || ptt.recording) return;

    clearPttPauseTimer();
    interruptAiSpeech();
    discardPttUtterance(ptt);

    ptt.holding = true;
    ptt.recording = false;
    syncPttUi();
    setStatus("Nahrávam… ťukni znova na Stop / odošli.");
    unlockAudioPlayback().catch(() => {});

    try {
      if (!ptt.stream || ptt.stream.getTracks().every((t) => t.readyState === "ended")) {
        ptt.stream = await navigator.mediaDevices.getUserMedia({
          audio: micAudioConstraints(),
        });
        state.micPermission = "granted";
        try {
          localStorage.setItem(MIC_KEY, "granted");
        } catch (_) {}
      }
      if (!state.ptt || !ptt.holding) {
        releasePttStream(ptt);
        return;
      }

      ptt.chunks = [];
      const mime = pickRecorderMimeType();
      ptt.recorderMime = mime || "audio/mp4";
      let recorder;
      try {
        recorder = mime
          ? new MediaRecorder(ptt.stream, { mimeType: mime })
          : new MediaRecorder(ptt.stream);
      } catch (_) {
        recorder = new MediaRecorder(ptt.stream);
        ptt.recorderMime = recorder.mimeType || "audio/mp4";
      }
      ptt.recorder = recorder;
      recorder.ondataavailable = (ev) => {
        if (ev.data?.size > 0) ptt.chunks.push(ev.data);
      };
      recorder.start(250);
      ptt.recording = true;
      syncPttUi();
    } catch (err) {
      ptt.holding = false;
      ptt.recording = false;
      releasePttStream(ptt);
      syncPttUi();
      setStatus(`Mikrofón: ${err.message || err}`, true);
    }
  }

  async function pttStopRecordingAndSend() {
    const ptt = state.ptt;
    if (!ptt) return;
    if (!ptt.holding && !ptt.recording) return;

    ptt.holding = false;
    ptt.pointerId = null;
    syncPttUi();
    clearPttPauseTimer();

    if (!ptt.recording || !ptt.recorder) {
      if (pttHasPendingUtterance(ptt)) {
        await flushPttAndUpload(ptt);
      } else {
        releasePttStream(ptt);
        pttReadyStatus();
      }
      return;
    }

    const recorder = ptt.recorder;
    const blobType = recorderBlobType(ptt.recorderMime || recorder.mimeType || "");

    await new Promise((resolve) => {
      recorder.onstop = () => {
        ptt.recording = false;
        ptt.recorder = null;
        if (ptt.chunks?.length) {
          ptt.pendingSegments.push(new Blob(ptt.chunks, { type: blobType }));
          ptt.chunks = [];
        }
        releasePttStream(ptt);
        resolve();
      };
      try {
        try {
          recorder.requestData?.();
        } catch (_) {}
        if (recorder.state === "paused") {
          try {
            recorder.resume();
          } catch (_) {}
        }
        if (recorder.state !== "inactive") recorder.stop();
        else recorder.onstop();
      } catch (_) {
        ptt.recording = false;
        ptt.recorder = null;
        releasePttStream(ptt);
        resolve();
      }
    });

    if (!pttHasPendingUtterance(ptt)) {
      setStatus("Príliš krátky záznam — ťukni znova a hovor dlhšie.");
      syncPttUi();
      return;
    }
    // Toggle režim: po druhom ťuknutí odošli hneď (bez čakania na ticho).
    await flushPttAndUpload(ptt);
  }

  function bindPttMicButton() {
    const mic = $("pttMicBtn");
    if (!mic || mic.dataset.pttBound === "1") return;
    mic.dataset.pttBound = "1";

    let lastToggleAt = 0;
    const onToggle = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const now = Date.now();
      if (now - lastToggleAt < 400) return;
      lastToggleAt = now;
      pttToggleMic(e).catch((err) => setStatus(err.message || String(err), true));
    };

    // Toggle: jedno ťuknutie = štart, druhé = stop + odoslať (nie hold).
    mic.addEventListener("click", onToggle);
    mic.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") onToggle(e);
    });
    mic.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  async function beginReadingListen() {
    try {
      await api("/api/reading/begin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId }),
      });
      setReadingActionPhase("reading");
      showPanels("reading", "reading");
      await startRecording("reading");
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  async function uploadConversation(blob, opts = {}) {
    const fromPtt = !!opts.fromPtt;
    setStatus("Spracúvam hlas…");
    const ptt = ensurePtt();
    ptt.processing = true;
    syncPttUi();
    const fd = new FormData();
    fd.append("session_id", state.sessionId);
    const ext = (blob.type || "").includes("mp4") || (blob.type || "").includes("aac")
      ? "mp4"
      : "webm";
    fd.append("audio", blob, `utterance.${ext}`);
    fd.append("speech_rate", String(currentSpeechRate()));
    const controller = new AbortController();
    ptt.abortController = controller;
    try {
      const res = await fetch("/api/conversation/utterance", {
        method: "POST",
        headers: authHeaders(),
        body: fd,
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Chyba");
      if (data.no_speech) {
        setStatus(data.detail || "Nepočul som ťa — skús znova.");
        if (fromPtt && isPttMode() && state.sessionId) pttReadyStatus();
        return;
      }
      const shown =
        data.transcript_display || data.said || data.transcript || "(audio)";
      appendChat("user", shown);
      appendChat("assistant", data.reply, { audioBase64: data.audio_base64 });
      if ((data.wrongs && data.wrongs.length) || (data.confused && data.confused.length) || (data.unknowns && data.unknowns.length)) {
        loadLearning().catch(() => {});
      }
      const confusedNote = data.confused?.length
        ? `Zapísané: nerozumel otázke — ${data.confused.map((c) => c.summary).filter(Boolean).join("; ")}. `
        : "";
      const wrongNote = data.wrongs?.length
        ? `Zapísané zlá odpoveď — ${data.wrongs.map((w) => w.summary).filter(Boolean).join("; ")}. `
        : "";
      if (data.learned_facts?.length) {
        setStatus(`Zapísané o tebe: ${data.learned_facts.join("; ")}`);
      } else if (wrongNote) {
        setStatus(`${wrongNote}Pozri learning store dole.`);
      } else if (confusedNote) {
        setStatus(`${confusedNote}AI to preformuluje.`);
      } else {
        setStatus("AI hovorí…");
      }
      await loadLearning();
      ptt.processing = false;
      syncPttUi();
      await unlockAudioPlayback();
      const played = await playBase64Mp3(data.audio_base64);
      if (fromPtt && isPttMode() && state.sessionId) {
        if (played) {
          if (wrongNote) setStatus(wrongNote.trim());
          else if (confusedNote) setStatus(confusedNote.trim());
          else pttReadyStatus();
        }
      }
    } catch (err) {
      if (err?.name === "AbortError") {
        setStatus("AI prerušená — ťukni na mikrofón a hovor.");
      } else {
        const msg = String(err.message || err);
        if (/session not found/i.test(msg)) {
          state.sessionId = null;
          await stopPtt();
          setStatus("Session vypršala (server sa reštartoval?). Spusti voľnú debatu znova.", true);
        } else {
          setStatus(msg, true);
        }
      }
    } finally {
      if (state.ptt) {
        state.ptt.processing = false;
        state.ptt.abortController = null;
      }
      syncPttUi();
    }
  }

  async function uploadReading(blob) {
    setStatus("Porovnávam čítanie…");
    const fd = new FormData();
    fd.append("session_id", state.sessionId);
    fd.append("audio", blob, "reading.webm");
    try {
      const res = await fetch("/api/reading/evaluate", {
        method: "POST",
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chyba");
      $("passage").innerHTML = data.highlighted_html || "";
      $("readFeedback").textContent = data.overall_feedback
        || `Nájdené chyby: ${(data.errors || []).length}`;
      showWrongWords(data.wrong_words || [], data.errors || []);
      playBase64Mp3(data.feedback_audio_base64);
      setReadingActionPhase("reading_done");
      showPanels("reading", "reading_done");
      if (data.practice) {
        const cleared = data.practice_cleared || [];
        const kept = data.practice_kept || [];
        if (cleared.length && !kept.length) {
          setStatus(`Precvičenie hotové — všetky ciele zmizli z learning store (${cleared.length}).`);
        } else if (cleared.length) {
          setStatus(
            `Vymazané: ${cleared.join(", ")}. Stále v store: ${kept.join(", ")}.`
          );
        } else if (kept.length) {
          setStatus(`Stále zle — v learning store ostáva: ${kept.join(", ")}.`);
        } else {
          setStatus(data.overall_feedback || "Precvičenie dokončené.");
        }
      } else {
        setStatus(
          data.wrong_words?.length
            ? `Hotovo. Zlé: ${data.wrong_words.length}. Môžeš vysvetliť text alebo začať debatu.`
            : "Výborne — bez chýb. Môžeš vysvetliť text alebo začať debatu."
        );
      }
      await loadLearning();
    } catch (err) {
      setReadingActionPhase("ready");
      setStatus(err.message, true);
    }
  }

  async function beginExplain() {
    setReadingActionPhase("explain");
    setStatus("Vysvetli nahlas, o čom text bol. Potom Stop.");
    try {
      await startRecording("explain");
    } catch (err) {
      setReadingActionPhase("reading_done");
      setStatus(err.message, true);
    }
  }

  async function uploadExplain(blob) {
    setStatus("Hodnotím vysvetlenie…");
    const fd = new FormData();
    fd.append("session_id", state.sessionId);
    fd.append("audio", blob, "explain.webm");
    try {
      const res = await fetch("/api/reading/explain", {
        method: "POST",
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chyba");
      $("readFeedback").textContent =
        `${data.correct ? "✓" : "✗"} ${data.feedback || ""}`
        + (data.missing_points?.length ? ` (chýba: ${data.missing_points.join(", ")})` : "");
      playBase64Mp3(data.audio_base64);
      setReadingActionPhase("reading_done");
      setStatus(data.correct ? "Vysvetlenie OK. Môžeš ešte debatu." : "Skús ešte raz alebo debatu o texte.");
      await loadLearning();
    } catch (err) {
      setReadingActionPhase("reading_done");
      setStatus(err.message, true);
    }
  }

  async function startDebate() {
    setStatus("Pripravujem otázky k textu…");
    try {
      const data = await api("/api/reading/start-debate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId }),
      });
      if (data.phase === "done" || !data.question) {
        showPanels("reading", "done");
        $("comprehensionPanel").classList.add("hidden");
        setStatus("Hotovo — žiadne otázky.");
        return;
      }
      showPanels("reading", "debate");
      $("questionText").textContent = data.question.question;
      $("compFeedback").textContent = "";
      playBase64Mp3(data.audio_base64);
      setStatus(`Debata — otázka ${data.question_index + 1} / ${data.total}`);
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  async function uploadComprehension(blob) {
    setStatus("Hodnotím odpoveď…");
    const fd = new FormData();
    fd.append("session_id", state.sessionId);
    fd.append("audio", blob, "answer.webm");
    try {
      const res = await fetch("/api/reading/debate", {
        method: "POST",
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chyba");
      $("compFeedback").textContent = `${data.correct ? "✓" : "✗"} ${data.feedback || ""}`;
      playBase64Mp3(data.audio_base64);
      if (data.done) {
        setStatus("Debata dokončená.");
        $("phaseBadge").textContent = "done";
      } else if (data.next_question) {
        $("questionText").textContent = data.next_question.question;
        setStatus(`Debata — otázka ${data.question_index + 1} / ${data.total}`);
      }
      await loadLearning();
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  async function previewSelectedVoice() {
    const ttsProvider = $("ttsProvider").value || "edge";
    const voiceId = $("voice").value;
    if (!voiceId) {
      setStatus("Najprv vyber hlas.", true);
      return;
    }
    setStatus("Prehrávam ukážku hlasu…");
    $("previewVoice").disabled = true;
    try {
      const res = await fetch("/api/speak", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          text: "Hello! This is a short preview of the selected English voice. How does it sound?",
          tts_provider: ttsProvider,
          voice_id: voiceId,
          speech_rate: currentSpeechRate(),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || res.statusText || "TTS preview zlyhalo");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.playbackRate = currentSpeechRate();
      audio.preservesPitch = true;
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
      const voiceLabel = $("voice").selectedOptions[0]?.textContent || voiceId;
      const rateLabel = $("speechRate").selectedOptions[0]?.textContent || "";
      setStatus(`Ukážka: ${ttsProvider} — ${voiceLabel} (${rateLabel})`);
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      $("previewVoice").disabled = false;
    }
  }

  function formatMatches(matches) {
    if (!matches?.length) return "";
    return matches
      .slice(0, 4)
      .map((m) => `• ${m.label}${m.reason ? ` (${m.reason})` : ""}`)
      .join("\n");
  }

  function openTopicModal() {
    $("topicModalError").hidden = true;
    $("topicModalError").textContent = "";
    $("topicModalForce").classList.add("hidden");
    $("newTopicLabel").value = "";
    $("newTopicDesc").value = "";
    $("topicModal").classList.remove("hidden");
    setTimeout(() => $("newTopicLabel").focus(), 50);
  }

  function closeTopicModal() {
    $("topicModal").classList.add("hidden");
  }

  function openSubtopicModal() {
    fillSelect($("subtopicParent"), state.meta?.topics || []);
    $("subtopicParent").value = $("topic").value;
    $("subtopicModalError").hidden = true;
    $("subtopicModalError").textContent = "";
    $("subtopicModalForce").classList.add("hidden");
    $("newSubtopicLabel").value = "";
    $("newSubtopicDesc").value = "";
    $("subtopicModal").classList.remove("hidden");
    setTimeout(() => $("newSubtopicLabel").focus(), 50);
  }

  function closeSubtopicModal() {
    $("subtopicModal").classList.add("hidden");
  }

  async function submitTopic(force = false) {
    const label = $("newTopicLabel").value.trim();
    const description = $("newTopicDesc").value.trim();
    const err = $("topicModalError");
    err.hidden = true;
    if (!label) {
      err.textContent = "Zadaj názov témy.";
      err.hidden = false;
      return;
    }
    $("topicModalSave").disabled = true;
    $("topicModalForce").disabled = true;
    try {
      const data = await api("/api/topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: effectiveUserId(),
          label,
          description,
          force,
        }),
      });
      applyTopics(data.topics || [], data.topic?.id);
      closeTopicModal();
      setStatus(`Téma „${label}“ pridaná.`);
    } catch (e) {
      const matches = e.detail?.matches;
      err.textContent = `${e.message}${matches ? `\n${formatMatches(matches)}` : ""}`;
      err.hidden = false;
      if (e.status === 409) $("topicModalForce").classList.remove("hidden");
    } finally {
      $("topicModalSave").disabled = false;
      $("topicModalForce").disabled = false;
    }
  }

  async function submitSubtopic(force = false) {
    const topicId = $("subtopicParent").value;
    const label = $("newSubtopicLabel").value.trim();
    const description = $("newSubtopicDesc").value.trim();
    const err = $("subtopicModalError");
    err.hidden = true;
    if (!topicId) {
      err.textContent = "Vyber tému.";
      err.hidden = false;
      return;
    }
    if (!label) {
      err.textContent = "Zadaj názov podtémy.";
      err.hidden = false;
      return;
    }
    $("subtopicModalSave").disabled = true;
    $("subtopicModalForce").disabled = true;
    try {
      const data = await api("/api/topics/subtopics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: effectiveUserId(),
          topic_id: topicId,
          label,
          description,
          force,
        }),
      });
      applyTopics(data.topics || [], topicId, data.subtopic?.id);
      closeSubtopicModal();
      setStatus(`Podtéma „${label}“ pridaná.`);
    } catch (e) {
      const matches = e.detail?.matches;
      err.textContent = `${e.message}${matches ? `\n${formatMatches(matches)}` : ""}`;
      err.hidden = false;
      if (e.status === 409) $("subtopicModalForce").classList.remove("hidden");
    } finally {
      $("subtopicModalSave").disabled = false;
      $("subtopicModalForce").disabled = false;
    }
  }

  function openUserModal() {
    $("userModalError").hidden = true;
    $("userModalError").textContent = "";
    $("newUserName").value = "";
    $("newUserPassword").value = "";
    $("newUserLevel").value = $("level")?.value || "A2";
    $("userModal").classList.remove("hidden");
    setTimeout(() => $("newUserName").focus(), 50);
  }

  function closeUserModal() {
    $("userModal").classList.add("hidden");
  }

  async function submitNewUser() {
    const name = $("newUserName").value.trim();
    const password = $("newUserPassword").value;
    const err = $("userModalError");
    err.hidden = true;
    if (!name) {
      err.textContent = "Zadaj meno používateľa.";
      err.hidden = false;
      return;
    }
    if (!password || password.length < 4) {
      err.textContent = "Heslo musí mať aspoň 4 znaky.";
      err.hidden = false;
      return;
    }
    $("userModalSave").disabled = true;
    try {
      const data = await api("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          password,
          preferred_level: $("newUserLevel").value || "A2",
        }),
      });
      await loadManagedUsers();
      closeUserModal();
      setStatus(`Účet „${data.user.name}“ vytvorený.`);
    } catch (e) {
      err.textContent = e.message || "Vytvorenie zlyhalo.";
      err.hidden = false;
    } finally {
      $("userModalSave").disabled = false;
    }
  }

  async function renameUser() {
    const id = effectiveUserId();
    if (!id) return;
    const currentLabel = state.isAdmin
      ? ($("manageUserSelect").selectedOptions[0]?.textContent || state.userName || "")
      : (state.userName || "");
    const name = prompt("Nové meno:", currentLabel.replace(/\s*\(admin\)\s*$/, ""));
    if (!name || !name.trim()) return;
    try {
      const data = await api(`/api/users/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      if (id === state.userId) {
        state.userName = data.user.name;
        $("currentUserName").textContent = data.user.name;
      }
      await loadManagedUsers();
      setStatus("Účet premenovaný.");
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  async function deleteUser() {
    const id = effectiveUserId();
    if (!id) return;
    const who =
      $("manageUserSelect")?.selectedOptions?.[0]?.textContent
      || state.userName
      || id;
    if (
      !confirm(
        `UPOZORNENIE: Zmazaním účtu „${who}“ sa natrvalo odstráni VŠETKO s ním spojené `
        + `(profil, história, slovíčka, chyby čítania, témy, nastavenia).\n\n`
        + `Táto akcia sa nedá vrátiť späť.\n\nChceš pokračovať?`
      )
    ) {
      return;
    }
    if (
      !confirm(
        `Naozaj pokračovať a natrvalo zmazať účet „${who}“ so všetkými dátami?`
      )
    ) {
      return;
    }
    const password = prompt(
      state.isAdmin && id !== state.userId
        ? "Zadaj svoje admin heslo na zmazanie tohto účtu:"
        : "Zadaj heslo na potvrdenie zmazania účtu:"
    );
    if (password == null) return;
    if (!password) {
      setStatus("Bez hesla účet nezmažem.", true);
      return;
    }
    try {
      await api(`/api/users/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      clearLessonSettings(id);
      if (id === state.userId) {
        clearSession();
        showAuthGate();
        $("authError").textContent = "Účet bol zmazaný.";
        $("authError").hidden = false;
        return;
      }
      state.managedUserId = state.userId;
      await loadManagedUsers();
      await loadMeta();
      await loadVoices();
      await loadLearning();
      setStatus("Účet a všetky jeho dáta boli odstránené.");
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  async function viewProfile() {
    const id = effectiveUserId();
    if (!id) return;
    try {
      const data = await api(`/api/users/${encodeURIComponent(id)}/profile`);
      $("profileText").textContent =
        `${data.profile || ""}\n\n--- HISTORY (tail) ---\n\n${data.history_tail || "(prázdne)"}`;
      $("profilePanel").classList.remove("hidden");
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  async function bootApp() {
    await loadManagedUsers();
    await loadMeta();
    await loadVoices();
    await loadLearning();
    const health = await api("/api/health");
    if (!health.llm_providers.length) {
      setStatus("Chýba LLM API kľúč (OpenAI / Gemini / Mistral). Edge TTS funguje bez kľúča.", true);
    } else {
      setStatus("Pripravené. Režim je hore; detailné nastavenia v paneli. Pre čítanie: Vygeneruj text → Štart čítania.");
    }
  }

  $("mode").addEventListener("change", () => {
    syncModeUi();
    saveLessonSettings();
  });
  $("topic").addEventListener("change", () => {
    syncSubtopics();
    saveLessonSettings();
  });
  $("llm")?.addEventListener("change", () => {
    syncLlmModels();
    saveLessonSettings();
  });
  $("ttsProvider").addEventListener("change", () => {
    loadVoices()
      .then(() => saveLessonSettings())
      .catch((e) => setStatus(e.message, true));
  });
  for (const id of SETTINGS_FIELDS) {
    if (id === "mode" || id === "topic" || id === "llm" || id === "ttsProvider") continue;
    $(id)?.addEventListener("change", () => {
      saveLessonSettings();
      if (id === "speechRate" && state.currentAudio) {
        try {
          state.currentAudio.playbackRate = currentSpeechRate();
        } catch (_) {}
      }
    });
  }
  $("previewVoice").addEventListener("click", () => {
    previewSelectedVoice().catch((e) => setStatus(e.message, true));
  });
  $("startBtn").addEventListener("click", () => startLesson(false));
  $("freeDebateBtn").addEventListener("click", () => startLesson(false, "free_debate"));
  $("restartBtn").addEventListener("click", () => startLesson(true));
  $("refreshLearning").addEventListener("click", () => loadLearning().catch((e) => setStatus(e.message, true)));
  $("practiceOpenBtn").addEventListener("click", openPracticePanel);
  $("practiceCancelBtn").addEventListener("click", closePracticePanel);
  $("practiceStartBtn").addEventListener("click", () => {
    startPractice().catch((e) => setStatus(e.message, true));
  });
  $("sendText").addEventListener("click", sendConversationText);
  $("textInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendConversationText();
  });
  $("playPassage").addEventListener("click", () => {
    ensurePassageAudio()
      .then((b64) => playBase64Mp3(b64))
      .catch((e) => setStatus(e.message, true));
  });
  $("startReadingBtn").addEventListener("click", () => beginReadingListen().catch((e) => setStatus(e.message, true)));
  $("stopRead").addEventListener("click", () => stopRecording("reading"));
  $("explainBtn").addEventListener("click", () => beginExplain().catch((e) => setStatus(e.message, true)));
  $("stopExplain").addEventListener("click", () => stopRecording("explain"));
  $("debateBtn").addEventListener("click", () => startDebate().catch((e) => setStatus(e.message, true)));
  $("recordConv").addEventListener("click", () => startRecording("conversation").catch((e) => setStatus(e.message, true)));
  $("stopConv").addEventListener("click", () => stopRecording("conversation"));
  {
    bindPttMicButton();
  }
  $("recordComp").addEventListener("click", () => startRecording("comprehension").catch((e) => setStatus(e.message, true)));
  $("stopComp").addEventListener("click", () => stopRecording("comprehension"));
  $("renameUserBtn").addEventListener("click", () => renameUser().catch((e) => setStatus(e.message, true)));
  $("deleteUserBtn").addEventListener("click", () => deleteUser().catch((e) => setStatus(e.message, true)));
  $("viewProfileBtn").addEventListener("click", () => viewProfile().catch((e) => setStatus(e.message, true)));
  $("logoutBtn").addEventListener("click", () => logout());
  $("closeProfileBtn").addEventListener("click", () => $("profilePanel").classList.add("hidden"));
  $("addUserBtn").addEventListener("click", openUserModal);
  $("userModalCancel").addEventListener("click", closeUserModal);
  $("userModalBackdrop").addEventListener("click", closeUserModal);
  $("userModalSave").addEventListener("click", () => submitNewUser().catch((e) => setStatus(e.message, true)));
  $("manageUserSelect").addEventListener("change", async () => {
    state.managedUserId = $("manageUserSelect").value || state.userId;
    try {
      await loadMeta();
      await loadVoices();
      await loadLearning();
      const label = $("manageUserSelect").selectedOptions[0]?.textContent || state.managedUserId;
      setStatus(`Spravuješ účet: ${label}`);
    } catch (err) {
      setStatus(err.message, true);
    }
  });
  $("addTopicBtn").addEventListener("click", openTopicModal);
  $("addSubtopicBtn").addEventListener("click", openSubtopicModal);
  $("topicModalCancel").addEventListener("click", closeTopicModal);
  $("topicModalBackdrop").addEventListener("click", closeTopicModal);
  $("topicModalSave").addEventListener("click", () => submitTopic(false).catch((e) => setStatus(e.message, true)));
  $("topicModalForce").addEventListener("click", () => submitTopic(true).catch((e) => setStatus(e.message, true)));
  $("subtopicModalCancel").addEventListener("click", closeSubtopicModal);
  $("subtopicModalBackdrop").addEventListener("click", closeSubtopicModal);
  $("subtopicModalSave").addEventListener("click", () => submitSubtopic(false).catch((e) => setStatus(e.message, true)));
  $("subtopicModalForce").addEventListener("click", () => submitSubtopic(true).catch((e) => setStatus(e.message, true)));

  $("authSubmit").addEventListener("click", () => submitAuth());
  $("authToggle").addEventListener("click", () => {
    setAuthMode(state.authMode === "login" ? "register" : "login");
  });
  $("authPassword").addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitAuth();
  });
  $("authName").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("authPassword").focus();
  });

  (async () => {
    setAuthMode("login");
    // Pri skrytí/zatvorení stránky uvoľni audio (ochrana pred RAM na iOS).
    const cleanupAudio = () => {
      try {
        stopCurrentAudio();
        stopAudioKeepalive();
        if (state.audioContext && state.audioContext.state !== "closed") {
          state.audioContext.suspend().catch(() => {});
        }
      } catch (_) {}
    };
    window.addEventListener("pagehide", cleanupAudio);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) cleanupAudio();
    });

    if (!state.token) {
      showAuthGate();
      return;
    }
    try {
      const me = await api("/api/auth/me");
      saveToken(state.token, me.user);
      showApp();
      await bootApp();
      // Pri refreshi NEVYŽADUJ prompt znova — len localStorage / Permissions API.
      await ensureMicPermission({ quiet: true, prompt: false });
      if (state.micPermission === "granted") {
        setStatus("Pripravené. Mikrofón je už povolený.");
      } else if (state.micPermission === "denied") {
        setStatus("Mikrofón je zablokovaný v prehliadači — povoľ ho v nastaveniach stránky.", true);
      } else {
        setStatus("Mikrofón ešte nie je povolený — pri Štart / Voľná debata ho vyžiadam.");
      }
    } catch (_) {
      clearSession();
      showAuthGate();
    }
  })();
})();
