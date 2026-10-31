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
const TEMPLATE = {
  complaint_review: "жалоба принята к рассмотрению", complaint_no_evidence: "нужны доказательства",
  complaint_invalid: "неверное оформление", complaint_rejected: "нарушений не выявлено",
  already_punished: "игрок уже наказан", duplicate: "повтор обращения", appeal: "обращение по наказанию",
  appeal_rejected: "наказание оставлено", offtopic: "просьба описать проблему", help: "запрос помощи",
  question: "просьба уточнить вопрос", question_kb: "ответ из базы прошлых ответов",
  report_complaint: "как подать жалобу", account: "аккаунт и безопасность", payment: "проверка платежа",
  fallback: "запасной ответ",
};

const VIEWS = [
  { id: "waiting", title: "Ждут администратора", count: true, test: (it) => it.status === "new" && it.result.needs_human,
    empty: "Все обращения, которым нужен администратор, разобраны." },
  { id: "ready", title: "Готовы к отправке", count: true, test: (it) => it.status === "new" && !it.result.needs_human,
    empty: "Готовых к отправке ответов нет." },
  { id: "all", title: "Все обращения", test: () => true, empty: "Обращений нет." },
  { id: "escalated", title: "Эскалированы", test: (it) => it.status === "escalated", empty: "Эскалированных обращений пока нет." },
  { id: "sent", title: "Отправлены", test: (it) => it.status === "sent", empty: "Отправленных ответов пока нет." },
  { id: "archive", title: "Архив", test: (it) => it.status !== "new", empty: "Закрытых обращений пока нет." },
];
const TOOLS = [
  { id: "batch", title: "Загрузка обращений", sub: "Файл с обращениями разбирается тем же конвейером, что и обращения из игры. Каждое обращение попадает в очередь." },
  { id: "load", title: "Проверка нагрузки", nav: "Нагрузка", sub: "Запросы идут на POST /triage этого сервиса из отдельного процесса — так, как их будет присылать игра." },
];

const state = {
  items: [], llm: null, batches: [], info: null,
  mode: "queue", view: "waiting", source: "all", selected: null, query: "",
  loading: true, error: null, dirty: false, note: "",
  checked: new Set(), tags: new Set(), listMode: "list", activeGroup: null, bulkText: null, lastChecked: null, quick: {}, chipsOpen: false,
  job: null, jobError: "", load: null, loadError: "", loadN: 500, loadC: 10, loadSource: "demo",
};
const timers = { job: null, load: null, toast: null };
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
const fmtNum = (n) => Number(n).toLocaleString("ru-RU");
const dec = (x, d) => Number(x).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtMs = (x) => (x == null ? "—" : x < 1000 ? `${x < 10 ? dec(x, 1) : Math.round(x)} мс` : `${dec(x / 1000, 2)} с`);
const fmtSec = (s) => (s < 60 ? `${dec(s, 1)} с` : `${Math.floor(s / 60)} мин ${Math.round(s % 60)} с`);
const pct = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : "0%");

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const today = new Date().toDateString() === d.toDateString();
  return today ? time : `${d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}, ${time}`;
}

// Метки обезличивания из выгрузки (<url>, <digits>…) показываем словами
const TOKENS = { "<url>": "[ссылка]", "<digits>": "[номер]", "<handle>": "[контакт]", "<email>": "[почта]", "<nick>": "[ник]" };
const clean = (s) => String(s ?? "").replace(/<(url|digits|handle|email|nick)>/g, (m) => TOKENS[m]);
const playerText = (t) => clean((Array.isArray(t.messages) ? t.messages : []).filter((m) => m.role === "player").map((m) => m.text).join("\n"));
const priorityRank = (it) => ({ p0: 0, p1: 1, p2: 2, p3: 3 })[it.result.priority] ?? 4;
const currentView = () => VIEWS.find((v) => v.id === state.view);
const scoped = () => state.items.filter((it) => state.source === "all" || it.source === state.source);

const itemId = (it) => String(it.ticket.ticket_id);
const shortId = (id) => (id.length > 10 ? id.slice(0, 8) : id);

// Теги обращения: по ним фильтруется очередь. Значение после двоеточия — код, подпись даёт tagLabel
function tagsOf(it) {
  const r = it.result, x = r.extracted;
  return [`cat:${r.category}`, `lang:${r.language}`, `prio:${r.priority}`,
    ...(x.nickname ? [`nick:${x.nickname}`] : []), ...x.rule_refs.map((ref) => `rule:${ref}`),
    ...(x.has_evidence ? [] : ["flag:noev"]), ...(r.is_duplicate ? ["flag:dup"] : []), ...(r.is_spam ? ["flag:spam"] : [])];
}

function tagLabel(tag) {
  const i = tag.indexOf(":"), kind = tag.slice(0, i), v = tag.slice(i + 1);
  if (kind === "cat") return CATEGORY[v] || v;
  if (kind === "lang") return LANG[v] || v;
  if (kind === "prio") return PRIORITY[v] || v;
  if (kind === "rule") return `Пункт ${v}`;
  if (kind === "flag") return { noev: "Без доказательств", dup: "Повторы", spam: "Спам" }[v] || v;
  return v;
}

function matchesSearch(it, q) {
  if (!q) return true;
  const r = it.result;
  return [it.ticket.ticket_id, r.extracted.nickname, playerText(it.ticket), CATEGORY[r.category], ...r.extracted.rule_refs]
    .some((s) => String(s ?? "").toLowerCase().includes(q));
}

function visibleItems() {
  const q = state.query.trim().toLowerCase();
  return scoped()
    .filter(currentView().test)
    .filter((it) => matchesSearch(it, q))
    .filter((it) => { const tags = tagsOf(it); return [...state.tags].every((t) => tags.includes(t)); })
    .sort((a, b) => (state.view === "archive" ? String(b.decided_at || "").localeCompare(String(a.decided_at || "")) : 0)
      || priorityRank(a) - priorityRank(b) || String(a.ticket.created_at || "").localeCompare(String(b.ticket.created_at || "")));
}

// Группа похожих: та же тема, тот же ответ, тот же язык — такие обращения можно закрыть разом
const groupKey = (it) => [it.result.category, it.result.draft.template, it.result.language, it.result.extracted.nickname ? 1 : 0].join("|");

function groupsOf(items) {
  const map = new Map();
  for (const it of items) {
    const k = groupKey(it);
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(it);
  }
  return [...map].map(([key, list]) => ({ key, items: list }))
    .sort((a, b) => priorityRank(a.items[0]) - priorityRank(b.items[0]) || b.items.length - a.items.length);
}

const selectedItem = () => state.items.find((it) => String(it.ticket.ticket_id) === state.selected) || null;
const sourceName = (id) => (id === "demo" ? "Демо-набор" : id === "form" ? "Добавленные вручную"
  : `Пачка «${state.batches.find((b) => b.id === id)?.name ?? id}»`);

// ---------- Отрисовка ----------
function render() {
  renderNav();
  const queue = state.mode === "queue";
  $("panes").hidden = !queue;
  $("batch-view").hidden = state.mode !== "batch";
  $("load-view").hidden = state.mode !== "load";
  const tool = TOOLS.find((t) => t.id === state.mode);
  $("page-title").textContent = queue ? "Очередь обращений" : tool.title;
  if (queue) {
    renderFinding();
    renderList();
    renderDetail();
  } else {
    $("finding").replaceChildren(h("span", { class: "rest" }, tool.sub));
    if (state.mode === "batch") renderBatch();
    else renderLoad();
  }
}

