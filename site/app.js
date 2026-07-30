(function () {
  "use strict";

  var state = { projects: [], query: "", sort: "stars", open: null };

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

  function detailHtml(p) {
    var outputs = (p.outputs_list || [])
      .map(function (o) {
        return (
          "<li><span>" + escapeHtml(o.label) + "</span>" +
          (o.type ? '<span class="output-type">' + escapeHtml(o.type) + "</span>" : "") +
          "</li>"
        );
      })
      .join("");
    var tags = allTags(p)
      .map(function (t) {
        return '<button class="tag" data-topic="' + escapeHtml(t) + '">' + escapeHtml(t) + "</button>";
      })
      .join("");
    return (
      '<div class="detail">' +
      (p.description ? '<p class="detail-desc">' + escapeHtml(p.description) + "</p>" : "") +
      (outputs
        ? '<div class="detail-section"><span class="detail-label">Outputs</span><ul class="outputs">' + outputs + "</ul></div>"
        : "") +
      (tags
        ? '<div class="detail-section"><span class="detail-label">Tags</span><div class="tag-list">' + tags + "</div></div>"
        : "") +
      '<div class="detail-foot">' +
      '<span class="detail-meta">Updated ' + escapeHtml(timeAgo(p.pushed_at)) + " · " + formatStars(p.stars || 0) + " stars</span>" +
      '<a class="repo-link" href="' + escapeHtml(p.html_url) + '" target="_blank" rel="noopener">Open repository ↗</a>' +
      "</div></div>"
    );
  }

  function render() {
    var list = visibleProjects();
    emptyEl.hidden = list.length > 0;
    rowsEl.innerHTML = list
      .map(function (p, i) {
        var name = p.astra_name || (p.full_name || "").split("/")[1] || p.full_name;
        var isOpen = state.open === p.full_name;
        var stat =
          state.sort === "updated" ? timeAgo(p.pushed_at) : formatStars(p.stars || 0) + " ★";
        return (
          '<li class="entry' + (isOpen ? " open" : "") + '">' +
          '<button class="row" data-repo="' + escapeHtml(p.full_name) + '" aria-expanded="' + isOpen + '">' +
          '<span class="row-rank">' + (i + 1) + "</span>" +
          '<span class="row-main">' +
          '<span class="row-title"><h2 class="row-name">' + escapeHtml(name) + '</h2><span class="row-repo">' + escapeHtml(p.full_name) + "</span></span>" +
          (p.description ? '<p class="row-desc">' + escapeHtml(p.description) + "</p>" : "") +
          "</span>" +
          '<span class="row-stat">' + escapeHtml(stat) + "</span>" +
          "</button>" +
          (isOpen ? detailHtml(p) : "") +
          "</li>"
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

  rowsEl.addEventListener("click", function (e) {
    var tag = e.target.closest(".tag");
    if (tag) {
      searchEl.value = tag.dataset.topic;
      state.query = tag.dataset.topic;
      render();
      return;
    }
    var row = e.target.closest(".row");
    if (row) {
      state.open = state.open === row.dataset.repo ? null : row.dataset.repo;
      render();
    }
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

  fetch("projects.json", { cache: "no-cache" })
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function () { init({ projects: [] }); });
})();
