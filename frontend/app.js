// ============ Инициализация Max Bridge ============
const WebApp = window.WebApp;

if (WebApp) {
  // initDataUnsafe — только для интерфейса, не для валидации
  const user = WebApp.initDataUnsafe?.user;
  if (user) {
    console.log('Пользователь:', user.first_name, user.id);
  }

  // initData — отправлять на backend для валидации
  // const initDataStr = WebApp.initData;
  // fetch(API + '/auth', { method: 'POST', body: JSON.stringify({ initData: initDataStr }) })

} else {
  console.warn('MAX Bridge недоступен — страница открыта вне MAX');
}

console.log(Api === window.Api); // должно быть true



// Состояние приложения
const state = {
    view: 'grade-select',           // grade-select, subjects, subject-olympiads, olympiad-detail (search), olympiad-detail-mine, news, my-olympiads, calendar, calendar-day-detail
    selectedSubject: null,
    selectedOlympiad: null,
    olympiadDetailOptions: null,
    sort: 'urgency',
    onlyWithDates: false,
    grade: null,
    subjectOlympiadsRaw: [],
    myOlympiadsRaw: [],
    myHiddenCount: 0,
    subjects: [],                   // справочник предметов с сервера
    settingsNeedSave: false,        // true, если при первом запуске класса не было
    news: [],                       // кеш новостей для счётчика на таббаре
    newsExpanded: {},                // развернутые категории в блоке новостей
    newsBadgeVisible: true,          // показывать ли счётчик на таббаре «Новости»
    settings: {
        grade: null,
        notifications_enabled: true,
        colorblind_mode: false
    },
    calendarDate: { year: 2026, month: 8 }, // 0-индексированный месяц, 8 = сентябрь
    calendarSelectedDay: null,
    calendarEvents: [],            // нормализованные события текущего месяца (для окна дня)
    calendarDayItems: [],          // элементы открытого дня (для галочек)
    calendarUnplannedExact: new Set(), // exact-этапы, с которых пользователь вручную снял галочку
    today: new Date(), // реальная текущая дата
};

// Резервный справочник предметов, пока основной не загрузился с бэкенда.
// Используется только для сопоставления названия предмета с цветом.
const SUBS = [
    { id: 1, n: 'Астрономия', c: '#FFE0B2' },
    { id: 2, n: 'Биология', c: '#F4B3C4' },
    { id: 3, n: 'География', c: '#E9C2E8' },
    { id: 4, n: 'Иностранный язык', c: '#D4A5F7' },
    { id: 5, n: 'Информатика', c: '#C9CFF5' },
    { id: 6, n: 'История', c: '#A8D8FF' },
    { id: 7, n: 'Литература', c: '#B2E6F5' },
    { id: 8, n: 'Математика', c: '#8FDCE0' },
    { id: 9, n: 'Обществознание', c: '#A7D9B5' },
    { id: 10, n: 'Право', c: '#C5E6B0' },
    { id: 11, n: 'Русский язык', c: '#FFF0B3' },
    { id: 12, n: 'Физика', c: '#F5E6C8' },
    { id: 13, n: 'Химия', c: '#BAAC9B' },
    { id: 14, n: 'Экономика', c: '#BFBAB4' }
];

// DOM элементы
const appbarEl = document.getElementById('appbar');
const searchbarEl = document.getElementById('searchbar');
const contentEl = document.getElementById('content');
const tabbarEl = document.getElementById('tabbar');

// Хелперы для генерации разметки
function iconLink(href, size) {
    return `<svg width="${size}" height="${size}"><use href="#${href}"/></svg>`;
}

function badge(text, cls) {
    return `<span class="badge ${cls}">${text}</span>`;
}

function subjectById(id) {
    return (state.subjects || []).find(s => s.id === Number(id));
}

function subjectByName(name) {
    return (state.subjects || []).find(s => s.name === name) ||
        SUBS.find(s => s.n === name);
}

function dot(subjectOrName, large = false) {
    const subject = typeof subjectOrName === 'string' ? subjectByName(subjectOrName) : subjectOrName;
    if (!subject) return '';
    const color = subject.color || subject.c;
    const code = subject.short_code || (subject.n || subject.name || '').charAt(0);
    return `<span class="dot-c${large ? ' lg' : ''}" style="background:${color};display:flex;align-items:center;justify-content:center;font-size:8px;font-weight:700;line-height:1;color:var(--text-1);overflow:hidden;">${code}</span>`;
}

function subjectColor(name) {
    const subject = subjectByName(name);
    return subject ? (subject.color || subject.c) : '#ccc';
}

function subjectNameById(id) {
    const sid = Number(id);
    const subject = (state.subjects || []).find(s => s.id === sid) || SUBS.find(s => s.id === sid);
    return subject ? (subject.name || subject.n) : '';
}

function subjectColorById(id) {
    const sid = Number(id);
    const subject = (state.subjects || []).find(s => s.id === sid) || SUBS.find(s => s.id === sid);
    return subject ? (subject.color || subject.c) : null;
}

function isOlympiadAvailableForGrade(item, grade) {
    if (grade == null) return true;
    const g = Number(grade);
    const min = item ? (item.grade_min ?? item.min_grade ?? null) : null;
    const max = item ? (item.grade_max ?? item.max_grade ?? null) : null;
    if (min != null && g < Number(min)) return false;
    if (max != null && g > Number(max)) return false;
    return true;
}

function hasKnownDates(item) {
    if (!item) return false;
    if (typeof item.has_known_dates === 'boolean') return item.has_known_dates;
    if (item.next_stage) return true;
    if (Array.isArray(item.stages)) {
        return item.stages.some(stage => stage && (
            stage.start_stage || stage.end_stage || stage.starts_on || stage.ends_on || stage.date
        ));
    }
    return false;
}

function sortOlympiadList(list) {
    const arr = (list || []).slice();
    switch (state.sort) {
        case 'level':
            arr.sort((a, b) => ((a.level || 0) - (b.level || 0)) || (a.name || '').localeCompare(b.name || '', 'ru'));
            break;
        case 'name':
            arr.sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ru'));
            break;
        default:
            break;
    }
    return arr;
}

function appbarHTML(options = {}) {
    const left = options.back
        ? `<button class="icon-btn" data-action="back"><svg width="22" height="22"><use href="#i-back"/></svg></button>`
        : '';
    const right = options.settings
        ? `<button class="icon-btn" data-action="settings"><svg width="21" height="21"><use href="#i-gear"/></svg></button>`
        : (options.more === false ? '' : `<button class="icon-btn" data-action="more"><span class="more">⋯</span></button>`);
    return `${left}<div class="title">${options.title || 'Мой Олимп'}${options.sub ? `<small>${options.sub}</small>` : ''}</div>${right}`;
}

function calendarAppbarHTML(year, monthIndex) {
    return `
        <div class="title">Календарь<small>${formatMonthYear(year, monthIndex)}</small></div>
        <button class="icon-btn" data-action="prev-month" aria-label="Предыдущий месяц"><svg width="20" height="20"><use href="#i-back"/></svg></button>
        <button class="icon-btn" data-action="next-month" aria-label="Следующий месяц"><svg width="20" height="20"><use href="#i-chev"/></svg></button>
    `;
}

function searchbarHTML(placeholder = "Найти олимпиаду или предмет") {
    return `<div class="search-field"><svg width="18" height="18"><use href="#i-search"/></svg><input type="text" placeholder="${placeholder}" id="searchInput"></div>`;
}

function newsBadgeCount() {
    if (!state.newsBadgeVisible) return 0;
    if (Array.isArray(state.news)) {
        return state.news.filter(n => n.category === 'urgent' || n.category === 'wait' || n.category === 'awaiting_answer').length;
    }
    const news = state.news || {};
    return (news.urgent || []).length + (news.awaiting_answer || []).length;
}

function tabbarHTML(active) {
    const tabs = [
        { id: 'search', label: 'Поиск', icon: 'i-search' },
        { id: 'news', label: 'Новости', icon: 'i-board', cnt: newsBadgeCount() },
        { id: 'my', label: 'Мои', icon: 'i-list-star' },
        { id: 'cal', label: 'Календарь', icon: 'i-cal' }
    ];
    return tabs.map(t => `
        <button class="tab ${active === t.id ? 'on' : ''}" data-tab="${t.id}">
            <span class="ic">${iconLink(t.icon, 23)}</span>
            ${t.cnt ? `<span class="cnt">${t.cnt}</span>` : ''}
            ${t.label}
        </button>
    `).join('');
}

