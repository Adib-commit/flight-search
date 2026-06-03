// ── auth init ─────────────────────────────────────────────────────────────────
const _token = localStorage.getItem("token");
const _user  = JSON.parse(localStorage.getItem("user") || "null");

if (!_token) { window.location.href = "/login"; }

// ── auto sign-out after 2 minutes of inactivity ───────────────────────────────
let _inactivityTimer;
let _pendingRequests = 0;   // active fetches; never log out while > 0
function _resetInactivityTimer() {
  clearTimeout(_inactivityTimer);
  _inactivityTimer = setTimeout(() => {
    if (_pendingRequests > 0) { _resetInactivityTimer(); return; }  // search running
    alert("Your session has expired after 2 minutes of inactivity. You will be signed out.");
    logout();
  }, 2 * 60 * 1000);
}
["mousemove", "keydown", "click", "scroll", "touchstart"].forEach(evt =>
  document.addEventListener(evt, _resetInactivityTimer, { passive: true })
);
// A network request in flight IS activity — a long search (fast+full+split can
// run minutes while the user only watches the spinner) must not trip the
// inactivity logout. Reset on every fetch start and completion.
const _origFetch = window.fetch.bind(window);
window.fetch = (...args) => {
  _pendingRequests++;
  _resetInactivityTimer();
  return _origFetch(...args).finally(() => {
    _pendingRequests = Math.max(0, _pendingRequests - 1);
    _resetInactivityTimer();
  });
};
_resetInactivityTimer(); // start on page load

function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
  window.location.href = "/login";
}

function authHeaders(extra) {
  return { "Content-Type": "application/json", "Authorization": `Bearer ${_token}`, ...extra };
}

// Populate nav bar
(function initNav() {
  const navUser = document.getElementById("nav-user");
  const btnLogout = document.getElementById("btn-logout");
  const navAdmin = document.getElementById("nav-admin");
  if (navUser && _user) navUser.textContent = `👤 ${_user.username}`;
  if (btnLogout) { btnLogout.style.display = ""; btnLogout.onclick = logout; }
  const navAccount = document.getElementById("nav-account");
  if (navAccount) navAccount.style.display = "";
  if (navAdmin && _user && _user.role === "admin") navAdmin.style.display = "";
  const watchEmailDisplay = document.getElementById("watch-email-display");
  if (watchEmailDisplay && _user) watchEmailDisplay.value = _user.email;

  // Load and show active watches badge
  fetch("/api/watches", { headers: { "Authorization": `Bearer ${_token}` } })
    .then(r => r.ok ? r.json() : [])
    .then(watches => {
      const active = watches.filter(w => w.active);
      const badge = document.getElementById("nav-watches-badge");
      if (badge && active.length > 0) {
        badge.style.display = "inline-flex";
        badge.style.cssText = "display:inline-flex;align-items:center;gap:.3rem;background:#0e7490;color:#fff;border-radius:999px;padding:2px 10px;font-size:.78rem;font-weight:600;";
        badge.innerHTML = `🔔 ${active.length} watch${active.length > 1 ? "es" : ""} active`;
        badge.title = active.map(w => `${w.origin}→${w.destination} ${w.departure}`).join(", ");
      }
    })
    .catch(() => {});
})();

// Show recent searches — use both window.load and a fallback timeout to
// guarantee it runs after DOM + auth state are fully settled.
window.addEventListener('load', renderRecentSearches);
setTimeout(renderRecentSearches, 200); // fallback in case load already fired

// ── airport autocomplete ──────────────────────────────────────────────────────
function _airportLabel(a) {
  return `${a.name} (${a.iata})`;
}

function _searchAirports(q) {
  if (!q || q.length < 1) return [];
  const u = q.toUpperCase();
  const l = q.toLowerCase();
  // Exact IATA match first, then name/city prefix, then substring
  const exact   = (window.AIRPORTS || []).filter(a => a.iata === u);
  const prefix  = (window.AIRPORTS || []).filter(a => a.iata !== u && (
    a.name.toLowerCase().startsWith(l) || a.city.toLowerCase().startsWith(l) || a.country.toLowerCase().startsWith(l)
  ));
  const substr  = (window.AIRPORTS || []).filter(a => a.iata !== u &&
    !a.name.toLowerCase().startsWith(l) && !a.city.toLowerCase().startsWith(l) &&
    (a.name.toLowerCase().includes(l) || a.city.toLowerCase().includes(l) || a.iata.includes(u))
  );
  return [...exact, ...prefix, ...substr].slice(0, 8);
}

function _initAirportAC(inputId, listId, hiddenId) {
  const input  = document.getElementById(inputId);
  const list   = document.getElementById(listId);
  const hidden = document.getElementById(hiddenId);
  if (!input || !list || !hidden) return;

  let activeIdx = -1;

  function showList(results) {
    activeIdx = -1;
    if (!results.length) { list.classList.remove('open'); list.innerHTML = ''; return; }
    list.innerHTML = results.map((a, i) => `
      <div class="airport-ac-item" data-iata="${a.iata}" data-idx="${i}">
        <span class="ac-iata">${a.iata}</span>
        <span class="ac-name">
          <div class="ac-airport">${a.name}</div>
          <div class="ac-city">${a.city}, ${a.country}</div>
        </span>
      </div>`).join('');
    list.classList.add('open');
  }

  function select(iata, label) {
    input.value  = label;
    hidden.value = iata;
    list.classList.remove('open');
    list.innerHTML = '';
  }

  input.addEventListener('input', () => {
    hidden.value = '';
    showList(_searchAirports(input.value.trim()));
  });

  input.addEventListener('keydown', (e) => {
    const items = list.querySelectorAll('.airport-ac-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, items.length - 1);
      items.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      items.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
    } else if (e.key === 'Enter' && activeIdx >= 0 && list.classList.contains('open')) {
      e.preventDefault();
      const item = items[activeIdx];
      if (item) select(item.dataset.iata, _airportLabel(window.AIRPORTS.find(a => a.iata === item.dataset.iata)));
    } else if (e.key === 'Escape') {
      list.classList.remove('open');
    }
  });

  list.addEventListener('mousedown', (e) => {
    const item = e.target.closest('.airport-ac-item');
    if (item) {
      const a = (window.AIRPORTS || []).find(x => x.iata === item.dataset.iata);
      if (a) select(a.iata, _airportLabel(a));
    }
  });

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !list.contains(e.target)) list.classList.remove('open');
  });
}

function _setAirportAC(inputId, hiddenId, iata) {
  const a = (window.AIRPORTS || []).find(x => x.iata === iata.toUpperCase());
  const input  = document.getElementById(inputId);
  const hidden = document.getElementById(hiddenId);
  if (!input || !hidden) return;
  if (a) { input.value = _airportLabel(a); hidden.value = a.iata; }
  else   { input.value = iata.toUpperCase(); hidden.value = iata.toUpperCase(); }
}

