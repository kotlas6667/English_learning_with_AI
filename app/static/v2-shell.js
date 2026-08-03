(() => {
  const $ = (id) => document.getElementById(id);

  const VIEWS = ["home", "practice", "progress", "profile", "lesson"];
  let currentView = "home";
  let recommendedScenario = null;
  let scenariosCache = [];

  const GOAL_LABELS = {
    travel: "cestovanie",
    work: "prácu",
    daily: "bežný život",
  };

  const SKILL_LABELS = {
    speaking: "Speaking",
    vocabulary: "Slovíčka",
    accuracy: "Presnosť",
  };

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function dailyTargetMinutes() {
    const raw = $("dailyMinutes")?.value || "15";
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : 15;
  }

  function authHeaders() {
    const token = localStorage.getItem("englearning_token");
    return token ? { "X-Session-Token": token } : {};
  }

  function showView(name) {
    const view = VIEWS.includes(name) ? name : "home";
    currentView = view;
    const isLesson = view === "lesson";

    document.body.classList.toggle("lesson-open", isLesson);

    for (const id of ["viewHome", "viewPractice", "viewProgress", "viewProfile", "lesson"]) {
      const el = $(id);
      if (!el) continue;
      const match =
        (id === "viewHome" && view === "home")
        || (id === "viewPractice" && view === "practice")
        || (id === "viewProgress" && view === "progress")
        || (id === "viewProfile" && view === "profile")
        || (id === "lesson" && view === "lesson");
      el.classList.toggle("hidden", !match);
    }

    const nav = $("bottomNav");
    if (nav) {
      nav.classList.toggle("hidden", isLesson || $("appMain")?.classList.contains("hidden"));
      nav.querySelectorAll("[data-nav]").forEach((btn) => {
        btn.classList.toggle("is-active", btn.getAttribute("data-nav") === view);
      });
    }

    if (view === "home") {
      loadScenarios().catch(() => {});
    }
  }

  function wireBottomNav() {
    const nav = $("bottomNav");
    if (!nav) return;
    nav.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-nav]");
      if (!btn) return;
      const name = btn.getAttribute("data-nav");
      if (name) showView(name);
    });
  }

  function setMinQuestions(n) {
    const el = $("minQuestions");
    if (!el) return;
    const want = String(n);
    const has = Array.from(el.options || []).some((o) => o.value === want);
    if (!has) {
      const opt = document.createElement("option");
      opt.value = want;
      opt.textContent = want;
      el.appendChild(opt);
    }
    el.value = want;
  }

  function startDaily() {
    setMinQuestions(8);
    if ($("mode")) $("mode").value = "conversation";
    window.__engSetPendingScenario?.(null);
    window.__engSaveLessonSettings?.();
    window.__engStartLesson?.(false);
  }

  function startRecommended() {
    if (recommendedScenario) {
      startScenario(recommendedScenario);
      return;
    }
    startDaily();
  }

  function startScenario(sc) {
    if (!sc) return;
    if (sc.level && $("level")) {
      const has = Array.from($("level").options || []).some((o) => o.value === sc.level);
      if (has) $("level").value = sc.level;
    }
    if (sc.topic && $("topic")) {
      const hasTopic = Array.from($("topic").options || []).some((o) => o.value === sc.topic);
      if (hasTopic) {
        $("topic").value = sc.topic;
        $("topic").dispatchEvent(new Event("change"));
      }
    }
    if (sc.subtopic && $("subtopic")) {
      const hasSub = Array.from($("subtopic").options || []).some((o) => o.value === sc.subtopic);
      if (hasSub) $("subtopic").value = sc.subtopic;
    }
    setMinQuestions(sc.min_questions || 8);
    if ($("mode")) $("mode").value = "conversation";
    window.__engSetPendingScenario?.(sc.id || null);
    window.__engSaveLessonSettings?.();
    window.__engStartLesson?.(false);
  }

  async function loadScenarios() {
    const list = $("scenariosList");
    const goal = $("learningGoal")?.value || "";
    const qs = goal ? `?topic_id=${encodeURIComponent(goal)}` : "";
    try {
      const res = await fetch(`/api/scenarios${qs}`, { headers: authHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Scenáre sa nepodarilo načítať");
      scenariosCache = Array.isArray(data.scenarios) ? data.scenarios : [];
    } catch (_) {
      scenariosCache = [];
    }
    renderScenarios(scenariosCache);
    updateRecommendation(scenariosCache);
  }

  function renderScenarios(items) {
    const list = $("scenariosList");
    if (!list) return;
    if (!items.length) {
      list.innerHTML = `<p class="scenarios-empty">Žiadne scenáre pre tento cieľ.</p>`;
      return;
    }
    list.innerHTML = "";
    for (const sc of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "scenario-card";
      btn.innerHTML = `
        <strong>${escapeHtml(sc.title || sc.id)}</strong>
        <span class="scenario-meta">${escapeHtml(sc.level || "")} · ${escapeHtml(sc.topic_id || "")}</span>
        <p class="scenario-blurb">${escapeHtml(sc.blurb_sk || "")}</p>`;
      btn.addEventListener("click", () => startScenario(sc));
      list.appendChild(btn);
    }
  }

  function updateRecommendation(items) {
    const title = $("homeRecoTitle");
    const blurb = $("homeRecoBlurb");
    recommendedScenario = items[0] || null;
    if (!recommendedScenario) {
      if (title) title.textContent = "Voľná konverzácia";
      if (blurb) blurb.textContent = "Spusti krátke cvičenie alebo zmeň cieľ v profile.";
      return;
    }
    if (title) title.textContent = recommendedScenario.title || recommendedScenario.id;
    if (blurb) {
      blurb.textContent =
        recommendedScenario.blurb_sk
        || `Úroveň ${recommendedScenario.level || "A2"} · scenár na mieru.`;
    }
  }

  function updateHomeGoal(stats) {
    const target = dailyTargetMinutes();
    const c = stats?.conversation || {};
    let todayMin = Number(c.today_minutes);
    if (!Number.isFinite(todayMin)) todayMin = 0;
    todayMin = Math.max(0, todayMin);
    const pct = Math.min(100, Math.round((todayMin / target) * 100));
    const fill = $("homeGoalFill");
    const meta = $("homeGoalMeta");
    const text = $("homeGoalText");
    if (fill) fill.style.width = `${pct}%`;
    if (meta) meta.textContent = `${todayMin} / ${target} min dnes`;
    if (text) {
      const goal = $("learningGoal")?.value || "daily";
      const label = GOAL_LABELS[goal] || "angličtinu";
      if (todayMin >= target) {
        text.textContent = `Dnešný cieľ splnený — môžeš ešte precvičiť ${label}.`;
      } else {
        text.textContent = `Dnešný cieľ: ${target} min konverzácie (${label}).`;
      }
    }
  }

  function renderSkills(skills) {
    const grid = $("skillsGrid");
    if (!grid) return;
    const data = skills && typeof skills === "object" ? skills : {};
    const keys = ["speaking", "vocabulary", "accuracy"];
    grid.innerHTML = keys
      .map((k) => {
        const val = Math.max(0, Math.min(100, Number(data[k]) || 0));
        const label = SKILL_LABELS[k] || k;
        return `<div class="skill-row">
          <div class="skill-row-head"><strong>${escapeHtml(label)}</strong><span>${val}</span></div>
          <div class="skill-bar" aria-hidden="true"><i style="width:${val}%"></i></div>
        </div>`;
      })
      .join("");
  }

  function updateHomeFromStats(data) {
    updateHomeGoal(data);
    renderSkills(data?.skills);
  }

  function showTurnFeedback(data) {
    const panel = $("turnFeedback");
    if (!panel || !data) return;
    // Prefer raw STT / display — never show AI-invented expansions as "what you said".
    const said =
      data.transcript_raw
      || data.transcript_display
      || data.said
      || data.transcript
      || "";
    const better = data.better || "";
    const tip = data.tip || "";
    const score = data.speak_score ?? data.score;
    const hasAny = said || better || tip || (score != null && score !== "");
    if (!hasAny) {
      panel.classList.add("hidden");
      return;
    }
    if ($("fbSaid")) $("fbSaid").textContent = said || "—";
    if ($("fbBetter")) $("fbBetter").textContent = better || "—";
    if ($("fbTip")) $("fbTip").textContent = tip || "—";
    if ($("fbScore")) {
      $("fbScore").textContent =
        score != null && score !== "" ? String(score) : "—";
    }
    panel.classList.remove("hidden");
  }

  function showRepeatBanner(data) {
    const banner = $("repeatBanner");
    const text = $("repeatBannerText");
    if (!banner) return;
    const needs = !!(data && (data.needs_repeat || data.awaiting_repeat));
    if (!needs) {
      banner.classList.add("hidden");
      return;
    }
    if (text) {
      if (data.unclear) {
        text.textContent = "AI si nie je istá, čo si povedal — zopakuj odpoveď.";
      } else if (data.confused?.length) {
        text.textContent = "Skús ešte raz — AI otázku preformuluje, odpovedz jednoducho.";
      } else {
        text.textContent = "Skús odpoveď ešte raz jasnejšie.";
      }
    }
    banner.classList.remove("hidden");
  }

  function wireRepeatBanner() {
    $("repeatAnswerBtn")?.addEventListener("click", () => {
      $("repeatBanner")?.classList.add("hidden");
      const mic = $("pttMicBtn");
      if (mic && !mic.classList.contains("hidden")) {
        mic.focus();
        mic.click();
      } else {
        window.__engFocusMic?.();
      }
    });
  }

  function showRecap(data) {
    const modal = $("recapModal");
    const body = $("recapBody");
    if (!modal || !body) return;
    const recap = data?.recap && typeof data.recap === "object" ? data.recap : data || {};
    const rows = [
      ["Téma", recap.topic || "—"],
      ["Úroveň", recap.level || "—"],
      ["Otázky", String(recap.questions_asked ?? "—")],
      ["Úspešnosť", recap.success_rate != null ? `${recap.success_rate}%` : "—"],
      ["Zlé odpovede", String(recap.wrongs_count ?? 0)],
      ["Neznáme slovíčka", String(recap.unknowns_count ?? 0)],
      ["Nerozumenie", String(recap.confused_count ?? 0)],
    ];
    body.innerHTML = rows
      .map(
        ([label, value]) =>
          `<div class="recap-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`
      )
      .join("");
    modal.classList.remove("hidden");
  }

  function hideRecap() {
    $("recapModal")?.classList.add("hidden");
  }

  function wireHomeActions() {
    $("homeDailyBtn")?.addEventListener("click", () => startDaily());
    $("homeRecoStart")?.addEventListener("click", () => startRecommended());
    $("homeFreeDebate")?.addEventListener("click", () => {
      if ($("mode")) $("mode").value = "free_debate";
      window.__engSetPendingScenario?.(null);
      window.__engStartLesson?.(false, "free_debate");
    });
    $("homeReading")?.addEventListener("click", () => {
      showView("practice");
      if ($("mode")) $("mode").value = "reading";
      $("mode")?.dispatchEvent(new Event("change"));
    });
    $("homePractice")?.addEventListener("click", () => {
      showView("progress");
      $("practiceOpenBtn")?.click();
    });
  }

  function wireRecap() {
    $("recapClose")?.addEventListener("click", hideRecap);
    $("recapBackdrop")?.addEventListener("click", hideRecap);
    $("recapHome")?.addEventListener("click", () => {
      hideRecap();
      document.body.classList.remove("lesson-open");
      showView("home");
    });
  }

  function wireLearningGoal() {
    $("learningGoal")?.addEventListener("change", () => {
      window.__engSaveLessonSettings?.();
      loadScenarios().catch(() => {});
      updateHomeGoal({});
    });
    $("dailyMinutes")?.addEventListener("change", () => {
      window.__engSaveLessonSettings?.();
      updateHomeGoal({});
    });
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  }

  function revealShellChrome() {
    const app = $("appMain");
    const nav = $("bottomNav");
    if (app && !app.classList.contains("hidden") && nav) {
      nav.classList.remove("hidden");
    }
  }

  // Observe auth → app transition so bottom nav appears after login.
  const appMain = $("appMain");
  if (appMain && typeof MutationObserver !== "undefined") {
    const mo = new MutationObserver(() => {
      revealShellChrome();
      if (!appMain.classList.contains("hidden") && currentView === "home") {
        // keep home
      }
    });
    mo.observe(appMain, { attributes: true, attributeFilter: ["class"] });
  }

  wireBottomNav();
  wireHomeActions();
  wireRecap();
  wireLearningGoal();
  wireRepeatBanner();
  registerServiceWorker();

  window.__engShowView = showView;
  window.__engShowTurnFeedback = showTurnFeedback;
  window.__engShowRepeatBanner = showRepeatBanner;
  window.__engShowRecap = showRecap;
  window.__engUpdateHomeFromStats = updateHomeFromStats;
  window.__engLoadScenarios = loadScenarios;

  // If already logged in when this script runs after app.js boot race, sync chrome.
  if (appMain && !appMain.classList.contains("hidden")) {
    revealShellChrome();
  }
})();
