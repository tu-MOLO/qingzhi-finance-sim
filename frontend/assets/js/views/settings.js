/* 智能体接口设置。形式与其余页签一致：文案全部来自配置目录，取值全部来自接口。
   这里不预置任何服务地址、模型名或凭据——交付之后由使用者自己填。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;

  var state = { busy: false };

  function el(id) { return document.getElementById(id); }

  /* 顶栏入口的字样随配置状态变：配好了说已就绪，没配直接写成要去配 */
  function entryText(data) {
    return Catalog.text(data.configured ? "app.badge.agent_ready" : "app.badge.agent_unset");
  }

  function statusLine(data) {
    return Catalog.text("settings.status.line", {
      provider: data.provider === "openai_compat"
        ? Catalog.text("settings.status.model")
        : Catalog.text("settings.status.rule"),
      key: data.hasKey ? Catalog.text("settings.status.set") : Catalog.text("settings.status.unset"),
      network: data.allowNetwork
        ? Catalog.text("settings.status.yes")
        : Catalog.text("settings.status.no")
    });
  }

  function render(data) {
    state.busy = false;
    el("agent-busy").classList.remove("on");
    el("agent-status").innerHTML =
      '<span class="as-line">' + Fmt.escapeHtml(statusLine(data)) + "</span>";
    el("agent-entry").textContent = entryText(data);
    el("agent-entry").classList.toggle("warn", !data.configured);
  }

  function fill(data) {
    el("set-provider").value = data.provider;
    el("set-base-url").value = data.baseUrl || "";
    el("set-model").value = data.model || "";
    if (data.temperature !== null && data.temperature !== undefined) {
      el("set-temperature").value = data.temperature;
    }
    if (data.maxTokens) { el("set-max-tokens").value = data.maxTokens; }
    if (data.timeoutSeconds) { el("set-timeout").value = data.timeoutSeconds; }
    el("set-network").checked = Boolean(data.allowNetwork);
    if (!data.baseUrl) {
      el("set-base-url").placeholder = Catalog.text("field.base_url.placeholder");
    }
    el("set-api-key").placeholder = Catalog.text("field.api_key.placeholder");
  }

  function readPayload() {
    return {
      provider: el("set-provider").value,
      allowNetwork: el("set-network").checked,
      baseUrl: el("set-base-url").value.trim(),
      model: el("set-model").value.trim(),
      apiKey: el("set-api-key").value,
      temperature: el("set-temperature").value,
      maxTokens: el("set-max-tokens").value,
      timeoutSeconds: el("set-timeout").value
    };
  }

  function busy(on, label) {
    state.busy = on;
    el("agent-busy").classList.toggle("on", on);
    if (on && label) { el("agent-busy-text").textContent = label; }
    el("save-agent").disabled = on;
    el("test-agent").disabled = on;
  }

  function note(message, tone) {
    var node = el("agent-result");
    node.textContent = message || "";
    node.className = "hint" + (tone ? " " + tone : "");
  }

  function load() {
    return Api.get("/agent-settings").then(function (data) {
      fill(data);
      render(data);
      note("");
      return data;
    });
  }

  /* 保存时先落库再回读一次状态，界面上的字样与后端判定始终同源 */
  function save() {
    if (state.busy) { return Promise.resolve(); }
    busy(true, Catalog.message("status.saving"));
    return Api.put("/agent-settings", readPayload())
      .then(function (data) {
        render(data);
        // 凭据保存后立刻清空输入框，界面上不再留着一份明文
        el("set-api-key").value = "";
        note(Catalog.message("status.saved"), "ok");
        global.App.Main.toast(Catalog.message("status.saved"));
      })
      .catch(function (error) {
        note(error.message, "bad");
      })
      .then(function () { busy(false); });
  }

  /* 测试连接不发也不会返回模型输出，只回报是否通得上 */
  function test() {
    if (state.busy) { return Promise.resolve(); }
    busy(true, Catalog.message("status.testing"));
    return Api.post("/agent-settings/test", readPayload())
      .then(function (data) {
        var probe = data.probe || {};
        render(data.settings || {});
        note(probe.connected
          ? Catalog.text("settings.test.pass", { ms: probe.elapsedMs || 0 })
          : Catalog.text("settings.test.fail", { reason: probe.reason || "" }),
             probe.connected ? "ok" : "bad");
      })
      .catch(function (error) {
        note(error.message, "bad");
      })
      .then(function () { busy(false); });
  }

  function init() {
    el("save-agent").addEventListener("click", save);
    el("test-agent").addEventListener("click", test);
    return load().catch(function (error) {
      // 读取失败时入口仍然要说清楚「还没配」，而不是留一段空白
      el("agent-entry").textContent = Catalog.text("app.badge.agent_unset");
      el("agent-entry").classList.add("warn");
      note(error.message, "bad");
      return null;
    });
  }

  global.App = global.App || {};
  global.App.SettingsView = {
    init: init,
    load: load
  };
})(window);