window.addEventListener('load', () => {
  _initAirportAC('ac-origin',      'ac-origin-list',      'origin-iata');
  _initAirportAC('ac-destination', 'ac-destination-list', 'destination-iata');
});

// ── main ──────────────────────────────────────────────────────────────────────
const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

function splitNames(value) {
  return (value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// All flight times / layovers shown in HOURS.
function fmtH(min) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h ${String(m).padStart(2, "0")}m` : `${h}h`;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = iso.split("T")[0];
  if (!d) return "";
  const [y, m, day] = d.split("-");
  return `${day}/${m}/${y}`;
}

function timeOnly(iso) {
  if (!iso) return "";
  const t = iso.split("T")[1] || "";
  return t.slice(0, 5);
}

function tagsFor(o, ids) {
  const tags = [];
  if (o.id === ids.best) tags.push("BEST VALUE");
  if (o.id === ids.cheap) tags.push("CHEAPEST");
  if (o.id === ids.fast) tags.push("FASTEST");
  return tags;
}

// Build one direction block (outbound or inbound) with segment rows + layover separators.
function renderLeg(segs, label) {
  if (!segs.length) return "";

  // Summary route line: A → B → C
  const stops = segs.map((s) => `<span class="stn">${s.origin}</span>`).join('<span class="hop">→</span>');
  const lastDst = `<span class="hop">→</span><span class="stn">${segs[segs.length - 1].destination}</span>`;
  const routeLine = `<div class="leg-route-line">${stops}${lastDst}</div>`;

  // Segment rows with layover rows between them
  let rows = "";
  segs.forEach((s) => {
    const ori = s.origin_name ? `${s.origin} <span class="ap-name">${s.origin_name}</span>` : s.origin;
    const dst = s.destination_name ? `${s.destination} <span class="ap-name">${s.destination_name}</span>` : s.destination;
    rows += `
      <div class="seg">
        <span class="seg-date">${fmtDate(s.departure_at)}</span>
        <span class="seg-route">${ori} → ${dst}</span>
        <span class="seg-carrier">${s.carrier_name} ${s.flight_number || ""}</span>
        <span class="seg-time">${timeOnly(s.departure_at)}–${timeOnly(s.arrival_at)}</span>
        <span class="seg-dur">${fmtH(s.duration_min)} flight</span>
      </div>`;
    if (s.layover_after_min > 0) {
      rows += `<div class="layover-row">⏳ Layover at ${s.destination}: ${fmtH(s.layover_after_min)}</div>`;
    }
  });

  return `<div class="leg-block">
    <div class="leg-header">${label}</div>
    ${routeLine}
    <div class="segs">${rows}</div>
  </div>`;
}

// Build a fallback Kiwi.com search link when the provider didn't return a booking URL.
function fallbackBookUrl(o) {
  const segs = o.segments || [];
  if (!segs.length) return "";
  const origin  = segs[0].origin;
  const inSegs  = segs.filter(s => s.direction === "inbound");
  const outSegs = segs.filter(s => s.direction === "outbound" || s.direction === "");
  // The destination for the kiwi search is the TURNAROUND city (end of the
  // outbound leg), NOT the last segment's destination — on a round trip the
  // last segment lands back at the origin, which would produce a bogus
  // TLV/TLV search that returns nothing.
  const dest    = (outSegs.length ? outSegs[outSegs.length - 1].destination : segs[segs.length - 1].destination);
  const depDate = (segs[0].departure_at || "").slice(0, 10);
  const retDate = inSegs.length ? (inSegs[0].departure_at || "").slice(0, 10) : "";
  if (retDate) {
    return `https://www.kiwi.com/en/search/results/${origin}/${dest}/${depDate}/${retDate}?adults=1`;
  }
  return `https://www.kiwi.com/en/search/results/${origin}/${dest}/${depDate}/no-return?adults=1`;
}

function providerLabel(url) {
  if (!url) return "Search on Kiwi.com";
  if (url.includes("skyscanner")) return "Book on Skyscanner";
  if (url.includes("kayak"))      return "Book on Kayak";
  if (url.includes("kiwi"))       return "Book on Kiwi.com";
  return "Book";
}

// One-way Kiwi search for a single direction — reproducible per leg, unlike a
// combined round-trip search which won't surface a synthesized self-transfer.
function oneWayKiwi(orig, dest, dateISO) {
  const d = (dateISO || "").slice(0, 10);
  return `https://www.kiwi.com/en/search/results/${orig}/${dest}/${d}/no-return?adults=1`;
}

// Render the full route path (every segment) for one itinerary.
function routePath(o) {
  if (!o.segments || !o.segments.length) return "";

  // Group by direction; fall back to first-half / second-half if direction not tagged
  const outSegs = o.segments.filter((s) => s.direction === "outbound" || s.direction === "");
  const inSegs  = o.segments.filter((s) => s.direction === "inbound");
  const hasDirections = o.segments.some((s) => s.direction);

  let html = "";
  if (hasDirections && inSegs.length) {
    const firstOut = outSegs[0], lastIn = inSegs[inSegs.length - 1];
    const outLabel = `✈ Outbound: ${firstOut?.origin ?? ""} → ${outSegs[outSegs.length-1]?.destination ?? ""}`;
    const inLabel  = `↩ Return: ${inSegs[0]?.origin ?? ""} → ${lastIn?.destination ?? ""}`;
    html = renderLeg(outSegs, outLabel) + renderLeg(inSegs, inLabel);
  } else {
    html = renderLeg(o.segments, "✈ Flight details");
  }

  let bookLink;
  if (o.booking_url) {
    // Real provider fare — single bookable ticket.
    bookLink = `<a class="book-link" href="${o.booking_url}" target="_blank" rel="noopener">🔗 ${providerLabel(o.booking_url)}</a>`;
  } else {
    // No single bookable fare: this is a stitched / self-transfer combo (often
    // mixed airlines via a hub). A combined round-trip search won't reproduce
    // it, so give per-direction one-way search links that actually do — and say
    // so plainly, since the legs must be booked separately.
    const outO = outSegs[0]?.origin, outD = outSegs[outSegs.length - 1]?.destination;
    let links = `<a class="book-link" href="${oneWayKiwi(outO, outD, outSegs[0]?.departure_at)}" target="_blank" rel="noopener">🔗 Search outbound ${outO}→${outD}</a>`;
    if (inSegs.length) {
      const inO = inSegs[0]?.origin, inD = inSegs[inSegs.length - 1]?.destination;
      links += ` <a class="book-link" href="${oneWayKiwi(inO, inD, inSegs[0]?.departure_at)}" target="_blank" rel="noopener">🔗 Search return ${inO}→${inD}</a>`;
    }
    bookLink = `<p class="split-desc">⚠ Self-transfer / multi-airline — no single ticket. Verify & book each direction separately:</p>${links}`;
  }

  return html + bookLink;
}

