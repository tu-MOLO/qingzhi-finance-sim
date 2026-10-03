/* 推演假设面板：逐个参数交代取值、性质、来源与三档区间，并允许改写可编辑参数。
   面板上的每一条文字都来自配置目录，取值一律由接口下发，代码中不写业务文案与业务取值。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;

  var state = { rows: [], sources: [], byId: {}, byName: {}, busy: false };

  /* 三档性质。徽标与左侧竖线用同一组取值，卡内与图例口径一致 */
  var TIERS = {
    measured: { cls: "m", mark: "var(--ink-400)" },
    assumed: { cls: "a", mark: "var(--red-500)" },
    conventional: { cls: "c", mark: "var(--ink-300)" }
  };

  function el(id) { return document.getElementById(id); }

  /* ---------------------------------------------------------- 取值与单位 */

  /* 比率类参数的量级都小于一，其余参数的量级不小于一，按量级选择格式化方式 */
  function isRate(row) {
    var n = Number(row.value_base);
    return isFinite(n) && n !== 0 && Math.abs(n) < 1;
  }

  function valueText(row, value) {
    var n = Number(value);
    if (value === null || value === undefined || !isFinite(n)) { return ""; }
    if (isRate(row)) { return Fmt.percent(n) + Fmt.units.percent; }
    return n % 1 === 0 ? Fmt.number(n) : Fmt.decimal(n, 1);
  }

  function unitText(row) {
    if (isRate(row)) { return ""; }
    return row.unit ? String(row.unit) : "";
  }

  /* ---------------------------------------------------------- 性质与来源 */

  /* 性质代码决定三档着色；性质色调决定是否需要标出不可靠，取不到色调时按性质代码判断 */
  function tierOf(row) {
    var code = row.property;
    return TIERS[code] ? TIERS[code] : TIERS.assumed;
  }

  function weakOf(row) {
    return (row.property_tone || row.property) !== "measured";
  }

  function indexSources() {
    state.byId = {};
    state.byName = {};
    state.sources.forEach(function (item) {
      if (item.id !== null && item.id !== undefined) { state.byId[String(item.id)] = item; }
      if (item.name) { state.byName[String(item.name)] = item; }
    });
  }

  /* 参数表里的 source 既可能存来源编号也可能存来源名称，两种都对得上才算命中 */
  function findSource(row) {
    var raw = row.source === null || row.source === undefined ? "" : String(row.source);
    if (!raw) { return null; }
    return state.byId[raw] || state.byName[raw] || null;
  }

  function sourceText(row) {
    var matched = findSource(row);
    if (matched) { return String(matched.name); }
    if (row.source) { return String(row.source); }
    return Catalog.text("assume.source_missing");
  }

  function periodText(row) {
    var matched = findSource(row);
    var period = (matched && matched.period) || row.period;
    return period ? String(period) : "";
  }

  /* ---------------------------------------------------------- 卡片 */

  function badge(row) {
    var tier = tierOf(row);
    var label = row.property_name || row.property || "";
    return '<span class="badge ' + tier.cls + '" title="' +
      Fmt.escapeHtml(Catalog.text("assume.property")) + "：" + Fmt.escapeHtml(label) + '">' +
      '<i class="swatch p' + tier.cls + '"></i>' + Fmt.escapeHtml(label) + "</span>";
  }

  /* 说明区一行一条：有标签的占标签列与取值列，无标签的直接从取值列起排，
     纵向与其他行的取值左边界对齐 */
  function metaRow(label, value) {
    if (!value) { return ""; }
    if (!label) {
      return '<span class="am-free">' + Fmt.escapeHtml(value) + "</span>";
    }
    return '<span class="am-k">' + Fmt.escapeHtml(label) + "</span>" +
      '<span class="am-v">' + Fmt.escapeHtml(value) + "</span>";
  }

  function rangeText(row) {
    var low = row.value_low === null || row.value_low === undefined ? null : Number(row.value_low);
    var high = row.value_high === null || row.value_high === undefined ? null : Number(row.value_high);
    if (low === null || high === null) { return ""; }
    return valueText(row, low) + " ~ " + valueText(row, high);
  }

  /* 编辑框里填的是原始取值，右侧标出单位；比率类另外交代口径，避免误填成百分数 */
  function editor(row) {
    var unit = row.unit ? String(row.unit) : "";
    var hint = isRate(row) ? Catalog.text("assume.rate_hint") : "";
    return '<div class="aa" data-editor="1" hidden>' +
      '<input type="number" step="any" value="' + Fmt.escapeHtml(row.value_base) + '">' +
      (unit ? '<span style="font-size:11.5px;color:var(--ink-400)">' +
        Fmt.escapeHtml(unit) + "</span>" : "") +
      '<button class="btn sm" data-act="save" data-key="' + Fmt.escapeHtml(row.key) + '">' +
      Fmt.escapeHtml(Catalog.text("assume.save")) + "</button>" +
      (hint ? '<div class="hint">' + Fmt.escapeHtml(hint) + "</div>" : "") + "</div>";
  }

  function card(row) {
    var tier = tierOf(row);
    var unit = unitText(row);
    var inner =
      '<span class="ak">' + Fmt.escapeHtml(row.name || "") + "</span>" +
      '<span class="ab">' + badge(row) + "</span>" +
      '<span class="av">' + Fmt.escapeHtml(valueText(row, row.value_base)) +
      (unit ? "<small>" + Fmt.escapeHtml(unit) + "</small>" : "") + "</span>" +
      '<div class="am">' +
      metaRow("", sourceText(row)) +
      metaRow(Catalog.text("assume.period"), periodText(row)) +
      metaRow(Catalog.text("assume.range"), rangeText(row)) +
      metaRow("", row.note ? String(row.note) : "") +
      "</div>";

    var editable = editableOf(row);
    var actions = editable
      ? editor(row) +
        '<div class="aa"><button class="btn sm" data-act="edit">' +
        Fmt.escapeHtml(Catalog.text("assume.edit")) + "</button></div>"
      : "";

    /* 竖线只在取值不可靠时才着色并转为虚线，实测值保持中性 */
    return '<div class="assume-item' + (weakOf(row) ? " weak" : "") +
      '" style="--tier:' + (weakOf(row) ? tier.mark : "var(--ink-100)") + '">' +
      inner + actions + "</div>";
  }

  /* 参数表只有 key 与数值都齐全时才能回写，可编辑标记一旦下发就以其为准 */
  function editableOf(row) {
    if (row.editable === false || Number(row.editable) === 0) { return false; }
    return Boolean(row.key) && isFinite(Number(row.value_base));
  }

  /* ---------------------------------------------------------- 渲染 */

  function body() {
    if (!state.rows.length) {
      return '<div class="empty">' + Fmt.escapeHtml(Catalog.text("assume.empty")) + "</div>";
    }
    var head = '<div class="assume-count">' +
      Fmt.escapeHtml(Catalog.text("assume.count", { n: state.rows.length })) + "</div>";
    return head + state.rows.map(card).join("");
  }

  function render() {
    var box = el("assume-list");
    return Api.get("/catalog/parameters").then(function (data) {
      state.rows = (data && data.rows) || [];
      state.sources = (data && data.sources) || [];
      indexSources();
      box.innerHTML = body();
      return state.rows;
    }).catch(function (error) {
      state.rows = [];
      box.innerHTML = '<div class="empty">' +
        Fmt.escapeHtml(Catalog.text("assume.empty")) + "</div>";
      global.App.Main.toast(error.message, "error");
    });
  }

  /* ---------------------------------------------------------- 改写 */

  function itemOf(node) {
    return node.closest ? node.closest(".assume-item") : null;
  }

  function toggleEditor(button) {
    var item = itemOf(button);
    if (!item) { return; }
    var box = item.querySelector("[data-editor]");
    if (!box) { return; }
    box.hidden = !box.hidden;
    if (!box.hidden) {
      var input = box.querySelector("input");
      if (input) { input.focus(); input.select(); }
    }
  }

  function save(button) {
    var item = itemOf(button);
    if (state.busy || !item) { return; }
    var input = item.querySelector("input");
    var key = button.getAttribute("data-key");
    var value = Number(input ? input.value : "");
    if (!key || !isFinite(value)) { return; }

    state.busy = true;
    button.disabled = true;
    Api.put("/catalog/parameters", { key: key, value_base: value })
      .then(function () {
        global.App.Main.toast(Catalog.text("assume.saved"));
        return global.App.Main.run({ silent: true });
      })
      .then(render)
      .catch(function (error) {
        global.App.Main.toast(error.message, "error");
      })
      .then(function () {
        state.busy = false;
        button.disabled = false;
      });
  }

  function init() {
    el("assume-list").addEventListener("click", function (event) {
      var button = event.target && event.target.closest ? event.target.closest("[data-act]") : null;
      if (!button) { return; }
      if (button.getAttribute("data-act") === "edit") { toggleEditor(button); }
      else { save(button); }
    });
  }

  global.App = global.App || {};
  global.App.AssumeView = { init: init, render: render };
  /* 参数取值的口径只有一处：其他面板复用这里的判定与格式化，避免同一参数两种写法 */
  global.App.ParamValue = { isRate: isRate, valueText: valueText, unitText: unitText };
})(window);
