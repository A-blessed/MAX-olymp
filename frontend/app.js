// ============ Инициализация VK Bridge ============
if (window.vkBridge) {
    vkBridge.send('VKWebAppInit');
}

// ============ Данные заглушек ============
const SUBJECTS = [
    { id: 1, name: 'Астрономия', color: '#FFE0B2' },
    { id: 2, name: 'Биология', color: '#F4B3C4' },
    { id: 3, name: 'География', color: '#E9C2E8' },
    { id: 4, name: 'Иностранный язык', color: '#D4A5F7' },
    { id: 5, name: 'Информатика', color: '#C9CFF5' },
    { id: 6, name: 'История', color: '#A8D8FF' },
    { id: 7, name: 'Литература', color: '#B2E6F5' },
    { id: 8, name: 'Математика', color: '#8FDCE0' },
    { id: 9, name: 'Обществознание', color: '#A7D9B5' },
    { id: 10, name: 'Право', color: '#C5E6B0' },
    { id: 11, name: 'Русский язык', color: '#FFF0B3' },
    { id: 12, name: 'Физика', color: '#F5E6C8' },
    { id: 13, name: 'Химия', color: '#BAAC9B' },
    { id: 14, name: 'Экономика', color: '#BFBAB4' }
];

const OLYMPIADS_MOCK = [
    { id: 1, subject_id: 8, name: 'Высшая проба', level: 1, description: 'Межпредметная олимпиада НИУ ВШЭ, около 30 профилей.' },
    { id: 2, subject_id: 8, name: 'Ломоносов', level: 1, description: 'Межпредметная олимпиада МГУ: отбор дистанционный, финал очно.' },
    { id: 3, subject_id: 8, name: 'Физтех', level: 2, description: 'Олимпиада МФТИ. Онлайн-отбор и очный финал в Долгопрудном.' },
    { id: 4, subject_id: 8, name: 'Турнир городов', level: 1, description: 'Математический турнир с авторскими задачами.' },
    { id: 5, subject_id: 12, name: 'Всероссийская олимпиада', level: 2, description: 'Отборочный этап начинается завтра.' },
    { id: 6, subject_id: 13, name: 'Ломоносов', level: 1, description: 'Заключительный этап 25–27 сентября, очный формат.' },
    { id: 7, subject_id: 13, name: 'Сеченовская олимпиада', level: 2, description: 'Олимпиада по химии и биологии, медицинская направленность.' },
    { id: 8, subject_id: 2, name: 'Высшая проба', level: 1, description: 'Биологический профиль олимпиады НИУ ВШЭ.' },
];

// Состояние приложения
const state = {
    view: 'grade-select',           // grade-select, subjects, subject-olympiads, olympiad-detail (search), olympiad-detail-mine, news, my-olympiads, calendar, calendar-day-detail
    selectedSubject: null,
    selectedOlympiad: null,
    sort: 'urgency',
    grade: null,
    myOlympiads: [],                // храним id добавленных
    catalogOlympiads: [],           // олимпиады, подходящие текущему классу
    settingsNeedSave: false,        // true, если при первом запуске класса не было
    news: [
        { id: 1, category: 'urgent', subject: 'Математика', title: 'Высшая проба', level: 1, text: 'Регистрация закрывается сегодня в 23:59', date: 'сегодня', badge: 'Закрывается сегодня' },
        { id: 2, category: 'urgent', subject: 'Физика', title: 'Всероссийская олимпиада', level: 2, text: 'Отборочный этап начинается завтра', date: 'вчера', badge: 'Завтра' },
        { id: 3, category: 'soon', subject: 'Химия', title: 'Ломоносов', level: 1, text: 'Заключительный этап 25–27 сентября, очный формат.', date: '3 дня назад', badge: 'Через 4 дня' },
        { id: 4, category: 'wait', subject: 'Биология', title: 'Высшая проба', level: 1, text: 'Результаты опубликованы. Подтверди, прошёл ли ты дальше.', date: '4 дня назад', badge: 'Ожидает ответа' },
        { id: 5, category: 'done', subject: 'История', title: 'Московская олимпиада', level: 1, text: 'Завершена', date: 'неделю назад', badge: 'Завершено' }
    ],
    settings: {
        grade: null,
        notifications_enabled: true,
        colorblind_mode: false
    },
    calendarDate: { year: 2026, month: 8 }, // 0-индексированный месяц, 8 = сентябрь
    calendarSelectedDay: null,
    today: new Date(), // реальная сегодняшняя дата
};