// FULL list of all routes, selected one highlighted.
function allRoutes(data) {
  const opts = (data.options || []).slice(0, 3);
  if (!opts.length) return "";
  const ids = {
    best: data.best_value[0] && data.best_value[0].id,
    cheap: data.cheapest && data.cheapest.id,
    fast: data.fastest && data.fastest.id,
  };

  const rows = opts
    .map((o, i) => {
      const tags = tagsFor(o, ids);
      const selected = o.id === ids.best;
      const tagHtml = tags
        .map((t) => `<span class="tag tag-${t.split(" ")[0].toLowerCase()}">${t}</span>`)
        .join(" ");
      const bookBtn = (() => {
        const url = o.booking_url || fallbackBookUrl(o);
        return url ? `<a class="book-btn" href="${url}" target="_blank" rel="noopener">Book →</a>` : "";
      })();
      return `
        <div class="route-card ${selected ? "selected" : ""}">
          <div class="route-head">
            <span class="rank">#${i + 1}</span>
            <span class="price">${(o.price_per_person ?? o.price_total).toFixed(2)} ${o.currency}/pp${o.price_total > (o.price_per_person ?? o.price_total) ? ` <span style="font-size:.8em;color:#94a3b8">(total ${o.price_total.toFixed(2)})</span>` : ""}</span>
            <span class="meta">${o.carrier_names.join(", ")}</span>
            <span class="meta">${o.stops_count} stop${o.stops_count === 1 ? "" : "s"}</span>
            <span class="meta">✈ ${fmtH(o.total_duration_min)}</span>
            <span class="meta">⏳ layover ${fmtH(o.layover_min)}</span>
            <span class="meta">score ${o.score ?? "-"}</span>
            ${tagHtml}
            ${bookBtn}
          </div>
          ${routePath(o)}
        </div>`;
    })
    .join("");

  return `<div class="card">
    <h3>🧭 Top 3 routes — selected highlighted</h3>
    <div class="route-list">${rows}</div>
  </div>`;
}

function costChart(data) {
  const opts = (data.options || []).slice(0, 3);
  if (!opts.length) return "";
  const ids = {
    best: data.best_value[0] && data.best_value[0].id,
    cheap: data.cheapest && data.cheapest.id,
    fast: data.fastest && data.fastest.id,
  };
  const maxPrice = Math.max(...opts.map((o) => o.price_total));
  const currency = opts[0].currency;

  const bars = opts
    .map((o, i) => {
      const pct = maxPrice > 0 ? (o.price_total / maxPrice) * 100 : 0;
      const tags = tagsFor(o, ids);
      let cls = "bar";
      if (o.id === ids.best) cls += " bar-best";
      else if (o.id === ids.cheap) cls += " bar-cheap";
      else if (o.id === ids.fast) cls += " bar-fast";
      const tagHtml = tags
        .map((t) => `<span class="tag">${t}</span>`)
        .join(" ");
      const label = `${o.carrier_names.join(", ")} · ${o.stops_count} stop${
        o.stops_count === 1 ? "" : "s"
      } · ✈ ${fmtH(o.total_duration_min)} · ⏳ ${fmtH(o.layover_min)}`;
      return `
        <div class="bar-row">
          <div class="bar-label" title="${label}">#${i + 1} ${label} ${tagHtml}</div>
          <div class="bar-track">
            <div class="${cls}" style="width:${Math.max(pct, 6)}%">
              <span class="bar-price">${(o.price_per_person ?? o.price_total).toFixed(2)} ${o.currency}/pp</span>
            </div>
          </div>
        </div>`;
    })
    .join("");

  return `<div class="card chart-card">
    <h3>💰 Cost per person — Top 3 (${currency})</h3>
    <div class="bar-chart">${bars}</div>
  </div>`;
}

function renderSplitSuggestion(split, cheapestRegular) {
  if (!split || !split.legs || !split.legs.length) return "";

  // Comparison vs cheapest regular flight
  let compHtml = "";
  if (cheapestRegular && cheapestRegular > 0) {
    const diff = split.total_price - cheapestRegular;
    const pct  = Math.abs((diff / cheapestRegular) * 100).toFixed(0);
    if (diff < 0) {
      compHtml = `<span class="tag tag-best" style="font-size:.85rem;vertical-align:middle">✅ ${pct}% CHEAPER than cheapest regular ($${cheapestRegular.toFixed(2)})</span>`;
    } else {
      compHtml = `<span class="tag" style="background:#b45309;font-size:.85rem;vertical-align:middle">⚠️ +$${diff.toFixed(2)} vs cheapest regular ($${cheapestRegular.toFixed(2)})</span>`;
    }
  }

  const totalHtml = `
    <div style="background:#0f1f35;border:1px solid #1e3a5f;border-radius:8px;padding:.75rem 1rem;margin-bottom:1rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem">
      <span style="font-weight:700;color:#93c5fd">🧮 Combined cheapest total &nbsp;${compHtml}</span>
      <span style="font-size:1.3rem;font-weight:700;color:#4ade80">$${split.total_price.toFixed(2)} ${split.currency}</span>
    </div>`;

  const legsHtml = split.legs.map((leg, legIdx) => {
    const legTitle = `<div class="leg-header" style="font-size:1rem;margin-bottom:.5rem">
      LEG ${legIdx + 1}: <b>${leg.label}</b> &nbsp;<span style="color:#64748b;font-size:.85rem">${leg.date}</span>
      ${leg.cheapest_price ? `<span style="float:right;color:#4ade80;font-weight:700">FROM $${leg.cheapest_price.toFixed(2)}</span>` : ""}
    </div>`;

    if (leg.error) {
      return `<div class="result-card">${legTitle}<p class="error">${leg.error}</p></div>`;
    }
    if (!leg.options || !leg.options.length) {
      return `<div class="result-card">${legTitle}<p class="sub">No flights found for this leg.</p></div>`;
    }

    const optionsHtml = leg.options.slice(0, 3).map((o, oi) => {
      const allSegs = o.segments || [];
      const outSegs = allSegs.filter(s => s.direction !== "inbound");
      const segsToRender = outSegs.length ? outSegs : allSegs;
      const carriers = o.carrier_names && o.carrier_names.length ? o.carrier_names.join(" + ") : "";
      const bookUrl = o.booking_url || (segsToRender.length ? fallbackBookUrl(o) : "");
      const bookBtn = bookUrl
        ? `<a href="${bookUrl}" target="_blank" rel="noopener" class="btn-book">Book →</a>`
        : "";
      const segHtml = segsToRender.length ? renderLeg(segsToRender, `✈ ${leg.label}`) : "";
      return `
        <div class="result-card" style="margin-bottom:.75rem;border-left:3px solid ${oi === 0 ? "#4ade80" : "#1e3a5f"}">
          <div class="result-header">
            <span class="price">$${(o.price_per_person ?? o.price_total).toFixed(2)}/pp${o.price_total > (o.price_per_person ?? o.price_total) ? ` <span style="font-size:.8em;color:#94a3b8">(total $${o.price_total.toFixed(2)})</span>` : ""} <span class="currency">${o.currency}</span></span>
            <span class="stops">${o.stops_count === 0 ? "Direct" : o.stops_count + " stop" + (o.stops_count > 1 ? "s" : "")}</span>
            <span class="dur">${fmtH(o.total_duration_min)}</span>
            <span style="color:#94a3b8;font-size:.82rem">${carriers}</span>
            ${bookBtn}
          </div>
          ${segHtml}
        </div>`;
    }).join("");

    return `<div style="margin-bottom:1.5rem">${legTitle}${optionsHtml}</div>`;
  }).join("");

  const via = split.legs[0]?.label?.split("→")[1]?.trim() || "stopover";
  return `<div class="card" id="split-suggestion-area" style="border:2px solid #0e7490">
    <h3>💡 Agent-built Multi-day Split-ticket &nbsp;<span style="color:#38bdf8;font-size:.9rem">via ${via}</span></h3>
    <p class="sub" style="margin-bottom:1rem">Each leg searched independently on different dates — book each separately.</p>
    ${totalHtml}
    ${legsHtml}
  </div>`;
}

