/* 启动与页面协作。负责加载配置目录、切换页签、触发推演与提示。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;
  var Sandbox = global.App.SandboxView;
  var Profile = global.App.ProfileView;
  var Term = global.App.TermView;
  var Settings = global.App.SettingsView;

  var state = { result: null, busy: false, toastTimer: null };

  /* 品牌标记：船与海浪。图形取当前文字色反白，尺寸由样式表统一控制；
     桅杆、船体与两道浪线各占一层，缩到图标大小时外轮廓仍然清楚。 */
  var BRAND_MARK =
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M12 4.4 17.4 14H12V4.4Z" fill="currentColor"/>' +
    '<path d="M11.9 7.6 8.2 14h3.7V7.6Z" fill="currentColor" opacity=".78"/>' +
    '<path d="M12 3.2v11.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
    '<path d="M6 14.6h12l-2.2 3.1H8.2z" fill="currentColor"/>' +
    '<path d="M2.6 19.3q2.4-1.7 4.8 0t4.8 0t4.8 0t4.8 0" fill="none" stroke="currentColor"' +
    ' stroke-width="1.5" stroke-linecap="round"/>' +
    '<path d="M2.6 21.8q2.4-1.5 4.8 0t4.8 0t4.8 0t4.8 0" fill="none" stroke="currentColor"' +
    ' stroke-width="1.4" stroke-linecap="round" opacity=".65"/>' +
    "</svg>";

  function el(id) { return document.getElementById(id); }

  /* 顶栏那个入口恒定可点：不论配没配，点进去都是设置页。
     配好了它是状态说明，没配它是等着去做的事，两者都指向同一处。 */
  function openSettings() {
    activate("settings");
    Settings.load().catch(function () { /* 读取失败时保留上一次的表单内容 */ });
  }

  function toast(message, tone) {
    if (!message) { return; }
    var node = el("toast");
    node.textContent = message;
    node.className = "toast on" + (tone ? " " + tone : "");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () { node.className = "toast"; }, 4200);
  }

  function activate(name) {
    document.querySelectorAll(".tab").forEach(function (tab) {
      tab.setAttribute("aria-selected", String(tab.getAttribute("data-tab") === name));
    });
    document.querySelectorAll(".panel").forEach(function (panel) {
      panel.classList.toggle("on", panel.id === "panel-" + name);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* 定位条：先说清对谁、做什么、不做什么，再给结论 */
  function renderPosition() {
    el("pos-for").textContent = Catalog.text("position.v.for_who");
    el("pos-what").textContent = Catalog.text("position.v.what");
    el("pos-not").textContent = Catalog.text("position.v.not");
  }

  /* 推演五步：把黑箱摊开，每步一句白话加一句输入说明。
     键名逐个列出，便于静态检查核对文案是否都被引用。 */
  var HOWTO_KEYS = [
    ["howto.step1.t", "howto.step1.d"],
    ["howto.step2.t", "howto.step2.d"],
    ["howto.step3.t", "howto.step3.d"],
    ["howto.step4.t", "howto.step4.d"],
    ["howto.step5.t", "howto.step5.d"]
  ];

  function renderHowto() {
    el("howto-steps").innerHTML = HOWTO_KEYS.map(function (pair, index) {
      return '<li><div class="hs-n">' + String(index + 1) + "</div><div>" +
        '<div class="hs-t">' + Fmt.escapeHtml(Catalog.text(pair[0])) + "</div>" +
        '<div class="hs-d">' + Fmt.escapeHtml(Catalog.text(pair[1])) + "</div>" +
        "</div></li>";
    }).join("");
  }

  function bindHowto() {
    var button = el("howto-toggle");
    button.addEventListener("click", function () {
      var box = el("howto-steps");
      var open = box.hidden;
      box.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      button.classList.toggle("on", open);
    });
  }

  function snapshot() {
    return state.result ? state.result.snapshot : null;
  }

  function hasResult() {
    return state.result !== null;
  }

  /* 推演。silent 表示不跳转页签，keepChoice 表示保留方案的选择状态 */
  function run(options) {
    var config = options || {};
    if (state.busy) { return Promise.resolve(); }
    state.busy = true;
    el("run").disabled = true;
    if (!config.silent) { el("run-hint").classList.add("on"); }

    return Api.post("/simulation/run", { profile: Profile.readProfile() })
      .then(function (result) {
        state.result = result;
        if (!config.keepChoice) { Sandbox.resetChoice(); }
        Sandbox.render(result);
        if (!config.silent) { activate("sandbox"); }
        /* 结论落地后紧接着让智能体把它讲一遍，解读与结论同屏出现 */
        return Sandbox.runInsight({ silent: true });
      })
      .catch(function (error) {
        toast(error.message, "error");
      })
      .then(function () {
        state.busy = false;
        el("run").disabled = false;
        el("run-hint").classList.remove("on");
        el("recalc").classList.remove("on");
      });
  }

  function dismissBoot() {
    var node = el("boot");
    if (!node) { return; }
    node.classList.add("off");
    setTimeout(function () { node.hidden = true; }, 300);
  }

  function init() {
    // 下拉框先接管外观：选项此时可能还没填充，结构变化由模块内部监听补齐
    if (global.App.Select) { global.App.Select.mount(); }
    document.querySelectorAll(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () { activate(tab.getAttribute("data-tab")); });
    });
    el("lookup").addEventListener("click", function () { Term.lookup(); });
    el("term-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter") { Term.lookup(); }
    });
    el("pos-edit").addEventListener("click", function () { activate("profile"); });
    el("agent-entry").addEventListener("click", openSettings);
    bindHowto();
    global.App.Explain.bind();

    return Catalog.load()
      .then(function () {
        Catalog.applyStaticTexts(document);
        el("brand-name").textContent = Catalog.text("app.name");
        el("brand-mark").innerHTML = BRAND_MARK;
        el("meta-version").textContent = Catalog.text("app.badge.ready");
        Settings.init();
        el("run-hint-text").textContent = Catalog.message("status.simulating");
        el("recalc-text").textContent = Catalog.message("status.recalculating");
        renderPosition();
        renderHowto();
        return Promise.all([Profile.init(), Term.init(), global.App.Explain.loadTerms()]);
      })
      .then(function () {
        Sandbox.init();
        if (global.App.AssumeView) { global.App.AssumeView.init(); }
        // 先跑完一次推演再揭幕，首屏落在结论上而不是空表单
        return run({ silent: true });
      })
      .then(function () {
        if (global.App.AssumeView) { return global.App.AssumeView.render(); }
        return null;
      })
      .then(function () { return Term.previewDefault(); })
      .then(function () { dismissBoot(); })
      .catch(function (error) {
        dismissBoot();
        toast(error.message || Catalog.message("status.data_missing"), "error");
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    // 默认进入结论页：系统先展示自己能做什么，录入退为由按钮触发
    init().then(function () { activate("sandbox"); });
  });

  global.App = global.App || {};
  global.App.Main = {
    toast: toast,
    run: run,
    silentRun: function () { return run({ silent: true }); },
    hasResult: hasResult,
    snapshot: snapshot
  };
})(window);
