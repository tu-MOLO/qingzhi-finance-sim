/* 配置目录：字典、界面文案、提示文案、账户与分级。
   页面上的每一条可见文字与每一个下拉选项都从这里取，代码中不写业务文案。 */
(function (global) {
  "use strict";

  var state = {
    dictionaries: {},
    uiTexts: {},
    messages: {},
    accounts: [],
    riskLevels: [],
    settings: {},
    parameters: {},
    parameterRows: []
  };

  function load() {
    return global.App.Api.get("/catalog").then(function (data) {
      state.dictionaries = data.dictionaries || {};
      state.uiTexts = data.uiTexts || {};
      state.messages = data.messages || {};
      state.accounts = data.accounts || [];
      state.riskLevels = data.riskLevels || [];
      state.settings = data.settings || {};
      state.parameters = data.parameters || {};
      state.parameterRows = data.parameterRows || [];
      global.App.Format.configure(state.uiTexts);
      global.App.Api.configure({
        offline: message("status.offline"),
        failed: message("status.data_missing"),
        timeout: message("status.timeout")
      });
      return state;
    });
  }

  /* 文案取值，支持 {name} 形式的占位替换 */
  function text(key, params) {
    var value = state.uiTexts[key];
    if (value === undefined) { return ""; }
    if (!params) { return value; }
    return value.replace(/\{(\w+)\}/g, function (whole, name) {
      return params[name] === undefined ? whole : String(params[name]);
    });
  }

  function message(code) {
    var item = state.messages[code];
    return item ? item.body : "";
  }

  function messageTitle(code) {
    var item = state.messages[code];
    return item && item.title ? item.title : "";
  }

  function items(typeCode) {
    return state.dictionaries[typeCode] || [];
  }

  function nameOf(typeCode, code) {
    var found = items(typeCode).filter(function (item) { return item.code === code; })[0];
    return found ? found.name : code;
  }

  /* 把页面上带 data-text 的元素按文案表填好 */
  function applyStaticTexts(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-text]").forEach(function (node) {
      var key = node.getAttribute("data-text");
      var value = state.uiTexts[key];
      if (value !== undefined) { node.textContent = value; }
    });
    var title = scope.querySelector("title") || document.querySelector("title");
    if (title) { title.textContent = text("app.name"); }
  }

  global.App = global.App || {};
  global.App.Catalog = {
    load: load,
    state: state,
    text: text,
    message: message,
    messageTitle: messageTitle,
    items: items,
    nameOf: nameOf,
    applyStaticTexts: applyStaticTexts
  };
})(window);