function renderNav() {
  const items = scoped();
  $("nav").replaceChildren(...VIEWS.map((v) => h("button", {
    class: "nav-item", "aria-current": state.mode === "queue" && state.view === v.id ? "true" : "false",
    onclick: () => switchView(v.id),
  }, h("span", {}, v.title), v.count ? h("span", { class: "count" }, fmtNum(items.filter(v.test).length)) : null)));
  $("nav-tools").replaceChildren(...TOOLS.filter((t) => !(state.info?.public && t.id === "batch") && !(state.info?.static && t.id === "load")).map((t) => h("button", {
    class: "nav-item", "aria-current": state.mode === t.id ? "true" : "false", onclick: () => switchMode(t.id),
  }, h("span", {}, t.nav || t.title),
    t.id === "batch" && state.job && !state.job.finished ? h("span", { class: "count" }, pct(state.job.done, state.job.total)) : null,
    t.id === "load" && state.load && !state.load.finished ? h("span", { class: "count" }, pct(state.load.done || 0, state.load.total)) : null)));
  $("mode").replaceChildren(
    state.llm
      ? h("p", {}, h("strong", {}, "Черновики: шаблоны и LLM"), `${state.llm.model}${state.info?.llm?.rpm ? `, до ${state.info.llm.rpm} в минуту` : ""}`)
      : h("p", {}, h("strong", {}, "Черновики: шаблоны"), "LLM не подключена, $0 за обращение"),
    state.info?.public
      ? h("p", {}, h("strong", {}, "Открытая демо-версия"), state.info.static
        ? "без сервера: демо-обращения разобраны заранее, новые разбираются в браузере по ключевым словам, решения живут до перезагрузки страницы"
        : "обращения выдуманные, цитаты правил скрыты, база ответов и LLM выключены, очередь общая для всех")
      : h("p", {}, h("strong", {}, "Решения администраторов"), "сохраняются для дообучения"),
  );
}

function renderFinding() {
  const el = $("finding");
  if (state.loading) return el.replaceChildren("Загружаю очередь…");
  if (state.error) return el.replaceChildren("Очередь не загрузилась.");
  const items = scoped();
  const waiting = items.filter(VIEWS[0].test);
  const ready = items.filter(VIEWS[1].test);
  const urgent = waiting.filter((it) => it.result.priority === "p0");
  const parts = [];
  if (urgent.length) {
    const names = [...new Set(urgent.map((it) => URGENT_NAME[it.result.category] || "угрозы вне игры"))];
    parts.push(h("span", { class: "urgent" },
      `${urgent.length} ${plural(urgent.length, "критичное ждёт", "критичных ждут", "критичных ждут")} ответа: ${names.join(", ")}.`), " ");
  }
  if (!waiting.length && !ready.length) parts.push(h("span", { class: "rest" }, "Очередь разобрана: новых обращений нет."));
  else parts.push(h("span", { class: "rest" }, `Ждут администратора: ${fmtNum(waiting.length)}, готовы к отправке: ${fmtNum(ready.length)}.`));
  el.replaceChildren(...parts);
}

function renderSourceSelect() {
  const sources = ["all", ...new Set(state.items.map((it) => it.source))];
  if (sources.length <= 2) return null;
  return h("label", { class: "source" }, h("span", { class: "sr-only" }, "Источник обращений"),
    h("select", { class: "input select-sm", onchange: (e) => { state.source = e.target.value; reselect(); render(); } },
      sources.map((s) => h("option", { value: s, selected: s === state.source },
        s === "all" ? "Все источники" : sourceName(s)))));
}

function renderChips(items) {
  const counts = new Map();
  for (const it of items) for (const t of tagsOf(it)) counts.set(t, (counts.get(t) || 0) + 1);
  const pick = (prefix, n, min = 1) => [...counts].filter(([t, c]) => t.startsWith(prefix) && c >= min && c < items.length && !state.tags.has(t))
    .sort((a, b) => b[1] - a[1]).slice(0, n);
  const chips = [...pick("cat:", 5), ...pick("lang:", 3), ...pick("prio:", 4), ...pick("rule:", 3, 2), ...pick("nick:", 3, 2), ...pick("flag:", 3)];
  const top = chips.sort((a, b) => b[1] - a[1]);
  const shown = state.chipsOpen ? top : top.slice(0, 4);
  $("chips").replaceChildren(
    ...[...state.tags].map((t) => h("button", { class: "chip on", onclick: () => toggleTag(t), "aria-label": `Убрать фильтр ${tagLabel(t)}` }, tagLabel(t), h("span", { "aria-hidden": "true" }, " ×"))),
    ...shown.map(([t, c]) => h("button", { class: "chip", onclick: () => toggleTag(t) }, tagLabel(t), " ", h("span", { class: "chip-n" }, fmtNum(c)))),
    ...(top.length > 4 ? [h("button", { class: "link chip-more", onclick: () => { state.chipsOpen = !state.chipsOpen; renderList(); } },
      state.chipsOpen ? "Свернуть" : `Ещё ${top.length - 4}`)] : []));
}

function renderListTools(items) {
  const open = items.filter((it) => it.status === "new");
  const allChecked = open.length > 0 && open.every((it) => state.checked.has(itemId(it)));
  $("list-tools").replaceChildren(...[
    h("div", { class: "segmented seg-sm", role: "group", "aria-label": "Вид очереди" },
      [["list", "Список"], ["groups", "Группы"]].map(([m, l]) => h("button", {
        type: "button", "aria-pressed": state.listMode === m ? "true" : "false", onclick: () => setListMode(m) }, l))),
    state.listMode === "list" && open.length
      ? h("button", { class: "link", onclick: () => setChecked(allChecked ? [] : open) }, allChecked ? "Снять выбор" : "Выбрать все") : null,
    state.checked.size ? h("button", { class: "btn btn-sm bulk-open", onclick: () => { document.body.dataset.pane = "detail"; render(); } }, `Выбрано ${fmtNum(state.checked.size)}`) : null,
    renderSourceSelect(),
  ].filter(Boolean));
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
      h("button", { class: "btn", onclick: () => loadQueue(true) }, "Повторить")));
  }
  const items = visibleItems();
  const groups = state.listMode === "groups" ? groupsOf(items.filter((it) => it.status === "new")) : null;
  $("list-meta").textContent = groups
    ? `${fmtNum(groups.length)} ${plural(groups.length, "группа", "группы", "групп")} · ${fmtNum(items.length)} ${plural(items.length, "обращение", "обращения", "обращений")}`
    : `${fmtNum(items.length)} ${plural(items.length, "обращение", "обращения", "обращений")} · сначала срочные`;
  renderChips(items);
  renderListTools(items);
  if (!items.length || (groups && !groups.length)) {
    const q = state.query.trim();
    const filtered = q || state.tags.size;
    return list.replaceChildren(h("li", { class: "empty" }, filtered ? "Под эти условия ничего не подходит. " : view.empty,
      filtered ? h("button", { class: "link", onclick: resetFilters }, "Сбросить фильтры") : null));
  }
  if (groups) return list.replaceChildren(...groups.map(groupRow));
  list.replaceChildren(...items.map((it) => {
    const r = it.result, t = it.ticket, done = it.status !== "new", id = itemId(it);
    let mark = null;
    if (it.status === "sent") mark = h("span", { class: "pill neutral" }, "Отправлено");
    else if (it.status === "escalated") mark = h("span", { class: "pill neutral" }, "Эскалировано");
    else if (r.priority === "p0" || r.priority === "p1") mark = h("span", { class: `pill ${r.priority}` }, PRIORITY[r.priority]);
    else if (r.is_duplicate) mark = h("span", { class: "pill neutral" }, "Повтор");
    const box = h("input", { type: "checkbox", class: "row-check", "data-check": id, "aria-label": `Выбрать ${id}`, disabled: done,
      onclick: (e) => toggleChecked(id, e.shiftKey) });
    box.checked = state.checked.has(id);
    return h("li", { class: "row-wrap" }, box, h("button", {
      class: `row${done ? " done" : ""}`, "aria-current": !state.checked.size && id === state.selected ? "true" : "false",
      "data-id": id, onclick: () => select(id, true),
    },
      h("span", { class: "row-title" }, CATEGORY[r.category] || r.category),
      h("span", { class: "row-slots" }, h("span", { class: "row-lang" }, (r.language || "").toUpperCase()), mark),
      h("span", { class: "row-text" }, h("span", { class: "id", title: id }, shortId(id)), playerText(t) || "—"),
      h("span", { class: "row-time" }, fmtTime(t.created_at)),
    ));
  }));
}

