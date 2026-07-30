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
        (p.description || "").toLowerCase().indexOf(q) !== -1
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

  function render() {
    var list = visibleProjects();
    emptyEl.hidden = list.length > 0;
    rowsEl.innerHTML = list
      .map(function (p, i) {
        var name = p.astra_name || (p.full_name || "").split("/")[1] || p.full_name;
        var stat =
          state.sort === "updated"
            ? '<span class="row-stat">' + escapeHtml(timeAgo(p.pushed_at)) + "</span>"
            : '<span class="row-stat">' + formatStars(p.stars || 0) + '<span class="unit">★</span></span>';
        return (
          '<li><a class="row" href="' + escapeHtml(p.html_url) + '" target="_blank" rel="noopener">' +
          '<span class="row-rank">' + (i + 1) + "</span>" +
          '<span class="row-main">' +
          '<h3 class="row-name">' + escapeHtml(name) + "</h3>" +
          '<p class="row-repo">' + escapeHtml(p.full_name) + "</p>" +
          "</span>" +
          stat +
          (p.description ? '<p class="row-desc">' + escapeHtml(p.description) + "</p>" : "") +
          "</a></li>"
        );
      })
      .join("");
  }

  function init(data) {
    state.projects = (data && data.projects) || [];
    countEl.textContent = "(" + state.projects.length + ")";
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

  var cmdBox = document.getElementById("cmd-box");
  var copyBtn = document.getElementById("copy-btn");
  cmdBox.addEventListener("click", function () {
    navigator.clipboard.writeText("git clone https://github.com/<owner/repo>").then(function () {
      copyBtn.classList.add("copied");
      setTimeout(function () { copyBtn.classList.remove("copied"); }, 1200);
    });
  });

  fetch("projects.json", { cache: "no-cache" })
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function () { init({ projects: [] }); });
})();
