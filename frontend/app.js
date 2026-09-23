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
    sort: 'urgency',
    grade: null,
    subjects: [],                   // справочник предметов с сервера
    settingsNeedSave: false,        // true, если при первом запуске класса не было
    news: [],                       // кеш новостей для счётчика на таббаре
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
    return (state.subjects || []).find(s => s.name === name);
}

function dot(subjectOrName, large = false) {
    const subject = typeof subjectOrName === 'string' ? subjectByName(subjectOrName) : subjectOrName;
    if (!subject) return '';
    return `<span class="dot-c${large ? ' lg' : ''}" style="background:${subject.color};display:flex;align-items:center;justify-content:center;font-size:8px;font-weight:700;line-height:1;color:var(--text-1);overflow:hidden;">${subject.short_code || ''}</span>`;
}

function subjectColor(name) {
    const subject = subjectByName(name);
    return subject ? subject.color : '#ccc';
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
        { id: 'news', label: 'Новости', icon: 'i-board', cnt: (state.news || []).filter(n => n.category === 'urgent' || n.category === 'wait').length },
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
    appbarEl.innerHTML = appbarHTML({ title: 'Мой Олимп', sub: `Олимпиады для ${state.settings.grade} класса` });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML();
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
    appbarEl.innerHTML = appbarHTML({ back: true, title: subjectName });
    searchbarEl.style.display = 'block';
    searchbarEl.innerHTML = searchbarHTML();
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('search');
    olympiadsBySubjectContent(subjectId, subjectName, filter);
}