function groupRow(g) {
  const first = g.items[0], r = first.result;
  const prio = r.priority === "p0" || r.priority === "p1" ? h("span", { class: `pill ${r.priority}` }, PRIORITY[r.priority]) : null;
  return h("li", {}, h("button", {
    class: "row group-row", "aria-current": state.activeGroup === g.key ? "true" : "false", "data-group": g.key,
    onclick: () => openGroup(g),
  },
    h("span", { class: "row-title" }, CATEGORY[r.category] || r.category),
    h("span", { class: "row-slots" }, h("span", { class: "row-lang" }, (r.language || "").toUpperCase()), prio),
    h("span", { class: "row-text" }, `Ответ: ${r.draft.template === "llm" ? "свой у каждого" : TEMPLATE[r.draft.template] || r.draft.template}`),
    h("span", { class: "group-count num" }, fmtNum(g.items.length))));
}

function fact(label, value, note) {
  const empty = value === null || value === undefined || value === "";
  return h("div", { class: "fact" }, h("dt", {}, label),
    h("dd", {}, empty ? h("span", { class: "dash" }, "—") : value, note ? h("span", { class: "note" }, ` ${note}`) : null));
}

// Коды категорий в текстах сервиса («report.payment») показываем названиями
const humanize = (s) => String(s).replace(/(complaint|report)\.[a-z_]+/g, (code) => `«${CATEGORY[code] || code}»`);
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("ru-RU") : "—");

function timeline(it) {
  return h("dl", { class: "timeline" },
    h("div", {}, h("dt", {}, "Принято"), h("dd", { class: "num" }, clock(it.received_at))),
    h("div", {}, h("dt", {}, "Разобрано"), h("dd", { class: "num" }, `за ${fmtMs(it.processing_ms)}`)),
    h("div", {}, h("dt", {}, it.status === "sent" ? "Отправлено" : "Эскалировано"), h("dd", { class: "num" }, clock(it.decided_at))));
}

// Шаблон из правки: появится среди быстрых ответов на этом языке
async function saveAsTemplate(it) {
  const title = prompt("Название шаблона", CATEGORY[it.result.category] || "");
  if (!title) return;
  const res = await fetch("/api/templates", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, text: it.final_text, lang: it.result.draft.language }),
  });
  const data = await res.json();
  delete state.quick[it.result.draft.language];
  showToast(res.ok ? "Шаблон сохранён, он есть среди быстрых ответов" : data.detail);
}

function feedbackMark(it) {
  if (!it.final_text) return null;
  if (state.info?.public) return null;
  return h("p", { class: "feedback" }, h("span", {}, "Правка сохранена для дообучения"),
    h("button", { class: "link", onclick: () => saveAsTemplate(it) }, "Сделать шаблоном"));
}

// Быстрый просмотр обращения, на которое можно ответить без администратора
function blindBadges(it) {
  const r = it.result, cited = r.draft_reply.cited;
  return h("dl", { class: "badges" }, [["Язык", LANG[r.language] || r.language], ["Суть", CATEGORY[r.category] || r.category],
    ["Правило", cited[0] || "не требуется"], ["Уверенность", `${Math.round(r.confidence * 100)}%`]].map(([k, v]) =>
      h("div", {}, h("dt", {}, k), h("dd", {}, v))));
}

function decisionBox(it) {
  const r = it.result;
  if (it.status === "sent") {
    return h("div", { class: "decision done" }, h("h3", {}, "Ответ отправлен"),
      h("p", {}, it.final_text ? "С правкой администратора." : "Черновик без изменений."), timeline(it), feedbackMark(it));
  }
  if (it.status === "escalated") {
    return h("div", { class: "decision done" }, h("h3", {}, "Передано старшей администрации"), timeline(it), feedbackMark(it));
  }
  if (r.needs_human) {
    return h("div", { class: "decision human" }, h("h3", {}, "Нужен администратор"),
      h("ul", {}, (r.needs_human_reasons || []).map((s) => h("li", {}, humanize(cap(s))))));
  }
  let why = "Черновик по проверенному шаблону, решения по существу не требуется.";
  if (r.is_spam) why = "Сообщение без содержания: черновик просит описать проблему.";
  else if (r.is_duplicate) why = `Повтор обращения ${r.duplicate_of}: черновик просит дождаться ответа по первому.`;
  else if (r.draft.template === "question_kb") why = "Ответ взят из базы прошлых ответов администраторов на такой же вопрос.";
  else if (r.draft.template === "llm") why = "Черновик написан LLM по похожему прошлому ответу администратора и прошёл проверки.";
  return h("div", { class: "decision auto" }, h("h3", {}, "Можно ответить без администратора"), h("p", {}, why));
}

