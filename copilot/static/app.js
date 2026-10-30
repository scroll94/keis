"use strict";

// Названия из taxonomy.json и контракта сервиса — словами, которыми пользуется поддержка
const CATEGORY = {
  "complaint.insult": "Оскорбления и токсичность",
  "complaint.cheat": "Читы и стороннее ПО",
  "complaint.dm": "Убийство без повода, нарушение РП",
  "complaint.scam": "Обман и мошенничество",
  "complaint.rmt_ads": "Реклама и продажа за реальные деньги",
  "complaint.admin": "Жалоба на администратора",
  "complaint.other": "Другое нарушение",
  "complaint.invalid": "Не жалоба или без описания",
  "report.question": "Вопрос по механике игры",
  "report.help": "Просьба о помощи",
  "report.complaint": "Жалоба на игрока через репорт",
  "report.account": "Аккаунт: доступ и взлом",
  "report.payment": "Платёж и донат",
  "report.offtopic": "Оффтоп и пустые сообщения",
};
const URGENT_NAME = { "report.payment": "платёж", "report.account": "взлом аккаунта" };
const PRIORITY = { p0: "Критично", p1: "Высокий", p2: "Обычный", p3: "Низкий" };
const LANG = { ru: "Русский", kk: "Қазақша", uz: "Oʻzbekcha", en: "English", es: "Español", pt: "Português" };
const KIND = { complaint: "Жалоба из лаунчера", report: "Репорт из игры" };
const SERVER = { cis: "сервер СНГ", kz: "сервер Казахстана", uz: "сервер Узбекистана" };
const VERDICT = {
  approved: "одобрить жалобу", need_evidence: "запросить доказательства", rejected: "отклонить жалобу",
  invalid_format: "неверное оформление", duplicate: "дубль", already_punished: "игрок уже наказан",
  appeal_approved: "снять наказание", appeal_rejected: "оставить наказание",
};

const VIEWS = [
  { id: "waiting", title: "Ждут администратора", count: true, test: (it) => it.status === "new" && it.result.needs_human,
    empty: "Все обращения, которым нужен администратор, разобраны." },
  { id: "ready", title: "Готовы к отправке", count: true, test: (it) => it.status === "new" && !it.result.needs_human,
    empty: "Готовых к отправке ответов нет." },
  { id: "all", title: "Все обращения", test: () => true, empty: "Обращений нет." },
  { id: "escalated", title: "Эскалированы", test: (it) => it.status === "escalated", empty: "Эскалированных обращений пока нет." },
  { id: "sent", title: "Отправлены", test: (it) => it.status === "sent", empty: "Отправленных ответов пока нет." },
];

const state = { items: [], llm: null, view: "waiting", selected: null, query: "", loading: true, error: null, dirty: false, note: "" };
const $ = (id) => document.getElementById(id);

// Элементы создаются только через textContent: текст игроков никогда не попадает в разметку как HTML
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const today = new Date().toDateString() === d.toDateString();
  return today ? time : `${d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}, ${time}`;
}

// Метки обезличивания из выгрузки (<url>, <digits>…) показываем словами
const TOKENS = { "<url>": "[ссылка]", "<digits>": "[номер]", "<handle>": "[контакт]", "<email>": "[почта]", "<nick>": "[ник]" };
const clean = (s) => (s || "").replace(/<(url|digits|handle|email|nick)>/g, (m) => TOKENS[m]);
const playerText = (t) => clean(t.messages.filter((m) => m.role === "player").map((m) => m.text).join("\n"));
const priorityRank = (it) => ({ p0: 0, p1: 1, p2: 2, p3: 3 })[it.result.priority] ?? 4;
const currentView = () => VIEWS.find((v) => v.id === state.view);

function visibleItems() {
  const q = state.query.trim().toLowerCase();
  return state.items
    .filter(currentView().test)
    .filter((it) => !q || [it.ticket.ticket_id, it.result.extracted.reported_nick, playerText(it.ticket)]
      .some((s) => (s || "").toLowerCase().includes(q)))
    .sort((a, b) => priorityRank(a) - priorityRank(b) || (a.ticket.created_at || "").localeCompare(b.ticket.created_at || ""));
}

