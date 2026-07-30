(function () {
  "use strict";

  var state = { projects: [], query: "", sort: "stars" };

  var rowsEl = document.getElementById("rows");
  var emptyEl = document.getElementById("empty");
  var searchEl = document.getElementById("search");
  var countEl = document.getElementById("count-all");
  var refreshedEl = document.getElementById("refreshed");

  function formatStars(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  function timeAgo(iso) {
    if (!iso) return "";
    var days = Math.floor((Date.now() - new Date(iso).getTime()) / 864e5);
    if (days < 1) return "today";
    if (days < 30) return days + "d ago";
    if (days < 365) return Math.floor(days / 30) + "mo ago";
    return Math.floor(days / 365) + "y ago";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function visibleProjects() {
    var q = state.query.trim().toLowerCase();
    var list = state.projects.filter(function (p) {
      if (!q) return true;
      return (
        (p.full_name || "").toLowerCase().indexOf(q) !== -1 ||
        (p.astra_name || "").toLowerCase().indexOf(q) !== -1 ||
        (p.description || "").toLowerCase().indexOf(q) !== -1 ||
        allTags(p).some(function (t) { return t.toLowerCase().indexOf(q) !== -1; })
      );
    });
    list.sort(function (a, b) {
      if (state.sort === "updated") {
        return new Date(b.pushed_at || 0) - new Date(a.pushed_at || 0);
      }
      return (b.stars || 0) - (a.stars || 0) || (a.full_name || "").localeCompare(b.full_name || "");
    });
    return list;
  }

  // GitHub topics + the astra.yaml's own tags, deduplicated.
  function allTags(p) {
    var seen = {};
    return (p.topics || []).concat(p.astra_tags || []).filter(function (t) {
      t = String(t);
      if (seen[t.toLowerCase()]) return false;
      seen[t.toLowerCase()] = true;
      return true;
    });
  }

  function specNote(p) {
    var bits = [];
    if (p.outputs) bits.push(p.outputs + " outputs");
    if (p.decisions) bits.push(p.decisions + " decisions");
    return bits.join(" · ");
  }

  function render() {
    var list = visibleProjects();
    emptyEl.hidden = list.length > 0;
    rowsEl.innerHTML = list
      .map(function (p, i) {
        var name = p.astra_name || (p.full_name || "").split("/")[1] || p.full_name;
        var stat =
          state.sort === "updated"
            ? escapeHtml(timeAgo(p.pushed_at))
            : formatStars(p.stars || 0) + '<span class="unit">✦</span>';
        var chips = allTags(p)
          .map(function (t) {
            return '<button class="chip" data-topic="' + escapeHtml(t) + '">' + escapeHtml(t) + "</button>";
          })
          .join("");
        var note = specNote(p);
        var meta =
          chips || note
            ? '<span class="row-meta">' + chips + (note ? '<span class="spec-note">' + escapeHtml(note) + "</span>" : "") + "</span>"
            : "";
        return (
          "<li>" +
          '<a class="row" href="' + escapeHtml(p.html_url) + '" target="_blank" rel="noopener">' +
          '<span class="row-rank">' + String(i + 1).padStart(2, "0") + "</span>" +
          '<span class="row-main">' +
          '<span class="row-title"><h3 class="row-name">' + escapeHtml(name) + '</h3><span class="row-repo">' + escapeHtml(p.full_name) + "</span></span>" +
          (p.description ? '<p class="row-desc">' + escapeHtml(p.description) + "</p>" : "") +
          meta +
          "</span>" +
          '<span class="row-stat">' + stat + "</span>" +
          "</a></li>"
        );
      })
      .join("");
  }

  function init(data) {
    state.projects = (data && data.projects) || [];
    countEl.textContent = state.projects.length;
    if (data && data.generated_at && refreshedEl) {
      refreshedEl.textContent = new Date(data.generated_at).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });
    }
    render();
  }

  searchEl.addEventListener("input", function () {
    state.query = searchEl.value;
    render();
  });

  // Topic chips filter on click instead of following the row link.
  rowsEl.addEventListener("click", function (e) {
    var chip = e.target.closest(".chip");
    if (!chip) return;
    e.preventDefault();
    e.stopPropagation();
    searchEl.value = chip.dataset.topic;
    state.query = chip.dataset.topic;
    render();
  });

  Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (t) {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      state.sort = tab.dataset.sort;
      render();
    });
  });

  fetch("projects.json", { cache: "no-cache" })
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function () { init({ projects: [] }); });
})();