// ============ Рендеринг конкретных экранов ============
function renderGradeSelect() {
    appbarEl.innerHTML = appbarHTML({ title: 'Мой Олимп' });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'none';
    const grades = [5, 6, 7, 8, 9, 10, 11];
    contentEl.innerHTML = `
        <div class="content" style="display:flex;flex-direction:column;justify-content:center;padding-bottom:70px">
            <div class="empty" style="padding:0 0 22px">
                <div class="ic">${iconLink('i-cal', 30)}</div>
                <h4>Укажи свой класс</h4>
                <p>Покажем только те олимпиады, в которых ты можешь участвовать в этом году.</p>
            </div>
            <div class="chips">
                ${grades.map(g => `<button class="chip-sel ${state.settings.grade === g ? 'on' : ''}" data-grade="${g}"><b>${g}</b><span>класс</span></button>`).join('')}
            </div>
            <div class="notice info" style="margin-top:24px">
                <span class="ni">${iconLink('i-info', 17)}</span>
                <div>Класс можно изменить в «Мои олимпиады» → Настройки.</div>
            </div>
        </div>
        <div class="sticky-actions"><button class="btn btn-primary" data-action="grade-confirm">Продолжить</button></div>
    `;
    const sticky = contentEl.querySelector('.sticky-actions');
    if (sticky) contentEl.appendChild(sticky);
}