function selectedItem() {
  return state.items.find((it) => it.ticket.ticket_id === state.selected) || null;
}

// ---------- Отрисовка ----------
function render() {
  renderNav();
  renderFinding();
  renderList();
  renderDetail();
}

function renderNav() {
  const nav = $("nav");
  nav.replaceChildren(...VIEWS.map((v) => {
    const n = state.items.filter(v.test).length;
    return h("button", {
      class: "nav-item", "aria-current": state.view === v.id ? "true" : "false",
      onclick: () => switchView(v.id),
    }, h("span", {}, v.title), v.count ? h("span", { class: "count" }, n) : null);
  }));
  const mode = $("mode");
  mode.replaceChildren(
    state.llm
      ? h("p", {}, h("strong", {}, "Черновики: шаблоны и LLM"), `${state.llm.provider} · ${state.llm.model}`)
      : h("p", {}, h("strong", {}, "Черновики: шаблоны"), "LLM не подключена, $0 за обращение"),
    h("p", {}, h("strong", {}, "Решения администраторов"), "сохраняются для дообучения"),
  );
}

function renderFinding() {
  const el = $("finding");
  if (state.loading) return el.replaceChildren("Загружаю очередь…");
  if (state.error) return el.replaceChildren("Очередь не загрузилась.");
  const waiting = state.items.filter(VIEWS[0].test);
  const ready = state.items.filter(VIEWS[1].test);
  const urgent = waiting.filter((it) => it.result.priority === "p0");
  const parts = [];
  if (urgent.length) {
    const names = [...new Set(urgent.map((it) => URGENT_NAME[it.result.category] || "угрозы вне игры"))];
    parts.push(h("span", { class: "urgent" },
      `${urgent.length} ${plural(urgent.length, "критичное ждёт", "критичных ждут", "критичных ждут")} ответа: ${names.join(", ")}.`), " ");
  }
  if (!waiting.length && !ready.length) parts.push(h("span", { class: "rest" }, "Очередь разобрана: новых обращений нет."));
  else parts.push(h("span", { class: "rest" }, `Ждут администратора: ${waiting.length}, готовы к отправке: ${ready.length}.`));
  el.replaceChildren(...parts);
}

function renderList() {
  const list = $("list");
  const view = currentView();
  $("list-title").textContent = view.title;
  if (state.loading) {
    $("list-meta").textContent = "";
    return list.replaceChildren(...Array.from({ length: 6 }, () => h("li", { class: "skeleton", "aria-hidden": "true" }, h("i"), h("i"))));
  }
  if (state.error) {
    $("list-meta").textContent = "";
    return list.replaceChildren(h("li", { class: "empty" }, `Не удалось загрузить очередь: ${state.error}. `,
      h("button", { class: "btn", onclick: load }, "Повторить")));
  }
  const items = visibleItems();
  $("list-meta").textContent = `${items.length} ${plural(items.length, "обращение", "обращения", "обращений")} · сначала срочные`;
  if (!items.length) {
    const q = state.query.trim();
    return list.replaceChildren(h("li", { class: "empty" }, q ? `Ничего не нашлось по запросу «${q}».` : view.empty));
  }
  list.replaceChildren(...items.map((it) => {
    const r = it.result, t = it.ticket, done = it.status !== "new";
    let mark = null;
    if (it.status === "sent") mark = h("span", { class: "pill neutral" }, "Отправлено");
    else if (it.status === "escalated") mark = h("span", { class: "pill neutral" }, "Эскалировано");
    else if (r.priority === "p0" || r.priority === "p1") mark = h("span", { class: `pill ${r.priority}` }, PRIORITY[r.priority]);
    else if (r.is_duplicate) mark = h("span", { class: "pill neutral" }, "Повтор");
    return h("li", {}, h("button", {
      class: `row${done ? " done" : ""}`, "aria-current": it.ticket.ticket_id === state.selected ? "true" : "false",
      "data-id": t.ticket_id, onclick: () => select(t.ticket_id, true),
    },
      h("span", { class: "row-title" }, CATEGORY[r.category] || r.category),
      h("span", { class: "row-slots" }, h("span", { class: "row-lang" }, (r.language || "").toUpperCase()), mark),
      h("span", { class: "row-text" }, h("span", { class: "id" }, t.ticket_id), playerText(t) || "—"),
      h("span", { class: "row-time" }, fmtTime(t.created_at)),
    ));
  }));
}

