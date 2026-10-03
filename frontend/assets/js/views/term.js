/* 术语拆解页：三层解释与免责提示。文案与语料来源均来自接口。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;

  var state = { terms: [] };

  function el(id) { return document.getElementById(id); }

  /* 毫秒换成带一位小数的秒，取值极小时不显示成 0.0 */
  function secondsOf(ms) {
    var value = Number(ms) || 0;
    return value > 0 && value < 100 ? "<0.1" : (value / 1000).toFixed(1);
  }

  function init() {
    return Api.get("/terms").then(function (data) {
      var terms = (data.terms || []).filter(function (item) { return item.enabled; });
      state.terms = terms;
      el("term-list").innerHTML = terms.map(function (item) {
        return '<option value="' + Fmt.escapeHtml(item.name) + '"></option>';
      }).join("");
      el("term-hint").textContent =
        (Catalog.state.uiTexts["section.term.note"] || "") + "　" +
        terms.map(function (item) { return item.name; }).join("、");
      el("term-input").placeholder = Catalog.text("term.placeholder");
      return terms;
    }).catch(function () { return []; });
  }

  function lookup() {
    var term = el("term-input").value.trim();
    if (!term) {
      global.App.Main.toast(Catalog.message("validation.term_required"));
      return Promise.resolve();
    }
    var button = el("lookup");
    var snapshot = global.App.Main.snapshot();
    button.disabled = true;
    el("agent-sec").hidden = false;
    el("agent-meta").innerHTML = '<span>' +
      Fmt.escapeHtml(Catalog.message("status.agent_running")) + "</span>";
    el("agent-steps").innerHTML = "";
    return Api.post("/terms/explain", { term: term, snapshot: snapshot })
      .then(render)
      .catch(function (error) {
        /* 未收录时不再只弹一句提示，而是原地给出交代与已收录词条的入口 */
        if (error.status === 404 || error.code === "E-02-01") {
          renderMissing(term);
          return;
        }
        global.App.Main.toast(error.message, error.status >= 500 ? "error" : "");
      })
      .then(function () { button.disabled = false; });
  }

  function renderMissing(term) {
    var picks = state.terms.slice(0, 8);
    var tags = picks.map(function (item) {
      return '<button class="ex-link" data-explain="' +
        Fmt.escapeHtml(item.term_code || item.code) + '">' +
        Fmt.escapeHtml(item.name) + "</button>";
    }).join("");
    el("agent-sec").hidden = true;
    el("agent-steps").innerHTML = "";
    el("layers").innerHTML = '<div class="card"><h4>' +
      Fmt.escapeHtml(Catalog.text("explain.missing", { term: term })) + "</h4><p>" +
      Fmt.escapeHtml(Catalog.text("explain.missing_note")) + "</p>" +
      (tags ? '<div class="ep-tags"><span class="ep-tags-k">' +
        Fmt.escapeHtml(Catalog.text("explain.suggest")) + "</span>" + tags + "</div>" : "") +
      "</div>";
  }

  function render(data) {
    var linked = data.linkedGoalName
      ? "　·　" + Catalog.text("term.linked_goal") + "：" + data.linkedGoalName
      : "　·　" + Catalog.text("term.no_goal");
    var sourceLine = (data.sources || []).map(function (doc) {
      var kind = doc.docTypeName || Catalog.nameOf("corpus_type", doc.docType) || doc.docType;
      return kind + "：" + doc.title;
    }).join("；") || "";

    var sourceBlock = sourceLine
      ? '<div class="src-line">' + Fmt.escapeHtml(Catalog.text("term.source_prefix")) +
        "：" + Fmt.escapeHtml(sourceLine) + "</div>"
      : '<div class="src-line">' + Fmt.escapeHtml(Catalog.text("term.agent.no_source")) + "</div>";

    el("layers").innerHTML = [
      '<div class="layer l1"><div class="ln">1</div><div><h4>' +
        Fmt.escapeHtml(Catalog.text("term.layer1")) + "</h4><p>" +
        Fmt.escapeHtml(data.layer1) + "</p></div></div>",
      '<div class="layer l2"><div class="ln">2</div><div><h4>' +
        Fmt.escapeHtml(Catalog.text("term.layer2")) + "</h4><p>" +
        Fmt.escapeHtml(data.layer2) + "</p></div></div>",
      '<div class="layer l3"><div class="ln">3</div><div><h4>' +
        Fmt.escapeHtml(Catalog.text("term.layer3")) + Fmt.escapeHtml(linked) + "</h4><p>" +
        Fmt.escapeHtml(data.layer3) + "</p>" +
        sourceBlock + "</div></div>",
      '<div class="notice"><b>' + Fmt.escapeHtml(Catalog.messageTitle("disclaimer.term")) +
        "　</b>" + Fmt.escapeHtml(data.disclaimer) + "</div>"
    ].join("");

    renderAgent(data);
  }

  /* 生成过程：用了哪个智能体、走的哪条生成路径、执行了哪些步骤 */
  function renderAgent(data) {
    var agent = data.agent || {};
    el("agent-sec").hidden = !agent.code;
    if (!agent.code) { return; }

    var isModel = (data.generatedBy || data.provider) === "openai_compat";
    // 本地规则模式下把「不依赖网络」这件事直接说明，避免使用者误以为需要联网
    var hint = isModel ? "" : Catalog.message("status.agent_rule_mode");
    var badge = '<span class="agent-badge' + (isModel ? "" : " rule") + '"' +
      (hint ? ' title="' + Fmt.escapeHtml(hint) + '"' : "") + ">" +
      Fmt.escapeHtml(Catalog.text("term.agent.provider")) + "　" +
      Fmt.escapeHtml(Catalog.text(isModel ? "term.agent.provider.model" : "term.agent.provider.rule")) +
      "</span>";
    var badges = [badge];
    if (data.degraded) {
      badges.push('<span class="agent-badge degraded">' +
        Fmt.escapeHtml(Catalog.message("status.agent_degraded")) + "</span>");
    }
    badges.push("<span>" + Fmt.escapeHtml(Catalog.text("explain.elapsed",
      { seconds: secondsOf(data.elapsedMs) })) + "</span>");

    el("agent-meta").innerHTML =
      "<b>" + Fmt.escapeHtml(agent.name || "") + "</b>" + badges.join("");
    el("agent-note").textContent = agent.description || "";

    var steps = data.steps || [];
    if (!steps.length) {
      el("agent-steps").innerHTML =
        '<div class="empty">' + Fmt.escapeHtml(Catalog.text("term.agent.trace_off")) + "</div>";
      return;
    }
    el("agent-steps").innerHTML =
      '<div class="agent-sub">' + Fmt.escapeHtml(Catalog.text("term.agent.steps")) + "</div>" +
      steps.map(function (step) {
        return '<div class="step ' + Fmt.escapeHtml(step.status || "") + '">' +
        '<div class="sn">' + Fmt.escapeHtml(String(step.index || "")) + "</div>" +
        '<div><div class="st">' + Fmt.escapeHtml(step.title || "") + "</div>" +
        '<div class="sd">' + Fmt.escapeHtml(step.detail || "") + "</div></div>" +
        '<div class="sm">' + Number(step.durationMs || 0) + " ms</div></div>";
    }).join("");
  }

  /* 首次进入时给一条示例解释，便于直接看到三层结构 */
  function previewDefault() {
    var first = el("term-list").querySelector("option");
    if (!first) { return Promise.resolve(null); }
    el("term-input").value = first.value;
    return Api.post("/terms/explain", { term: first.value, snapshot: null })
      .then(render)
      .catch(function () { return null; });
  }

  global.App = global.App || {};
  global.App.TermView = {
    init: init,
    lookup: lookup,
    previewDefault: previewDefault
  };
})(window);