function topPicks(data) {
  // Always surface the three headline itineraries explicitly, even when the
  // cheapest/fastest are not in the best-value top-3 (e.g. a cheap but slow
  // self-transfer). Answers "where do I see the $X cheapest?".
  const picks = [
    { o: data.best_value && data.best_value[0], label: "⭐ Best Value", color: "#4ade80" },
    { o: data.cheapest, label: "💲 Cheapest", color: "#38bdf8" },
    { o: data.fastest, label: "⚡ Fastest", color: "#f59e0b" },
  ].filter(p => p.o);
  if (!picks.length) return "";
  // De-dupe by id so we don't show the same flight 3x, but keep the label list.
  const byId = {};
  for (const p of picks) {
    const e = (byId[p.o.id] ||= { o: p.o, labels: [], color: p.color });
    e.labels.push(p.label);
  }
  const cards = Object.values(byId).map(({ o, labels, color }) => {
    const pp = (o.price_per_person ?? o.price_total).toFixed(2);
    const totalNote = o.price_total > (o.price_per_person ?? o.price_total)
      ? ` <span style="font-size:.8em;color:#94a3b8">(total $${o.price_total.toFixed(2)})</span>` : "";
    const url = o.booking_url || fallbackBookUrl(o);
    const bookBtn = url ? `<a class="book-btn" href="${url}" target="_blank" rel="noopener">Book →</a>` : "";
    return `
      <div class="route-card" style="border-left:4px solid ${color}">
        <div class="route-head">
          <span>${labels.map(l => `<span class="tag tag-best" style="margin-right:.25rem">${l}</span>`).join("")}</span>
          <span class="price">${pp} ${o.currency}/pp${totalNote}</span>
          <span class="meta">${o.carrier_names.join(", ")}</span>
          <span class="meta">${o.stops_count} stop${o.stops_count === 1 ? "" : "s"}</span>
          <span class="meta">✈ ${fmtH(o.total_duration_min)}</span>
          <span class="meta">⏳ layover ${fmtH(o.layover_min)}</span>
          ${bookBtn}
        </div>
        ${routePath(o)}
      </div>`;
  }).join("");
  return `<div class="card">
    <h3>🏷️ Top picks — Best Value · Cheapest · Fastest</h3>
    <div class="route-list">${cards}</div>
  </div>`;
}

function render(data) {
  let html = "";
  if (data.notice) {
    // Filters removed every regular itinerary (e.g. all over max price). Show the
    // reason but keep going — a multi-day split via the hub may still fit budget.
    html += `<div class="card" style="border-left:4px solid #f59e0b">
      <h3>⚠️ No regular itinerary matched your filters</h3>
      <p class="sub">${data.notice}</p>
      ${data.split_via ? `<p class="sub">Checking an agent-built multi-day split via <b>${data.split_via}</b> — it may still beat your budget…</p>` : ""}
    </div>`;
  }
  html += topPicks(data);
  html += costChart(data);
  html += allRoutes(data);
  if (data.split_via) {
    html += `<div id="split-suggestion-area" class="card" style="border:2px solid #0e7490">
      <h3>💡 Agent-built Multi-day Split-ticket &nbsp;<span style="color:#38bdf8;font-size:.9rem">via ${data.split_via}</span></h3>
      <p class="sub"><span class="loading">⏳ Searching each leg independently… this takes ~30-60s</span></p>
    </div>`;
  }
  html += `<p class="badge">${data.total_considered} itineraries considered · times shown in hours</p>`;
  resultsEl.innerHTML = html;

  if (data.split_via) {
    const cheapestRegular = data.cheapest?.price_total || 0;
    const maxPrice = data._searchPayload?.max_price || null;
    _fetchSplitSuggestion(data._searchPayload, data.split_via, cheapestRegular, data.options || [], maxPrice);
  }
}

// ── Recent searches ─────────────────────────────────────────────────────────
const RECENT_KEY = "flight_recent_searches";
const RECENT_MAX = 5;