// Шаги разбора одного обращения — словами, из того, что вернул конвейер
function processSteps(it) {
  const r = it.result, d = r.draft, m = d.llm;
  const reason = (prefix) => (r.reasons.find((s) => s.startsWith(prefix)) || "").slice(prefix.length).trim();
  const how = reason("категория:");
  const relabel = r.reasons.find((s) => s.startsWith("категория уточнена LLM"));
  let draftHow = d.template === "llm" ? `LLM ${m?.model ?? ""}, ${fmtMs(m?.latency_ms)}, ${m?.tokens_in ?? "?"} + ${m?.tokens_out ?? "?"} токенов`
    : d.template === "question_kb" ? `база прошлых ответов админов (${reason("ответ из базы знаний") || "похожий вопрос"})`
    : `шаблон «${TEMPLATE[d.template] || d.template}»`;
  if (m && d.template !== "llm") draftHow += ` · LLM не помогла: ${m.error || m.rejected}`;
  const cites = d.citations.length;
  return [
    ["Язык", `${LANG[r.language] || r.language}${it.ticket.server_lang ? `, сервер: ${it.ticket.server_lang}` : ""}`],
    ["Категория", `${CATEGORY[r.category] || r.category} · ${relabel ? "уточнена LLM" : how || "—"} · уверенность ${Math.round(r.confidence * 100)}%`],
    ["Приоритет", `${PRIORITY[r.priority]} · ${humanize(reason("приоритет:") || "по категории")}`],
    ["Спам и повторы", r.is_spam ? "спам: сообщение без содержания" : r.is_duplicate ? `повтор обращения ${r.duplicate_of}` : "нет"],
    ...(r.suggested_verdict ? [["Вероятный вердикт", `${VERDICT[r.suggested_verdict.label] || r.suggested_verdict.label} · ${Math.round(r.suggested_verdict.p * 100)}%`]] : []),
    ["Черновик", draftHow],
    ["Проверка ссылок", cites ? `${cites} ${plural(cites, "пункт", "пункта", "пунктов")} правил, все есть в rules.json; обещаний нет` : "ссылок на правила нет; обещаний нет"],
    ["Маршрут", r.needs_human ? `к администратору (${(r.needs_human_reasons || []).length} ${plural((r.needs_human_reasons || []).length, "причина", "причины", "причин")})` : "можно отправить без администратора"],
  ];
}

function citesBlock(list) {
  return list.length
    ? h("ul", { class: "cites", "aria-label": "Основания из правил" }, list.map((c) => h("li", { class: "cite" },
        h("span", { class: "code" }, c.ref), h("span", { class: "section" }, c.section, h("span", { class: "verified" }, " · есть в rules.json")), c.quote ? h("q", {}, c.quote) : null)))
    : h("p", { class: "no-cites" }, "Без ссылок на правила: в этой ситуации они не нужны.");
}

function similarBlock(it) {
  const open = state.items.filter((x) => x.status === "new" && x !== it);
  const same = open.filter((x) => groupKey(x) === groupKey(it));
  const nick = it.result.extracted.nickname;
  const sameNick = nick ? open.filter((x) => x.result.extracted.nickname === nick) : [];
  if (!same.length && !sameNick.length) return null;
  return h("div", { class: "similar" },
    same.length ? h("div", {}, h("span", {}, `Такая же тема и ответ: ещё ${fmtNum(same.length)}`),
      it.status === "new" ? h("button", { class: "btn btn-sm", onclick: () => openGroup({ key: groupKey(it), items: [it, ...same] }) }, `Ответить всем ${fmtNum(same.length + 1)}`) : null) : null,
    sameNick.length ? h("div", {}, h("span", {}, `На этого же игрока: ещё ${fmtNum(sameNick.length)}`),
      h("button", { class: "btn btn-sm", onclick: () => toggleTag(`nick:${nick}`) }, "Показать")) : null);
}

function renderDetail() {
  const pane = $("detail");
  if (state.checked.size && !state.loading) return renderBulk();
  const it = selectedItem();
  if (state.loading) return pane.replaceChildren(h("div", { class: "detail-body" }, h("div", { class: "skeleton" }, h("i"), h("i"), h("i"))));
  if (!it) {
    return pane.replaceChildren(h("div", { class: "detail-body" },
      h("p", { class: "empty" }, state.error ? "Обращение недоступно, пока очередь не загрузится." : "Выберите обращение в списке слева.")));
  }
  const t = it.ticket, r = it.result, x = r.extracted, d = r.draft, open = it.status === "new";
  const accused = (Array.isArray(t.messages) ? t.messages : []).filter((m) => m.role === "reported_player");
  const evidence = [];
  if (x.evidence.images_count) evidence.push(`${x.evidence.images_count} ${plural(x.evidence.images_count, "скриншот", "скриншота", "скриншотов")}`);
  if (x.evidence.links) evidence.push(`${x.evidence.links} ${plural(x.evidence.links, "ссылка", "ссылки", "ссылок")}`);
  const source = d.template === "llm" ? "LLM" : d.template === "question_kb" ? "база прошлых ответов" : "шаблон";
  const verdict = r.suggested_verdict;
  const steps = processSteps(it);

  const draft = h("textarea", {
    class: "draft", id: "draft", "aria-label": "Черновик ответа игроку", readonly: !open,
    oninput: () => { state.dirty = true; state.note = "Есть несохранённая правка"; updateStatus(); },
    onkeydown: (e) => { if (open && (e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); decide("send"); } },
  });
  draft.value = it.final_text || d.text;

  pane.replaceChildren(
    h("div", { class: "detail-body" },
      h("button", { class: "btn back", onclick: showList }, "← К очереди"),
      h("div", { class: "d-meta" }, h("span", { class: "mono" }, String(t.ticket_id)), "·", h("span", {}, KIND[t.kind] || t.kind),
        "·", h("span", { class: "num" }, fmtTime(t.created_at)), t.region ? ["·", h("span", {}, SERVER[t.region] || t.region)] : null,
        it.source !== "demo" ? ["·", h("span", {}, sourceName(it.source))] : null),
      h("div", { class: "d-head" }, h("h2", { id: "detail-title", tabindex: "-1" }, CATEGORY[r.category] || r.category),
        h("span", { class: `pill ${r.priority === "p0" || r.priority === "p1" ? r.priority : "neutral"}` }, PRIORITY[r.priority]),
        h("span", { class: "d-lang" }, LANG[r.language] || r.language)),
      h("div", { class: "chips detail-tags" }, tagsOf(it).filter((tag) => !tag.startsWith("flag:")).map((tag) =>
        h("button", { class: `chip${state.tags.has(tag) ? " on" : ""}`, title: "Показать все такие обращения", onclick: () => toggleTag(tag) }, tagLabel(tag)))),
      open && !r.needs_human ? blindBadges(it) : null,
      decisionBox(it),
      similarBlock(it),
      h("section", { class: "block" },
        h("div", { class: "block-head" }, h("h3", {}, "Сообщение игрока"), h("span", { class: "meta" }, "слова игрока, не проверены")),
        h("p", { class: "message" }, clean(r.text_fix?.fixed) || playerText(t) || "—"),
        r.text_fix ? h("p", { class: "text-fix" }, h("strong", {}, "Кодировка исправлена. "), "Исходник: ", clean(r.text_fix.original)) : null,
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
          open ? h("span", { class: "meta" }, "Ctrl+Enter — отправить") : null),
        open ? h("div", { class: "quick", id: "quick", "aria-label": "Быстрые ответы" }) : null,
        draft,
        h("div", { id: "cites-box" }, citesBlock(d.citations))),
      h("details", { class: "block process" },
        h("summary", {}, h("span", { class: "summary-title" }, "Как обработано"),
          h("span", { class: "meta" }, it.processing_ms != null ? `${steps.length} шагов за ${fmtMs(it.processing_ms)}` : `${steps.length} шагов`)),
        h("dl", { class: "steps" }, steps.map(([k, v]) => h("div", { class: "step" }, h("dt", {}, k), h("dd", {}, v))))),
    ),
    h("div", { class: "actions" },
      h("button", { class: "btn primary", disabled: !open, onclick: () => decide("send") }, "Отправить игроку"),
      h("button", { class: "btn", disabled: !open, onclick: () => decide("save") }, "Сохранить правку"),
      h("button", { class: "btn", disabled: !open, onclick: () => decide("escalate") }, "Эскалировать"),
      h("span", { class: "status", id: "status", role: "status" }),
    ),
  );
  updateStatus();
  if (open) renderQuick(d.language);
}

