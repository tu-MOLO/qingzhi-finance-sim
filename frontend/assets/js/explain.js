/* 就地解释层。结论文案与专业词不再需要跳转页签，点开即在原地展开三层。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;

  var state = { busy: false, terms: [] };

  function el(id) { return document.getElementById(id); }

  function openPop() {
    el("explain-pop").hidden = false;
    document.body.classList.add("pop-open");
  }

  function closePop() {
    el("explain-pop").hidden = true;
    document.body.classList.remove("pop-open");
  }

  function fill(html) {
    el("ep-body").innerHTML = html;
  }

  function request(term, title) {
    if (state.busy) { return; }
    state.busy = true;
    el("ep-term").textContent = title || term;
    el("ep-foot").textContent = "";
    fill('<div class="empty">' + Fmt.escapeHtml(Catalog.text("explain.loading")) + "</div>");
    openPop();

    return Api.post("/terms/explain", { term: term, snapshot: global.App.Main.snapshot() })
      .then(function (data) { render(data); })
      .catch(function (error) {
        /* 未收录不等于出错：给一句交代，再把已收录的词条摆出来供直接点开 */
        if (error.status === 404 || error.code === "E-02-01") {
          fill(missingHtml(term, title));
          return;
        }
        fill('<div class="empty">' + Fmt.escapeHtml(error.message || Catalog.text("explain.fail")) +
          "</div>");
      })
      .then(function () { state.busy = false; });
  }

  /* 未收录时的兜底：说明这个说法还没进库，并给出已收录词条的入口 */
  function missingHtml(term, title) {
    var picks = state.terms.slice(0, 8);
    var tags = picks.map(function (item) {
      return '<button class="ex-link" data-explain="' +
        Fmt.escapeHtml(item.term_code || item.code) + '">' +
        Fmt.escapeHtml(item.name) + "</button>";
    }).join("");
    return '<div class="ep-missing">' +
      Fmt.escapeHtml(Catalog.text("explain.missing", { term: title || term })) + "</div>" +
      (tags
        ? '<div class="ep-missing-note">' +
          Fmt.escapeHtml(Catalog.text("explain.missing_note")) + "</div>" +
          '<div class="ep-tags"><span class="ep-tags-k">' +
          Fmt.escapeHtml(Catalog.text("explain.suggest")) + "</span>" + tags + "</div>"
        : "");
  }

  function render(data) {
    var linked = data.linkedGoalName
      ? "　·　" + Catalog.text("term.linked_goal") + "：" + data.linkedGoalName
      : "　·　" + Catalog.text("term.no_goal");
    /* 术语第三层以首要目标落数，其余目标一并纳入，这里交代清楚不是一个人在算 */
    var scope = data.linkedGoalIds || [];
    if (scope.length > 1) {
      linked += "　·　" + Catalog.text("term.other_goals", { n: Fmt.number(scope.length - 1) });
    }
    var sourceLine = (data.sources || []).map(function (doc) {
      var kind = doc.docTypeName || Catalog.nameOf("corpus_type", doc.docType) || doc.docType;
      return kind + "：" + doc.title;
    }).join("；") || "";

    var sourceBlock = sourceLine
      ? '<div class="src-line">' + Fmt.escapeHtml(Catalog.text("term.source_prefix")) +
        "：" + Fmt.escapeHtml(sourceLine) + "</div>"
      : "";

    fill([
      '<div class="layer l1"><div class="ln">1</div><div><h4>' +
        Fmt.escapeHtml(Catalog.text("term.layer1")) + "</h4><p>" +
        Fmt.escapeHtml(data.layer1) + "</p></div></div>",
      '<div class="layer l2"><div class="ln">2</div><div><h4>' +
        Fmt.escapeHtml(Catalog.text("term.layer2")) + "</h4><p>" +
        Fmt.escapeHtml(data.layer2) + "</p></div></div>",
      '<div class="layer l3"><div class="ln">3</div><div><h4>' +
        Fmt.escapeHtml(Catalog.text("term.layer3")) + Fmt.escapeHtml(linked) + "</h4><p>" +
        Fmt.escapeHtml(data.layer3) + "</p>" + sourceBlock + "</div></div>",
      '<div class="notice"><b>' + Fmt.escapeHtml(Catalog.messageTitle("disclaimer.term")) +
        "　</b>" + Fmt.escapeHtml(data.disclaimer) + "</div>"
    ].join(""));

    var agent = data.agent || {};
    /* 后端在术语接口里把 provider 改名为 generatedBy，这里读错字段会永远显示本地规则 */
    var provider = data.generatedBy || data.provider;
    if (agent.code) {
      el("ep-foot").textContent = [
        Catalog.text("explain.by_agent", { agent: agent.name }),
        Catalog.text(provider === "openai_compat"
          ? "term.agent.provider.model" : "term.agent.provider.rule"),
        data.degraded ? Catalog.text("explain.degraded") : "",
        Catalog.text("explain.elapsed", { seconds: secondsOf(data.elapsedMs) })
      ].filter(Boolean).join("　·　");
    }
    renderTrace(data.steps || []);
  }

  /* 毫秒换成带一位小数的秒；Sub-0.1 秒的取值单独处理，避免出现「0.0 秒」 */
  function secondsOf(ms) {
    var value = Number(ms) || 0;
    /* 本地规则常在几毫秒内返回，显示「0.0 秒」既不好看也不像话 */
    return value < 100 ? "<0.1" : (value / 1000).toFixed(1);  }

  /* 智能体的三段式执行轨迹：前置工具、生成、合规校验，让用户看清这段话是怎么来的 */
  function renderTrace(steps) {
    var box = el("ep-trace");
    if (!box) { return; }
    if (!steps.length) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    box.innerHTML =
      '<div class="trace-head">' + Fmt.escapeHtml(Catalog.text("explain.trace")) + "</div>" +
      '<ul class="trace-list">' + steps.map(function (step) {
        return '<li><span class="ts">' + Fmt.escapeHtml(step.title || step.ref || "") + "</span>" +
          '<span class="tv">' + Fmt.escapeHtml(step.detail || step.status || "") +
          "</span></li>";
      }).join("") + "</ul>";
  }

  /* 事件委托：任何带 data-explain 的元素都可触发，渲染后无需重新绑定 */
  function bind() {
    document.addEventListener("click", function (event) {
      var node = event.target.closest ? event.target.closest("[data-explain]") : null;
      if (!node) { return; }
      event.preventDefault();
      request(node.getAttribute("data-explain"), node.textContent.trim());
    });

    el("ep-close").addEventListener("click", closePop);
    el("explain-pop").addEventListener("click", function (event) {
      if (event.target === el("explain-pop")) { closePop(); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !el("explain-pop").hidden) { closePop(); }
    });
  }

  /* 术语表取一次即可，供自动标记使用 */
  function loadTerms() {
    return Api.get("/terms").then(function (data) {
      state.terms = (data.terms || []).filter(function (item) { return item.enabled; });
      return state.terms;
    }).catch(function () { state.terms = []; return state.terms; });
  }

  /* 把一段文案里的词标记成可解释。命中术语名或别名时挂上标记。 */
  function mark(html, terms) {
    var list = terms || state.terms;
    if (!list || !list.length) { return html; }
    var pairs = [];
    list.forEach(function (item) {
      pairs.push({ name: item.name, code: item.term_code || item.code });
      (item.aliases || []).forEach(function (alias) {
        pairs.push({ name: alias, code: item.term_code || item.code });
      });
    });
    pairs.sort(function (a, b) { return b.name.length - a.name.length; });

    var escaped = Fmt.escapeHtml(html);
    pairs.forEach(function (pair) {
      if (!pair.name) { return; }
      var needle = Fmt.escapeHtml(pair.name);
      if (escaped.indexOf(needle) === -1) { return; }
      escaped = escaped.split(needle).join(
        '<span class="ex" data-explain="' + Fmt.escapeHtml(pair.code) + '">' + needle + "</span>");
    });
    return escaped;
  }

  global.App = global.App || {};
  global.App.Explain = {
    bind: bind,
    open: request,
    mark: mark,
    loadTerms: loadTerms,
    close: closePop
  };
})(window);
