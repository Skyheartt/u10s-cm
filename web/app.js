const FAVORITES_KEY = "u10s-cm-favorites";
const PAGE_SIZE = 50;

const state = {
  data: null,
  tab: "all",
  query: "",
  page: 0,
  favorites: loadFavorites(),
  playerId: null,
  mapFilter: "has",
  mapQuery: "",
  mapPage: 0,
  mapSort: "number",
};

const app = document.querySelector("#app");

fetch("data/standings.json", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error("The standings file is missing.");
    return response.json();
  })
  .then((data) => {
    state.data = prepare(data);
    window.addEventListener("hashchange", onRoute);
    onRoute();
  })
  .catch((error) => {
    app.replaceChildren(p(error.message || "The leaderboard could not be loaded.", "error"));
  });

function knownTime(value) {
  return typeof value === "number" && value > 0 && value < 4294967295 ? value : null;
}

function prepare(data) {
  const maps = data.maps || [];
  const players = (data.players || []).map((player) => {
    const records = new Map(player.records || []);
    let count = 0;
    for (const [index, value] of records) {
      const time = knownTime(value);
      const map = maps[index];
      if (time != null && map && time <= map.cm) count += 1;
    }
    return {
      id: player.id,
      name: player.name || player.id,
      records,
      count,
      tracked: Boolean(player.tracked),
    };
  });
  players.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  let rank = 0;
  let previous = null;
  players.forEach((player, index) => {
    if (player.count !== previous) rank = index + 1;
    previous = player.count;
    player.rank = rank;
  });
  return {
    updatedAt: data.updatedAt || null,
    mapCount: maps.length,
    maps,
    players,
    errors: data.errors || [],
    byId: new Map(players.map((player) => [player.id, player])),
  };
}