async function renderQuick(lang) {
  try {
    if (!state.quick[lang]) state.quick[lang] = await fetch(`/api/quick?lang=${encodeURIComponent(lang)}`).then((r) => r.json());
  } catch { return; }
  const box = $("quick");
  if (!box) return;
  box.replaceChildren(...state.quick[lang].map((q) => h("button", { class: "chip", type: "button", onclick: () => {
    $("draft").value = q.text;
    $("cites-box").replaceChildren(citesBlock(q.citations));
    state.dirty = true;
    state.note = `Быстрый ответ: ${q.title}`;
    updateStatus();
  } }, q.title)));
}

// ---------- Ответ сразу многим ----------
function renderBulk() {
  const pane = $("detail");
  const items = state.items.filter((it) => state.checked.has(itemId(it)));
  const humans = items.filter((it) => it.result.needs_human);
  const keys = new Set(items.map(groupKey));
  const first = items[0], r = first.result;
  const sameText = keys.size === 1 && !["llm", "question_kb"].includes(r.draft.template);
  const nick = r.extracted.nickname;
  const sample = nick ? r.draft.text.replaceAll(nick, "{ник}") : r.draft.text;
  const reasons = [...new Set(humans.flatMap((it) => (it.result.needs_human_reasons || []).map((s) => s.replace(/\s*\([\d.,]+\)$/, ""))))].slice(0, 3);
  const n = items.length;
  const shown = items.slice(0, 100);
  pane.replaceChildren(
    h("div", { class: "detail-body" },
      h("button", { class: "btn back", onclick: showList }, "← К очереди"),
      h("div", { class: "d-head" }, h("h2", { id: "detail-title", tabindex: "-1" }, `Выбрано ${fmtNum(n)} ${plural(n, "обращение", "обращения", "обращений")}`),
        h("button", { class: "link", onclick: () => setChecked([]) }, "Снять выбор")),
      h("p", { class: "d-lang" }, keys.size === 1
        ? `${CATEGORY[r.category] || r.category} · ${LANG[r.language] || r.language}`
        : `${fmtNum(keys.size)} разных ${plural(keys.size, "группа", "группы", "групп")} ответов: каждому уйдёт его черновик`),
      humans.length
        ? h("div", { class: "decision human" }, h("h3", {}, `${fmtNum(humans.length)} из ${fmtNum(n)} ждут решения администратора`),
            h("ul", {}, reasons.map((s) => h("li", {}, humanize(cap(s))))))
        : h("div", { class: "decision auto" }, h("h3", {}, "Можно ответить всем без проверки"), h("p", {}, "Черновики по шаблону, решения по существу не требуется.")),
      h("section", { class: "block" },
        h("div", { class: "block-head" }, h("h3", {}, "Ответ"),
          sameText ? h("button", { class: "link", onclick: () => { state.bulkText = state.bulkText === null ? sample : null; renderBulk(); } },
            state.bulkText === null ? "Изменить текст для всех" : "Вернуть черновики") : null),
        sameText
          ? (() => {
              const area = h("textarea", { class: "draft", id: "bulk-text", "aria-label": "Текст ответа всем", readonly: state.bulkText === null,
                oninput: (e) => { state.bulkText = e.target.value; } });
              area.value = state.bulkText ?? sample;
              return area;
            })()
          : h("p", { class: "muted" }, "У каждого обращения свой черновик, он и будет отправлен."),
        sameText && state.bulkText !== null ? h("p", { class: "muted" }, "{ник} заменится ником нарушителя из каждого обращения.") : null),
      h("section", { class: "block" },
        h("div", { class: "block-head" }, h("h3", {}, "Обращения")),
        h("ul", { class: "bulk-list" }, shown.map((it) => {
          const id = itemId(it);
          const box = h("input", { type: "checkbox", "aria-label": `Убрать ${id}`, onclick: () => toggleChecked(id) });
          box.checked = true;
          return h("li", {}, box,
            h("button", { class: "bulk-open-row", onclick: () => openOne(id) }, h("span", { class: "mono", title: id }, shortId(id)), " ", playerText(it.ticket) || "—"));
        })),
        n > shown.length ? h("p", { class: "muted" }, `и ещё ${fmtNum(n - shown.length)}`) : null)),
    h("div", { class: "actions" },
      h("button", { class: "btn primary", onclick: () => bulkDecide("send") }, `Отправить ${fmtNum(n)} ${plural(n, "ответ", "ответа", "ответов")}`),
      h("button", { class: "btn", onclick: () => bulkDecide("escalate") }, "Эскалировать"),
      h("span", { class: "status", id: "status", role: "status" }, "Ctrl+Enter — отправить")));
}

async function postBulk(ids, action, text) {
  const res = await fetch("/api/tickets/bulk", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids, action, text }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const updated = new Map((await res.json()).items.map((it) => [itemId(it), it]));
  state.items = state.items.map((it) => updated.get(itemId(it)) || it);
}

async function bulkDecide(action) {
  const items = state.items.filter((it) => state.checked.has(itemId(it)));
  const humans = items.filter((it) => it.result.needs_human).length;
  if (action === "send" && humans && !confirm(`Отправить ${items.length} ${plural(items.length, "ответ", "ответа", "ответов")}? ${humans} из них ждут решения администратора.`)) return;
  const ids = items.map(itemId);
  try {
    await postBulk(ids, action, state.bulkText ?? undefined);
    state.checked.clear();
    state.bulkText = null;
    state.activeGroup = null;
    document.body.dataset.pane = "list";
    reselect();
    render();
    showToast(`${action === "send" ? "Отправлено" : "Эскалировано"}: ${fmtNum(ids.length)}`, ids);
  } catch (e) {
    showToast(`Не удалось: ${e.message}`);
  }
}

function showToast(text, undoIds) {
  const el = $("toast");
  clearTimeout(timers.toast);
  el.replaceChildren(h("span", {}, text), ...(undoIds ? [h("button", { class: "link toast-undo", onclick: async () => {
    el.hidden = true;
    await postBulk(undoIds, "reopen");
    reselect();
    render();
  } }, "Отменить")] : []));
  el.hidden = false;
  timers.toast = setTimeout(() => { el.hidden = true; }, 10000);
}

function updateStatus() {
  const el = $("status");
  if (!el) return;
  const it = selectedItem();
  if (it && it.status !== "new") el.textContent = `Решение принято ${fmtTime(it.decided_at)}`;
  else el.textContent = state.note || (it && it.final_text ? "Черновик изменён администратором" : "");
}

// ---------- Загрузка обращений ----------
function kpi(label, value, sub) {
  return h("div", { class: "kpi" }, h("dt", {}, label), h("dd", {}, h("span", { class: "kpi-value num" }, value), sub ? h("small", {}, sub) : null));
}

