const $ = (selector) => document.querySelector(selector);
const groupSelect = $("#groupSelect");
const dateSelect = $("#dateSelect");
const scheduleList = $("#scheduleList");
const lessonCount = $("#lessonCount");
const dayHeading = $("#dayHeading");
const teacherSearch = $("#teacherSearch");
const teacherSearchButton = $("#teacherSearchButton");
const teacherResults = $("#teacherResults");

const todayISO = () => {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
};
dateSelect.value = todayISO();

let scheduleData = null;
let bellsData = null;

function formatDate(iso) {
  if (!iso) return "Выбранная дата";
  return new Intl.DateTimeFormat("ru-RU", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    .format(new Date(`${iso}T12:00:00`));
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[ch]));
}
function emptyState(title, message) {
  scheduleList.innerHTML = `<div class="empty-state panel"><span class="empty-icon">◷</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(message)}</p></div>`;
  lessonCount.textContent = "Нет данных";
}
function renderSchedule() {
  const date = dateSelect.value;
  const group = groupSelect.value;
  dayHeading.textContent = formatDate(date);
  const entries = scheduleData?.groups?.[group]?.[date];
  if (!Array.isArray(entries)) {
    emptyState("Расписание пока недоступно", scheduleData?.message || "Для этой группы и даты нет подтверждённых данных. Проверь официальный источник.");
    return;
  }
  if (!entries.length) {
    emptyState("Занятий нет в данных источника", "Источник не вернул пары на эту дату. Это не означает автоматически, что занятий нет: проверь официальную страницу.");
    return;
  }
  lessonCount.textContent = `${entries.length} ${entries.length === 1 ? "занятие" : entries.length < 5 ? "занятия" : "занятий"}`;
  scheduleList.innerHTML = entries.map(item => `
    <article class="panel lesson">
      <div class="lesson-time">${escapeHtml(item.start || "Время не указано")}${item.end ? `–${escapeHtml(item.end)}` : ""}</div>
      <div><div class="lesson-title">${escapeHtml(item.subject || "Предмет не указан")}</div><div class="lesson-meta">${escapeHtml(item.teacher || "Преподаватель не указан")}</div></div>
      <span class="room-chip">${escapeHtml(item.room || "Аудитория не указана")}</span>
    </article>`).join("");
}
function renderStatus() {
  const status = scheduleData?.status;
  $("#syncMessage").textContent = status === "ok" ? "Последняя проверка источника завершилась успешно." : (scheduleData?.message || "Синхронизация ещё не настроена.");
  $("#lastSync").textContent = scheduleData?.lastSuccessfulSync
    ? `Последнее обновление: ${new Date(scheduleData.lastSuccessfulSync).toLocaleString("ru-RU")}`
    : "Последнее обновление: пока нет";
}
function renderBells() {
  if (!bellsData || bellsData.status !== "verified" || !Array.isArray(bellsData.bells) || !bellsData.bells.length) {
    $("#bellsMessage").textContent = bellsData?.message || "Время звонков не подтверждено официальным источником.";
    return;
  }
  $("#bellsMessage").textContent = "Подтверждённое расписание звонков:";
  $("#bellsList").innerHTML = bellsData.bells.map(b => `<div>${escapeHtml(b.lesson)} пара · ${escapeHtml(b.start)}–${escapeHtml(b.end)}</div>`).join("");
}
function searchTeacher() {
  const query = teacherSearch.value.trim().toLocaleLowerCase("ru-RU");
  if (!query) { teacherResults.textContent = "Введи фамилию преподавателя."; return; }
  if (!scheduleData?.groups) { teacherResults.textContent = "Поиск станет доступен после подключения подтверждённых данных."; return; }
  const matches = [];
  for (const [group, dates] of Object.entries(scheduleData.groups)) {
    for (const [date, lessons] of Object.entries(dates || {})) {
      for (const lesson of (Array.isArray(lessons) ? lessons : [])) {
        if ((lesson.teacher || "").toLocaleLowerCase("ru-RU").includes(query)) {
          matches.push(`${formatDate(date)} · ${group} · ${lesson.start || "время не указано"} · ${lesson.subject || "предмет не указан"}`);
        }
      }
    }
  }
  teacherResults.textContent = matches.length ? matches.join(" | ") : "Совпадений в загруженных данных не найдено.";
}
async function loadData() {
  try {
    const [scheduleResponse, bellsResponse] = await Promise.all([
      fetch(`data/schedule.json?v=${Date.now()}`, { cache: "no-store" }),
      fetch(`data/bells.json?v=${Date.now()}`, { cache: "no-store" })
    ]);
    if (scheduleResponse.ok) scheduleData = await scheduleResponse.json();
    if (bellsResponse.ok) bellsData = await bellsResponse.json();
  } catch (error) {
    console.warn("Не удалось загрузить данные расписания:", error);
  }
  renderSchedule();
  renderStatus();
  renderBells();
  const hasData = scheduleData?.status === "ok" && scheduleData?.groups;
  teacherSearch.disabled = !hasData;
  teacherSearchButton.disabled = !hasData;
}
groupSelect.addEventListener("change", renderSchedule);
dateSelect.addEventListener("change", renderSchedule);
$("#todayButton").addEventListener("click", () => { dateSelect.value = todayISO(); renderSchedule(); });
teacherSearchButton.addEventListener("click", searchTeacher);
teacherSearch.addEventListener("keydown", e => { if (e.key === "Enter") searchTeacher(); });
loadData();