async function renderSubjects() {
    appbarEl.innerHTML = appbarHTML({ title: 'Мой Олимп', sub: `Олимпиады для ${state.settings.grade} класса`, more: false });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML('Найти предмет');
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('search');

    try {
        const data = await Api.catalog.subjects(state.settings.grade);
        state.subjects = Array.isArray(data) ? data : ((data && (data.items || data.subjects)) || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить справочник предметов', err);
        state.subjects = [];
    }
    renderSubjectList('');
}

function renderSubjectList(filter = '') {
    const subjects = state.subjects || [];
    const filtered = subjects.filter(s => (s.name || '').toLowerCase().includes((filter || '').toLowerCase()));
    contentEl.innerHTML = `<div class="list">
        ${filtered.map(s => `
            <div class="row-card" data-subject-id="${s.id}" data-subject-name="${s.name}">
                ${dot(s, true)}
                <div class="rc-body">
                    <div class="rc-title">${s.name}</div>
                    <div class="rc-sub">${s.olympiad_count || 0} олимпиад</div>
                </div>
                ${iconLink('i-chev', 18)}
            </div>
        `).join('')}
    </div>`;
}

function renderOlympiadsBySubject(subjectId, subjectName, filter = '') {
    appbarEl.innerHTML = appbarHTML({ back: true, title: subjectName, more: false });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML('Найти олимпиаду');
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('search');
    olympiadsBySubjectContent(subjectId, subjectName, filter);
}

async function olympiadsBySubjectContent(subjectId, subjectName, filter = '') {
    let olympiads = [];
    try {
        const data = await Api.catalog.list({ subjectId, q: filter, sort: state.sort, grade: state.settings.grade });
        olympiads = Array.isArray(data) ? data : (data.items || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить олимпиады предмета', err);
        olympiads = [];
    }

    state.subjectOlympiadsRaw = olympiads;
    renderSubjectOlympiadList(subjectName, filter);
}

function renderSubjectOlympiadList(subjectName, filter = '') {
    let olympiads = (state.subjectOlympiadsRaw || []).slice();

    if (state.onlyWithDates) {
        olympiads = olympiads.filter(hasKnownDates);
    }

    if (filter) {
        const q = filter.toLowerCase();
        olympiads = olympiads.filter(o =>
            (o.name || '').toLowerCase().includes(q) ||
            (o.description || o.summary || '').toLowerCase().includes(q)
        );
    }

    olympiads = sortOlympiadList(olympiads);

    contentEl.innerHTML = `
        <div class="sort-row">
            <button class="sort-btn active" data-action="open-sort">${iconLink('i-sort', 15)} сортировка${iconLink('i-down', 14)}</button>
            <button class="known-dates-btn ${state.onlyWithDates ? 'on' : ''}" data-action="toggle-known-dates">
                <span class="box">${state.onlyWithDates ? iconLink('i-check', 12) : ''}</span>
                <span>с известными датами</span>
            </button>
        </div>
        ${olympiads.map(o => {
            return `
            <div class="card" data-olympiad-id="${o.id}" data-saved="${o.saved === true}">
                ${dot(subjectName)}
                <div class="c-body">
                    <div class="c-top">
                        <span class="c-title">${o.name}</span>
                        ${badge(o.level + ' ур.', 'lvl')}
                    </div>
                    <div class="c-sub">${subjectName}</div>
                    <div class="c-text">${o.description || o.summary || ''}</div>
                </div>
                ${o.saved ? `<span class="saved-mark">${iconLink('i-check', 13)}<span>пишу</span></span>` : ''}
            </div>
        `;
        }).join('')}
        ${olympiads.length === 0 ? '<p>Нет олимпиад по данному запросу</p>' : ''}
    `;
}

async function renderOlympiadDetail(olympiadId, options = {}) {
    const {
        useMyData = false,
        activeTab = 'search',
        backView = 'subject-olympiads'
    } = options;

    state.olympiadDetailOptions = options;

    let olympiad;
    try {
        olympiad = useMyData ? await Api.my.get(olympiadId) : await Api.catalog.get(olympiadId);
    } catch (err) {
        console.warn('[API] Не удалось загрузить олимпиаду', err);
        olympiad = null;
    }

    if (!olympiad) {
        contentEl.innerHTML = `<div class="empty"><p>Не удалось загрузить олимпиаду</p></div>`;
        return;
    }

    state.selectedOlympiad = olympiad;

    const subject = subjectById(olympiad.subject_id);
    const subjectName = subject ? subject.name : (olympiad.subject_name || '');
    const saved = useMyData || olympiad.saved === true;
    const officialUrl = olympiad.official_url || '';
    const displayUrl = officialUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');

    appbarEl.innerHTML = appbarHTML({ back: true, title: 'Олимпиада', more: false });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = activeTab === 'my' ? tabbarHTML('my') : tabbarHTML('search');

    contentEl.innerHTML = `
        <div class="content flush">
            <div class="hero">
                <h1>${olympiad.name}</h1>
                <div class="subject">${dot(subject, true)}${subjectName}</div>
                <div class="meta-row">
                    ${olympiad.level ? badge(olympiad.level + ' ур.', 'lvl') : ''}
                    ${olympiad.grades ? badge(olympiad.grades, 'grey') : ''}
                    ${olympiad.level === 'I' ? badge('Льготы при поступлении', 'grey') : ''}
                </div>
                <p class="extra">${olympiad.description || olympiad.summary || ''}</p>
            </div>
            <div class="detail-wrap">
                ${organizersHTML(olympiad.organizers)}
                <div class="detail-block">
                    <h4>Даты этапов</h4>
                    ${stagesHTML(olympiad.stages, saved, saved)}
                </div>
                ${officialUrl ? `<a class="link-row" href="${officialUrl}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit;">${iconLink('i-link', 19)}<span class="lt">${displayUrl}</span>${iconLink('i-chev', 17)}</a>` : ''}
                ${saved ? `
                    <div class="act-row">
                        <button class="btn btn-ghost" data-action="view-in-calendar">${iconLink('i-cal', 18)} Посмотреть в календаре</button>
                    </div>
                    <div class="act-row">
                        <button class="btn btn-danger" data-action="remove-olympiad" data-id="${olympiadId}">${iconLink('i-cross', 18)} Удалить из моих олимпиад</button>
                    </div>
                ` : ''}
            </div>
        </div>
        ${saved ? '' : `
        <div class="sticky-actions transparent">
            <button class="btn btn-primary" data-action="add-olympiad" data-id="${olympiadId}">Буду писать</button>
        </div>
        `}
    `;
    const sticky = contentEl.querySelector('.sticky-actions');
    if (sticky) contentEl.appendChild(sticky);
}

function formatDayMonth(date) {
    if (!date) return '';
    const months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
    return `${date.getDate()} ${months[date.getMonth()]}`;
}

function stagesHTML(stages, showPlanActions = false, showPlanLabel = true) {
    if (!Array.isArray(stages) || stages.length === 0) {
        return `<div class="kv"><span class="k">Даты этапов</span><span class="v empty">Информация появится позже</span></div>`;
    }

    const today = new Date(state.today.getFullYear(), state.today.getMonth(), state.today.getDate());

    return stages.map(st => {
        const stageId = st.id || st.stage_id;
        const precision = stagePrecision(st);
        const plannedOn = parseDate(st.planned_on || st.plannedOn);
        const exactDate = parseDate(st.starts_on || st.start_stage || st.date || st.exact_date);
        const stageWindowEnd = parseDate(st.window_end || st.end_stage || st.ends_on);
        const planWindowEnd = parseDate(st.plan_window_end || st.planWindowEnd);
        const windowClosed = (!!stageWindowEnd && stageWindowEnd < today) || (!!planWindowEnd && planWindowEnd < today);
        const result = st.result || st.user_result ||
            (st.status === 'passed' ? 'passed' : st.status === 'failed' ? 'failed' : '');
        // Сервер отдаёт status: upcoming | active | finished | unknown, а закрытый
        // ответом «не прошёл» этап помечает флагом locked.
        const past = st.status === 'past' || st.status === 'finished';
        const blocked = st.locked === true || st.status === 'blocked' || st.status === 'failed' || result === 'failed';

        const cls = ['stage', st.status || ''];
        if (past) cls.push('past');
        if (blocked) cls.push('blocked');

        const markerClass = past ? 'past' : (blocked ? 'blocked' : 'future');

        let planLabel = '';
        if (precision === 'exact') {
            const date = plannedOn || exactDate;
            if (date) planLabel = `Запланировано на ${formatDayMonth(date)}`;
        } else if (precision === 'range' || precision === 'until') {
            if (plannedOn) planLabel = `Запланировано на ${formatDayMonth(plannedOn)}`;
            else if (st.plannable) planLabel = 'Можно планировать';
        } else if (st.plannable) {
            planLabel = 'Можно планировать';
        }

        // На закрытый этап сервер ответ не примет (stage_locked) — кнопки не показываем.
        const showResultButtons = showPlanActions && windowClosed && stageId && st.locked !== true;
        if (showResultButtons) planLabel = '';

        return `
            <div class="${cls.join(' ')}">
                <div class="marker"><span class="mk ${markerClass}"></span></div>
                <div class="s-body">
                    <div class="s-top"><span class="s-name">${st.name || 'Этап'}</span></div>
                    <div class="s-date">${st.raw_date_range || st.date_range || 'Дата пока неизвестна'}</div>
                    ${showPlanLabel && planLabel ? `<span class="s-planned">${planLabel}</span>` : ''}
                    ${showResultButtons ? `
                        <div class="s-actions">
                            <button class="btn btn-sm ${result === 'passed' ? 'btn-primary' : 'btn-ghost'}" data-action="stage-passed" data-stage-id="${stageId}">Я прошёл(а)</button>
                            <button class="btn btn-sm ${result === 'failed' ? 'btn-primary' : 'btn-ghost'}" data-action="stage-failed" data-stage-id="${stageId}">Я не прошёл(а)</button>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function normalizeOrganizers(organizers) {
    if (Array.isArray(organizers)) return organizers;
    if (organizers && typeof organizers === 'object') return Object.values(organizers);
    return [];
}

function organizersHTML(organizers) {
    const list = normalizeOrganizers(organizers).filter(Boolean);
    if (!list.length) return '';

    return `
        <div class="detail-block">
            <h4>Организаторы</h4>
            <div class="orgs">
                ${list.map((org, index) => {
                    const name = typeof org === 'string' ? org : (org.name || org.full_name || org.title || '');
                    const role = typeof org === 'string' ? '' : (org.role || org.type || org.role_name || '');
                    const logo = String(index + 1);
                    return `
                        <div class="org">
                            <span class="logo">${logo}</span>
                            <div>
                                <div class="on">${name}</div>
                                ${role ? `<div class="od">${role}</div>` : ''}
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        </div>
    `;
}

function renderNewsCompactCard(n, categoryKey = '') {
    const subject = typeof n.subject === 'string'
        ? subjectByName(n.subject)
        : (n.subject && typeof n.subject === 'object' ? n.subject : subjectById(n.subject_id));
    const subjectName = subject
        ? (subject.name || subject.n || '')
        : (n.subject_name || (typeof n.subject === 'string' ? n.subject : ''));
    const title = n.title || n.olympiad_name || n.name || '';
    const level = n.level || '';
    const olympiadId = n.olympiad_id || n.olympiadId || n.olympiad || '';

    return `
        <div class="news-card ${categoryKey}" data-olympiad-id="${olympiadId}" data-from-mine="true">
            ${dot(subject)}
            <div class="c-body">
                <div class="c-top">
                    <span class="c-title">${title}</span>
                    ${level ? badge(level + ' ур.', 'lvl') : ''}
                </div>
                <div class="c-sub">${subjectName}</div>
            </div>
        </div>
    `;
}

async function renderNews() {
    appbarEl.innerHTML = appbarHTML({ title: 'Новости', more: false });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';

    try {
        const data = await Api.news();
        state.news = data || {};
    } catch (err) {
        console.warn('[API] Не удалось загрузить новости', err);
        state.news = {};
    }
    tabbarEl.innerHTML = tabbarHTML('news');
    renderNewsContent();
}

function renderNewsContent() {
    const getItems = (key) => {
        if (Array.isArray(state.news)) {
            return state.news.filter(n => n.category === key);
        }
        return Array.isArray(state.news[key]) ? state.news[key] : [];
    };

    const categories = [
        { key: 'dates_added', label: 'Появились даты', color: '#9500FF' },
        { key: 'urgent', label: 'Срочно', color: 'var(--danger)' },
        { key: 'soon', label: 'Скоро', color: 'var(--warn)' },
        { key: 'later', label: 'Позже', color: 'var(--max-blue)' },
        { key: 'awaiting_answer', label: 'Ожидает ответа от тебя', color: 'var(--max-primary)' },
        { key: 'finished', label: 'Завершено', color: 'var(--grey-stage)' }
    ];

    contentEl.innerHTML = categories.map(cat => {
        const items = getItems(cat.key);
        const expanded = !!state.newsExpanded[cat.key];
        const visibleItems = expanded ? items : items.slice(0, 1);

        if (cat.key === 'dates_added') {
            return `
                <div class="news-group">
                    <div class="news-head">
                        <h4 style="color:${cat.color}">${cat.label}</h4>
                        <span class="n">${items.length}</span>
                        ${items.length > 1 ? `<button class="news-expand ${expanded ? 'open' : ''}" data-action="toggle-news-expand" data-category="${cat.key}">${iconLink('i-down', 17)}</button>` : ''}
                    </div>
                    ${items.length === 0 ? '<div class="news-empty">Здесь пока пусто</div>' : visibleItems.map(n => renderNewsCompactCard(n, cat.key)).join('')}
                </div>
            `;
        }

        if (cat.key === 'awaiting_answer' && items.length === 0) {
            return `
                <div class="news-group">
                    <div class="news-head">
                        <h4 style="color:${cat.color}">${cat.label}</h4>
                        <span class="n">0</span>
                    </div>
                    <div class="news-empty">Здесь пока пусто</div>
                </div>
            `;
        }

        if (cat.key === 'finished') {
            return `
                <div class="news-group">
                <div class="news-head">
                <h4 style="color:${cat.color}">${cat.label}</h4>
                <span class="n">${items.length}</span>
                <svg class="chev" width="17" height="17"><use href="#i-chev"/></svg>
                </div>
                </div>
            `;
        }

        if (items.length === 0) return '';

        return `
            <div class="news-group">
                <div class="news-head">
                <h4 style="color:${cat.color}">${cat.label}</h4>
                <span class="n">${items.length}</span>
                ${items.length > 1 ? `<button class="news-expand ${expanded ? 'open' : ''}" data-action="toggle-news-expand" data-category="${cat.key}">${iconLink('i-down', 17)}</button>` : ''}
                </div>
                ${visibleItems.map(n => renderNewsCompactCard(n, cat.key)).join('')}
            </div>
        `;
    }).join('');
}

async function renderMyOlympiads(filter = '') {
    appbarEl.innerHTML = appbarHTML({ title: 'Мои олимпиады', settings: true });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML();
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('my');
    await myOlympiadsContent(filter);
}

function sortMyOlympiads(list) {
    switch (state.sort) {
        case 'level':
            list.sort((a, b) => a.level - b.level || a.name.localeCompare(b.name, 'ru'));
            break;
        case 'name':
            list.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
            break;
        case 'urgency':
        default:
            break;
    }
    return list;
}

async function myOlympiadsContent(filter = '') {
    let myOlympiadsData = [];
    try {
        const data = await Api.my.list({ q: filter, grade: state.settings.grade });
        myOlympiadsData = Array.isArray(data) ? data : (data.items || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить мои олимпиады', err);
        myOlympiadsData = [];
    }

    const totalBeforeFilter = myOlympiadsData.length;
    myOlympiadsData = myOlympiadsData.filter(o => isOlympiadAvailableForGrade(o, state.settings.grade));
    const hiddenCount = totalBeforeFilter - myOlympiadsData.length;

    state.myOlympiadsRaw = myOlympiadsData;
    state.myHiddenCount = hiddenCount;
    renderMyOlympiadList(filter);
}

function renderMyOlympiadList(filter = '') {
    let myOlympiadsData = (state.myOlympiadsRaw || []).slice();

    if (state.onlyWithDates) {
        myOlympiadsData = myOlympiadsData.filter(hasKnownDates);
    }

    if (filter) {
        const q = filter.toLowerCase();
        myOlympiadsData = myOlympiadsData.filter(o =>
            (o.name || '').toLowerCase().includes(q) ||
            (o.subject_name || '').toLowerCase().includes(q)
        );
    }

    myOlympiadsData = sortOlympiadList(myOlympiadsData);

    contentEl.innerHTML = `
        <div class="sort-row">
            <button class="sort-btn active" data-action="open-sort-my">${iconLink('i-sort', 15)} сортировка${iconLink('i-down', 14)}</button>
            <button class="known-dates-btn ${state.onlyWithDates ? 'on' : ''}" data-action="toggle-known-dates">
                <span class="box">${state.onlyWithDates ? iconLink('i-check', 12) : ''}</span>
                <span>с известными датами</span>
            </button>
        </div>
        ${state.myHiddenCount > 0 ? `<div class="notice info"><span class="ni">${iconLink('i-info', 17)}</span><div>Скрыто ${state.myHiddenCount} олимпиад, недоступных для ${state.settings.grade} класса.</div></div>` : ''}
        ${myOlympiadsData.length === 0 ? `
            <div class="empty">
                <div class="ic">${iconLink('i-list-star', 28)}</div>
                <h4>${filter ? 'Ничего не найдено' : 'Пока здесь пусто'}</h4>
                <p>${filter ? 'Попробуйте изменить запрос.' : 'Перейди на вкладку «Поиск», выбери олимпиаду и нажми «Буду писать».'}</p>
                ${!filter ? `<button class="btn btn-primary" data-action="go-to-search">Перейти к поиску</button>` : ''}
            </div>
        ` : myOlympiadsData.map(o => {
            const subject = subjectById(o.subject_id);
            return `
                <div class="card" data-olympiad-id="${o.id}" data-from-mine="true">
                    ${dot(subject)}
                    <div class="c-body">
                        <div class="c-top">
                            <span class="c-title">${o.name}</span>
                            ${badge(o.level + ' ур.', 'lvl')}
                        </div>
                        <div class="c-sub">${subject ? subject.name : ''}</div>
                        <div class="c-text">${o.description || o.summary || ''}</div>
                    </div>
                </div>
            `;
        }).join('')}
    `;
}

// ============ Календарь ============
function toISODate(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function parseDate(value) {
    if (!value) return null;
    if (value instanceof Date) {
        return new Date(value.getFullYear(), value.getMonth(), value.getDate());
    }
    if (typeof value === 'string') {
        const m = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
        const d = new Date(value);
        if (!isNaN(d.getTime())) return new Date(d.getFullYear(), d.getMonth(), d.getDate());
    }
    return null;
}

function calendarOlympiadsFromData(data) {
    if (Array.isArray(data)) return data;
    if (!data || typeof data !== 'object') return [];

    // Массив внутри обёртки: { items: [...] }, { events: [...] }, { olympiads: [...] }
    const arrayKeys = ['items', 'events', 'olympiads'];
    for (const key of arrayKeys) {
        if (Array.isArray(data[key])) return data[key];
    }

    // Словарь внутри обёртки: { items: { "392": {...} } }
    const candidates = [];
    for (const key of arrayKeys) {
        const dict = data[key];
        if (dict && typeof dict === 'object' && !Array.isArray(dict)) {
            candidates.push(...Object.values(dict));
        }
    }

    // Словарь на верхнем уровне: { "392": {...} }
    if (!candidates.length) {
        candidates.push(...Object.values(data));
    }

    return candidates.filter(v => v && typeof v === 'object');
}

function olympiadSubjectName(item) {
    if (typeof item.subject === 'string') return item.subject;
    return item.subject_name || (item.subject && item.subject.name) || '';
}

function olympiadSubjectColor(item) {
    return item.color || item.subject_color || (item.subject && item.subject.color) || undefined;
}

function stageStart(stage) {
    return stage.starts_on || stage.start_stage || stage.window_start || stage.start || stage.date_start;
}

function stageEnd(stage) {
    return stage.ends_on || stage.end_stage || stage.window_end || stage.end || stage.date_end;
}

function stagePrecision(stage) {
    if (stage.date_precision) return stage.date_precision;
    if (stage.precision) return stage.precision;

    const start = parseDate(stageStart(stage));
    const end = parseDate(stageEnd(stage));

    if (start && end) {
        return isSameDate(start, end) ? 'exact' : 'range';
    }
    if (start) return 'exact';
    if (end) return 'until';
    return 'unknown';
}

function olympiadStages(item) {
    const stages = Array.isArray(item.stages) ? item.stages.slice() : [];

    if (item.next_stage) {
        const next = item.next_stage;
        const exists = stages.some(s =>
            s && (s.id === next.id || (s.name === next.name && s.starts_on === next.starts_on))
        );
        if (!exists) stages.push(next);
    }

    return stages;
}

function normalizeFlatCalendarEvent(item) {
    const subjectId = item.subject_id;
    return {
        activity_id: item.stage_id || item.activity_id,
        olympiad_id: item.olympiad_id || item.id,
        name: item.olympiad_name || item.name,
        subject_id: subjectId,
        subject: item.subject_name ||
            (typeof item.subject === 'string' ? item.subject : (item.subject && item.subject.name)) ||
            (subjectId ? subjectNameById(subjectId) : ''),
        date_precision: item.date_precision ||
            (item.single_day ? 'exact' : undefined) ||
            (item.window_start && item.window_end ? 'range' : undefined) ||
            (item.window_end ? 'until' : undefined),
        start_stage: item.window_start || item.start_stage || item.starts_on || item.start,
        end_stage: item.window_end || item.end_stage || item.ends_on || item.end,
        color: item.color ||
            item.subject_color ||
            (item.subject && item.subject.color) ||
            (subjectId ? subjectColorById(subjectId) : undefined),
        name_stage: item.stage_name || item.name_stage,
        stage_id: item.stage_id,
        kind: item.kind,
        planned_on: item.planned_on
    };
}

function normalizeCalendarEvents(data) {
    const events = [];

    calendarOlympiadsFromData(data).forEach(item => {
        if (!item) return;

        const stages = olympiadStages(item);

        if (stages.length) {
            stages.forEach(stage => {
                if (!stage) return;
                events.push({
                    activity_id: item.activity_id || item.id,
                    olympiad_id: item.olympiad_id || item.id,
                    stage_id: stage.id || stage.stage_id,
                    name: item.name || item.olympiad_name,
                    subject: olympiadSubjectName(item),
                    date_precision: stagePrecision(stage),
                    start_stage: stageStart(stage),
                    end_stage: stageEnd(stage),
                    color: olympiadSubjectColor(item),
                    name_stage: stage.name || stage.name_stage,
                    source_text: stage.source_text || stage.raw_date_range,
                    parser_warning: stage.parser_warning,
                    planned_on: stage.planned_on || item.planned_on
                });
            });
        } else if (item.date_precision || item.window_start || item.window_end || item.start_stage || item.end_stage || item.starts_on || item.ends_on) {
            events.push(normalizeFlatCalendarEvent(item));
        }
    });

    return events;
}

function isStageInFuture(ev) {
    const precision = ev.date_precision || ev.precision;
    if (precision === 'unknown' || !precision) return false;

    const today = new Date(state.today.getFullYear(), state.today.getMonth(), state.today.getDate());

    if (precision === 'range' || precision === 'until') {
        const end = parseDate(ev.end_stage);
        return !!end && end >= today;
    }

    if (precision === 'exact') {
        const date = parseDate(ev.start_stage || ev.end_stage);
        return !!date && date >= today;
    }

    return false;
}

function isEventOnDate(ev, date) {
    const precision = ev.date_precision || ev.precision || 'unknown';
    const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());

    if (precision === 'range') {
        const start = parseDate(ev.start_stage);
        const end = parseDate(ev.end_stage);
        return !!start && !!end && day >= start && day <= end;
    }

    if (precision === 'until') {
        const end = parseDate(ev.end_stage);
        if (!end) return false;
        const start = addDays(end, -10);
        return day >= start && day <= end;
    }

    if (precision === 'exact') {
        const exact = parseDate(ev.start_stage || ev.end_stage || ev.date || ev.exact_date);
        return !!exact && isSameDate(day, exact);
    }

    return false;
}

function eventKey(ev) {
    if (ev.stage_id) return String(ev.stage_id);
    if (ev.activity_id) return String(ev.activity_id);
    return `${ev.olympiad_id || ev.id || 'ev'}:${ev.name || ''}:${ev.start_stage || ''}:${ev.end_stage || ''}`;
}

function plannedDateStr(ev) {
    const planned = parseDate(ev.planned_on);
    return planned ? toISODate(planned) : null;
}

function findCalendarEventByKey(key) {
    return (state.calendarEvents || []).find(ev => eventKey(ev) === key);
}

function forEachDayMatching(weeks, date, callback) {
    if (!date) return;
    weeks.forEach(week => {
        week.days.forEach(dayObj => {
            const current = new Date(dayObj.year, dayObj.month, dayObj.day);
            if (isSameDate(current, date)) callback(dayObj);
        });
    });
}

function addDayMark(dayObj, ev, color) {
    if (!dayObj._markKeys) dayObj._markKeys = new Set();
    const key = eventKey(ev);
    if (dayObj._markKeys.has(key)) return;
    dayObj._markKeys.add(key);
    if (!dayObj._markColors) dayObj._markColors = [];
    dayObj._markColors.push(color);
}

function pluralOlympiads(n) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return 'олимпиада';
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'олимпиады';
    return 'олимпиад';
}

async function getMyOlympiadNames() {
    try {
        const data = await Api.my.list({ q: '', grade: state.settings.grade });
        const list = Array.isArray(data) ? data : ((data && (data.items || [])) || []);
        const available = list.filter(o => isOlympiadAvailableForGrade(o, state.settings.grade));
        return new Set(available
            .map(o => o.name || o.olympiad_name || o.title)
            .filter(Boolean)
            .map(name => name.trim().toLowerCase())
        );
    } catch (err) {
        console.warn('[API] Не удалось загрузить мои олимпиады для календаря', err);
        return null;
    }
}

async function renderCalendar(year, monthIndex) {
    if (year === undefined || monthIndex === undefined) {
        year = state.calendarDate.year || 2026;
        monthIndex = state.calendarDate.month ?? 8; // сентябрь по умолчанию
    }
    state.calendarDate = { year, month: monthIndex };

    appbarEl.innerHTML = calendarAppbarHTML(year, monthIndex);
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('cal');

    const weeks = buildCalendarMonth(year, monthIndex);

    const firstDay = weeks[0]?.days[0];
    const lastDay = weeks[weeks.length - 1]?.days[6];
    const from = toISODate(new Date(firstDay.year, firstDay.month, firstDay.day));
    const to = toISODate(new Date(lastDay.year, lastDay.month, lastDay.day));

    let events = [];
    try {
        const data = await Api.calendar.range(from, to);
        events = normalizeCalendarEvents(data).filter(isStageInFuture);
    } catch (err) {
        console.warn('[API] Не удалось загрузить календарь', err);
    }

    // В календаре показываем только олимпиады из вкладки «Мои олимпиады».
    const myOlympiadNames = await getMyOlympiadNames();
    if (myOlympiadNames) {
        events = events.filter(ev => {
            const name = (ev.name || ev.olympiad_name || ev.title || '').trim().toLowerCase();
            return myOlympiadNames.has(name);
        });
    }

    state.calendarEvents = events;

    const lanesByWeek = buildLanesForMonth(events, weeks);

    contentEl.innerHTML = `<div class="cal-card">` +
        calDow() +
        weeks.map((week, wi) => calWeek(week.days, lanesByWeek[wi] || [])).join('') +
        legend(getLegendSubjects(events)) +
        `</div>`;
}

function buildCalendarMonth(year, monthIndex) {
    const firstDayOfMonth = new Date(year, monthIndex, 1);
    const startWeekday = (firstDayOfMonth.getDay() + 6) % 7; // 0 = понедельник
    const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();

    const gridStart = new Date(year, monthIndex, 1 - startWeekday);
    const totalDays = Math.ceil((startWeekday + daysInMonth) / 7) * 7;
    const gridEnd = new Date(year, monthIndex, 1 - startWeekday + totalDays);

    const weeks = [];
    const currentDate = new Date(gridStart);
    while (currentDate < gridEnd) {
        const week = [];
        for (let i = 0; i < 7; i++) {
            const day = currentDate.getDate();
            const month = currentDate.getMonth();
            const currentYear = currentDate.getFullYear();
            week.push({
                day,
                month,
                year: currentYear,
                isCurrentMonth: month === monthIndex && currentYear === year,
                isToday: isSameDate(currentDate, state.today)
            });
            currentDate.setDate(currentDate.getDate() + 1);
        }
        weeks.push({ days: week });
    }
    return weeks;
}

function shiftMonth(delta) {
    let y = state.calendarDate.year;
    let m = state.calendarDate.month + delta;
    if (m < 0) {
        m = 11;
        y -= 1;
    } else if (m > 11) {
        m = 0;
        y += 1;
    }
    renderCalendar(y, m);
}

function isSameDate(d1, d2) {
    if (!d1 || !d2) return false;
    return d1.getFullYear() === d2.getFullYear() &&
        d1.getMonth() === d2.getMonth() &&
        d1.getDate() === d2.getDate();
}

function formatMonthYear(year, monthIndex) {
    const monthNames = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
        'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
    return `${monthNames[monthIndex]} ${year}`;
}

function addDays(date, days) {
    const result = new Date(date);
    result.setDate(result.getDate() + days);
    return result;
}

function diffDays(from, to) {
    const a = new Date(from.getFullYear(), from.getMonth(), from.getDate());
    const b = new Date(to.getFullYear(), to.getMonth(), to.getDate());
    return Math.round((b - a) / 86400000);
}

function eventSubject(ev) {
    if (ev && typeof ev.subject === 'string') return ev.subject;
    if (ev && ev.subject && typeof ev.subject === 'object' && ev.subject.name) return ev.subject.name;
    return ev.subject_name || 'Олимпиада';
}

function eventColor(ev) {
    return ev.color ||
        ev.subject_color ||
        (ev && ev.subject && typeof ev.subject === 'object' && ev.subject.color) ||
        subjectColor(eventSubject(ev)) ||
        '#ccc';
}

function pushRangeLane(lanesByWeek, weeks, lane) {
    weeks.forEach((week, wi) => {
        const weekStart = new Date(week.days[0].year, week.days[0].month, week.days[0].day);
        const weekEnd = new Date(week.days[6].year, week.days[6].month, week.days[6].day);

        if (lane.end < weekStart || lane.start > weekEnd) return;

        const fromDate = lane.start > weekStart ? lane.start : weekStart;
        const toDate = lane.end < weekEnd ? lane.end : weekEnd;

        const from = Math.max(0, Math.min(6, diffDays(weekStart, fromDate)));
        const to = Math.max(0, Math.min(6, diffDays(weekStart, toDate)));

        lanesByWeek[wi].push({
            subject: lane.subject,
            c: lane.color,
            from,
            to,
            ...(lane.type === 'until' ? { type: 'until' } : {})
        });
    });
}

function buildLanesForMonth(events, weeks) {
    const lanesByWeek = weeks.map(() => []);

    (events || []).forEach(ev => {
        const precision = ev.date_precision || ev.precision || 'unknown';
        const subject = eventSubject(ev);
        const color = eventColor(ev);

        if (precision === 'range') {
            const start = parseDate(ev.start_stage);
            const end = parseDate(ev.end_stage);
            if (!start || !end) return;
            pushRangeLane(lanesByWeek, weeks, { subject, color, start, end, type: 'range' });
        } else if (precision === 'until') {
            const end = parseDate(ev.end_stage);
            if (!end) return;
            const start = addDays(end, -10);
            pushRangeLane(lanesByWeek, weeks, { subject, color, start, end, type: 'until' });
        }
        // precision === 'unknown' — полос не рисуем, но метки planned_on учитываем ниже.

        // Кружок/диаграмма на дне: exact-событие и/или отметка «планирую писать».
        const exactDate = precision === 'exact'
            ? parseDate(ev.start_stage || ev.end_stage || ev.date || ev.exact_date)
            : null;
        const plannedDate = parseDate(ev.planned_on);

        if (exactDate) {
            forEachDayMatching(weeks, exactDate, dayObj => addDayMark(dayObj, ev, color));
        }
        if (plannedDate) {
            forEachDayMatching(weeks, plannedDate, dayObj => addDayMark(dayObj, ev, color));
        }
    });

    // Метка «+N» и готовые сегменты для диаграммы (sel1/sel2/sel3).
    weeks.forEach(week => {
        week.days.forEach(dayObj => {
            const colors = dayObj._markColors || [];
            if (colors.length > 0) dayObj.sel = colors.slice(0, 3);
            if (colors.length > 3) dayObj.plus = colors.length - 3;
        });
    });

    lanesByWeek.forEach(lanes => lanes.sort((a, b) => a.from - b.from || a.to - b.to));
    return lanesByWeek;
}

function getLegendSubjects(events) {
    const seen = new Set();
    return (events || [])
        .filter(ev => (ev.date_precision || ev.precision || 'unknown') !== 'unknown')
        .map(ev => eventSubject(ev))
        .filter(Boolean)
        .filter(subject => {
            if (seen.has(subject)) return false;
            seen.add(subject);
            return true;
        });
}

function calDow() {
    return `<div class="cal-dow">${['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'].map(d => `<span>${d}</span>`).join('')}</div>`;
}

function calDay(dayObj) {
    if (!dayObj) return '<div class="day empty-day"></div>';

    const { day, isCurrentMonth, isToday } = dayObj;

    const cls = ['day'];
    if (!isCurrentMonth) cls.push('dim');
    // Синяя обводка — только у сегодняшней даты
    if (isToday) cls.push('today');

    let vars = '';
    const sel = dayObj.sel || [];
    if (sel.length === 1) {
        cls.push('sel1');
        vars = `--seg1:${sel[0]}`;
    } else if (sel.length === 2) {
        cls.push('sel2');
        vars = `--seg1:${sel[0]};--seg2:${sel[1]}`;
    } else if (sel.length >= 3) {
        cls.push('sel3');
        vars = `--seg1:${sel[0]};--seg2:${sel[1]};--seg3:${sel[2]}`;
    }

    const plus = dayObj.plus ? `<span class="plus">+${dayObj.plus}</span>` : '';

    return `<div class="${cls.join(' ')}" style="${vars}" data-day="${day}" data-month="${dayObj.month}" data-year="${dayObj.year}" data-other-month="${!isCurrentMonth}">
        <div class="circle"><span class="num">${day}</span></div>
        ${plus}
    </div>`;
}

function calWeek(days, lanes) {
    lanes = lanes || [];

    const rows = [];
    lanes.forEach(l => {
        let placed = false;
        for (let row of rows) {
            if (!row.some(ex => !(l.to < ex.from - 1 || l.from > ex.to + 1))) {
                row.push(l);
                placed = true;
                break;
            }
        }
        if (!placed) rows.push([l]);
    });

    const laneH = rows.length > 0 ? Math.max(3, 7 - (rows.length - 1)) : 7;

    let lanesHtml = '<div class="lanes">';
    rows.forEach(row => {
        lanesHtml += '<div class="lane-row">' + row.map(l => {
            const left = (l.from / 7 * 100);
            const w = ((l.to - l.from + 1) / 7 * 100);
            const background = l.type === 'until'
                ? `linear-gradient(to right, transparent 0%, ${l.c} 100%)`
                : l.c;
            const laneClass = 'lane' + (l.type === 'until' ? ' lane-until' : '');
            return `<span class="${laneClass}" style="left:calc(${left}% + 3px);width:calc(${w}% - 6px);background:${background}"></span>`;
        }).join('') + '</div>';
    });
    lanesHtml += '</div>';

    const daysHtml = days.map(dayObj => calDay(dayObj)).join('');
    return `<div class="cal-week" style="--lane-h:${laneH}px">${lanesHtml}${daysHtml}</div>`;
}

function legend(subjects) {
    const subjectItems = subjects.map(s => {
        const sub = subjectByName(s);
        const color = sub ? (sub.color || sub.c) : subjectColor(s);
        return `<div class="li"><i style="background:${color}"></i>${s}</div>`;
    }).join('');

    const hint = `
        <div class="cal-legend-hint">
            <span class="hint"><i class="sw range"></i>промежуток дат</span>
            <span class="hint"><i class="sw single"></i>один день</span>
            <span class="hint"><i class="sw ends"></i>срок до даты</span>
        </div>
    `;

    return `<div class="legend">${subjectItems}</div>${hint}`;
}

function calendarDayItems(day) {
    const date = new Date(state.calendarDate.year, state.calendarDate.month, day);
    const dateStr = toISODate(date);

    const items = (state.calendarEvents || [])
        .filter(ev => isEventOnDate(ev, date))
        .map(ev => {
            const precision = ev.date_precision || ev.precision || 'unknown';
            const plannedOn = plannedDateStr(ev);
            const key = eventKey(ev);
            const stageId = ev.stage_id || ev.activity_id;
            const exactUnplanned = state.calendarUnplannedExact.has(key);
            const plannedOther = !!plannedOn && plannedOn !== dateStr;

            let selected = plannedOn === dateStr;
            if (precision === 'exact' && !plannedOther) selected = !exactUnplanned;

            return {
                ...ev,
                key,
                precision,
                stageId,
                dateStr,
                plannedOn,
                plannedOther,
                selected,
                selectable: !!stageId && !plannedOther,
                limitReached: false
            };
        });

    const manualSelectedCount = items.filter(i =>
        i.selected && (i.precision === 'range' || i.precision === 'until')
    ).length;

    items.forEach(item => {
        if (!item.selected && item.selectable &&
            (item.precision === 'range' || item.precision === 'until') &&
            manualSelectedCount >= 3) {
            item.limitReached = true;
        }
    });

    return items;
}

function renderCalendarDayDetail(day, limitHit = false) {
    state.calendarSelectedDay = day;

    const { year, month } = state.calendarDate;
    const monthName = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'][month];
    const weekday = new Date(year, month, day).toLocaleDateString('ru-RU', { weekday: 'long' });
    const weekdayCap = weekday.charAt(0).toUpperCase() + weekday.slice(1);

    const items = calendarDayItems(day);
    state.calendarDayItems = items;
    const selectedCount = items.filter(item => item.selected).length;

    appbarEl.innerHTML = appbarHTML({ back: true, title: `${day} ${monthName} ${year}`, sub: weekdayCap });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('cal');

    contentEl.innerHTML = `
        ${limitHit ? `<div class="notice warn"><span class="ni">${iconLink('i-warn', 17)}</span><div>Можно отметить не больше трёх олимпиад в этот день.</div></div>` : ''}
        <div class="daybar"><div class="db-t">${selectedCount} ${pluralOlympiads(selectedCount)} в этот день</div>${iconLink('i-down', 18)}</div>
        ${items.length === 0 ? `
            <div class="empty">
                <div class="ic">${iconLink('i-cal', 28)}</div>
                <h4>Нет олимпиад</h4>
                <p>В этот день нет олимпиад из вкладки «Мои олимпиады».</p>
            </div>
        ` : `
            <div class="list">${items.map(renderCalendarDayItem).join('')}</div>
        `}
    `;
}

function renderCalendarDayItem(item) {
    const subjectName = item.subject || item.subject_name || '';
    const title = item.name || item.olympiad_name || 'Олимпиада';
    const sub = [subjectName, item.name_stage].filter(Boolean).join(' · ');
    const text = item.source_text || item.parser_warning || '';

    const cls = ['card', 'day-check'];
    if (item.plannedOther) cls.push('taken');

    const cbCls = ['cb'];
    let cbIcon = '';
    if (item.plannedOther) {
        cbCls.push('lock');
        cbIcon = iconLink('i-lock', 12);
    } else if (item.selected) {
        cbCls.push('on');
        cbIcon = iconLink('i-check', 13);
    }

    return `
        <div class="${cls.join(' ')}" data-action="toggle-day-plan" data-key="${item.key}" data-stage-id="${item.stageId || ''}">
            ${dot(subjectName)}
            <div class="c-body">
                <div class="c-top"><span class="c-title">${title}</span></div>
                ${sub ? `<div class="c-sub">${sub}</div>` : ''}
                ${text ? `<div class="c-text">${text}</div>` : ''}
            </div>
            <div class="cb-side">
                ${item.plannedOther && item.plannedOn ? `<span class="planned-other-date">${formatDayMonth(parseDate(item.plannedOn))}</span>` : ''}
                <span class="${cbCls.join(' ')}">${cbIcon}</span>
            </div>
        </div>
    `;
}

function renderSettingsModal() {
    const modal = document.createElement('div');
    modal.className = 'scrim center';
    modal.innerHTML = `
        <div class="modal">
            <h3>Настройки</h3>
            <div class="menu-item">
                <div class="mi-ic">${iconLink('i-edit', 18)}</div>
                <div class="mi-body"><div class="mi-t">Класс обучения</div><div class="mi-d">Сейчас: ${state.settings.grade} класс</div></div>
                <button class="btn btn-sm btn-primary" data-action="change-grade">Изменить</button>
            </div>
            <div class="menu-item">
                <div class="mi-ic">${iconLink('i-bell', 18)}</div>
                <div class="mi-body"><div class="mi-t">PUSH-уведомления</div><div class="mi-d">Напоминания об этапах</div></div>
                <button class="switch ${state.settings.notifications_enabled ? 'on' : ''}" data-action="toggle-notifications"></button>
            </div>
            <div class="menu-item">
                <div class="mi-ic">${iconLink('i-eye', 18)}</div>
                <div class="mi-body"><div class="mi-t">Режим для дальтоников</div><div class="mi-d">Текстовые метки к цветам</div></div>
                <button class="switch ${state.settings.colorblind_mode ? 'on' : ''}" data-action="toggle-colorblind"></button>
            </div>
            <button class="btn btn-primary" style="margin-top:18px" data-action="close-modal">Готово</button>
        </div>
    `;
    document.getElementById('app').appendChild(modal);
}

function renderGradeModal() {
    const modal = document.createElement('div');
    modal.className = 'scrim center';
    modal.innerHTML = `
        <div class="modal">
            <h3>Выбери класс</h3>
            <p style="font-size:13px;color:var(--text-3);margin:0 0 var(--s4);line-height:1.45;">Покажем олимпиады для выбранного класса.</p>
            <div class="chips">
                ${[5, 6, 7, 8, 9, 10, 11].map(g => `
                    <button class="chip-sel ${state.settings.grade === g ? 'on' : ''}" data-action="select-grade" data-grade="${g}">
                        <b>${g}</b><span>класс</span>
                    </button>
                `).join('')}
            </div>
        </div>
    `;
    document.getElementById('app').appendChild(modal);
}

function renderSortModal() {
    const modal = document.createElement('div');
    modal.className = 'scrim';
    modal.innerHTML = `
        <div class="sheet">
            <div class="grabber"></div>
            <h3>Сортировать по…</h3>
            <button class="option ${state.sort === 'level' ? 'on' : ''}" data-sort-value="level">
                <span class="op-t">Уровню олимпиады<span class="op-d">Сначала I уровень, затем II и III</span></span>
                <span class="check">${state.sort === 'level' ? iconLink('i-check', 13) : ''}</span>
            </button>
            <button class="option ${state.sort === 'urgency' ? 'on' : ''}" data-sort-value="urgency">
                <span class="op-t">Срочности<span class="op-d">Ближайшие даты регистрации в начале</span></span>
                <span class="check">${state.sort === 'urgency' ? iconLink('i-check', 13) : ''}</span>
            </button>
            <button class="option ${state.sort === 'name' ? 'on' : ''}" data-sort-value="name">
                <span class="op-t">Названию<span class="op-d">Алфавитный порядок</span></span>
                <span class="check">${state.sort === 'name' ? iconLink('i-check', 13) : ''}</span>
            </button>
        </div>
    `;
    document.getElementById('app').appendChild(modal);
}

function closeModal() {
    const modal = document.querySelector('.scrim');
    if (modal) modal.remove();
}

async function toggleSetting(field) {
    const previousValue = state.settings[field];
    const nextValue = !previousValue;

    state.settings[field] = nextValue;
    closeModal();
    renderSettingsModal();

    try {
        await Api.settings.save({ [field]: nextValue });
    } catch (err) {
        console.warn('[API] Не удалось сохранить настройку', err);
        state.settings[field] = previousValue;
        closeModal();
        renderSettingsModal();
    }
}

// ============ Обработка кликов ============
document.addEventListener('click', async function (e) {
    // Клик по фону модалки (вне самой панели) — просто закрываем без применения
    const scrim = e.target.closest('.scrim');
    if (scrim && !e.target.closest('.sheet') && !e.target.closest('.modal')) {
        closeModal();
        return;
    }

    const target = e.target.closest('[data-action], [data-tab], [data-subject-id], [data-olympiad-id], [data-day], [data-grade], [data-sort-value], [data-stage-id]');
    if (!target) return;

    const action = target.dataset.action;
    const tab = target.dataset.tab;
    const subjectId = target.dataset.subjectId;
    const subjectName = target.dataset.subjectName;
    const olympiadId = target.dataset.olympiadId;
    const day = target.dataset.day;
    const grade = target.dataset.grade;
    const sortValue = target.dataset.sortValue;
    const stageId = target.dataset.stageId;
    const fromMine = target.dataset.fromMine === 'true';
    const savedFlag = target.dataset.saved === 'true';

    if (action === 'close') {
        if (window.WebApp) WebApp.close();
        return;
    }

    if (action === 'prev-month') {
        shiftMonth(-1);
        return;
    }

    if (action === 'next-month') {
        shiftMonth(1);
        return;
    }

    if (action === 'back') {
        if (state.view === 'subject-olympiads') {
            state.selectedSubject = null;
            state.view = 'subjects';
            renderSubjects();
        } else if (state.view === 'olympiad-detail') {
            state.selectedOlympiad = null;
            state.view = 'subject-olympiads';
            if (state.selectedSubject) {
                renderOlympiadsBySubject(state.selectedSubject.id, state.selectedSubject.name);
            } else {
                renderSubjects();
            }
        } else if (state.view === 'olympiad-detail-mine') {
            state.selectedOlympiad = null;
            state.view = 'my-olympiads';
            renderMyOlympiads();
        } else if (state.view === 'calendar-day-detail') {
            state.view = 'calendar';
            renderCalendar();
        }
        return;
    }

    if (action === 'settings') {
        renderSettingsModal();
        return;
    }
    if (action === 'close-modal') {
        closeModal();
        return;
    }
    if (action === 'toggle-notifications') {
        await toggleSetting('notifications_enabled');
        return;
    }
    if (action === 'toggle-colorblind') {
        await toggleSetting('colorblind_mode');
        return;
    }
    if (action === 'change-grade') {
        closeModal();
        renderGradeModal();
        return;
    }
    if (action === 'select-grade') {
        const selectedGrade = parseInt(grade);
        if (selectedGrade) {
            state.settings.grade = selectedGrade;
            try {
                await Api.settings.save({
                    grade: selectedGrade,
                    notifications_enabled: state.settings.notifications_enabled,
                    colorblind_mode: state.settings.colorblind_mode
                });
            } catch (err) {
                console.warn('[API] Не удалось сохранить класс', err);
            }
            closeModal();
            state.view = 'subjects';
            renderSubjects();
        }
        return;
    }
    if (action === 'grade-confirm') {
        if (state.settingsNeedSave) {
            try {
                await Api.settings.save({
                    grade: state.settings.grade,
                    notifications_enabled: state.settings.notifications_enabled,
                    colorblind_mode: state.settings.colorblind_mode
                });
            } catch (err) {
                console.warn('[API] Не удалось сохранить настройки', err);
            }
            state.settingsNeedSave = false;
        }
        state.view = 'subjects';
        renderSubjects();
        return;
    }
    if (action === 'open-sort' || action === 'open-sort-my') {
        renderSortModal();
        return;
    }
    if (action === 'toggle-known-dates') {
        state.onlyWithDates = !state.onlyWithDates;
        const searchInput = document.getElementById('searchInput');
        const query = searchInput ? searchInput.value : '';
        if (state.view === 'subject-olympiads' && state.selectedSubject) {
            renderSubjectOlympiadList(state.selectedSubject.name, query);
        } else if (state.view === 'my-olympiads') {
            renderMyOlympiadList(query);
        }
        return;
    }
    if (action === 'reset-filter') {
        const searchInput = document.getElementById('searchInput');
        if (searchInput) searchInput.value = '';
        if (state.view === 'subject-olympiads') {
            await olympiadsBySubjectContent(state.selectedSubject.id, state.selectedSubject.name, '');
        } else if (state.view === 'my-olympiads') {
            await myOlympiadsContent('');
        }
        return;
    }
    if (action === 'add-olympiad') {
        const id = parseInt(target.dataset.id);
        try {
            await Api.my.add(id);
        } catch (err) {
            console.warn('[API] Не удалось добавить олимпиаду', err);
        }
        const opts = state.olympiadDetailOptions || { useMyData: false, activeTab: 'search', backView: 'subject-olympiads' };
        renderOlympiadDetail(id, { ...opts, useMyData: true });
        return;
    }
    if (action === 'remove-olympiad') {
        const id = parseInt(target.dataset.id);
        try {
            await Api.my.remove(id);
        } catch (err) {
            console.warn('[API] Не удалось удалить олимпиаду', err);
        }
        const opts = state.olympiadDetailOptions || { useMyData: true, activeTab: 'my', backView: 'my-olympiads' };
        renderOlympiadDetail(id, { ...opts, useMyData: false });
        return;
    }
    if (action === 'answer-passed' || action === 'answer-failed') {
        const id = parseInt(stageId);
        if (id) {
            try {
                if (action === 'answer-passed') {
                    await Api.stage.markPassed(id);
                } else {
                    await Api.stage.markFailed(id);
                }
            } catch (err) {
                console.warn('[API] Не удалось сохранить результат этапа', err);
            }
            renderNews();
        }
        return;
    }
    if (action === 'stage-passed' || action === 'stage-failed') {
        const id = parseInt(stageId);
        if (id) {
            try {
                if (action === 'stage-passed') {
                    await Api.stage.markPassed(id);
                } else {
                    await Api.stage.markFailed(id);
                }
            } catch (err) {
                console.warn('[API] Не удалось сохранить результат этапа', err);
            }
            const oid = state.selectedOlympiad && state.selectedOlympiad.id;
            if (oid) {
                const opts = state.olympiadDetailOptions || { useMyData: true, activeTab: 'my', backView: 'my-olympiads' };
                renderOlympiadDetail(oid, opts);
            }
        }
        return;
    }
    if (action === 'toggle-news-expand') {
        const category = target.dataset.category;
        if (category) {
            state.newsExpanded[category] = !state.newsExpanded[category];
            renderNewsContent();
        }
        return;
    }
    if (action === 'view-in-calendar') {
        state.view = 'calendar';
        renderCalendar();
        return;
    }
    if (action === 'go-to-search') {
        state.view = 'subjects';
        renderSubjects();
        return;
    }

    if (action === 'toggle-day-plan') {
        const key = target.dataset.key;
        const item = (state.calendarDayItems || []).find(i => i.key === key);
        if (!item || !item.stageId || item.plannedOther) return;

        if (item.limitReached) {
            renderCalendarDayDetail(state.calendarSelectedDay, true);
            return;
        }

        const dateStr = item.dateStr || toISODate(new Date(
            state.calendarDate.year,
            state.calendarDate.month,
            state.calendarSelectedDay
        ));

        if (item.selected) {
            try {
                await Api.stage.unplan(item.stageId);
            } catch (err) {
                console.warn('[API] Не удалось снять выбор', err);
            }
            const ev = findCalendarEventByKey(key);
            if (ev) ev.planned_on = null;
            if (item.precision === 'exact') state.calendarUnplannedExact.add(key);
        } else {
            try {
                await Api.stage.plan(item.stageId, dateStr);
            } catch (err) {
                console.warn('[API] Не удалось отметить олимпиаду', err);
            }
            const ev = findCalendarEventByKey(key);
            if (ev) ev.planned_on = dateStr;
            if (item.precision === 'exact') state.calendarUnplannedExact.delete(key);
        }

        renderCalendarDayDetail(state.calendarSelectedDay);
        return;
    }

    // Переключение вкладок
    if (tab) {
        switch (tab) {
            case 'search':
                if (state.selectedSubject) {
                    state.view = 'subject-olympiads';
                    renderOlympiadsBySubject(state.selectedSubject.id, state.selectedSubject.name);
                } else {
                    state.view = 'subjects';
                    renderSubjects();
                }
                break;
            case 'news':
                state.view = 'news';
                state.newsBadgeVisible = false;
                renderNews();
                break;
            case 'my':
                state.view = 'my-olympiads';
                renderMyOlympiads();
                break;
            case 'cal':
                state.view = 'calendar';
                renderCalendar();
                break;
        }
        return;
    }

    // Клик по предмету
    if (subjectId) {
        const subject = subjectById(parseInt(subjectId));
        if (subject) {
            state.selectedSubject = subject;
            state.view = 'subject-olympiads';
            renderOlympiadsBySubject(subject.id, subject.name);
        }
        return;
    }

    // Клик по олимпиаде
    if (olympiadId) {
        const id = parseInt(olympiadId);
        state.selectedOlympiad = id;
        if (fromMine) {
            state.view = 'olympiad-detail-mine';
            renderOlympiadDetail(id, { useMyData: true, activeTab: 'my', backView: 'my-olympiads' });
        } else {
            state.view = 'olympiad-detail';
            renderOlympiadDetail(id, {
                useMyData: savedFlag,
                activeTab: 'search',
                backView: 'subject-olympiads'
            });
        }
        return;
    }

    // Клик по дню календаря
    if (day) {
        if (target.dataset.otherMonth === 'true') {
            const year = parseInt(target.dataset.year);
            const month = parseInt(target.dataset.month);
            await renderCalendar(year, month);
            state.view = 'calendar-day-detail';
            renderCalendarDayDetail(parseInt(day));
            return;
        }
        state.view = 'calendar-day-detail';
        renderCalendarDayDetail(parseInt(day));
        return;
    }

    // Выбор класса
    if (grade) {
        state.settings.grade = parseInt(grade);
        if (state.view === 'grade-select') {
            renderGradeSelect();
        }
        return;
    }

    // Выбор сортировки в модалке
    if (sortValue) {
        state.sort = sortValue;
        closeModal();
        const searchInput = document.getElementById('searchInput');
        const query = searchInput ? searchInput.value : '';
        if (state.view === 'subject-olympiads' && state.selectedSubject) {
            renderSubjectOlympiadList(state.selectedSubject.name, query);
        } else if (state.view === 'my-olympiads') {
            renderMyOlympiadList(query);
        }
        return;
    }
});

// ============ Поиск ============
document.addEventListener('input', async function (e) {
    if (e.target.id === 'searchInput') {
        const val = e.target.value;
        if (state.view === 'subjects') {
            renderSubjectList(val);
        } else if (state.view === 'subject-olympiads' && state.selectedSubject) {
            renderSubjectOlympiadList(state.selectedSubject.name, val);
        } else if (state.view === 'my-olympiads') {
            renderMyOlympiadList(val);
        }
    }
});

// ============ Инициализация приложения ============
async function initApp() {
    try {
        await Api.me();
    } catch (err) {
        console.warn('[API] Ошибка авторизации', err);
    }

    let settings = {};
    try {
        settings = (await Api.settings.get()) || {};
    } catch (err) {
        console.warn('[API] Не удалось получить настройки', err);
    }

    const rawGrade = settings.grade ?? settings.class ?? null;
    state.settings.grade = rawGrade !== null && rawGrade !== undefined ? Number(rawGrade) : null;
    state.settings.notifications_enabled = settings.notifications_enabled ?? settings.push ?? true;
    state.settings.colorblind_mode = settings.colorblind_mode ?? settings.colorblind ?? false;

    if (state.settings.grade == null) {
        state.settingsNeedSave = true;
        state.view = 'grade-select';
        renderGradeSelect();
    } else {
        state.view = 'subjects';
        renderSubjects();
    }
}

initApp();