function barList(rows, total, label) {
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return h("ul", { class: "bars" }, rows.map(([key, n]) => h("li", {},
    h("span", { class: "bar-label" }, label(key)),
    h("span", { class: "bar-value num" }, `${fmtNum(n)} · ${pct(n, total)}`),
    h("span", { class: "bar-track", "aria-hidden": "true" }, h("span", { class: "bar-fill", style: `width:${(n / max) * 100}%` })))));
}

function renderBatch() {
  const box = $("batch-view");
  const j = state.job;
  const running = j && !j.finished;
  const file = h("input", { type: "file", accept: ".jsonl,.json", id: "batch-file", class: "sr-only", disabled: running, onchange: onBatchFile });
  const upload = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Новая пачка")),
    h("p", { class: "muted" }, "Файл в формате выгрузки кейса: .jsonl, одно обращение в строке, или .json с массивом. До 5000 обращений за раз."),
    h("div", { class: "row-actions" },
      h("label", { class: `btn primary${running ? " is-disabled" : ""}`, for: "batch-file" }, "Выбрать файл"), file,
      state.info?.validation_available
        ? h("button", { class: "btn", disabled: running, onclick: () => startBatch("/api/batches/sample", { n: 500 }) }, "500 обращений из валидации")
        : null),
    state.jobError ? h("p", { class: "error-text", role: "alert" }, state.jobError) : null);
  const blocks = [upload];
  if (j) blocks.push(batchSummary(j));
  const others = state.batches.filter((b) => !j || b.id !== j.id);
  if (others.length) {
    blocks.push(h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Прошлые пачки")),
      h("ul", { class: "plain-list" }, others.map((b) => h("li", {},
        h("button", { class: "link", onclick: () => { pollJob(b.id); } }, b.name), h("span", { class: "muted" }, ` · ${fmtNum(b.total)} обращений`))))));
  }
  box.replaceChildren(...blocks);
}

function batchSummary(j) {
  const total = j.done || 1;
  const progress = j.total ? Math.round((j.done / j.total) * 100) : 0;
  const prio = ["p0", "p1", "p2", "p3"];
  const llm = j.llm || {};
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, `Пачка «${j.name}»`),
      h("span", { class: "meta" }, j.finished ? `разобрана за ${fmtSec(j.elapsed_s)}` : `идёт разбор · ${fmtSec(j.elapsed_s)}`)),
    h("div", { class: "progress", role: "progressbar", "aria-label": "Разобрано", "aria-valuenow": progress, "aria-valuemin": "0", "aria-valuemax": "100" },
      h("span", { style: `width:${progress}%` })),
    j.error ? h("p", { class: "error-text", role: "alert" }, `Разбор остановился: ${j.error}`) : null,
    h("dl", { class: "kpis" },
      kpi("Разобрано", `${fmtNum(j.done)} из ${fmtNum(j.total)}`),
      kpi("Скорость", `${fmtNum(j.per_second)}`, "в секунду"),
      kpi("Время на обращение", fmtMs(j.p95_ms), "p95"),
      kpi("Самое долгое", fmtMs(j.max_ms))),
    h("div", { class: "split" },
      h("div", {},
        h("h3", {}, "Куда ушли"),
        h("ul", { class: "bars" },
          [["Нужен администратор", j.needs_human], ["Можно ответить сразу", j.auto], ["Спам", j.spam], ["Повторы", j.duplicates]].map(([k, n]) =>
            h("li", {}, h("span", { class: "bar-label" }, k), h("span", { class: "bar-value num" }, `${fmtNum(n)} · ${pct(n, total)}`),
              h("span", { class: "bar-track", "aria-hidden": "true" }, h("span", { class: "bar-fill", style: `width:${(n / total) * 100}%` }))))),
        h("h3", {}, "Приоритет"),
        h("dl", { class: "prio-strip" }, prio.map((p) => h("div", {}, h("dt", {}, PRIORITY[p]), h("dd", { class: "num" }, fmtNum(j.priorities?.[p] || 0))))),
        h("h3", {}, "Языки"),
        h("p", { class: "langs" }, (j.languages || []).map(([l, n]) => `${LANG[l] || l} ${fmtNum(n)}`).join(" · ") || "—"),
        llm.calls ? [h("h3", {}, "LLM"), h("p", { class: "muted" },
          `${fmtNum(llm.calls)} ${plural(llm.calls, "вызов", "вызова", "вызовов")}: приняты ${fmtNum(llm.accepted || 0)}` +
          `${llm.limited ? `, лимит в минуту ${fmtNum(llm.limited)}` : ""}${llm.failed ? `, ошибки и отказы проверок ${fmtNum(llm.failed)}` : ""}.` +
          `${llm.limited ? " Сверх лимита ставится шаблон, обращение уходит администратору." : ""}`)] : null),
      h("div", {}, h("h3", {}, "Категории"), barList(j.categories || [], total, (c) => CATEGORY[c] || c))),
    j.finished && j.done ? h("div", { class: "row-actions" },
      h("button", { class: "btn primary", onclick: () => openBatch(j.id) }, "Открыть в очереди")) : null);
}

async function onBatchFile(e) {
  const f = e.target.files?.[0];
  e.target.value = "";
  if (!f) return;
  let tickets;
  try {
    const text = (await f.text()).trim();
    tickets = text.startsWith("[") ? JSON.parse(text) : text.split(/\r?\n/).filter((l) => l.trim()).map((l) => JSON.parse(l));
    if (!Array.isArray(tickets) || !tickets.length) throw new Error("в файле нет обращений");
  } catch (err) {
    state.jobError = `Файл не прочитан: ${err.message}. Нужен .jsonl (обращение в строке) или .json (массив).`;
    return render();
  }
  startBatch("/api/batches", { name: f.name, tickets });
}

async function startBatch(url, body) {
  state.jobError = "";
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    state.job = data;
    state.batches = [...state.batches.filter((b) => b.id !== data.id), { id: data.id, name: data.name, total: data.total }];
    pollJob(data.id);
  } catch (err) {
    state.jobError = `Не удалось запустить разбор: ${err.message}`;
  }
  render();
}

