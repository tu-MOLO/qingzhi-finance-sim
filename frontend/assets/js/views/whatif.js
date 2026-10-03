/* 反事实与敏感性：把每个可争论的假设上下扰动，按影响幅度排成龙卷风图。
   页面上的每一条文字都来自配置目录，每一个取值都来自接口下发，代码中不写业务文案与业务取值。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;

  var state = { data: null, pick: null, busy: false, bound: false };

  function el(id) { return document.getElementById(id); }

  /* 当前看的是哪个目标：默认首要目标，切换后整块数值跟着换一套 */
  function goalsOf(data) {
    var list = (data && data.goals) || [];
    if (!list.length && data && data.goal) { list = [data.goal]; }
    return list.slice().sort(function (a, b) {
      return (Number(a.priority) || 0) - (Number(b.priority) || 0);
    });
  }

  function picked(data) {
    var list = goalsOf(data);
    if (!list.length) { return null; }
    var hit = list.filter(function (item) { return item.goalId === state.pick; })[0];
    return hit || list[0];
  }

  /* 某个参数在某个目标上的一组数。目标缺失时退回行顶层的主目标数值 */
  function bucketOf(row, goalId) {
    var bag = row.byGoal || {};
    return bag[goalId] || row;
  }

  /* ---------------------------------------------------------- 取值格式化 */

  /* 比率类参数的量级小于一，其余参数的量级不小于一，按量级选择格式化方式 */
  function isRate(value) {
    var n = Number(value);
    return isFinite(n) && n !== 0 && Math.abs(n) < 1;
  }

  function valueText(value) {
    var n = Number(value);
    if (value === null || value === undefined || !isFinite(n)) { return ""; }
    return isRate(value) ? Fmt.percent(n) + Fmt.units.percent : Fmt.decimal(n, 1);
  }

  /* 单位一律取接口下发的值，比率类参数也照常带上，不再因为格式化成百分数而丢掉单位 */
  function unitText(row) {
    return row.unit ? String(row.unit) : "";
  }

  function probabilityText(value) {
    return Fmt.percent(value) + Fmt.units.percent;
  }

  /* 影响幅度是两个达成概率之差，口径说明合并显示在数值旁；说明文案若带占位，填入不带百分号的数值 */
  function swingDefinition(value) {
    var bare = Fmt.percent(value);
    return Catalog.text("whatif.swing_def", { value: bare, swing: bare, delta: bare });
  }

  /* 一组「标签 + 起点 → 终点 + 单位」，两组并排时用标签区分哪组是参数、哪组是概率 */
  function rangeHtml(labelKey, from, to, unit, tone) {
    return '<span style="white-space:nowrap">' +
      '<span style="font-family:var(--sans);color:var(--ink-400)">' +
      Fmt.escapeHtml(Catalog.text(labelKey)) + "</span>　" +
      '<span style="color:' + tone + ';font-variant-numeric:tabular-nums">' +
      Fmt.escapeHtml(from) + " → " + Fmt.escapeHtml(to) +
      (unit ? "　" + Fmt.escapeHtml(unit) : "") + "</span></span>";
  }

  /* ---------------------------------------------------------- 龙卷风图 */

  /* 条形宽度按最大影响幅度归一，非零的至少留一点可见长度，零影响的画不出来 */
  function widthOf(row, maxSwing) {
    var swing = Number(row.swing) || 0;
    if (swing <= 0 || maxSwing <= 0) { return 0; }
    return Math.max(swing / maxSwing * 100, 2);
  }

  function rowHtml(row, maxSwing, lead, goalId) {
    var unit = unitText(row);
    var bag = bucketOf(row, goalId);
    var definition = swingDefinition(bag.swing);
    var mark = lead ? "var(--red-500)" : "var(--ink-100)";
    var ink = lead ? "var(--red-700)" : "var(--ink-700)";
    return '<div style="padding:9px 0 9px 12px;border-top:1px solid var(--ink-100);' +
      "border-left:3px solid " + mark + '"' +
      (lead ? ' title="' + Fmt.escapeHtml(Catalog.text("whatif.lead")) + '"' : "") + ">" +
      '<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">' +
      '<span style="font-size:13px;font-weight:' + (lead ? "500" : "400") + '">' +
      Fmt.escapeHtml(row.name || "") + "</span>" +
      '<span style="margin-left:auto;display:inline-flex;align-items:baseline;gap:8px;flex-wrap:wrap">' +
      '<span style="font-family:var(--mono);font-size:13.5px;color:' + ink +
      ';font-variant-numeric:tabular-nums">' +
      Fmt.escapeHtml(Catalog.text("whatif.swing")) + "　" +
      Fmt.escapeHtml(probabilityText(bag.swing)) + "</span>" +
      (definition ? '<span style="font-family:var(--sans);font-size:11px;color:var(--ink-400)">' +
        Fmt.escapeHtml(definition) + "</span>" : "") + "</span></div>" +
      '<div style="margin-top:6px;height:9px;background:var(--ink-50);border-radius:var(--r-sm);' +
      'overflow:hidden"><div style="height:100%;width:' + widthOf(bag, maxSwing).toFixed(1) +
      "%;background:" + (lead ? "var(--red-500)" : "var(--ink-300)") + '"></div></div>' +
      '<div style="margin-top:5px;font-size:11.5px;font-family:var(--mono);' +
      'display:flex;flex-wrap:wrap;gap:2px 16px">' +
      rangeHtml("whatif.param_range", valueText(row.low), valueText(row.high), unit, "var(--ink-500)") +
      rangeHtml("whatif.prob_range", probabilityText(bag.lowProbability),
        probabilityText(bag.highProbability), "", "var(--ink-700)") +
      "</div></div>";
  }

  /* 目标多于一个时给一排切换按钮，选定哪个就整块换成哪个目标的一组数 */
  function pickerHtml(data, goal) {
    var list = goalsOf(data);
    if (list.length < 2) { return ""; }
    return '<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;' +
      'padding-bottom:8px;font-size:12px;color:var(--ink-400)">' +
      Fmt.escapeHtml(Catalog.text("whatif.pick")) + "　" +
      list.map(function (item) {
        var on = goal && item.goalId === goal.goalId;
        return '<button type="button" data-goal="' + Fmt.escapeHtml(item.goalId) + '"' +
          ' style="font:inherit;cursor:pointer;border:1px solid ' +
          (on ? "var(--red-500)" : "var(--ink-100)") + ";background:" +
          (on ? "var(--red-50)" : "transparent") + ";color:" +
          (on ? "var(--red-700)" : "var(--ink-500)") +
          ';border-radius:999px;padding:2px 10px">' +
          Fmt.escapeHtml(item.name) + "</button>";
      }).join("") + "</div>";
  }

  function body(data) {
    var rows = (data && data.rows) || [];
    if (!rows.length) {
      return '<div class="empty">' + Fmt.escapeHtml(Catalog.text("whatif.empty")) + "</div>";
    }
    var goal = picked(data) || data.goal || {};
    var goalId = goal.goalId || (data.goal || {}).goalId;
    var maxSwing = Math.max.apply(null, rows.map(function (row) {
      return Number(bucketOf(row, goalId).swing) || 0;
    })) || 0;
    var head = pickerHtml(data, goal) +
      '<div style="font-size:12px;color:var(--ink-400);padding-bottom:6px">' +
      Fmt.escapeHtml(Catalog.text("whatif.base")) + "　" + Fmt.escapeHtml(goal.name || "") + "　" +
      Fmt.escapeHtml(probabilityText(goal.baseProbability)) +
      (data.pathsReused ? "　·　" + Fmt.escapeHtml(Catalog.text("whatif.reused")) : "") + "</div>" +
      (data.pathsReused
        ? '<div style="font-size:11.5px;color:var(--ink-400);padding:2px 0 0">' +
          Fmt.escapeHtml(Catalog.text("whatif.reused_note")) + "</div>"
        : "") +
      '<div style="font-size:12.5px;color:var(--ink-700);padding:2px 0 8px">' +
      Fmt.escapeHtml(Catalog.text("whatif.lead")) + "</div>" +
      '<div style="font-size:12px;color:var(--ink-500);padding-bottom:2px">' +
      Fmt.escapeHtml(Catalog.text("whatif.rank")) + "</div>";
    var disclaimer = (data && data.disclaimer) || {};
    var foot = (disclaimer.title || disclaimer.body)
      ? '<div class="notice" style="margin-top:14px"><b>' +
        Fmt.escapeHtml(disclaimer.title || "") + "　</b>" +
        Fmt.escapeHtml(disclaimer.body || "") + "</div>"
      : "";
    return head + rows.map(function (row, index) {
      return rowHtml(row, maxSwing, index === 0, goalId);
    }).join("") + foot;
  }

  /* 切换按钮是重绘出来的，事件挂在容器上，重绘后不需要重新绑定 */
  function bindPicker() {
    var box = el("whatif-body");
    box.addEventListener("click", function (event) {
      var node = event.target.closest ? event.target.closest("[data-goal]") : null;
      if (!node || !state.data) { return; }
      state.pick = node.getAttribute("data-goal");
      box.innerHTML = body(state.data);
    });
  }

  /* ---------------------------------------------------------- 触发 */

  function run() {
    if (state.busy) { return Promise.resolve(); }
    var button = el("run-whatif");
    var box = el("whatif-body");
    state.busy = true;
    button.disabled = true;
    box.innerHTML = '<div class="empty">' +
      Fmt.escapeHtml(Catalog.message("status.simulating")) + "</div>";
    return Api.post("/simulation/whatif", { profile: global.App.ProfileView.readProfile() })
      .then(function (data) {
        state.data = data;
        /* 换了一份数据，原先选中的目标可能已经不在里面，回到首要目标 */
        state.pick = (data.goal || {}).goalId || null;
        /* 容器空态时带着 empty 类（居中且灰），正式内容渲染前摘掉 */
        box.className = "";
        box.innerHTML = body(data);
      })
      .catch(function (error) {
        box.innerHTML = '<div class="empty">' +
          Fmt.escapeHtml(Catalog.text("whatif.fail")) + "</div>";
        global.App.Main.toast(error.message, "error");
      })
      .then(function () {
        state.busy = false;
        button.disabled = false;
      });
  }

  function init() {
    if (state.bound) { return; }
    el("run-whatif").addEventListener("click", function () { run(); });
    bindPicker();
    state.bound = true;
  }

  /* 启动脚本尚未接管本页签，这里自行挂上按钮，重复调用不会重复绑定 */
  document.addEventListener("DOMContentLoaded", function () { init(); });

  global.App = global.App || {};
  global.App.WhatifView = { init: init, run: run };
})(window);