function fact(label, value, note) {
  const empty = value === null || value === undefined || value === "";
  return h("div", { class: "fact" }, h("dt", {}, label),
    h("dd", {}, empty ? h("span", { class: "dash" }, "—") : value, note ? h("span", { class: "note" }, ` ${note}`) : null));
}

function decisionBox(it) {
  const r = it.result;
  if (it.status === "sent") {
    return h("div", { class: "decision done" }, h("h3", {}, "Ответ отправлен"),
      h("p", {}, `${fmtTime(it.decided_at)}${it.final_text ? ", с правкой администратора" : ", черновик без изменений"}.`));
  }
  if (it.status === "escalated") {
    return h("div", { class: "decision done" }, h("h3", {}, "Передано старшей администрации"), h("p", {}, `${fmtTime(it.decided_at)}.`));
  }
  if (r.needs_human) {
    // Коды категорий в причинах («report.payment») показываем названиями
    const human = (s) => s.replace(/(complaint|report)\.[a-z_]+/g, (code) => `«${CATEGORY[code] || code}»`);
    return h("div", { class: "decision human" }, h("h3", {}, "Нужен администратор"),
      h("ul", {}, (r.needs_human_reasons || []).map((s) => h("li", {}, human(s[0].toUpperCase() + s.slice(1))))));
  }
  let why = "Черновик по проверенному шаблону, решения по существу не требуется.";
  if (r.is_spam) why = "Сообщение без содержания: черновик просит описать проблему.";
  else if (r.is_duplicate) why = `Повтор обращения ${r.duplicate_of}: черновик просит дождаться ответа по первому.`;
  else if (r.draft.template === "question_kb") why = "Ответ взят из базы прошлых ответов администраторов на такой же вопрос.";
  else if (r.draft.template === "llm") why = "Черновик написан LLM и прошёл проверки: цитаты существуют, обещаний нет.";
  return h("div", { class: "decision auto" }, h("h3", {}, "Можно ответить без администратора"), h("p", {}, why));
}

