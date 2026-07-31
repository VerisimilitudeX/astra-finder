(function () {
  "use strict";

  var state = { projects: [], datasets: [], repoData: {}, query: "", sort: "stars" };

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
    if (days < 30) return days + " days ago";
    if (days < 365) return Math.floor(days / 30) + " months ago";
    return Math.floor(days / 365) + " years ago";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function allTags(p) {
    var seen = {};
    return (p.topics || []).concat(p.astra_tags || []).filter(function (t) {
      t = String(t);
      if (seen[t.toLowerCase()]) return false;
      seen[t.toLowerCase()] = true;
      return true;
    });
  }

  function displayName(p) {
    return p.astra_name || (p.full_name || "").split("/")[1] || p.full_name;
  }

  // repo -> {names: []} from datasets.json, so search also matches data file names
  function buildRepoData() {
    var map = {};
    state.datasets.forEach(function (d) {
      (d.occurrences || []).forEach(function (o) {
        var entry = (map[o.repo] = map[o.repo] || { names: [] });
        if (entry.names.indexOf(o.name) === -1) entry.names.push(o.name);
      });
    });
    state.repoData = map;
  }

  function visibleProjects() {
    var q = state.query.trim().toLowerCase();
    var list = state.projects.filter(function (p) {
      if (!q) return true;
      var extra = state.repoData[p.full_name] ? state.repoData[p.full_name].names : [];
      var hay = [p.full_name, p.astra_name, p.description]
        .concat(allTags(p))
        .concat(extra)
        .concat((p.findings_list || []).map(function (f) { return f.label; }));
      return hay.some(function (h) {
        return h && String(h).toLowerCase().indexOf(q) !== -1;
      });
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
        var stat =
          state.sort === "updated" ? timeAgo(p.pushed_at) : formatStars(p.stars || 0) + " ★";
        var headline = (p.findings_list || [])[0];
        return (
          '<li class="entry">' +
          '<a class="row" href="repo.html?r=' + encodeURIComponent(p.full_name) + '">' +
          '<span class="row-rank">' + (i + 1) + "</span>" +
          '<span class="row-main">' +
          '<span class="row-title"><h2 class="row-name">' + escapeHtml(displayName(p)) + "</h2>" +
          '<span class="row-repo">' + escapeHtml(p.full_name) + "</span>" +
          (p.verified ? '<span class="verified-mark" title="Passes ASTRA validation">✓ verified</span>' : "") +
          "</span>" +
          (p.description ? '<p class="row-desc">' + escapeHtml(p.description) + "</p>" : "") +
          (headline && headline.label
            ? '<p class="row-finding">Finding: ' + escapeHtml(headline.label) + "</p>"
            : "") +
          "</span>" +
          '<span class="row-stat">' + escapeHtml(stat) + "</span>" +
          "</a>" +
          "</li>"
        );
      })
      .join("");
  }

  searchEl.addEventListener("input", function () {
    state.query = searchEl.value;
    render();
  });

  Array.prototype.forEach.call(document.querySelectorAll(".sort"), function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".sort").forEach(function (b) {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      state.sort = btn.dataset.sort;
      render();
    });
  });

  var initialQuery = new URLSearchParams(location.search).get("q");
  if (initialQuery) {
    searchEl.value = initialQuery;
    state.query = initialQuery;
  }

  Promise.all([
    fetch("projects.json", { cache: "no-cache" }).then(function (r) { return r.json(); }),
    fetch("datasets.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).catch(function () { return { datasets: [] }; }),
  ])
    .then(function (results) {
      var data = results[0];
      state.projects = (data && data.projects) || [];
      state.datasets = (results[1] && results[1].datasets) || [];
      buildRepoData();
      countEl.textContent = state.projects.length;
      if (data && data.generated_at && refreshedEl) {
        refreshedEl.textContent = new Date(data.generated_at).toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        });
      }
      render();
    })
    .catch(function () {
      state.projects = [];
      render();
    });
})();