function pollJob(id) {
  clearInterval(timers.job);
  const tick = async () => {
    try {
      const res = await fetch(`/api/jobs/${id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.job = await res.json();
    } catch (err) {
      state.jobError = `Нет связи с сервисом: ${err.message}`;
      clearInterval(timers.job);
    }
    if (state.job?.finished) {
      clearInterval(timers.job);
      await loadQueue(false);
    }
    if (state.mode === "batch") renderBatch();
    renderNav();
  };
  tick();
  timers.job = setInterval(tick, 400);
}

function openBatch(id) {
  state.mode = "queue";
  state.source = id;
  state.view = "all";
  reselect();
  render();
}

// ---------- Проверка нагрузки ----------
function segmented(label, values, current, onPick, fmt = (v) => v) {
  return h("div", { class: "field" }, h("span", { class: "field-label" }, label),
    h("div", { class: "segmented", role: "group", "aria-label": label }, values.map((v) => h("button", {
      type: "button", "aria-pressed": v === current ? "true" : "false", onclick: () => onPick(v),
    }, fmt(v)))));
}

function renderLoad() {
  const box = $("load-view");
  const lt = state.load;
  const running = lt && !lt.finished;
  const sources = [["demo", "Демо-набор, по кругу"], ...state.batches.map((b) => [b.id, `Пачка «${b.name}», по кругу`])];
  const controls = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Параметры")),
    h("div", { class: "controls" },
      segmented("Сколько запросов", [100, 500, 1000], state.loadN, (v) => { state.loadN = v; renderLoad(); }, fmtNum),
      segmented("Одновременно", [1, 10, 50], state.loadC, (v) => { state.loadC = v; renderLoad(); }),
      h("div", { class: "field" }, h("label", { class: "field-label", for: "load-source" }, "Какие обращения"),
        h("select", { id: "load-source", class: "input", onchange: (e) => { state.loadSource = e.target.value; } },
          sources.map(([v, l]) => h("option", { value: v, selected: v === state.loadSource }, l))))),
    h("div", { class: "row-actions" },
      h("button", { class: "btn primary", disabled: running, onclick: startLoad }, running ? "Идёт проверка…" : "Запустить проверку"),
      h("span", { class: "muted" }, "Лимит кейса: p95 не больше 5 секунд.")),
    state.loadError ? h("p", { class: "error-text", role: "alert" }, state.loadError) : null);
  box.replaceChildren(controls, lt ? loadResults(lt) : null);
}

function loadResults(lt) {
  const done = lt.done || 0;
  const progress = lt.total ? Math.round((done / lt.total) * 100) : 0;
  const p95 = lt.p95_ms;
  const verdict = lt.finished && p95 != null
    ? (p95 <= 5000 ? `p95 ${fmtMs(p95)} — в ${Math.max(1, Math.floor(5000 / Math.max(p95, 1)))} раз ниже лимита в 5 с.` : `p95 ${fmtMs(p95)} — выше лимита в 5 с.`)
    : null;
  const hist = lt.hist || [];
  const edges = lt.buckets_ms || [];
  const maxBin = Math.max(1, ...hist);
  const llm = lt.llm || {};
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, `${fmtNum(lt.total)} запросов, по ${lt.concurrency} одновременно`),
      h("span", { class: "meta" }, lt.failed ? "остановилась с ошибкой" : lt.finished ? `готово за ${fmtSec(lt.elapsed_s || 0)}` : `идёт · ${fmtSec(lt.elapsed_s || 0)}`)),
    h("div", { class: "progress", role: "progressbar", "aria-label": "Отправлено", "aria-valuenow": progress, "aria-valuemin": "0", "aria-valuemax": "100" },
      h("span", { style: `width:${progress}%` })),
    lt.failed ? h("p", { class: "error-text", role: "alert" }, lt.message || "Проверка остановилась.") : null,
    verdict ? h("p", { class: `verdict-line ${p95 <= 5000 ? "ok" : "bad"}` }, verdict) : null,
    h("dl", { class: "kpis", style: "--cols:6" },
      kpi("Обработано", `${fmtNum(done)} из ${fmtNum(lt.total)}`),
      kpi("Ошибок", fmtNum(lt.errors || 0)),
      kpi("Задержка p50", fmtMs(lt.p50_ms)),
      kpi("Задержка p95", fmtMs(p95)),
      kpi("Самая долгая", fmtMs(lt.max_ms)),
      kpi("Запросов в секунду", fmtNum(lt.rps || 0))),
    h("h3", {}, "Распределение задержки"),
    h("div", { class: "hist", role: "img", "aria-label": "Сколько запросов уложилось в каждый интервал задержки" },
      hist.map((n, i) => h("div", { class: "hist-col" },
        h("span", { class: "hist-count num" }, n ? fmtNum(n) : ""),
        h("span", { class: "hist-bar", style: `height:${Math.round((n / maxBin) * 120)}px` }),
        h("span", { class: "hist-label" }, i < edges.length ? `до ${fmtMs(edges[i])}` : `больше ${fmtMs(edges[edges.length - 1])}`)))),
    llm.calls ? h("p", { class: "muted" },
      `LLM: ${fmtNum(llm.calls)} ${plural(llm.calls, "вызов", "вызова", "вызовов")}, приняты ${fmtNum(llm.accepted || 0)}` +
      `${llm.limited ? `, сверх лимита в минуту ${fmtNum(llm.limited)} (шаблон вместо LLM, ответ не задерживается)` : ""}` +
      `${llm.failed ? `, ошибки ${fmtNum(llm.failed)}` : ""}.`) : null,
    (lt.slowest || []).length ? [
      h("h3", {}, "Самые долгие запросы"),
      h("ul", { class: "slow-list" }, lt.slowest.map((s) => h("li", {},
        h("span", { class: "num slow-ms" }, fmtMs(s.ms)),
        h("span", { class: "mono" }, s.ticket),
        h("span", { class: "muted" }, !s.ok ? "ошибка запроса"
          : s.llm ? `разбор на сервере ${fmtMs(s.server_ms)}: ${/^LLM/.test(s.llm) ? `вызов ${s.llm}` : `LLM — ${s.llm}`}`
          : `разбор на сервере ${fmtMs(s.server_ms)}, остальное — ожидание в очереди запросов`)))),
    ] : null);
}

async function startLoad() {
  state.loadError = "";
  try {
    const res = await fetch("/api/loadtests", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ n: state.loadN, concurrency: state.loadC, source: state.loadSource }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    state.load = { ...data, done: 0, finished: false };
    clearInterval(timers.load);
    const tick = async () => {
      try {
        const r = await fetch(`/api/loadtests/${data.id}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        state.load = { ...state.load, ...(await r.json()) };
      } catch (err) {
        state.loadError = `Нет связи с сервисом: ${err.message}`;
        clearInterval(timers.load);
      }
      if (state.load.finished) clearInterval(timers.load);
      if (state.mode === "load") renderLoad();
      renderNav();
    };
    timers.load = setInterval(tick, 300);
  } catch (err) {
    state.loadError = `Не удалось запустить проверку: ${err.message}`;
  }
  renderLoad();
}

// ---------- Действия в очереди ----------
function reselect() {
  const items = visibleItems();
  if (!items.some((it) => itemId(it) === state.selected)) state.selected = items[0] ? itemId(items[0]) : null;
}

function toggleTag(tag) {
  if (state.tags.has(tag)) state.tags.delete(tag);
  else state.tags.add(tag);
  state.mode = "queue";
  state.checked.clear();
  state.activeGroup = null;
  document.body.dataset.pane = "list";
  reselect();
  render();
}

function resetFilters() {
  state.tags.clear();
  state.query = "";
  $("search").value = "";
  reselect();
  render();
}

function setListMode(m) {
  state.listMode = m;
  state.checked.clear();
  state.activeGroup = null;
  state.bulkText = null;
  render();
}

function setChecked(items) {
  state.checked = new Set(items.map(itemId));
  state.activeGroup = null;
  state.bulkText = null;
  render();
}

function toggleChecked(id, range) {
  const ids = visibleItems().filter((it) => it.status === "new").map(itemId);
  if (range && state.lastChecked && ids.includes(state.lastChecked) && ids.includes(id)) {
    const [a, b] = [ids.indexOf(state.lastChecked), ids.indexOf(id)].sort((x, y) => x - y);
    ids.slice(a, b + 1).forEach((x) => state.checked.add(x));
  } else if (state.checked.has(id)) state.checked.delete(id);
  else state.checked.add(id);
  state.lastChecked = id;
  state.bulkText = null;
  if (!state.checked.size) state.activeGroup = null;
  render();
  document.querySelector(`[data-check="${CSS.escape(id)}"]`)?.focus();
}

