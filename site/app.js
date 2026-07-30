(function () {
  "use strict";

  var state = { projects: [], query: "", sort: "stars", open: null, dataset: null };

  var rowsEl = document.getElementById("rows");
  var emptyEl = document.getElementById("empty");
  var searchEl = document.getElementById("search");
  var countEl = document.getElementById("count-all");
  var refreshedEl = document.getElementById("refreshed");
  var lineageEl = document.getElementById("lineage");
  var filterNoteEl = document.getElementById("filter-note");

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

  function datasetsOf(p) {
    return (p.inputs_list || [])
      .map(function (i) { return i.dataset; })
      .filter(Boolean);
  }

  function displayName(p) {
    return p.astra_name || (p.full_name || "").split("/")[1] || p.full_name;
  }

  function visibleProjects() {
    var q = state.query.trim().toLowerCase();
    var list = state.projects.filter(function (p) {
      if (state.dataset && datasetsOf(p).indexOf(state.dataset) === -1) return false;
      if (!q) return true;
      var hay = [p.full_name, p.astra_name, p.description]
        .concat(allTags(p))
        .concat(datasetsOf(p))
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

  function badgeMarkdown(p) {
    var base = new URL(".", location.href).href;
    var img = base + "badges/" + p.full_name.replace("/", "--") + ".svg";
    return "[![ASTRA verified](" + img + ")](" + base + ")";
  }

  function sameDataAnalyses(p) {
    var mine = datasetsOf(p);
    if (!mine.length) return [];
    return state.projects.filter(function (o) {
      if (o.full_name === p.full_name) return false;
      return datasetsOf(o).some(function (d) { return mine.indexOf(d) !== -1; });
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

    var datasets = (p.inputs_list || [])
      .filter(function (i) { return i.dataset; })
      .map(function (i) {
        return '<button class="tag dataset-tag" data-dataset="' + escapeHtml(i.dataset) + '" title="' + escapeHtml(i.label) + '">' + escapeHtml(i.dataset) + "</button>";
      })
      .join("");
    if (datasets) {
      html += '<div class="detail-section"><span class="detail-label">Input data</span><div class="tag-list">' + datasets + "</div></div>";
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

    html +=
      '<div class="detail-section"><span class="detail-label">Verification badge</span>' +
      '<div class="badge-embed"><img src="badges/' + escapeHtml(p.full_name.replace("/", "--")) + '.svg" alt="ASTRA verified" onerror="this.closest(\'.detail-section\').style.display=\'none\'">' +
      '<code>' + escapeHtml(badgeMarkdown(p)) + "</code>" +
      '<button class="copy-badge" data-md="' + escapeHtml(badgeMarkdown(p)) + '">copy</button></div></div>';

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
    if (filterNoteEl) {
      filterNoteEl.innerHTML = state.dataset
        ? 'Showing analyses of <strong>' + escapeHtml(state.dataset) + '</strong> <button class="clear-filter" id="clear-filter">clear</button>'
        : "";
    }
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
          '<span class="row-title"><h2 class="row-name">' + escapeHtml(displayName(p)) + '</h2><span class="row-repo">' + escapeHtml(p.full_name) + "</span></span>" +
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
    renderLineage();
  }

  function renderLineage() {
    if (!lineageEl) return;
    var map = {};
    state.projects.forEach(function (p) {
      datasetsOf(p).forEach(function (d) {
        (map[d] = map[d] || []).push(p);
      });
    });
    var keys = Object.keys(map).sort(function (a, b) {
      return map[b].length - map[a].length || a.localeCompare(b);
    });
    if (!keys.length) {
      lineageEl.innerHTML = '<p class="lineage-empty">No declared input datasets yet.</p>';
      return;
    }
    lineageEl.innerHTML = keys
      .map(function (d) {
        var uses = map[d]
          .map(function (p) {
            return '<button class="link-btn" data-open="' + escapeHtml(p.full_name) + '">' + escapeHtml(displayName(p)) + "</button>";
          })
          .join('<span class="sep">·</span>');
        return (
          '<div class="dataset-row">' +
          '<div class="dataset-head"><button class="dataset-name" data-dataset="' + escapeHtml(d) + '">' + escapeHtml(d) + "</button>" +
          '<span class="dataset-count">' + map[d].length + (map[d].length === 1 ? " analysis" : " analyses") + "</span></div>" +
          '<div class="dataset-uses">' + uses + "</div>" +
          "</div>"
        );
      })
      .join("");
  }

  function openAnalysis(fullName) {
    state.open = fullName;
    state.dataset = null;
    state.query = "";
    searchEl.value = "";
    render();
    var el = document.querySelector('[data-entry="' + CSS.escape(fullName) + '"]');
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
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

  document.addEventListener("click", function (e) {
    var clear = e.target.closest("#clear-filter");
    if (clear) {
      state.dataset = null;
      render();
      return;
    }
    var openBtn = e.target.closest(".link-btn");
    if (openBtn) {
      openAnalysis(openBtn.dataset.open);
      return;
    }
    var ds = e.target.closest("[data-dataset]");
    if (ds) {
      e.preventDefault();
      e.stopPropagation();
      state.dataset = ds.dataset.dataset;
      state.open = null;
      render();
      document.getElementById("index").scrollIntoView({ behavior: "smooth" });
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
    var tag = e.target.closest(".tag");
    if (tag && tag.dataset.topic) {
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

  fetch("projects.json", { cache: "no-cache" })
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function () { init({ projects: [] }); });
})();