// DOM элементы
const appbarEl = document.getElementById('appbar');
const searchbarEl = document.getElementById('searchbar');
const contentEl = document.getElementById('content');
const tabbarEl = document.getElementById('tabbar');

// ============ API ============
const API = "https://hatching-landside-crown.ngrok-free.dev";

async function api(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
        ...options,
        headers: {
            "Authorization": `tma ${window.WebApp?.initData || ''}`,
            "ngrok-skip-browser-warning": "true",
            ...options.headers,
        },
    });

    if (response.status === 401) {
        const { detail } = await response.json();
        if (detail?.code === "expired") {
            window.WebApp?.close?.();
            return;
        }
        throw new Error("Не авторизован");
    }

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

// Хелперы для генерации разметки
function iconLink(href, size) {
    return `<svg width="${size}" height="${size}"><use href="#${href}"/></svg>`;
}

function badge(text, cls) {
    return `<span class="badge ${cls}">${text}</span>`;
}

function dot(subjectName, large = false) {
    const subject = SUBJECTS.find(s => s.name === subjectName);
    if (!subject) return '';
    return `<span class="dot-c${large ? ' lg' : ''}" style="background:${subject.color}"></span>`;
}

function appbarHTML(options = {}) {
    const left = options.back
        ? `<button class="icon-btn" data-action="back"><svg width="22" height="22"><use href="#i-back"/></svg></button>`
        : `<button class="icon-btn" data-action="close" style="color:var(--text-1)"><svg width="20" height="20"><use href="#i-cross"/></svg></button>`;
    const right = options.settings
        ? `<button class="icon-btn" data-action="settings"><svg width="21" height="21"><use href="#i-gear"/></svg></button>`
        : `<button class="icon-btn" data-action="more"><span class="more">⋯</span></button>`;
    return `${left}<div class="title">${options.title || 'Мой Олимп'}${options.sub ? `<small>${options.sub}</small>` : ''}</div>${right}`;
}

function searchbarHTML(placeholder = "Найти олимпиаду или предмет") {
    return `<div class="search-field"><svg width="18" height="18"><use href="#i-search"/></svg><input type="text" placeholder="${placeholder}" id="searchInput"></div>`;
}