function openGroup(g) {
  if (g.items.length === 1) return openOne(itemId(g.items[0]));
  state.checked = new Set(g.items.map(itemId));
  state.activeGroup = g.key;
  state.bulkText = null;
  document.body.dataset.pane = "detail";
  render();
  $("detail").scrollTop = 0;
}

function openOne(id) {
  state.checked.clear();
  state.activeGroup = null;
  state.bulkText = null;
  state.selected = id;
  document.body.dataset.pane = "detail";
  render();
  $("detail").scrollTop = 0;
}

function switchView(id) {
  state.mode = "queue";
  state.view = id;
  closeMenu();
  reselect();
  render();
}

function switchMode(mode) {
  state.mode = mode;
  closeMenu();
  render();
}

function closeMenu() {
  $("sidebar").classList.remove("open");
  $("menu-btn").setAttribute("aria-expanded", "false");
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
  const before = visibleItems().map((x) => String(x.ticket.ticket_id));
  const text = $("draft").value;
  try {
    const res = await fetch(`/api/tickets/${encodeURIComponent(it.ticket.ticket_id)}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    const id = String(updated.ticket.ticket_id);
    state.items = state.items.map((x) => (String(x.ticket.ticket_id) === id ? updated : x));
    state.dirty = false;
    if (action === "save") {
      state.note = `Правка сохранена ${fmtTime(updated.decided_at)}`;
      render();
      return;
    }
    showToast(`${id}: ${action === "send" ? "ответ отправлен" : "передано старшей администрации"}`, [id]);
    // Следующее обращение того же раздела — чтобы разбирать очередь подряд
    const after = visibleItems().map((x) => String(x.ticket.ticket_id));
    state.selected = after.includes(id) ? id : before.slice(before.indexOf(id) + 1).find((x) => after.includes(x)) ?? after[after.length - 1] ?? null;
    state.note = "";
    render();
  } catch (e) {
    state.note = `Не удалось сохранить решение (${e.message}). Попробуйте ещё раз.`;
    updateStatus();
  }
}

async function loadQueue(initial) {
  if (initial) {
    state.loading = true;
    state.error = null;
    render();
  }
  try {
    const res = await fetch("/api/queue");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.items = data.items;
    state.llm = data.llm;
    state.batches = data.batches || [];
    state.loading = false;
    if (initial) state.selected = visibleItems()[0] ? String(visibleItems()[0].ticket.ticket_id) : null;
    else reselect();
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
      state.mode = "queue";
      state.source = "all";
      state.view = item.result.needs_human ? "waiting" : "ready";
      dialog.close();
      $("flash").textContent = `${item.ticket.ticket_id}: обращение разобрано за ${fmtMs(item.processing_ms)}`;
      select(String(item.ticket.ticket_id), true);
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
  if (state.mode !== "queue") state.mode = "queue";
  reselect();
  render();
});
$("menu-btn").addEventListener("click", () => {
  const open = $("sidebar").classList.toggle("open");
  $("menu-btn").setAttribute("aria-expanded", String(open));
});
function moveSelection(delta) {
  if (state.listMode === "groups") {
    const gs = groupsOf(visibleItems().filter((it) => it.status === "new"));
    const i = gs.findIndex((g) => g.key === state.activeGroup);
    const g = gs[Math.min(gs.length - 1, Math.max(0, i + delta))];
    if (g) openGroup(g);
    return;
  }
  const ids = visibleItems().map(itemId);
  const next = ids[Math.min(ids.length - 1, Math.max(0, ids.indexOf(state.selected) + delta))];
  if (!next || next === state.selected) return;
  if (state.dirty && !confirm("Правка черновика не сохранена. Перейти без сохранения?")) return;
  state.selected = next;
  state.dirty = false;
  state.note = "";
  render();
  document.querySelector(`.row[data-id="${CSS.escape(next)}"]`)?.scrollIntoView({ block: "nearest" });
}

document.addEventListener("keydown", (e) => {
  if (document.querySelector("dialog[open]")) return;
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    if (state.mode !== "queue") return;
    if (state.checked.size) bulkDecide("send");
    else if (selectedItem()?.status === "new") decide("send");
    return;
  }
  if (e.target.matches?.("input, textarea, select")) {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey || state.mode !== "queue") return;
  const it = selectedItem();
  // Режим «вслепую»: Enter или пробел отправляют только то, что не требует администратора
  if ((e.key === "Enter" || e.key === " ") && !e.target.matches?.("button, a, summary, label")) {
    e.preventDefault();
    if (!state.checked.size && selectedItem()?.status === "new" && !selectedItem().result.needs_human) decide("send");
    return;
  }
  const actions = {
    j: () => moveSelection(1), ArrowDown: () => moveSelection(1),
    k: () => moveSelection(-1), ArrowUp: () => moveSelection(-1),
    x: () => { if (it?.status === "new") toggleChecked(state.selected); },
    r: () => $("draft")?.focus(),
    e: () => { if (state.checked.size) bulkDecide("escalate"); else if (it?.status === "new") decide("escalate"); },
    g: () => setListMode(state.listMode === "list" ? "groups" : "list"),
    "/": () => $("search").focus(),
    "?": () => $("help-dialog").showModal(),
    Escape: () => { if (state.checked.size) setChecked([]); },
  };
  if (actions[e.key]) {
    e.preventDefault();
    actions[e.key]();
  }
});
$("help-btn").addEventListener("click", () => $("help-dialog").showModal());

// Поток выдуманных обращений: появляются в очереди по одному, разбор настоящий
$("stream-btn").addEventListener("click", async () => {
  const btn = $("stream-btn"), demo = state.items.filter((it) => it.source === "demo").map((it) => it.ticket);
  if (!demo.length) return;
  btn.disabled = true;
  state.mode = "queue";
  state.view = "all";
  state.source = "all";
  const total = 30, stamp = Date.now(), latency = [];
  for (let i = 0; i < total; i++) {
    const { ticket_id, created_at, ...t } = demo[i % demo.length];
    t.reporter_hash = `flow-${stamp}-${i}`;
    if (t.reported_hash) t.reported_hash = `flow-${stamp}-${i}`;
    const res = await fetch("/api/tickets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(t) });
    if (res.ok) {
      const item = await res.json();
      state.items.push(item);
      latency.push(item.processing_ms);
    }
    renderNav();
    renderFinding();
    renderList();
    showToast(`Поток: ${i + 1} из ${total}, разбор ${fmtMs(latency.reduce((a, b) => a + b, 0) / (latency.length || 1))} в среднем`);
    await new Promise((r) => setTimeout(r, 120));
  }
  btn.disabled = false;
  reselect();
  render();
});

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("theme-btn").textContent = theme === "dark" ? "Светлая" : "Тёмная";
  try { localStorage.setItem("theme", theme); } catch { /* тема просто не запомнится */ }
}
$("theme-btn").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
{
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch { /* браузер запретил хранилище */ }
  applyTheme(saved || "light");
}
setupDialog();
fetch("/api/info").then((r) => r.json()).then((info) => { state.info = info; render(); }).catch(() => {});
loadQueue(true);