async function olympiadsBySubjectContent(subjectId, subjectName, filter = '') {
    let olympiads = [];
    try {
        const data = await Api.catalog.list({ subjectId, q: filter, sort: state.sort });
        olympiads = Array.isArray(data) ? data : (data.items || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить олимпиады предмета', err);
        olympiads = [];
    }

    contentEl.innerHTML = `
        <div class="sort-row">
            <button class="sort-btn active" data-action="open-sort">${iconLink('i-sort', 15)} Сортировать по…${iconLink('i-down', 14)}</button>
            <button class="reset-btn" data-action="reset-filter">Сбросить фильтр</button>
        </div>
        ${olympiads.map(o => `
            <div class="card" data-olympiad-id="${o.id}" data-saved="${o.saved === true}">
                ${dot(subjectName)}
                <div class="c-body">
                    <div class="c-top">
                        <span class="c-title">${o.name}</span>
                        ${badge(o.level + ' ур.', 'lvl')}
                    </div>
                    <div class="c-sub">${subjectName}</div>
                    <div class="c-text">${o.description || ''}</div>
                </div>
            </div>
        `).join('')}
        ${olympiads.length === 0 ? '<p>Нет олимпиад по данному запросу</p>' : ''}
    `;
}

async function renderOlympiadDetail(olympiadId, fromMine = false) {
    let olympiad;
    try {
        olympiad = await Api.catalog.get(olympiadId);
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
    if (!subject) return;
    const saved = fromMine || olympiad.saved === true;
    const officialUrl = olympiad.official_url || '';
    const displayUrl = officialUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');

    appbarEl.innerHTML = appbarHTML({ back: true, title: 'Олимпиада' });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = fromMine ? tabbarHTML('my') : tabbarHTML('search');

    contentEl.innerHTML = `
        <div class="content flush">
            <div class="hero">
                <h1>${olympiad.name}</h1>
                <div class="subject">${dot(subject, true)}${subject.name}</div>
                <div class="meta-row">
                    ${olympiad.level ? badge(olympiad.level + ' ур.', 'lvl') : ''}
                    ${olympiad.grades ? badge(olympiad.grades, 'grey') : ''}
                    ${olympiad.level === 'I' ? badge('Льготы при поступлении', 'grey') : ''}
                </div>
                <p class="extra">${olympiad.description || ''}</p>
            </div>
            <div class="detail-wrap">
                ${organizersHTML(olympiad.organizers)}
                <div class="detail-block">
                    <h4>Даты этапов</h4>
                    ${stagesHTML(olympiad.stages)}
                </div>
                ${officialUrl ? `<a class="link-row" href="${officialUrl}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit;">${iconLink('i-link', 19)}<span class="lt">${displayUrl}</span>${iconLink('i-chev', 17)}</a>` : ''}
            </div>
        </div>
        <div class="sticky-actions">
            ${saved
                ? (fromMine
                    ? '<button class="btn btn-ghost" data-action="remove-olympiad" data-id="' + olympiadId + '">Удалить из моих олимпиад</button>'
                    : '<button class="btn btn-ghost" data-action="remove-olympiad" data-id="' + olympiadId + '">✓ Добавлено</button>')
                : '<button class="btn btn-primary" data-action="add-olympiad" data-id="' + olympiadId + '">Буду писать</button>'}
        </div>
    `;
    const sticky = contentEl.querySelector('.sticky-actions');
    if (sticky) contentEl.appendChild(sticky);
}

function stagesHTML(stages) {
    if (!Array.isArray(stages) || stages.length === 0) {
        return `<div class="kv"><span class="k">Даты этапов</span><span class="v empty">Информация появится позже</span></div>`;
    }

    return stages.map(st => `
        <div class="stage ${st.status || ''}">
            <div class="marker"><span class="mk ${st.status === 'past' ? 'past' : 'future'}"></span></div>
            <div class="s-body">
                <div class="s-top"><span class="s-name">${st.name || 'Этап'}</span></div>
                <div class="s-date">${st.raw_date_range || st.date_range || 'Дата пока неизвестна'}</div>
                ${st.plannable ? `<span class="s-planned">Можно планировать</span>` : ''}
            </div>
        </div>
    `).join('');
}

function organizersHTML(organizers) {
    if (!Array.isArray(organizers) || organizers.length === 0) return '';

    return `
        <div class="detail-block">
            <h4>Организаторы</h4>
            <div class="orgs">
                ${organizers.slice(0, 3).map(org => {
                    const name = org.name || org.full_name || org.title || '';
                    const role = org.role || org.type || org.role_name || '';
                    const logo = org.short_name || org.abbr || org.logo || (name ? name.split(' ').map(word => word[0]).join('') : '');
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

async function renderNews() {
    appbarEl.innerHTML = appbarHTML({ title: 'Новости' });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';

    try {
        const data = await Api.news();
        state.news = Array.isArray(data) ? data : (data.items || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить новости', err);
        state.news = [];
    }
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
                            <div class="c-text">${n.message || n.text || ''}</div>
                            <div class="c-foot">
                                ${n.badge ? badge(n.badge, n.category === 'urgent' ? 'soon' : n.category === 'wait' ? 'lvl2' : 'grey') : ''}
                                <span class="news-time" style="margin-left:auto">${n.date || ''}</span>
                            </div>
                            ${n.category === 'wait' && (n.stage_id || n.stageId) ? `<div class="c-foot" style="margin-top:6px">
                                <button class="btn btn-sm btn-primary" data-action="answer-passed" data-stage-id="${n.stage_id || n.stageId}">Я прошёл(а)</button>
                                <button class="btn btn-sm btn-ghost" data-action="answer-failed" data-stage-id="${n.stage_id || n.stageId}">Я не прошёл(а)</button>
                            </div>` : ''}
                        </div>
                    </div>
                `).join('')}
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
        const data = await Api.my.list({ q: filter });
        myOlympiadsData = Array.isArray(data) ? data : (data.items || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить мои олимпиады', err);
        myOlympiadsData = [];
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
                        <div class="c-text">${o.description || ''}</div>
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

async function renderCalendar(year, monthIndex) {
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

    const firstDay = weeks[0]?.days[0];
    const lastDay = weeks[weeks.length - 1]?.days[6];
    const from = toISODate(new Date(firstDay.year, firstDay.month, firstDay.day));
    const to = toISODate(new Date(lastDay.year, lastDay.month, lastDay.day));

    let events = [];
    try {
        const data = await Api.calendar.range(from, to);
        events = Array.isArray(data) ? data : (data.items || data.events || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить календарь', err);
    }

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

function buildLanesForMonth(events, weeks) {
    const lanesByWeek = [];

    weeks.forEach(week => {
        const lanes = [];
        (events || []).forEach(ev => {
            const start = parseDate(ev.start || ev.starts_on || ev.date_from || ev.start_date);
            const end = parseDate(ev.end || ev.ends_on || ev.date_to || ev.end_date || ev.start || ev.starts_on || ev.date_from || ev.start_date);
            if (!start || !end) return;

            const subject = ev.subject || ev.subject_name || 'Олимпиада';
            const color = ev.color || ev.subject_color || subjectColor(subject);

            week.days.forEach((dayObj, idx) => {
                const current = new Date(dayObj.year, dayObj.month, dayObj.day);
                if (current >= start && current <= end) {
                    let lane = lanes.find(l => l.subject === subject);
                    if (!lane) {
                        lane = { subject, c: color, from: idx, to: idx };
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

function getLegendSubjects(events) {
    const seen = new Set();
    return (events || [])
        .map(ev => ev.subject || ev.subject_name)
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
        const sub = subjectByName(s);
        if (!sub) return '';
        return `<div class="li"><i style="background:${sub.color}"></i>${s}</div>`;
    }).join('')}</div>`;
}

async function renderCalendarDayDetail(day) {
    const { year, month } = state.calendarDate;
    const monthName = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'][month];
    const dateStr = toISODate(new Date(year, month, day));

    appbarEl.innerHTML = appbarHTML({ back: true, title: `${day} ${monthName} ${year}`, sub: 'Среда' });
    searchbarEl.style.display = 'none';
    tabbarEl.style.display = 'flex';
    tabbarEl.innerHTML = tabbarHTML('cal');

    let items = [];
    try {
        const data = await Api.calendar.day(dateStr);
        items = Array.isArray(data) ? data : (data.items || data.events || data.olympiads || []);
    } catch (err) {
        console.warn('[API] Не удалось загрузить день календаря', err);
    }

    contentEl.innerHTML = `
        <div class="daybar"><div class="db-t">${items.length} олимпиад(ы) в этот день</div>${iconLink('i-down', 18)}</div>
        ${items.map(item => renderDayItem(item)).join('')}
        <button class="btn btn-ghost" style="margin-top:6px">Снять выбор со всех</button>
    `;
}

function renderDayItem(item) {
    const subjectName = item.subject || item.subject_name || '';
    const title = item.title || item.name || item.olympiad_name || 'Олимпиада';
    const level = item.level || '';
    const text = item.description || item.message || item.stage_name || item.format || '';

    return `
        <div class="card">
            ${dot(subjectName)}
            <div class="c-body">
                <div class="c-top"><span class="c-title">${title}</span>${level ? badge(level + ' ур.', 'lvl') : ''}</div>
                <div class="c-sub">${subjectName}</div>
                ${text ? `<div class="c-text">${text}</div>` : ''}
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
document.addEventListener('click', async function (e) {
    // Клик по фону модалки (вне самой панели) — просто закрываем без применения
    const scrim = e.target.closest('.scrim');
    if (scrim && !e.target.closest('.sheet')) {
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
        renderOlympiadDetail(id, false);
        return;
    }
    if (action === 'remove-olympiad') {
        const id = parseInt(target.dataset.id);
        try {
            await Api.my.remove(id);
        } catch (err) {
            console.warn('[API] Не удалось удалить олимпиаду', err);
        }
        renderOlympiadDetail(id, false);
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
        if (savedFlag || fromMine) {
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
            await olympiadsBySubjectContent(state.selectedSubject.id, state.selectedSubject.name, query);
        } else if (state.view === 'my-olympiads') {
            await myOlympiadsContent(query);
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
        } else if (state.view === 'subject-olympiads') {
            await olympiadsBySubjectContent(state.selectedSubject.id, state.selectedSubject.name, val);
        } else if (state.view === 'my-olympiads') {
            await myOlympiadsContent(val);
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