function onRoute() {
  const match = location.hash.match(/^#\/player\/([^/]+)$/);
  const nextId = match ? decodeURIComponent(match[1]) : null;
  if (nextId !== state.playerId) {
    state.playerId = nextId;
    state.mapPage = 0;
  }
  render();
}

function render() {
  const focusId = document.activeElement && document.activeElement.id;
  const selection = focusId && document.activeElement.setSelectionRange
    ? [document.activeElement.selectionStart, document.activeElement.selectionEnd]
    : null;
  app.replaceChildren(header(), state.playerId ? playerView() : boardView(), footer());
  if (!focusId) return;
  const node = document.getElementById(focusId);
  if (!node) return;
  node.focus();
  if (selection && node.setSelectionRange) node.setSelectionRange(selection[0], selection[1]);
}

function header() {
  const block = document.createElement("header");
  block.className = "top";
  const copy = document.createElement("div");
  copy.append(
    el("h1", {}, ["U10S CM"]),
    el("p", { class: "lede" }, [`Who has the champion medal on Everios's ${state.data.mapCount} U10S maps.`]),
    el("p", { class: "meta" }, [updatedLabel()]),
  );
  block.append(copy);
  return block;
}

function updatedLabel() {
  if (!state.data.updatedAt) return "Player results appear after the first refresh.";
  const when = new Date(state.data.updatedAt);
  const stamp = Number.isNaN(when.getTime())
    ? state.data.updatedAt
    : when.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  return `Updated ${stamp}. Refreshed about every 3 hours.`;
}

function boardView() {
  const players = filteredPlayers();
  const pages = Math.max(1, Math.ceil(players.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages - 1);
  const start = state.page * PAGE_SIZE;
  const slice = players.slice(start, start + PAGE_SIZE);
  const panel = el("section", { class: "panel" });
  panel.append(toolbar(players.length), playerRows(slice, players.length));
  if (players.length) panel.append(pager(start, slice.length, players.length, pages));
  return panel;
}

function toolbar(shown) {
  const bar = el("div", { class: "toolbar" });
  const tabs = el("div", { class: "tabs", role: "tablist" });
  tabs.append(
    tabButton("all", `All (${state.data.players.length})`),
    tabButton("favorites", `Favorites (${favoriteCount()})`),
  );
  const search = el("input", {
    id: "player-search",
    class: "search",
    type: "search",
    placeholder: "Search a player",
    value: state.query,
    "aria-label": "Search a player",
    oninput: (event) => {
      state.query = event.target.value;
      state.page = 0;
      render();
    },
  });
  bar.append(tabs, search);
  bar.dataset.shown = String(shown);
  return bar;
}

function tabButton(id, label) {
  return el("button", {
    class: "tab",
    role: "tab",
    "aria-selected": state.tab === id ? "true" : "false",
    onclick: () => {
      state.tab = id;
      state.page = 0;
      if (location.hash) location.hash = "";
      else {
        state.playerId = null;
        render();
      }
    },
  }, [label]);
}

function playerRows(players, total) {
  const list = el("div", { class: "rows" });
  if (!state.data.updatedAt) {
    list.append(p("No results yet. The first leaderboard refresh has not run.", "empty"));
    return list;
  }
  if (!total) {
    list.append(p(state.tab === "favorites"
      ? "No favorites yet. Star a player on the All list. The list stays in this browser."
      : "No player matches.", "empty"));
    return list;
  }
  for (const player of players) list.append(playerRow(player));
  return list;
}

function playerRow(player) {
  const href = `#/player/${encodeURIComponent(player.id)}`;
  const row = el("div", { class: "row" });
  row.addEventListener("click", () => { location.hash = href; });
  row.append(
    el("span", { class: "rank" }, [String(player.rank)]),
    el("a", { class: "name", href }, [player.name]),
    el("span", { class: "count" }, [String(player.count)]),
    bar(player.count),
    starButton(player.id),
  );
  return row;
}

function bar(count) {
  const total = state.data.mapCount || 700;
  const node = el("span", { class: "bar", "aria-hidden": "true" });
  const fill = document.createElement("span");
  fill.style.setProperty("--p", `${Math.round((count / total) * 100)}%`);
  node.append(fill);
  return node;
}

function starButton(id) {
  const on = state.favorites.has(id);
  const button = el("button", {
    class: "star",
    "aria-pressed": on ? "true" : "false",
    "aria-label": on ? "Remove from favorites" : "Add to favorites",
    onclick: (event) => {
      event.stopPropagation();
      toggleFavorite(id);
    },
  });
  button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 3.2l2.4 5.2 5.7.7-4.2 3.9 1.1 5.6L12 15.8 7 18.6l1.1-5.6L3.9 9.1l5.7-.7L12 3.2z"></path></svg>`;
  return button;
}

function pager(start, shown, total, pages) {
  const node = el("div", { class: "pager" });
  const label = total ? `${start + 1}–${start + shown} of ${total}` : "0 players";
  node.append(
    el("button", {
      class: "page-btn",
      disabled: state.page === 0,
      onclick: () => { state.page -= 1; render(); },
    }, ["Previous"]),
    el("span", {}, [label]),
    el("button", {
      class: "page-btn",
      disabled: state.page >= pages - 1,
      onclick: () => { state.page += 1; render(); },
    }, ["Next"]),
  );
  return node;
}

function playerView() {
  const player = state.data.byId.get(state.playerId);
  const block = document.createElement("div");
  const head = el("div", { class: "player-head" });
  const copy = document.createElement("div");
  copy.append(el("button", {
    class: "back",
    onclick: () => { location.hash = ""; },
  }, ["← All players"]));
  if (!player) {
    copy.append(el("h1", {}, ["Player not found"]));
    head.append(copy);
    block.append(head, el("section", { class: "panel" }, [p("This player has no champion medal in the current file.", "empty")]));
    return block;
  }
  const total = state.data.mapCount || 700;
  const percent = total ? Math.round((player.count / total) * 1000) / 10 : 0;
  copy.append(
    el("h2", {}, [player.name]),
    el("p", { class: "lede" }, [`${player.count} of ${total} · ${percent}% · rank ${player.rank}`]),
  );
  if (player.tracked) {
    copy.append(el("p", { class: "meta" }, ["Personal bests are included on maps without the medal."]));
  }
  head.append(copy, el("div", { class: "player-actions" }, [
    el("button", {
      class: "text-btn",
      "aria-pressed": state.favorites.has(player.id) ? "true" : "false",
      onclick: () => toggleFavorite(player.id),
    }, [state.favorites.has(player.id) ? "Favorited" : "Add to favorites"]),
  ]));

  const rows = filteredMaps(player);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  state.mapPage = Math.min(state.mapPage, pages - 1);
  const start = state.mapPage * PAGE_SIZE;
  const slice = rows.slice(start, start + PAGE_SIZE);
  const panel = el("section", { class: "panel" });
  panel.append(mapToolbar(player, rows.length), mapRows(slice, rows.length), mapPager(start, slice.length, rows.length, pages));
  block.append(head, panel);
  return block;
}

function mapToolbar(player, shown) {
  const bar = el("div", { class: "toolbar" });
  const filters = el("div", { class: "filters" });
  filters.append(
    filterButton("has", `Has medal (${player.count})`),
    filterButton("missing", `Missing (${state.data.mapCount - player.count})`),
    filterButton("all", `All (${state.data.mapCount})`),
  );
  const controls = el("div", { class: "player-actions" });
  controls.append(
    el("input", {
      id: "map-search",
      class: "search",
      type: "search",
      placeholder: "Search a map",
      value: state.mapQuery,
      "aria-label": "Search a map",
      oninput: (event) => {
        state.mapQuery = event.target.value;
        state.mapPage = 0;
        render();
      },
    }),
    mapSortSelect(),
  );
  bar.append(filters, controls);
  bar.dataset.shown = String(shown);
  return bar;
}

function filterButton(id, label) {
  return el("button", {
    class: "filter",
    "aria-pressed": state.mapFilter === id ? "true" : "false",
    onclick: () => {
      state.mapFilter = id;
      state.mapPage = 0;
      render();
    },
  }, [label]);
}

function mapSortSelect() {
  const select = el("select", {
    id: "map-sort",
    class: "select",
    "aria-label": "Sort maps",
    onchange: (event) => {
      state.mapSort = event.target.value;
      state.mapPage = 0;
      render();
    },
  });
  const options = [
    ["number", "Map number"],
    ["tight", "Closest to the medal"],
    ["margin", "Largest margin"],
  ];
  for (const [value, label] of options) {
    const option = el("option", { value }, [label]);
    if (value === state.mapSort) option.selected = true;
    select.append(option);
  }
  return select;
}

function filteredMaps(player) {
  const query = state.mapQuery.trim().toLowerCase();
  let rows = state.data.maps.map((map, index) => {
    const time = knownTime(player.records.get(index));
    const medal = time != null && time <= map.cm;
    return { map, index, time, medal, gap: time == null ? null : time - map.cm };
  });
  if (state.mapFilter === "has") rows = rows.filter((row) => row.medal);
  if (state.mapFilter === "missing") rows = rows.filter((row) => !row.medal);
  if (query) rows = rows.filter((row) => row.map.name.toLowerCase().includes(query));
  if (state.mapSort === "tight") {
    rows.sort((a, b) => (a.gap == null) - (b.gap == null) || Math.abs(a.gap) - Math.abs(b.gap) || a.index - b.index);
  } else if (state.mapSort === "margin") {
    rows.sort((a, b) => (a.gap == null) - (b.gap == null) || a.gap - b.gap || a.index - b.index);
  }
  return rows;
}

function mapRows(rows, total) {
  const list = el("div", { class: "rows" });
  if (!total) {
    list.append(p("No map matches.", "empty"));
    return list;
  }
  const head = el("div", { class: "map-row subtle" });
  head.append(
    el("span", {}, ["Map"]),
    el("span", { class: "cm-col" }, ["Champion"]),
    el("span", {}, ["Player"]),
    el("span", {}, ["Gap"]),
    el("span", { class: "link-col" }, [""]),
  );
  list.append(head);
  for (const row of rows) list.append(mapRow(row));
  return list;
}

function mapRow(row) {
  const line = el("div", { class: "map-row" });
  const gapClass = row.gap == null ? "gap" : row.gap < 0 ? "gap under" : row.gap > 0 ? "gap over" : "gap";
  const link = el("a", {
    class: "external link-col",
    href: `https://trackmania.io/#/leaderboard/${encodeURIComponent(row.map.uid)}`,
    target: "_blank",
    rel: "noreferrer",
  }, ["TM.io"]);
  line.append(
    el("span", { class: "name" }, [row.map.name]),
    el("span", { class: "time cm-col" }, [formatTime(row.map.cm)]),
    el("span", { class: "time" }, [row.time == null ? "—" : formatTime(row.time)]),
    el("span", { class: gapClass }, [row.gap == null ? "—" : formatSigned(row.gap)]),
    link,
  );
  return line;
}

function mapPager(start, shown, total, pages) {
  const node = el("div", { class: "pager" });
  const label = total ? `${start + 1}–${start + shown} of ${total}` : "0 maps";
  node.append(
    el("button", {
      class: "page-btn",
      disabled: state.mapPage === 0,
      onclick: () => { state.mapPage -= 1; render(); },
    }, ["Previous"]),
    el("span", {}, [label]),
    el("button", {
      class: "page-btn",
      disabled: state.mapPage >= pages - 1,
      onclick: () => { state.mapPage += 1; render(); },
    }, ["Next"]),
  );
  return node;
}

function footer() {
  const note = "A medal counts when the personal best is at or under the champion time. Favorites are saved in this browser only.";
  const extra = state.data.errors.length
    ? " Some maps kept their previous results because a request failed."
    : "";
  return el("p", { class: "foot" }, [note + extra]);
}

function favoriteCount() {
  let count = 0;
  for (const player of state.data.players) {
    if (state.favorites.has(player.id)) count += 1;
  }
  return count;
}

function filteredPlayers() {
  const query = state.query.trim().toLowerCase();
  return state.data.players.filter((player) => {
    if (state.tab === "favorites" && !state.favorites.has(player.id)) return false;
    if (query && !player.name.toLowerCase().includes(query)) return false;
    return true;
  });
}

function toggleFavorite(id) {
  if (state.favorites.has(id)) state.favorites.delete(id);
  else state.favorites.add(id);
  localStorage.setItem(FAVORITES_KEY, JSON.stringify([...state.favorites]));
  render();
}

function loadFavorites() {
  try {
    const parsed = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

function formatTime(ms) {
  const sign = ms < 0 ? "−" : "";
  const abs = Math.abs(ms);
  const minutes = Math.floor(abs / 60000);
  const seconds = Math.floor((abs % 60000) / 1000);
  const millis = String(abs % 1000).padStart(3, "0");
  if (minutes > 0) return `${sign}${minutes}:${String(seconds).padStart(2, "0")}.${millis}`;
  return `${sign}${seconds}.${millis}`;
}

function formatSigned(ms) {
  if (ms === 0) return "0.000";
  if (ms > 0) return `+${formatTime(ms)}`;
  return formatTime(ms);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "style") node.setAttribute("style", value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  for (const child of children) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}

function p(text, className) {
  return el("p", { class: className }, [text]);
}
