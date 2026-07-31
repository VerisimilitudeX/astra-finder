(function () {
  "use strict";

  var state = { projects: [], datasets: [], repoData: {}, query: "", sort: "stars", open: null };

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

  // repo -> {hashes: Set-like object, names: [], files: []} from datasets.json
  function buildRepoData() {
    var map = {};
    state.datasets.forEach(function (d) {
      (d.occurrences || []).forEach(function (o) {
        var entry = (map[o.repo] = map[o.repo] || { hashes: {}, names: [], files: [] });
        if (!entry.hashes[d.hash]) {
          entry.files.push({ hash: d.hash, name: o.name, role: o.role, path: o.path, branch: o.branch, repo: o.repo });
        }
        entry.hashes[d.hash] = true;
        if (entry.names.indexOf(o.name) === -1) entry.names.push(o.name);
      });
    });
    Object.keys(map).forEach(function (r) {
      map[r].files.sort(function (a, b) {
        return a.role === b.role ? a.name.localeCompare(b.name) : a.role === "input" ? -1 : 1;
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

  var CANONICAL_BASE = "https://verisimilitudex.github.io/astra-finder/";

  function badgeAlt(p) {
    return p.verified ? "ASTRA verified" : "ASTRA failing";
  }

  function badgeMarkdown(p) {
    var img = CANONICAL_BASE + "badges/" + p.full_name.replace("/", "--") + ".svg";
    return "[![" + badgeAlt(p) + "](" + img + ")](" + CANONICAL_BASE + ")";
  }

  function badgeEmbedHtml(p) {
    return (
      '<div class="badge-embed"><img src="badges/' + escapeHtml(p.full_name.replace("/", "--")) + '.svg" alt="' + escapeHtml(badgeAlt(p)) + '">' +
      "<code>" + escapeHtml(badgeMarkdown(p)) + "</code>" +
      '<button class="copy-badge" data-md="' + escapeHtml(badgeMarkdown(p)) + '">copy</button></div>'
    );
  }

  function sameDataAnalyses(p) {
    var mine = state.repoData[p.full_name];
    if (!mine) return [];
    return state.projects.filter(function (o) {
      if (o.full_name === p.full_name) return false;
      var theirs = state.repoData[o.full_name];
      if (!theirs) return false;
      return Object.keys(mine.hashes).some(function (h) { return theirs.hashes[h]; });
    });
  }

  function detailHtml(p) {
    var html = '<div class="detail">';
    if (p.description) html += '<p class="detail-desc">' + escapeHtml(p.description) + "</p>";

    var findings = (p.findings_list || [])
      .map(function (f) {
        return (
          "<li>" +
          (f.label ? '<span class="finding-label">' + escapeHtml(f.label) + "</span>" : "") +
          (f.claim ? '<span class="finding-claim">' + escapeHtml(f.claim) + "</span>" : "") +
          "</li>"
        );
      })
      .join("");
    if (findings) {
      html += '<div class="detail-section"><span class="detail-label">Findings</span><ul class="findings">' + findings + "</ul></div>";
    }

    var outputs = (p.outputs_list || [])
      .map(function (o) {
        return (
          "<li><span>" + escapeHtml(o.label) + "</span>" +
          (o.type ? '<span class="output-type">' + escapeHtml(o.type) + "</span>" : "") +
          "</li>"
        );
      })
      .join("");
    if (outputs) {
      html += '<div class="detail-section"><span class="detail-label">Outputs</span><ul class="outputs">' + outputs + "</ul></div>";
    }

    var files = ((state.repoData[p.full_name] || {}).files || [])
      .slice(0, 12)
      .map(function (f) {
        var raw = "https://raw.githubusercontent.com/" + f.repo + "/" + f.branch + "/" + f.path;
        return (
          "<li>" +
          '<span><a class="file-link" href="dataset.html?h=' + escapeHtml(f.hash) + '">' + escapeHtml(f.name) + "</a>" +
          '<code class="dataset-hash">' + escapeHtml(f.hash.slice(0, 12)) + "</code></span>" +
          '<span class="file-side"><span class="role role-' + escapeHtml(f.role) + '">' + escapeHtml(f.role) + "</span>" +
          '<a class="raw-link" href="' + escapeHtml(raw) + '" target="_blank" rel="noopener">raw ↗</a></span>' +
          "</li>"
        );
      })
      .join("");
    if (files) {
      html += '<div class="detail-section"><span class="detail-label">Data files</span><ul class="outputs datafiles">' + files + "</ul></div>";
    }

    var siblings = sameDataAnalyses(p)
      .map(function (o) {
        return '<button class="link-btn" data-open="' + escapeHtml(o.full_name) + '">' + escapeHtml(displayName(o)) + "</button>";
      })
      .join('<span class="sep">·</span>');
    if (siblings) {
      html += '<div class="detail-section"><span class="detail-label">Same data, other analyses</span><div class="siblings">' + siblings + "</div></div>";
    }

    var tags = allTags(p)
      .map(function (t) {
        return '<button class="tag" data-topic="' + escapeHtml(t) + '">' + escapeHtml(t) + "</button>";
      })
      .join("");
    if (tags) {
      html += '<div class="detail-section"><span class="detail-label">Tags</span><div class="tag-list">' + tags + "</div></div>";
    }

    if (p.verified) {
      html +=
        '<div class="detail-section"><span class="detail-label">Verification badge</span>' +
        badgeEmbedHtml(p) + "</div>";
    } else {
      var reasons = (p.verification_errors || [])
        .slice(0, 4)
        .map(function (e) { return "<li>" + escapeHtml(e) + "</li>"; })
        .join("");
      html +=
        '<div class="detail-section"><span class="detail-label">Verification</span>' +
        '<p class="verify-note">Indexed, but the spec does not pass ASTRA validation:</p>' +
        (reasons ? '<ul class="verify-errors">' + reasons + "</ul>" : "") +
        badgeEmbedHtml(p) +
        "</div>";
    }

    html +=
      '<div class="detail-foot">' +
      '<span class="detail-meta">Updated ' + escapeHtml(timeAgo(p.pushed_at)) + " · " + formatStars(p.stars || 0) + " stars</span>" +
      '<a class="repo-link" href="' + escapeHtml(p.html_url) + '" target="_blank" rel="noopener">Open repository ↗</a>' +
      "</div></div>";
    return html;
  }

  function render() {
    var list = visibleProjects();
    emptyEl.hidden = list.length > 0;
    rowsEl.innerHTML = list
      .map(function (p, i) {
        var isOpen = state.open === p.full_name;
        var stat =
          state.sort === "updated" ? timeAgo(p.pushed_at) : formatStars(p.stars || 0) + " ★";
        var headline = (p.findings_list || [])[0];
        return (
          '<li class="entry' + (isOpen ? " open" : "") + '" data-entry="' + escapeHtml(p.full_name) + '">' +
          '<button class="row" data-repo="' + escapeHtml(p.full_name) + '" aria-expanded="' + isOpen + '">' +
          '<span class="row-rank">' + (i + 1) + "</span>" +
          '<span class="row-main">' +
          '<span class="row-title"><h2 class="row-name">' + escapeHtml(displayName(p)) + "</h2>" +
          '<span class="row-repo">' + escapeHtml(p.full_name) + "</span>" +
          (p.verified ? '<span class="verified-mark" title="Passes ASTRA validation">✓ verified</span>' : "") +
          "</span>" +
          (p.description ? '<p class="row-desc">' + escapeHtml(p.description) + "</p>" : "") +
          (headline && headline.label && !isOpen
            ? '<p class="row-finding">Finding: ' + escapeHtml(headline.label) + "</p>"
            : "") +
          "</span>" +
          '<span class="row-stat">' + escapeHtml(stat) + "</span>" +
          "</button>" +
          (isOpen ? detailHtml(p) : "") +
          "</li>"
        );
      })
      .join("");
  }

  function openAnalysis(fullName) {
    state.open = fullName;
    render();
    var el = document.querySelector('[data-entry="' + CSS.escape(fullName) + '"]');
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  searchEl.addEventListener("input", function () {
    state.query = searchEl.value;
    render();
  });

  document.addEventListener("click", function (e) {
    var openBtn = e.target.closest(".link-btn[data-open]");
    if (openBtn) {
      openAnalysis(openBtn.dataset.open);
      return;
    }
    var copyBadge = e.target.closest(".copy-badge");
    if (copyBadge) {
      e.preventDefault();
      e.stopPropagation();
      navigator.clipboard.writeText(copyBadge.dataset.md).then(function () {
        copyBadge.textContent = "copied";
        setTimeout(function () { copyBadge.textContent = "copy"; }, 1200);
      });
      return;
    }
    var tag = e.target.closest(".tag[data-topic]");
    if (tag) {
      e.preventDefault();
      e.stopPropagation();
      searchEl.value = tag.dataset.topic;
      state.query = tag.dataset.topic;
      render();
      return;
    }
    var row = e.target.closest(".row");
    if (row && rowsEl.contains(row)) {
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