function saveSearch(payload) {
  let list = [];
  try { list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch (_) {}
  // Deduplicate: remove existing identical entry (same route + dates)
  const key = s => `${s.origin}|${s.destination}|${s.flight_dates?.departure}|${s.flight_dates?.return||""}`;
  list = list.filter(s => key(s) !== key(payload));
  list.unshift({ ...payload, _saved: new Date().toISOString() });
  list = list.slice(0, RECENT_MAX);
  localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  renderRecentSearches();
}

function applySearch(payload) {
  // Fill the airport autocomplete display + hidden IATA values
  _setAirportAC('ac-origin',      'origin-iata',      payload.origin || "");
  _setAirportAC('ac-destination', 'destination-iata', payload.destination || "");
  form.querySelector('[name=departure]').value      = payload.flight_dates?.departure || "";
  form.querySelector('[name=return]').value         = payload.flight_dates?.return || "";
  form.querySelector('[name=traveler_count]').value = payload.traveler_count || 1;
  form.querySelector('[name=max_connections]').value = payload.max_connections ?? "";
  form.querySelector('[name=include]').value        = (payload.airline_filters?.include || []).join(", ");
  form.querySelector('[name=exclude]').value        = (payload.airline_filters?.exclude || []).join(", ");
  form.querySelector('[name=max_price]').value      = payload.max_price || "";
  // Scroll to top of form and auto-submit
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  form.requestSubmit();
}

function renderRecentSearches() {
  const container = document.getElementById("recent-searches");
  if (!container) {
    // DOM not ready yet — retry shortly
    setTimeout(renderRecentSearches, 100);
    return;
  }
  let list = [];
  try { list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch (_) {}
  if (!list.length) {
    container.innerHTML = `<div class="recent-searches-bar"><span class="recent-label">🕒 Recent:</span><span style="color:#475569;font-size:.78rem;padding:.3rem 0">No recent searches yet — results will appear here after your first search.</span></div>`;
    return;
  }

  const chips = list.map((s, i) => {
    const dep  = s.flight_dates?.departure || "";
    const ret  = s.flight_dates?.return ? ` → ${s.flight_dates.return}` : " (one-way)";
    const conn = s.max_connections != null ? `, max ${s.max_connections} stop${s.max_connections===1?"":"s"}` : "";
    const pax  = s.traveler_count > 1 ? `, ${s.traveler_count} pax` : "";
    const inc  = (s.airline_filters?.include || []).length ? ` ✈${s.airline_filters.include.join("+")}` : "";
    const label = `${s.origin} → ${s.destination}  ${dep}${ret}${pax}${conn}${inc}`;
    return `<button class="recent-chip" onclick="applySearch(recentList[${i}])" title="Click to re-run this search">
      <span class="recent-route">${s.origin} → ${s.destination}</span>
      <span class="recent-meta">${dep}${ret}${pax}${conn}${inc}</span>
    </button>`;
  }).join("");

  container.innerHTML = `
    <div class="recent-searches-bar">
      <span class="recent-label">🕒 Recent:</span>
      <div class="recent-chips">${chips}</div>
      <button class="recent-clear" onclick="clearRecentSearches()" title="Clear history">✕ Clear</button>
    </div>`;

  // Expose list to inline onclick handlers
  window.recentList = list;
}

function clearRecentSearches() {
  localStorage.removeItem(RECENT_KEY);
  renderRecentSearches();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  resultsEl.innerHTML = "";
  statusEl.innerHTML = '<span class="loading">Searching…</span>';

  const f = new FormData(form);
  const maxPriceRaw = f.get("max_price");
  const maxConnRaw = f.get("max_connections");

  // If user typed a raw 3-letter IATA without picking from dropdown, accept it directly
  const originVal = (f.get("origin") || document.getElementById("ac-origin")?.value || "").toUpperCase().trim();
  const destVal   = (f.get("destination") || document.getElementById("ac-destination")?.value || "").toUpperCase().trim();
  if (!originVal || !destVal) {
    statusEl.innerHTML = `<span class="error">Please select a valid origin and destination airport.</span>`;
    return;
  }

  const payload = {
    origin: originVal,
    destination: destVal,
    flight_dates: {
      departure: f.get("departure"),
      return: f.get("return") || null,
    },
    traveler_count: Number(f.get("traveler_count")) || 1,
    max_connections: maxConnRaw !== "" && maxConnRaw !== null ? Number(maxConnRaw) : null,
    airline_filters: {
      include: splitNames(f.get("include")),
      exclude: splitNames(f.get("exclude")),
    },
    max_price: maxPriceRaw ? Number(maxPriceRaw) : null,
  };

  // Save to recent searches immediately — before the API call so it persists
  // even when the search returns no results or hits a filter error.
  saveSearch(payload);

  // Two-phase search: fast tier (Kiwi+Kayak, ~3s) renders first, then the
  // full tier (adds Skyscanner, ~40s) replaces it when ready.
  const _doSearch = async (tier) => {
    const resp = await fetch(`/api/search?tier=${tier}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    return { ok: resp.ok, data };
  };

  let fastShown = false;
  try {
    const fast = await _doSearch("fast");
    if (fast.ok) {
      statusEl.innerHTML = '<span class="loading">Checking Skyscanner for more deals…</span>';
      fast.data._searchPayload = payload;
      render(fast.data);
      fastShown = true;
    }
    // Phase 2: full set (folds in Skyscanner). Replaces phase-1 results.
    const full = await _doSearch("full");
    if (!full.ok) {
      if (!fastShown) {
        statusEl.innerHTML = `<span class="error">${full.data.detail || "Search failed."}</span>`;
      } else {
        statusEl.innerHTML = '<span class="muted">Showing Kiwi + Kayak results (Skyscanner unavailable).</span>';
      }
      return;
    }
    statusEl.innerHTML = "";
    full.data._searchPayload = payload;
    render(full.data);
  } catch (err) {
    if (!fastShown) {
      statusEl.innerHTML = `<span class="error">Network error: ${err.message}</span>`;
    } else {
      statusEl.innerHTML = '<span class="muted">Showing partial results (network error fetching Skyscanner).</span>';
    }
  }
});
// ── price watch ──────────────────────────────────────────────────────────────

async function _fetchSplitSuggestion(searchPayload, via, cheapestRegular, regularOptions, maxPrice) {
  const area = document.getElementById("split-suggestion-area");
  if (!area) return;
  try {
    const resp = await fetch("/api/search/split-suggestion", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ search: searchPayload, via }),
    });
    const split = resp.ok ? await resp.json() : null;
    // Honour the budget: a split that exceeds max price isn't a valid offer.
    if (split && split.legs && split.legs.length && maxPrice && split.total_price > maxPrice) {
      area.outerHTML = `<div class="card split-card"><p class="split-desc">No split-ticket via <b>${via}</b> under your $${maxPrice.toFixed(0)} budget: cheapest multi-day combo is $${split.total_price.toFixed(2)}.</p></div>`;
      return;
    }
    const cheaper = !cheapestRegular || cheapestRegular <= 0 || (split && split.total_price < cheapestRegular);
    if (split && split.legs && split.legs.length && cheaper) {
      const newHtml = renderSplitSuggestion(split, cheapestRegular);
      const area = document.getElementById("split-suggestion-area");
      if (area) area.outerHTML = newHtml;
      _injectSplitIntoChart(split, cheapestRegular, regularOptions);
    } else if (split && split.legs && split.legs.length) {
      // Found a split but it is NOT cheaper than the regular round-trip — do not
      // promote it; the split feature exists to surface CHEAPER multi-day combos.
      area.outerHTML = `<div class="card split-card"><p class="split-desc">No cheaper split-ticket via <b>${via}</b>: best multi-day combo is $${split.total_price.toFixed(2)} vs regular cheapest $${cheapestRegular.toFixed(2)}.</p></div>`;
    } else {
      area.outerHTML = `<div class="card split-card"><p class="split-desc">No cheaper split-ticket found via <b>${via}</b> for these dates.</p></div>`;
    }
  } catch (e) {
    console.error("split-suggestion error:", e);
    if (area) area.outerHTML = `<div class="card split-card"><p class="split-desc error">Split suggestion failed: ${e.message}</p></div>`;
  }
}

function _injectSplitIntoChart(split, cheapestRegular, regularOptions) {
  const chart = document.querySelector(".bar-chart");
  if (!chart) return;
  const allPrices = (regularOptions || []).map(o => o.price_total).concat([split.total_price]);
  const maxPrice = Math.max(...allPrices);
  const pct = maxPrice > 0 ? (split.total_price / maxPrice) * 100 : 50;
  const currency = split.currency;
  const diff = cheapestRegular > 0 ? split.total_price - cheapestRegular : null;
  const diffLabel = diff !== null
    ? (diff < 0 ? ` ✅ saves $${Math.abs(diff).toFixed(2)}` : ` ⚠️ +$${diff.toFixed(2)}`)
    : "";
  const cls = diff !== null && diff < 0 ? "bar bar-best" : "bar";
  const bar = document.createElement("div");
  bar.className = "bar-row";
  bar.innerHTML = `
    <div class="bar-label">💡 Split via ${split.legs[0]?.label?.split("→")[1]?.trim() || "via"} (agent-built, ${split.legs.length} legs)${diffLabel}</div>
    <div class="bar-track">
      <div class="${cls}" style="width:${Math.max(pct, 6)}%;background:#0e7490">
        <span class="bar-price">${split.total_price.toFixed(2)} ${currency}</span>
      </div>
    </div>`;
  chart.appendChild(bar);
}

function buildSearchPayload() {
  const f = new FormData(document.getElementById("search-form"));
  const maxPriceRaw = f.get("max_price");
  const maxConnRaw = f.get("max_connections");
  return {
    origin: (f.get("origin") || "").toUpperCase(),
    destination: (f.get("destination") || "").toUpperCase(),
    flight_dates: {
      departure: f.get("departure"),
      return: f.get("return") || null,
    },
    traveler_count: Number(f.get("traveler_count")) || 1,
    max_connections: maxConnRaw !== "" && maxConnRaw !== null ? Number(maxConnRaw) : null,
    airline_filters: {
      include: splitNames(f.get("include")),
      exclude: splitNames(f.get("exclude")),
    },
    max_price: maxPriceRaw ? Number(maxPriceRaw) : null,
  };
}

async function loadWatches() {
  try {
    const resp = await fetch("/api/watches", { headers: authHeaders() });
    if (resp.status === 401) return;  // not logged in
    const watches = await resp.json();
    renderWatches(watches);
    // Refresh nav badge
    const active = watches.filter(w => w.active);
    const badge = document.getElementById("nav-watches-badge");
    if (badge) {
      if (active.length > 0) {
        badge.style.cssText = "display:inline-flex;align-items:center;gap:.3rem;background:#0e7490;color:#fff;border-radius:999px;padding:2px 10px;font-size:.78rem;font-weight:600;";
        badge.innerHTML = `🔔 ${active.length} watch${active.length > 1 ? "es" : ""} active`;
        badge.title = active.map(w => `${w.origin}→${w.destination} ${w.departure}`).join(", ");
      } else {
        badge.style.display = "none";
      }
    }
  } catch (e) { /* ignore */ }
}

function renderWatches(watches) {
  const el = document.getElementById("watches-list");
  if (!watches.length) { el.innerHTML = ""; return; }
  const rows = watches.map((w) => `
    <div class="watch-card">
      <div class="watch-meta">
        <span class="watch-route">${w.origin} → ${w.destination}</span>
        <span class="watch-dates">${w.departure}${w.ret ? " – " + w.ret : ""}</span>
        <span class="watch-email">📧 ${w.email}</span>
        ${w.best_price != null ? `<span class="watch-price">Best seen: <b>${w.best_price.toFixed(2)} ${w.currency}</b></span>` : ""}
        ${w.last_checked ? `<span class="watch-checked">Last checked: ${w.last_checked.slice(0,16).replace("T"," ")}</span>` : ""}
      </div>
      <button class="btn-remove" data-id="${w.id}">✕ Remove</button>
    </div>`).join("");
  el.innerHTML = `<h3>Active watches (${watches.length})</h3>${rows}`;
  el.querySelectorAll(".btn-remove").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`/api/watches/${btn.dataset.id}`, { method: "DELETE", headers: authHeaders() });
      loadWatches();
    });
  });
}

document.getElementById("watch-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const statusEl = document.getElementById("watch-status");
  const emailInput = document.getElementById("watch-email-display");
  const email = (emailInput && emailInput.value.trim()) || (_user && _user.email);
  if (!email) { statusEl.innerHTML = '<span class="error">Enter your email to activate a price watch.</span>'; return; }

  const searchForm = document.getElementById("search-form");
  if (!searchForm.checkValidity()) {
    statusEl.innerHTML = `<span class="error">Fill in the search form (origin, destination, departure date) before activating a watch.</span>`;
    return;
  }

  statusEl.innerHTML = `<span class="loading">Running baseline search & registering watch…</span>`;
  try {
    const resp = await fetch("/api/watches", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ email, search: buildSearchPayload() }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      statusEl.innerHTML = `<span class="error">${data.detail || "Could not create watch."}</span>`;
      return;
    }
    const basePrice = data.current_best != null
      ? `Baseline price: <b>${data.current_best.toFixed(2)} ${data.currency}</b>.`
      : "No baseline price yet (search returned no results).";
    statusEl.innerHTML = `<span class="success">✅ Watch activated! (ID: ${data.id}) ${basePrice} You'll be emailed at <b>${email}</b> if the price drops.</span>`;
    loadWatches();
  } catch (err) {
    statusEl.innerHTML = `<span class="error">Network error: ${err.message}</span>`;
  }
});

document.getElementById("btn-run-now").addEventListener("click", async () => {
  const statusEl = document.getElementById("run-now-status");
  const btn = document.getElementById("btn-run-now");
  btn.disabled = true;
  statusEl.innerHTML = '<span class="loading">⚡ Checking prices now… (may take ~30s)</span>';
  try {
    const resp = await fetch("/api/watches/run-now", { method: "POST", headers: authHeaders() });
    const data = await resp.json();
    if (!resp.ok) { statusEl.innerHTML = `<span class="error">${data.detail || "Failed."}</span>`; return; }
    const rows = (data.results || []).map(r => {
      const icon = r.dropped ? '✅ DROPPED' : (r.new_price === r.old_best ? '– unchanged' : '↑ rose');
      const newStr = r.new_price != null ? `$${r.new_price.toFixed(2)}` : 'no results';
      return `<li>${r.route}: ${newStr} ${icon}${r.dropped ? ` (was $${r.old_best.toFixed(2)}) — email sent to ${r.email}` : ''}</li>`;
    }).join("");
    statusEl.innerHTML = `<span class="success">Checked ${data.checked} watch(es).<ul style="margin:.3rem 0 0 1rem">${rows}</ul></span>`;
    loadWatches();
  } catch (e) {
    statusEl.innerHTML = `<span class="error">Error: ${e.message}</span>`;
  } finally {
    btn.disabled = false;
  }
});

loadWatches();

// ── Multi-day stopover ─────────────────────────────────────────────────────

let _stopoverLegs = [];

function _renderStopoverLegsUI() {
  const cont = document.getElementById("stopover-legs");
  if (!cont) return;
  cont.innerHTML = _stopoverLegs.map((leg, i) => `
    <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap" class="sv-leg-row">
      <span style="color:#64748b;font-size:.8rem;min-width:48px">Leg ${i + 1}</span>
      <input value="${leg.origin}" onchange="_stopoverLegs[${i}].origin=this.value.toUpperCase().trim()" maxlength="3"
             placeholder="From" style="width:65px;text-transform:uppercase" title="Origin IATA" />
      <span style="color:#64748b">→</span>
      <input value="${leg.destination}" onchange="_stopoverLegs[${i}].destination=this.value.toUpperCase().trim()" maxlength="3"
             placeholder="To" style="width:65px;text-transform:uppercase" title="Destination IATA" />
      <input type="date" value="${leg.date}" onchange="_stopoverLegs[${i}].date=this.value"
             style="width:150px" title="Departure date" />
    </div>`).join("");
}

function addStopoverLeg(origin = "", destination = "", date = "") {
  _stopoverLegs.push({ origin, destination, date });
  _renderStopoverLegsUI();
}

function removeStopoverLeg() {
  if (_stopoverLegs.length > 2) _stopoverLegs.pop();
  _renderStopoverLegsUI();
}

function fillRoundTrip() {
  const f = new FormData(document.getElementById("search-form"));
  const origin = (f.get("origin") || "").toUpperCase().trim();
  const dest   = (f.get("destination") || "").toUpperCase().trim();
  const dep    = f.get("departure") || "";
  const ret    = f.get("return") || "";
  if (!origin || !dest || !dep) {
    alert("Fill in the main search form (origin, destination, departure) first.");
    return;
  }
  // Prompt for via airport
  const via = (prompt("Enter the stopover airport IATA code (e.g. OTP, AMS):", "") || "").toUpperCase().trim();
  if (!via) return;
  const via_out_date = prompt(`Date of ${via} → ${dest} leg (YYYY-MM-DD):`, dep) || "";
  const via_ret_date = ret ? (prompt(`Date of ${dest} → ${via} return leg (YYYY-MM-DD):`, ret) || "") : "";
  const ret_date_final = ret || "";

  _stopoverLegs = [
    { origin, destination: via, date: dep },
    { origin: via, destination: dest, date: via_out_date },
  ];
  if (ret) {
    _stopoverLegs.push({ origin: dest, destination: via, date: via_ret_date });
    _stopoverLegs.push({ origin: via, destination: origin, date: ret_date_final });
  }
  _renderStopoverLegsUI();
  document.getElementById("stopover-section").open = true;
}

// Default: 4 legs pre-populated as empty placeholders
(function initStopoverLegs() {
  if (_stopoverLegs.length === 0) {
    _stopoverLegs = [
      { origin: "", destination: "", date: "" },
      { origin: "", destination: "", date: "" },
      { origin: "", destination: "", date: "" },
      { origin: "", destination: "", date: "" },
    ];
    _renderStopoverLegsUI();
  }
})();

// ── Stopover recent searches ────────────────────────────────────────────────
const STOPOVER_RECENT_KEY = "flight_stopover_recent";
const STOPOVER_RECENT_MAX = 5;

function _svKey(p) {
  // Signature: ordered legs (route+date) + pax + filters, so re-running the
  // same multi-day itinerary dedupes.
  return (p.legs || []).map(l => `${l.origin}>${l.destination}@${l.date}`).join("|")
    + `#${p.traveler_count || 1}#${p.max_connections ?? ""}#${p.max_price ?? ""}`;
}

function saveStopoverSearch(payload) {
  let list = [];
  try { list = JSON.parse(localStorage.getItem(STOPOVER_RECENT_KEY) || "[]"); } catch (_) {}
  list = list.filter(s => _svKey(s) !== _svKey(payload));
  list.unshift({ ...payload, _saved: new Date().toISOString() });
  list = list.slice(0, STOPOVER_RECENT_MAX);
  localStorage.setItem(STOPOVER_RECENT_KEY, JSON.stringify(list));
  renderStopoverRecent();
}

function applyStopoverSearch(payload) {
  _stopoverLegs = (payload.legs || []).map(l => ({ origin: l.origin, destination: l.destination, date: l.date }));
  _renderStopoverLegsUI();
  const t = document.getElementById("sv-travelers"); if (t) t.value = payload.traveler_count || 1;
  const c = document.getElementById("sv-max-conn");  if (c) c.value = payload.max_connections != null ? String(payload.max_connections) : "";
  const m = document.getElementById("sv-max-price"); if (m) m.value = payload.max_price || "";
  const sec = document.getElementById("stopover-section"); if (sec) sec.open = true;
  sec?.scrollIntoView({ behavior: "smooth", block: "start" });
  searchStopover();
}

function renderStopoverRecent() {
  const container = document.getElementById("stopover-recent");
  if (!container) { setTimeout(renderStopoverRecent, 100); return; }
  let list = [];
  try { list = JSON.parse(localStorage.getItem(STOPOVER_RECENT_KEY) || "[]"); } catch (_) {}
  if (!list.length) {
    container.innerHTML = `<div class="recent-searches-bar"><span class="recent-label">🕒 Recent stopovers:</span><span style="color:#475569;font-size:.78rem;padding:.3rem 0">None yet — your multi-day searches appear here.</span></div>`;
    return;
  }
  const chips = list.map((s, i) => {
    const route = (s.legs || []).map(l => l.origin).concat((s.legs || []).slice(-1).map(l => l.destination)).join(" → ");
    const d0 = s.legs?.[0]?.date || "";
    const dN = s.legs?.[s.legs.length - 1]?.date || "";
    const span = d0 && dN ? `${d0}${dN !== d0 ? " … " + dN : ""}` : "";
    const pax  = s.traveler_count > 1 ? `, ${s.traveler_count} pax` : "";
    const conn = s.max_connections != null ? `, max ${s.max_connections}/leg` : "";
    return `<button class="recent-chip" onclick="applyStopoverSearch(stopoverRecentList[${i}])" title="Click to re-run this multi-day search">
      <span class="recent-route">${route}</span>
      <span class="recent-meta">${s.legs?.length || 0} legs · ${span}${pax}${conn}</span>
    </button>`;
  }).join("");
  container.innerHTML = `
    <div class="recent-searches-bar">
      <span class="recent-label">🕒 Recent stopovers:</span>
      <div class="recent-chips">${chips}</div>
      <button class="recent-clear" onclick="clearStopoverRecent()" title="Clear history">✕ Clear</button>
    </div>`;
  window.stopoverRecentList = list;
}

function clearStopoverRecent() {
  localStorage.removeItem(STOPOVER_RECENT_KEY);
  renderStopoverRecent();
}

renderStopoverRecent();

async function searchStopover() {
  const statusEl = document.getElementById("stopover-status");
  const resultsEl = document.getElementById("stopover-results");
  statusEl.innerHTML = "";
  resultsEl.innerHTML = "";

  // Collect current values from DOM inputs (they may not have triggered onchange)
  const rows = document.querySelectorAll(".sv-leg-row");
  rows.forEach((row, i) => {
    const inputs = row.querySelectorAll("input");
    if (inputs[0]) _stopoverLegs[i].origin      = inputs[0].value.toUpperCase().trim();
    if (inputs[1]) _stopoverLegs[i].destination  = inputs[1].value.toUpperCase().trim();
    if (inputs[2]) _stopoverLegs[i].date          = inputs[2].value;
  });

  const legs = _stopoverLegs.filter(l => l.origin && l.destination && l.date);
  if (legs.length < 2) {
    statusEl.innerHTML = '<span class="error">Fill in at least 2 legs (origin, destination, date).</span>';
    return;
  }

  const maxConn = document.getElementById("sv-max-conn").value;
  const maxPrice = document.getElementById("sv-max-price").value;
  const travelers = parseInt(document.getElementById("sv-travelers").value) || 1;

  const payload = {
    legs,
    traveler_count: travelers,
    airline_filters: { include: [], exclude: [] },
    ...(maxConn !== "" ? { max_connections: parseInt(maxConn) } : {}),
    ...(maxPrice ? { max_price: parseFloat(maxPrice) } : {}),
  };

  // Save to stopover recent searches before the API call so it persists even
  // when the search returns no results.
  saveStopoverSearch(payload);

  statusEl.innerHTML = `<span class="loading">Searching ${legs.length} legs in parallel…</span>`;
  try {
    const resp = await fetch("/api/search/stopover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      statusEl.innerHTML = `<span class="error">${data.detail || "Search failed."}</span>`;
      return;
    }
    statusEl.innerHTML = `<span class="success">Found results for ${data.legs.length} legs — combined cheapest: <b>$${data.total_price.toFixed(2)} ${data.currency}</b></span>`;
    resultsEl.innerHTML = renderStopoverResults(data);
  } catch (err) {
    statusEl.innerHTML = `<span class="error">Network error: ${err.message}</span>`;
  }
}

function renderStopoverResults(data) {
  if (!data.legs || !data.legs.length) return "<p class='sub'>No results.</p>";

  const totalHtml = `
    <div style="background:#0f1f35;border:1px solid #1e3a5f;border-radius:8px;padding:.75rem 1rem;margin-bottom:1rem;display:flex;justify-content:space-between;align-items:center">
      <span style="font-weight:700;color:#93c5fd">🧮 Combined cheapest total</span>
      <span style="font-size:1.3rem;font-weight:700;color:#4ade80">$${data.total_price.toFixed(2)} ${data.currency}</span>
    </div>`;

  const legsHtml = data.legs.map((leg, legIdx) => {
    const legTitle = `<div class="leg-header" style="font-size:1rem;margin-bottom:.5rem">
      Leg ${legIdx + 1}: <b>${leg.label}</b> &nbsp;<span style="color:#64748b;font-size:.85rem">${leg.date}</span>
      ${leg.cheapest_price ? `<span style="float:right;color:#4ade80;font-weight:700">From $${leg.cheapest_price.toFixed(2)}</span>` : ""}
    </div>`;

    if (leg.error) {
      return `<div class="result-card">${legTitle}<p class="error">${leg.error}</p></div>`;
    }
    if (!leg.options || !leg.options.length) {
      return `<div class="result-card">${legTitle}<p class="sub">No flights found for this leg.</p></div>`;
    }

    // Show up to 3 options for this leg
    const optionsHtml = leg.options.slice(0, 3).map((o, oi) => {
      const outSegs = o.segments || [];
      const carriers = o.carrier_names && o.carrier_names.length
        ? o.carrier_names.join(" + ")
        : (o.carriers || []).join(" + ");
      const bookBtn = o.booking_url
        ? `<a href="${o.booking_url}" target="_blank" rel="noopener" class="btn-book">Book →</a>`
        : "";
      const label = `✈ ${leg.label}`;
      const segHtml = renderLeg(outSegs.filter(s => s.direction !== "inbound" || outSegs.every(s2 => !s2.direction)), label);
      return `
        <div class="result-card" style="margin-bottom:.75rem;border-left:3px solid ${oi === 0 ? "#4ade80" : "#1e3a5f"}">
          <div class="result-header">
            <span class="price">$${(o.price_per_person ?? o.price_total).toFixed(2)}/pp${o.price_total > (o.price_per_person ?? o.price_total) ? ` <span style="font-size:.8em;color:#94a3b8">(total $${o.price_total.toFixed(2)})</span>` : ""} <span class="currency">${o.currency}</span></span>
            <span class="stops">${o.stops_count === 0 ? "Direct" : o.stops_count + " stop" + (o.stops_count > 1 ? "s" : "")}</span>
            <span class="dur">${fmtH(o.total_duration_min)}</span>
            <span style="color:#94a3b8;font-size:.82rem">${carriers}</span>
            ${bookBtn}
          </div>
          ${segHtml}
        </div>`;
    }).join("");

    return `<div style="margin-bottom:1.5rem">${legTitle}${optionsHtml}</div>`;
  }).join("");

  return totalHtml + legsHtml;
}