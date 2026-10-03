/* 数值与金额格式化。单位文案来自接口下发的界面文案，代码中不写单位。 */
(function (global) {
  "use strict";

  var UNITS = { yuan: "", wan: "", month: "", perMonth: "", percent: "", path: "" };

  function configure(uiTexts) {
    if (!uiTexts) { return; }
    UNITS.yuan = uiTexts["unit.yuan"] || "";
    UNITS.wan = uiTexts["unit.wan"] || "";
    UNITS.month = uiTexts["unit.month"] || "";
    UNITS.perMonth = uiTexts["unit.per_month"] || "";
    UNITS.percent = uiTexts["unit.percent"] || "";
    UNITS.path = uiTexts["unit.path"] || "";
  }

  function number(value) {
    var n = Math.round(Number(value) || 0);
    return (n < 0 ? "-" : "") + Math.abs(n).toLocaleString("zh-CN");
  }

  /* 超过一万元时换算为万元并保留一位小数 */
  function amount(value) {
    var n = Number(value) || 0;
    return Math.abs(n) >= 10000
      ? (n / 10000).toFixed(1) + " " + UNITS.wan
      : number(n) + " " + UNITS.yuan;
  }

  function tenThousand(value) {
    return (Number(value) / 10000).toFixed(1);
  }

  function percent(value) {
    return (Number(value) * 100).toFixed(1);
  }

  function decimal(value, digits) {
    return Number(value).toFixed(digits === undefined ? 1 : digits);
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/[&<>"']/g, function (ch) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
      });
  }

  global.App = global.App || {};
  global.App.Format = {
    configure: configure,
    units: UNITS,
    number: number,
    amount: amount,
    tenThousand: tenThousand,
    percent: percent,
    decimal: decimal,
    escapeHtml: escapeHtml
  };
})(window);