function renderDetail() {
  const pane = $("detail");
  const it = selectedItem();
  if (state.loading) return pane.replaceChildren(h("div", { class: "detail-body" }, h("div", { class: "skeleton" }, h("i"), h("i"), h("i"))));
  if (!it) {
    return pane.replaceChildren(h("div", { class: "detail-body" },
      h("p", { class: "empty" }, state.error ? "Обращение недоступно, пока очередь не загрузится." : "Выберите обращение в списке слева.")));
  }
  const t = it.ticket, r = it.result, x = r.extracted, d = r.draft, open = it.status === "new";
  const accused = t.messages.filter((m) => m.role === "reported_player");
  const evidence = [];
  if (x.evidence.images_count) evidence.push(`${x.evidence.images_count} ${plural(x.evidence.images_count, "скриншот", "скриншота", "скриншотов")}`);
  if (x.evidence.links) evidence.push(`${x.evidence.links} ${plural(x.evidence.links, "ссылка", "ссылки", "ссылок")}`);
  const source = d.template === "llm" ? "LLM" : d.template === "question_kb" ? "база прошлых ответов" : "шаблон";
  const verdict = r.suggested_verdict;

  const draft = h("textarea", {
    class: "draft", id: "draft", "aria-label": "Черновик ответа игроку", readonly: !open,
    oninput: () => { state.dirty = true; state.note = "Есть несохранённая правка"; updateStatus(); },
  });
  draft.value = it.final_text || d.text;

  pane.replaceChildren(
    h("div", { class: "detail-body" },
      h("button", { class: "btn back", onclick: showList }, "← К очереди"),
      h("div", { class: "d-meta" }, h("span", { class: "mono" }, t.ticket_id), "·", h("span", {}, KIND[t.kind] || t.kind),
        "·", h("span", { class: "num" }, fmtTime(t.created_at)), t.region ? ["·", h("span", {}, SERVER[t.region] || t.region)] : null),
      h("div", { class: "d-head" }, h("h2", { id: "detail-title", tabindex: "-1" }, CATEGORY[r.category] || r.category),
        h("span", { class: `pill ${r.priority === "p0" || r.priority === "p1" ? r.priority : "neutral"}` }, PRIORITY[r.priority]),
        h("span", { class: "meta d-lang" }, LANG[r.language] || r.language)),
      decisionBox(it),
      h("section", { class: "block" },
        h("div", { class: "block-head" }, h("h3", {}, "Сообщение игрока"), h("span", { class: "meta" }, "слова игрока, не проверены")),
        h("p", { class: "message" }, playerText(t) || "—"),
        accused.map((m) => h("p", { class: "message" }, h("span", { class: "who" }, "Комментарий обвиняемого"), clean(m.text)))),
      h("section", { class: "block" },
        h("div", { class: "block-head" }, h("h3", {}, "Что известно")),
        h("dl", { class: "facts" },
          t.kind === "complaint" ? fact("Нарушитель", x.reported_nick) : fact("Игрок по номеру", (x.player_ids || []).join(", ")),
          fact("Доказательства", evidence.join(" · ") || "нет"),
          fact("Пункты от игрока", x.rule_refs_claimed.length ? h("span", { class: "mono" }, x.rule_refs_claimed.join(", ")) : null,
            x.rule_refs_claimed.length ? "не проверены" : null),
          fact("Повтор", r.is_duplicate ? h("span", {}, "обращения ", h("span", { class: "mono" }, r.duplicate_of)) : "нет"),
          fact("Вероятный вердикт", verdict ? `${VERDICT[verdict.label] || verdict.label} · ${Math.round(verdict.p * 100)}%` : null),
          fact("Уверенность в категории", h("span", { class: "num" }, `${Math.round(r.confidence * 100)}%`)))),
      h("section", { class: "block" },
        h("div", { class: "block-head" }, h("h3", {}, "Черновик ответа"),
          h("span", { class: "meta" }, `${source} · ${LANG[d.language] || d.language}`),
          open ? h("span", { class: "meta" }, "можно править перед отправкой") : null),
        draft,
        d.citations.length
          ? h("ul", { class: "cites", "aria-label": "Основания из правил" }, d.citations.map((c) => h("li", { class: "cite" },
              h("span", { class: "code" }, c.ref), h("span", { class: "section" }, c.section), h("q", {}, c.quote))))
          : h("p", { class: "no-cites" }, "Без ссылок на правила: в этой ситуации они не нужны.")),
    ),
    h("div", { class: "actions" },
      h("button", { class: "btn primary", disabled: !open, onclick: () => decide("send") }, "Отправить игроку"),
      h("button", { class: "btn", disabled: !open, onclick: () => decide("save") }, "Сохранить правку"),
      h("button", { class: "btn", disabled: !open, onclick: () => decide("escalate") }, "Эскалировать"),
      h("span", { class: "status", id: "status", role: "status" }),
    ),
  );
  updateStatus();
}

function updateStatus() {
  const el = $("status");
  if (!el) return;
  const it = selectedItem();
  if (it && it.status !== "new") el.textContent = `Решение принято ${fmtTime(it.decided_at)}`;
  else el.textContent = state.note || (it && it.final_text ? "Черновик изменён администратором" : "");
}

// ---------- Действия ----------
function switchView(id) {
  state.view = id;
  $("sidebar").classList.remove("open");
  $("menu-btn").setAttribute("aria-expanded", "false");
  const items = visibleItems();
  if (!items.some((it) => it.ticket.ticket_id === state.selected)) select(items[0]?.ticket.ticket_id ?? null, false);
  render();
}

function select(id, user) {
  if (state.dirty && id !== state.selected && !confirm("Правка черновика не сохранена. Перейти без сохранения?")) return;
  state.selected = id;
  state.dirty = false;
  state.note = "";
  if (user) {
    document.body.dataset.pane = "detail";
    render();
    $("detail").scrollTop = 0;
    $("detail-title")?.focus({ preventScroll: true });
  }
}

function showList() {
  document.body.dataset.pane = "list";
  render();
  document.querySelector(`.row[data-id="${CSS.escape(state.selected || "")}"]`)?.focus();
}

