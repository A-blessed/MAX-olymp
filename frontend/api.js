/**
 * Клиент бэкенда «МойОлимп».
 *
 * Подключается обычным тегом перед app.js:
 *
 *     <script src="api.js"></script>
 *     <script src="app.js"></script>
 *
 * и создаёт глобальные `Api` и `ApiError`. Сборщик не нужен.
 *
 * Все методы возвращают промис с разобранным JSON. Ошибку бросают в виде
 * ApiError, у которого есть `code` — по нему и нужно ветвиться, а `message`
 * написан для пользователя и его можно показать как есть.
 */

(function () {
  "use strict";

  // Адрес бэкенда. При переезде на постоянный хостинг меняется только он.
  const BASE_URL = "https://my-olymp.ru";

  /**
   * Ошибка от бэкенда.
   *
   * `code` — стабильный машинный код (`day_limit_reached`, `expired`, …),
   * `message` — текст для пользователя, `status` — HTTP-код.
   */
  class ApiError extends Error {
    constructor(status, code, message) {
      super(message || `HTTP ${status}`);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
    }

    /** Строку запуска пора обновить: мини-приложение нужно переоткрыть. */
    get isExpired() {
      return this.code === "expired";
    }
  }

  function buildQuery(params) {
    if (!params) return "";
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      // Массив превращается в повторяющийся параметр: ?subject_id=1&subject_id=4
      if (Array.isArray(value)) {
        value.forEach((item) => search.append(key, item));
      } else {
        search.append(key, value);
      }
    }
    const query = search.toString();
    return query ? `?${query}` : "";
  }

  /** Дата в формате, который понимает бэкенд: 2026-09-23. */
  function toApiDate(value) {
    if (typeof value === "string") return value;
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  async function request(path, options) {
    const { method = "GET", body, query } = options || {};

    const headers = {
      // Подпись запуска: сервер по ней определяет пользователя.
      // Передавать id пользователя отдельно не нужно.
      Authorization: `tma ${(window.WebApp && window.WebApp.initData) || ""}`,
      // Нужен, пока адрес туннельный: без него ngrok на бесплатном тарифе
      // отдаёт браузеру HTML-заглушку вместо JSON.
      "ngrok-skip-browser-warning": "true",
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";

    let response;
    try {
      response = await fetch(`${BASE_URL}${path}${buildQuery(query)}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (networkError) {
      // Сеть отвалилась или сервер недоступен — отдельный случай,
      // интерфейс может показать работу по кэшу.
      throw new ApiError(0, "network_error", "Нет связи с сервером");
    }

    if (response.status === 204) return null;

    let payload = null;
    try {
      payload = await response.json();
    } catch (parseError) {
      payload = null;
    }

    if (!response.ok) {
      const detail = payload && payload.detail;
      if (detail && typeof detail === "object") {
        throw new ApiError(response.status, detail.code, detail.message);
      }
      throw new ApiError(
        response.status,
        "http_error",
        typeof detail === "string" ? detail : `Ошибка ${response.status}`
      );
    }

    return payload;
  }

  const Api = {
    baseUrl: BASE_URL,
    toApiDate,

    /** Профиль текущего пользователя. Хороший первый запрос при старте. */
    me() {
      return request("/api/me");
    },

    settings: {
      /** { grade, notifications_enabled, colorblind_mode } */
      get() {
        return request("/api/me/settings");
      },
      /**
       * Меняет только переданные поля.
       * Имена полей именно такие: grade, notifications_enabled, colorblind_mode.
       * Класс — число от 1 до 11, `null` сбрасывает его.
       */
      save(patch) {
        return request("/api/me/settings", { method: "PATCH", body: patch });
      },
    },

    /** Вкладка «Поиск»: каталог всех олимпиад. */
    catalog: {
      /**
       * @param {object} params
       * @param {string} [params.q]      поиск по названию
       * @param {number} [params.subjectId]
       * @param {number} [params.subject_id]  алиас subjectId
       * @param {number} [params.level]  1, 2 или 3
       * @param {string} [params.sort]   urgency | name | level
       * @param {number} [params.limit]  до 200
       * @param {number} [params.offset]
       */
      list(params) {
        const p = params || {};
        return request("/api/catalog/olympiads", {
          query: {
            q: p.q,
            subject_id: p.subjectId ?? p.subject_id,
            level: p.level,
            sort: p.sort,
            limit: p.limit,
            offset: p.offset,
          },
        });
      },

      /**
       * Справочник предметов с числом олимпиад для класса.
       * Каждый предмет: { id, name, color, short_code, olympiad_count }.
       * @param {number} grade
       */
      subjects(grade) {
        return request("/api/catalog/subjects", {
          query: { grade },
        });
      },

      /** Олимпиада со всеми этапами. Поле `saved` — для кнопки «Буду писать». */
      get(olympiadId) {
        return request(`/api/catalog/olympiads/${olympiadId}`);
      },
    },

    /** Вкладка «Мои олимпиады». */
    my: {
      /**
       * @param {object} params
       * @param {string}   [params.sort]       urgency | level | subject
       * @param {number[]} [params.subjectIds] фильтр по предметам
       */
      list(params) {
        const p = params || {};
        return request("/api/me/olympiads", {
          query: { sort: p.sort, subject_id: p.subjectIds },
        });
      },

      get(olympiadId) {
        return request(`/api/me/olympiads/${olympiadId}`);
      },

      /** Кнопка «Буду писать». Повторный вызов не создаёт дубля. */
      add(olympiadId) {
        return request(`/api/me/olympiads/${olympiadId}`, { method: "POST" });
      },

      /** «Удалить из моих олимпиад». Вернёт null. */
      remove(olympiadId) {
        return request(`/api/me/olympiads/${olympiadId}`, { method: "DELETE" });
      },
    },

    /**
     * Действия над этапом.
     *
     * Все четыре метода возвращают состояние всей олимпиады целиком —
     * то же, что `Api.my.get(id)`. Так сделано потому, что ответ
     * «не прошёл» блокирует следующие этапы и снимает их с календаря:
     * интерфейсу нужно перерисовать всю карточку, а не один этап.
     */
    stage: {
      /** «Я прошёл(а) в следующий этап» */
      markPassed(stageId) {
        return request(`/api/me/stages/${stageId}/result`, {
          method: "PUT",
          body: { result: "passed" },
        });
      },

      /** «Я не прошёл(а)» — завершает олимпиаду для пользователя. */
      markFailed(stageId) {
        return request(`/api/me/stages/${stageId}/result`, {
          method: "PUT",
          body: { result: "failed" },
        });
      },

      /** Отменить ответ. Планы следующих этапов при этом не возвращаются. */
      clearResult(stageId) {
        return request(`/api/me/stages/${stageId}/result`, { method: "DELETE" });
      },

      /** Поставить галочку в окне «В этот день я буду писать…». */
      plan(stageId, day) {
        return request(`/api/me/stages/${stageId}/plan`, {
          method: "PUT",
          body: { planned_on: toApiDate(day) },
        });
      },

      /** Снять галочку. */
      unplan(stageId) {
        return request(`/api/me/stages/${stageId}/plan`, { method: "DELETE" });
      },
    },

    calendar: {
      /**
       * Полосы этапов за период. Без аргументов — текущий месяц.
       * У каждой записи есть window_start, window_end, single_day и planned_on.
       */
      range(dateFrom, dateTo) {
        return request("/api/me/calendar", {
          query: {
            date_from: dateFrom ? toApiDate(dateFrom) : undefined,
            date_to: dateTo ? toApiDate(dateTo) : undefined,
          },
        });
      },

      /**
       * Содержимое окна «В этот день я буду писать…».
       * У каждого варианта: selected, planned_on_other_day, selectable.
       */
      day(day) {
        return request(`/api/me/calendar/${toApiDate(day)}`);
      },
    },

    /**
     * Вкладка «Новости»: { urgent, soon, later, awaiting_answer, finished }.
     * У каждой новости готовый текст в `message`.
     */
    news() {
      return request("/api/me/news");
    },
  };

  window.Api = Api;
  window.ApiError = ApiError;
})();