function tabbarHTML(active) {
    const tabs = [
        { id: 'search', label: 'Поиск', icon: 'i-search' },
        { id: 'news', label: 'Новости', icon: 'i-board', cnt: state.news.filter(n => n.category === 'urgent' || n.category === 'wait').length },
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

// Методы API. Внутри реальный вызов `api()` закомментирован,
// пока работаем с моками.
async function apiGetCatalogOlympiads(params = {}) {
    console.log('[API] Вызван метод: GET /api/catalog/olympiads', params);

    // const qs = new URLSearchParams(params).toString();
    // return api(`/api/catalog/olympiads${qs ? `?${qs}` : ''}`);

    return await new Promise(resolve => {
        setTimeout(() => {
            let items = OLYMPIADS_MOCK.slice();

            // Фильтр по поисковому запросу
            if (params.q) {
                const q = params.q.toLowerCase();
                items = items.filter(o => o.name.toLowerCase().includes(q));
            }

            // Фильтр по предмету
            if (params.subject_id) {
                const subjectId = Number(params.subject_id);
                items = items.filter(o => o.subject_id === subjectId);
            }

            // Фильтр по уровню
            if (params.level) {
                const level = Number(params.level);
                items = items.filter(o => o.level === level);
            }

            // Сортировка
            switch (params.sort) {
                case 'level':
                    items.sort((a, b) => a.level - b.level || a.name.localeCompare(b.name, 'ru'));
                    break;
                case 'name':
                    items.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
                    break;
                case 'urgency':
                default:
                    items.sort((a, b) => a.id - b.id);
                    break;
            }

            const total = items.length;
            const limit = Math.min(Math.max(Number(params.limit) || 50, 1), 200);
            const offset = Math.max(Number(params.offset) || 0, 0);
            const pageItems = items.slice(offset, offset + limit);

            resolve({
                items: pageItems.map(o => ({ ...o, saved: state.myOlympiads.includes(o.id) })),
                total,
                limit,
                offset
            });
        }, 300);
    });
}

async function apiGetCatalogOlympiadById(id) {
    console.log(`[API] Вызван метод: GET /api/catalog/olympiads/${id}`);

    // return api(`/api/catalog/olympiads/${id}`);

    return await new Promise((resolve, reject) => {
        setTimeout(() => {
            const olympiad = OLYMPIADS_MOCK.find(o => o.id === Number(id));
            if (!olympiad) {
                reject(new Error('not_found'));
                return;
            }

            resolve({
                ...olympiad,
                saved: state.myOlympiads.includes(olympiad.id),
                stages: buildMockStages(olympiad)
            });
        }, 300);
    });
}

async function apiGetMe() {
    console.log('[API] Вызван метод: GET /api/me');
    //return api('/api/me');
}

async function apiGetMeSettings() {
    console.log('[API] Вызван метод: GET /api/me/settings');

    // return api('/api/me/settings');

    // Заглушка: пока считаем, что класс ещё не выбран
    return { push: true, colorblind: false };
}

function apiPatch(path, body = {}) {
    console.log(`[API] PATCH ${path}`, body);
    // return api(path, { method: 'PATCH', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });
}

function apiPatchMeSettings() {
    apiPatch('/api/me/settings', {
        class: state.settings.grade,
        push: state.settings.notifications_enabled,
        colorblind: state.settings.colorblind_mode
    });
}

// Вспомогательная заглушка этапов для детального просмотра
function buildMockStages(olympiad) {
    return [
        {
            id: olympiad.id * 10 + 1,
            name: 'Регистрация',
            kind: 'registration',
            starts_on: '2026-09-01',
            start_precision: 'day',
            days_until_start: null,
            plannable: true,
            raw_date_range: '1 сен 2026',
            status: 'upcoming'
        },
        {
            id: olympiad.id * 10 + 2,
            name: 'Отборочный этап',
            kind: 'qualifying',
            starts_on: '2026-09-20',
            start_precision: 'day',
            days_until_start: 3,
            plannable: true,
            raw_date_range: '20 сен 2026',
            status: 'upcoming'
        },
        {
            id: olympiad.id * 10 + 3,
            name: 'Заключительный этап',
            kind: 'final',
            starts_on: '2026-11-18',
            start_precision: 'day',
            days_until_start: null,
            plannable: true,
            raw_date_range: '18 ноя 2026',
            status: 'upcoming'
        }
    ];
}

// ============ Фильтрация и сортировка олимпиад ============
function filterAndSortOlympiads(subjectId, filter = '') {
    let olympiads = OLYMPIADS_MOCK.filter(o => o.subject_id === subjectId);

    if (filter) {
        const lower = filter.toLowerCase();
        olympiads = olympiads.filter(o => o.name.toLowerCase().includes(lower));
    }

    switch (state.sort) {
        case 'level':
            olympiads.sort((a, b) => a.level - b.level || a.name.localeCompare(b.name, 'ru'));
            break;
        case 'name':
            olympiads.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
            break;
        case 'urgency':
        default:
            olympiads.sort((a, b) => a.id - b.id);
            break;
    }
    return olympiads;
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
    appbarEl.innerHTML = appbarHTML({ title: 'Мой Олимп', sub: `Олимпиады для ${state.settings.grade} класса` });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML();
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('search');

    const data = await apiGetCatalogOlympiads({ class: state.settings.grade });
    state.catalogOlympiads = data.items;
    renderSubjectList('');
}

function renderSubjectList(filter = '') {
    const filtered = SUBJECTS.filter(s => s.name.toLowerCase().includes(filter.toLowerCase()));
    const olympiads = state.catalogOlympiads.length ? state.catalogOlympiads : OLYMPIADS_MOCK;
    const counts = {};
    olympiads.forEach(o => { counts[o.subject_id] = (counts[o.subject_id] || 0) + 1; });
    contentEl.innerHTML = `<div class="list">
        ${filtered.map(s => `
            <div class="row-card" data-subject-id="${s.id}" data-subject-name="${s.name}">
                ${dot(s.name, true)}
                <div class="rc-body">
                    <div class="rc-title">${s.name}</div>
                    <div class="rc-sub">${counts[s.id] || 0} олимпиад</div>
                </div>
                ${iconLink('i-chev', 18)}
            </div>
        `).join('')}
    </div>`;
}

function renderOlympiadsBySubject(subjectId, subjectName, filter = '') {
    appbarEl.innerHTML = appbarHTML({ back: true, title: subjectName });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML();
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('search');
    olympiadsBySubjectContent(subjectId, subjectName, filter);
}

function olympiadsBySubjectContent(subjectId, subjectName, filter = '') {
    const olympiads = filterAndSortOlympiads(subjectId, filter);
    contentEl.innerHTML = `
        <div class="sort-row">
            <button class="sort-btn active" data-action="open-sort">${iconLink('i-sort', 15)} Сортировать по…${iconLink('i-down', 14)}</button>
            <button class="reset-btn" data-action="reset-filter">Сбросить фильтр</button>
        </div>
        ${olympiads.map(o => `
            <div class="card" data-olympiad-id="${o.id}">
                ${dot(subjectName)}
                <div class="c-body">
                    <div class="c-top">
                        <span class="c-title">${o.name}</span>
                        ${badge(o.level + ' ур.', 'lvl')}
                    </div>
                    <div class="c-sub">${subjectName}</div>
                    <div class="c-text">${o.description}</div>
                </div>
            </div>
        `).join('')}
        ${olympiads.length === 0 ? '<p>Нет олимпиад по данному запросу</p>' : ''}
    `;
}

async function renderOlympiadDetail(olympiadId, fromMine = false) {
    let olymp;
    try {
        olymp = await apiGetCatalogOlympiadById(olympiadId);
    } catch (err) {
        olymp = OLYMPIADS_MOCK.find(o => o.id === olympiadId);
        if (!olymp) return;
    }
    const subject = SUBJECTS.find(s => s.id === olymp.subject_id);
    if (!subject) return;
    appbarEl.innerHTML = appbarHTML({ back: true, title: 'Олимпиада' });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = fromMine ? tabbarHTML('my') : tabbarHTML('search');

    contentEl.innerHTML = `
        <div class="content flush">
            <div class="hero">
                <h1>${olymp.name}</h1>
                <div class="subject">${dot(subject.name, true)}${subject.name}</div>
                <div class="meta-row">
                    ${badge(olymp.level + ' ур.', 'lvl')}
                    ${badge(`${state.settings.grade} класс`, 'grey')}
                    ${olymp.level === 1 ? badge('Льготы при поступлении', 'grey') : ''}
                </div>
                <p class="extra">${olymp.description}</p>
            </div>
            <div class="detail-wrap">
                <div class="detail-block">
                    <h4>Организаторы</h4>
                    <div class="orgs">
                        <div class="org"><span class="logo">ВШЭ</span><div><div class="on">НИУ «Высшая школа экономики»</div><div class="od">Основной организатор</div></div></div>
                        <div class="org"><span class="logo">МГУ</span><div><div class="on">МГУ им. М.В. Ломоносова</div><div class="od">Соорганизатор</div></div></div>
                    </div>
                </div>
                <div class="detail-block">
                    <h4>Даты этапов</h4>
                    <div class="kv"><span class="k">Регистрация</span><span class="v empty">Дата пока неизвестна</span></div>
                    <div class="kv"><span class="k">Отборочный этап</span><span class="v empty">Дата пока неизвестна</span></div>
                    <div class="kv"><span class="k">Заключительный этап</span><span class="v empty">Дата пока неизвестна</span></div>
                </div>
                <div class="link-row">${iconLink('i-link', 19)}<span class="lt">olymp.hse.ru</span>${iconLink('i-chev', 17)}</div>
            </div>
        </div>
        <div class="sticky-actions">
            ${state.myOlympiads.includes(olympiadId)
                ? '<button class="btn btn-ghost" data-action="remove-olympiad" data-id="' + olympiadId + '">Удалить из моих олимпиад</button>'
                : '<button class="btn btn-primary" data-action="add-olympiad" data-id="' + olympiadId + '">Буду писать</button>'}
        </div>
    `;
    const sticky = contentEl.querySelector('.sticky-actions');
    if (sticky) contentEl.appendChild(sticky);
}

function renderNews() {
    appbarEl.innerHTML = appbarHTML({ title: 'Новости' });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('news');

    const categories = [
        { key: 'urgent', label: 'Срочно', color: 'var(--danger)' },
        { key: 'soon', label: 'Скоро', color: 'var(--warn)' },
        { key: 'wait', label: 'Ожидает ответа от тебя', color: 'var(--max-primary)' },
        { key: 'done', label: 'Завершено', color: 'var(--grey-stage)' }
    ];

    contentEl.innerHTML = categories.map(cat => {
        const items = state.news.filter(n => n.category === cat.key);
        if (items.length === 0) return '';
        return `
            <div class="news-group">
                <div class="news-head">
                    <h4 style="color:${cat.color}">${cat.label}</h4>
                    <span class="n">${items.length}</span>
                </div>
                ${items.map(n => `
                    <div class="news-card ${n.category}">
                        ${dot(n.subject)}
                        <div class="c-body">
                            <div class="c-top">
                                <span class="c-title">${n.title}</span>
                                ${n.category === 'wait' ? iconLink('i-warn', 17) : ''}
                            </div>
                            <div class="c-sub">${n.subject} · ${n.level} ур.</div>
                            <div class="c-text">${n.text}</div>
                            <div class="c-foot">
                                ${n.badge ? badge(n.badge, n.category === 'urgent' ? 'soon' : n.category === 'wait' ? 'lvl2' : 'grey') : ''}
                                <span class="news-time" style="margin-left:auto">${n.date}</span>
                            </div>
                            ${n.category === 'wait' ? `<div class="c-foot" style="margin-top:6px">
                                <button class="btn btn-sm btn-primary" data-action="answer-passed" data-news-id="${n.id}" data-subject="${n.subject}">Я прошёл(а)</button>
                                <button class="btn btn-sm btn-ghost" data-action="answer-failed" data-news-id="${n.id}" data-subject="${n.subject}">Я не прошёл(а)</button>
                            </div>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }).join('');
}

function renderMyOlympiads(filter = '') {
    appbarEl.innerHTML = appbarHTML({ title: 'Мои олимпиады', settings: true });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML();
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('my');
    myOlympiadsContent(filter);
}

function myOlympiadsContent(filter = '') {
    let myOlympiadsData = state.myOlympiads
        .map(id => OLYMPIADS_MOCK.find(o => o.id === id))
        .filter(Boolean);

    if (filter) {
        const lower = filter.toLowerCase();
        myOlympiadsData = myOlympiadsData.filter(o => o.name.toLowerCase().includes(lower));
    }

    sortMyOlympiads(myOlympiadsData);

    contentEl.innerHTML = `
        <div class="sort-row">
            <button class="sort-btn active" data-action="open-sort-my">${iconLink('i-sort', 15)} Срочности${iconLink('i-down', 14)}</button>
            <button class="reset-btn" data-action="reset-filter">Сбросить фильтр</button>
        </div>
        ${myOlympiadsData.length === 0 ? `
            <div class="empty">
                <div class="ic">${iconLink('i-list-star', 28)}</div>
                <h4>${filter ? 'Ничего не найдено' : 'Пока здесь пусто'}</h4>
                <p>${filter ? 'Попробуйте изменить запрос.' : 'Перейди на вкладку «Поиск», выбери олимпиаду и нажми «Буду писать».'}</p>
                ${!filter ? `<button class="btn btn-primary" data-action="go-to-search">Перейти к поиску</button>` : ''}
            </div>
        ` : myOlympiadsData.map(o => {
            const subject = SUBJECTS.find(s => s.id === o.subject_id);
            return `
                <div class="card" data-olympiad-id="${o.id}" data-from-mine="true">
                    ${dot(subject.name)}
                    <div class="c-body">
                        <div class="c-top">
                            <span class="c-title">${o.name}</span>
                            ${badge(o.level + ' ур.', 'lvl')}
                        </div>
                        <div class="c-sub">${subject.name}</div>
                        <div class="c-text">${o.description}</div>
                    </div>
                </div>
            `;
        }).join('')}
    `;
}

// ============ Календарь ============
function renderCalendar(year, monthIndex) {
    if (year === undefined || monthIndex === undefined) {
        year = state.calendarDate.year || 2026;
        monthIndex = state.calendarDate.month ?? 8; // сентябрь по умолчанию
    }
    state.calendarDate = { year, month: monthIndex };

    appbarEl.innerHTML = appbarHTML({ title: 'Календарь', sub: formatMonthYear(year, monthIndex) });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('cal');

    const weeks = buildCalendarMonth(year, monthIndex);
    const lanesByWeek = getDemoLanesForMonth(year, monthIndex, weeks);

    contentEl.innerHTML = `<div class="cal-card">` +
        calDow() +
        weeks.map((week, wi) => calWeek(week.days, lanesByWeek[wi] || [])).join('') +
        legend(getLegendSubjects(year, monthIndex)) +
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

function getDemoLanesForMonth(year, monthIndex, weeks) {
    if (year !== 2026 || monthIndex !== 8) return [];

    const demoSchedules = [
        { subject: 'Математика', start: '2026-09-03', end: '2026-09-07' },
        { subject: 'Русский язык', start: '2026-09-09', end: '2026-09-13' },
        { subject: 'Физика', start: '2026-09-11', end: '2026-09-17' },
        { subject: 'Информатика', start: '2026-09-17', end: '2026-09-20' },
        { subject: 'Химия', start: '2026-09-23', end: '2026-09-26' },
        { subject: 'Биология', start: '2026-09-25', end: '2026-09-28' }
    ];

    const subjectColor = name => {
        const sub = SUBJECTS.find(s => s.name === name);
        return sub ? sub.color : '#ccc';
    };

    function parseDate(str) {
        const [y, m, d] = str.split('-').map(Number);
        return new Date(y, m - 1, d);
    }

    const lanesByWeek = [];

    weeks.forEach(week => {
        const lanes = [];
        demoSchedules.forEach(schedule => {
            const start = parseDate(schedule.start);
            const end = parseDate(schedule.end);
            week.days.forEach((dayObj, idx) => {
                const current = new Date(dayObj.year, dayObj.month, dayObj.day);
                if (current >= start && current <= end) {
                    let lane = lanes.find(l => l.subject === schedule.subject);
                    if (!lane) {
                        lane = { subject: schedule.subject, c: subjectColor(schedule.subject), from: idx, to: idx };
                        lanes.push(lane);
                    } else {
                        lane.to = idx;
                    }
                }
            });
        });
        lanes.sort((a, b) => a.from - b.from);
        lanesByWeek.push(lanes);
    });

    return lanesByWeek;
}

function getLegendSubjects(year, monthIndex) {
    if (year !== 2026 || monthIndex !== 8) return [];
    return ['Математика', 'Русский язык', 'Физика', 'Информатика', 'Химия', 'Биология'];
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

    const plus = dayObj.plus ? `<span class="plus">+${dayObj.plus}</span>` : '';

    return `<div class="${cls.join(' ')}" data-day="${day}" data-month="${dayObj.month}" data-year="${dayObj.year}" data-other-month="${!isCurrentMonth}">
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

    let lanesHtml = '<div class="lanes">';
    rows.forEach(row => {
        lanesHtml += '<div class="lane-row">' + row.map(l => {
            const left = (l.from / 7 * 100);
            const w = ((l.to - l.from + 1) / 7 * 100);
            return `<span class="lane" style="left:calc(${left}% + 3px);width:calc(${w}% - 6px);background:${l.c}"></span>`;
        }).join('') + '</div>';
    });
    lanesHtml += '</div>';

    const daysHtml = days.map(dayObj => calDay(dayObj)).join('');
    return `<div class="cal-week">${lanesHtml}${daysHtml}</div>`;
}

function legend(subjects) {
    return `<div class="legend">${subjects.map(s => {
        const sub = SUBJECTS.find(x => x.name === s);
        if (!sub) return '';
        return `<div class="li"><i style="background:${sub.color}"></i>${s}</div>`;
    }).join('')}</div>`;
}

function renderCalendarDayDetail(day) {
    const { year, month } = state.calendarDate;
    const monthName = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'][month];
    appbarEl.innerHTML = appbarHTML({ back: true, title: `${day} ${monthName} ${year}`, sub: 'Среда' });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('cal');
    contentEl.innerHTML = `
        <div class="daybar"><div class="db-t">3 олимпиады в этот день</div>${iconLink('i-down', 18)}</div>
        ${[
            ['Химия', 'Ломоносов', 'I', 'Отборочный этап · дистанционно'],
            ['Математика', 'Высшая проба', 'I', 'Отборочный этап · 3 часа на решение'],
            ['Биология', 'Высшая проба', 'I', 'Заключительный этап · очно']
        ].map(o => `
            <div class="card">
                ${dot(o[0])}
                <div class="c-body">
                    <div class="c-top"><span class="c-title">${o[1]}</span>${badge(o[2] + ' ур.', 'lvl')}</div>
                    <div class="c-sub">${o[0]}</div>
                    <div class="c-text">${o[3]}</div>
                </div>
            </div>
        `).join('')}
        <button class="btn btn-ghost" style="margin-top:6px">Снять выбор со всех</button>
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
                <button class="btn btn-sm btn-outline" data-action="change-grade">Изменить</button>
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

// ============ Обработка кликов ============
document.addEventListener('click', function (e) {
    // Клик по фону модалки (вне самой панели) — просто закрываем без применения
    const scrim = e.target.closest('.scrim');
    if (scrim && !e.target.closest('.sheet')) {
        closeModal();
        return;
    }

    const target = e.target.closest('[data-action], [data-tab], [data-subject-id], [data-olympiad-id], [data-day], [data-grade], [data-sort-value], [data-news-id]');
    if (!target) return;

    const action = target.dataset.action;
    const tab = target.dataset.tab;
    const subjectId = target.dataset.subjectId;
    const subjectName = target.dataset.subjectName;
    const olympiadId = target.dataset.olympiadId;
    const day = target.dataset.day;
    const grade = target.dataset.grade;
    const sortValue = target.dataset.sortValue;
    const newsId = target.dataset.newsId;
    const fromMine = target.dataset.fromMine === 'true';

    if (action === 'close') {
        if (window.vkBridge) vkBridge.send('VKWebAppClose');
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
        state.settings.notifications_enabled = !state.settings.notifications_enabled;
        closeModal();
        renderSettingsModal();
        return;
    }
    if (action === 'toggle-colorblind') {
        state.settings.colorblind_mode = !state.settings.colorblind_mode;
        closeModal();
        renderSettingsModal();
        return;
    }
    if (action === 'change-grade') {
        closeModal();
        state.view = 'grade-select';
        renderGradeSelect();
        return;
    }
    if (action === 'grade-confirm') {
        if (state.settingsNeedSave) {
            apiPatchMeSettings();
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
    if (action === 'reset-filter') {
        const searchInput = document.getElementById('searchInput');
        if (searchInput) searchInput.value = '';
        if (state.view === 'subject-olympiads') {
            olympiadsBySubjectContent(state.selectedSubject.id, state.selectedSubject.name, '');
        } else if (state.view === 'my-olympiads') {
            myOlympiadsContent('');
        }
        return;
    }
    if (action === 'add-olympiad') {
        const id = parseInt(target.dataset.id);
        if (!state.myOlympiads.includes(id)) state.myOlympiads.push(id);
        console.log('[API] POST /api/me/olympiads/' + id);
        renderOlympiadDetail(id, false);
        return;
    }
    if (action === 'remove-olympiad') {
        const id = parseInt(target.dataset.id);
        state.myOlympiads = state.myOlympiads.filter(x => x !== id);
        console.log('[API] DELETE /api/me/olympiads/' + id);
        renderOlympiadDetail(id, false);
        return;
    }
    if (action === 'answer-passed' || action === 'answer-failed') {
        const newsId = parseInt(target.dataset.newsId);
        const newsItem = state.news.find(n => n.id === newsId);
        if (newsItem) {
            const result = action === 'answer-passed' ? 'passed' : 'failed';
            console.log(`[API] PUT /api/me/stages/{stage_id}/result result=${result}`);
            newsItem.category = 'done';
            newsItem.badge = result === 'passed' ? 'Пройден' : 'Не пройден';
            newsItem.text = result === 'passed' ? 'Вы прошли в следующий этап' : 'Вы не прошли';
            renderNews();
        }
        return;
    }
    if (action === 'go-to-search') {
        state.view = 'subjects';
        renderSubjects();
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
        const subject = SUBJECTS.find(s => s.id === parseInt(subjectId));
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
        if (state.myOlympiads.includes(id) || fromMine) {
            state.view = 'olympiad-detail-mine';
            renderOlympiadDetail(id, true);
        } else {
            state.view = 'olympiad-detail';
            renderOlympiadDetail(id, false);
        }
        return;
    }

    // Клик по дню календаря
    if (day) {
        if (target.dataset.otherMonth === 'true') return;
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
        if (state.view === 'subject-olympiads') {
            olympiadsBySubjectContent(state.selectedSubject.id, state.selectedSubject.name, query);
        } else if (state.view === 'my-olympiads') {
            myOlympiadsContent(query);
        }
        return;
    }
});

// ============ Поиск ============
document.addEventListener('input', function (e) {
    if (e.target.id === 'searchInput') {
        const val = e.target.value;
        if (state.view === 'subjects') {
            renderSubjectList(val);
        } else if (state.view === 'subject-olympiads') {
            olympiadsBySubjectContent(state.selectedSubject.id, state.selectedSubject.name, val);
        } else if (state.view === 'my-olympiads') {
            myOlympiadsContent(val);
        }
    }
});

// ============ Инициализация приложения ============
async function initApp() {
    try {
        await apiGetMe();
    } catch (err) {
        console.warn('[API] Ошибка авторизации', err);
    }

    const settings = await apiGetMeSettings();
    state.settings.grade = settings.class ?? null;
    state.settings.notifications_enabled = settings.push ?? true;
    state.settings.colorblind_mode = settings.colorblind ?? false;

    if (settings.class == null) {
        state.settingsNeedSave = true;
        state.view = 'grade-select';
        renderGradeSelect();
    } else {
        state.view = 'subjects';
        renderSubjects();
    }
}

initApp();