async function decide(action) {
  const it = selectedItem();
  if (!it) return;
  const before = visibleItems().map((x) => x.ticket.ticket_id);
  const text = $("draft").value;
  try {
    const res = await fetch(`/api/tickets/${encodeURIComponent(it.ticket.ticket_id)}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    state.items = state.items.map((x) => (x.ticket.ticket_id === updated.ticket.ticket_id ? updated : x));
    state.dirty = false;
    const id = updated.ticket.ticket_id;
    if (action === "save") {
      state.note = `Правка сохранена ${fmtTime(updated.decided_at)}`;
      render();
      return;
    }
    $("flash").textContent = `${id}: ${action === "send" ? "ответ отправлен" : "передано старшей администрации"} в ${fmtTime(updated.decided_at)}`;
    // Следующее обращение того же раздела — чтобы разбирать очередь подряд
    const after = visibleItems().map((x) => x.ticket.ticket_id);
    const next = after.includes(id) ? id : before.slice(before.indexOf(id) + 1).find((x) => after.includes(x)) ?? after[after.length - 1] ?? null;
    state.selected = next;
    state.note = "";
    render();
  } catch (e) {
    state.note = `Не удалось сохранить решение (${e.message}). Попробуйте ещё раз.`;
    updateStatus();
  }
}

async function load() {
  state.loading = true;
  state.error = null;
  render();
  try {
    const res = await fetch("/api/queue");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.items = data.items;
    state.llm = data.llm;
    state.loading = false;
    state.selected = visibleItems()[0]?.ticket.ticket_id ?? null;
  } catch (e) {
    state.loading = false;
    state.error = e.message;
  }
  render();
}

// ---------- Новое обращение ----------
function setupDialog() {
  const dialog = $("new-dialog"), form = $("new-form");
  const syncKind = () => {
    const complaint = form.kind.value === "complaint";
    form.querySelectorAll("[data-complaint]").forEach((el) => { el.hidden = !complaint; });
  };
  form.addEventListener("change", syncKind);
  $("new-btn").addEventListener("click", () => { form.reset(); syncKind(); dialog.showModal(); form.text.focus(); });
  form.addEventListener("submit", async (e) => {
    if (e.submitter?.value !== "ok") return;
    e.preventDefault();
    if (!form.reportValidity()) return;
    const lang = form.server.value;
    const kind = form.kind.value;
    const ticket = {
      kind, server_lang: lang, region: { ru: "cis", kk: "kz", uz: "uz" }[lang],
      reporter_hash: `web-${Date.now()}`,
      messages: [{ role: "player", text: form.text.value.trim() }],
    };
    if (kind === "complaint") {
      ticket.images_count = Number(form.images.value) || 0;
      if (form.nick.value.trim()) ticket.reported_nick = form.nick.value.trim();
    }
    $("new-submit").disabled = true;
    try {
      const res = await fetch("/api/tickets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ticket) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const item = await res.json();
      state.items.push(item);
      state.view = item.result.needs_human ? "waiting" : "ready";
      dialog.close();
      $("flash").textContent = `${item.ticket.ticket_id}: обращение разобрано`;
      select(item.ticket.ticket_id, true);
    } catch (err) {
      alert(`Не удалось разобрать обращение: ${err.message}`);
    } finally {
      $("new-submit").disabled = false;
    }
  });
}

// ---------- Запуск ----------
$("search").addEventListener("input", (e) => {
  state.query = e.target.value;
  const items = visibleItems();
  if (!items.some((it) => it.ticket.ticket_id === state.selected)) state.selected = items[0]?.ticket.ticket_id ?? null;
  render();
});
$("menu-btn").addEventListener("click", () => {
  const open = $("sidebar").classList.toggle("open");
  $("menu-btn").setAttribute("aria-expanded", String(open));
});
$("list").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const ids = visibleItems().map((it) => it.ticket.ticket_id);
  const i = ids.indexOf(state.selected);
  const next = ids[Math.min(ids.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
  if (!next || next === state.selected) return;
  e.preventDefault();
  state.selected = next;
  state.dirty = false;
  state.note = "";
  render();
  document.querySelector(`.row[data-id="${CSS.escape(next)}"]`)?.focus();
});
setupDialog();
load();
