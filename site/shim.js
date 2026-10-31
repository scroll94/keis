// Сервер для GitHub Pages: отвечает на запросы /api/ прямо в браузере. Данные собирает scripts/build_site.py.
(() => {
  const D = window.SITE_DATA;
  const rx = (pattern) => new RegExp(pattern, "iu");
  const has = (pattern, text) => rx(pattern).test(text);
  const opened = new Date().toISOString();
  const items = new Map(D.items.map((it) => [String(it.ticket.ticket_id), { ...it, received_at: opened }]));
  const playerText = (t) => (t.messages || []).filter((m) => m.role === "player").map((m) => m.text).join("\n");
  const baked = new Map(D.items.map((it) => [playerText(it.ticket), it]));

  const fixText = (raw, server) => (server === "kk" || /[ќѓћјѕ]/.test(raw)
    ? [...raw].map((c) => D.fix[c] ?? c).join("") : raw).replace(/[ \t]+/g, " ").trim();

  function detectLang(text, server) {
    const letters = [...text].filter((c) => /\p{L}/u.test(c));
    if (letters.length < 2) return server === "kk" || server === "uz" ? server : "ru";
    if (letters.filter((c) => /[Ѐ-ӿ]/.test(c)).length >= letters.length / 2) {
      const hits = [...text].filter((c) => D.kk_letters.includes(c)).length + (server === "kk" ? [...text].filter((c) => "іІ".includes(c)).length : 0);
      if (hits >= 2 || (server === "kk" && hits >= 1)) return "kk";
      return /[ўҳЎҲ]/.test(text) ? "uz" : "ru";
    }
    if (has(D.re.uz, text)) return "uz";
    if (has(D.re.ru_translit, text)) return "ru";
    if (has(D.re.en, text)) return "en";
    return server === "uz" ? "uz" : "ru";
  }

  // Та же логика, что copilot.classify.keyword_category
  function keywordCategory(kind, text, evidence) {
    const t = text.toLowerCase();
    if (kind === "report") {
      if (has(D.re.empty, t)) return ["report.offtopic", 0.9, "пустое или служебное сообщение"];
      for (const [cat, pattern] of Object.entries(D.re.report)) {
        const m = t.match(rx(pattern));
        if (m) return [cat, 0.7, `ключевое слово «${m[0].trim()}»`];
      }
      return [t.length > 25 ? "report.question" : "report.offtopic", 0.4, "нет явных признаков"];
    }
    if (has(D.re.invalid, t) && !evidence) return ["complaint.invalid", 0.85, "нет описания и доказательств"];
    for (const [cat, pattern] of Object.entries(D.re.complaint)) {
      const m = t.match(rx(pattern));
      if (m) return [cat, 0.7, `ключевое слово «${m[0].trim()}»`];
    }
    if (has(D.re.payment, t) || has(D.re.account, t)) return ["complaint.other", 0.5, "жалоба с темой аккаунта или платежа"];
    if (!evidence && t.length < 15) return ["complaint.invalid", 0.6, "короткая жалоба без доказательств"];
    return ["complaint.other", 0.4, "нет явных признаков"];
  }

  function triage(t, id) {
    const raw = playerText(t);
    const text = fixText(raw, t.server_lang);
    const images = Number(t.images_count) || 0;
    const links = (text.match(/https?:\/\/|<url>/g) || []).length;
    const evidence = images > 0 || links > 0 ? 1 : 0;
    let [cat, conf, why] = keywordCategory(t.kind, text, evidence);
    if (t.kind === "complaint" && has(D.re.appeal, text)) [cat, why] = ["complaint.admin", "оспаривание своего наказания"];
    const lang = detectLang(text, t.server_lang);
    const nick = t.reported_nick ? 1 : 0;
    const key = t.kind === "report" ? `${cat}|${lang}` : `${cat}|${evidence}|${nick}|${lang}`;
    const base = D.archetypes[key] || D.archetypes[`complaint.other|${evidence}|${nick}|${lang}`];
    const nickJson = JSON.stringify(t.reported_nick || "").slice(1, -1);
    const r = JSON.parse(JSON.stringify(base).replaceAll(D.nick_token, nickJson));
    const critical = has(D.re.p0, text);
    const refund = has(D.re.promise, text);
    const lowConfidence = conf < 0.5;
    r.ticket_id = id;
    r.language = lang;
    r.lang = lang;
    r.category = cat;
    r.priority = critical ? "p0" : r.priority;
    r.confidence = conf;
    r.extracted.evidence = { images_count: images, links };
    r.extracted.has_evidence = Boolean(evidence);
    r.extracted.server = t.region || null;
    r.extracted.region = t.region || null;
    r.text_fix = raw.split(/\s+/).join(" ") !== text.split(/\s+/).join(" ") ? { original: raw, fixed: text } : null;
    if (critical) r.needs_human_reasons.push("критичный приоритет");
    if (refund) r.needs_human_reasons.push("просьба о возврате или снятии наказания");
    if (lowConfidence) r.needs_human_reasons.push(`низкая уверенность (${conf.toFixed(2)})`);
    r.needs_human = r.needs_human || critical || refund || lowConfidence;
    r.reasons = [`категория: ${why}`, "разобрано в браузере по ключевым словам, модель работает только на сервере", ...r.needs_human_reasons];
    return r;
  }

  function addTicket(t) {
    const id = `new-${String(items.size + 1).padStart(3, "0")}`;
    const started = performance.now();
    const known = baked.get(playerText(t));
    const result = known ? { ...JSON.parse(JSON.stringify(known.result)), ticket_id: id } : triage({ kind: "report", ...t }, id);
    const created = new Date().toISOString();
    const item = {
      ticket: { ...t, ticket_id: id, created_at: created }, result, status: "new", final_text: null, decided_at: null,
      // Для заранее разобранных обращений — время настоящего сервиса
      received_at: created, source: "form", processing_ms: known ? known.processing_ms : Math.round((performance.now() - started) * 10) / 10,
    };
    items.set(id, item);
    return item;
  }

  function applyDecision(item, action, text) {
    const draft = item.result.draft.text;
    if (action === "reopen") return Object.assign(item, { status: "new", final_text: null, decided_at: null });
    const typed = (text || "").trim().replaceAll("{ник}", item.result.extracted.nickname || "этого игрока");
    const final = typed || item.final_text || draft;
    item.final_text = final !== draft ? final : null;
    item.decided_at = new Date().toISOString();
    if (action !== "save") item.status = action === "send" ? "sent" : "escalated";
    return item;
  }

  const reply = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

  function route(path, method, body) {
    const decision = path.match(/^\/api\/tickets\/(.+)\/decision$/);
    if (path === "/api/info") return reply({ public: true, static: true, llm: null, validation_available: false, batches: [] });
    if (path === "/api/queue") return reply({ items: [...items.values()], llm: null, batches: [] });
    if (path.startsWith("/api/quick")) {
      const lang = new URLSearchParams(path.split("?")[1]).get("lang");
      return reply(D.quick[lang] || D.quick.ru);
    }
    if (path === "/api/tickets" && method === "POST") return reply(addTicket(body));
    if (path === "/api/tickets/bulk") {
      return reply({ items: body.ids.filter((id) => items.has(id)).map((id) => applyDecision(items.get(id), body.action, body.text)) });
    }
    if (decision) {
      const item = items.get(decodeURIComponent(decision[1]));
      return item ? reply(applyDecision(item, body.action, body.text)) : reply({ detail: "нет обращения" }, 404);
    }
    return reply({ detail: "на этой версии сайта нет сервера" }, 403);
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (url, options = {}) => {
    const path = String(url);
    if (!path.startsWith("/api/")) return realFetch(url, options);
    return route(path, options.method || "GET", options.body ? JSON.parse(options.body) : null);
  };
})();
