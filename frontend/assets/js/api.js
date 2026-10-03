/* 接口客户端。所有请求走同源相对路径，不向任何外部地址发起通信。 */
(function (global) {
  "use strict";

  var PREFIX = "/api/v1";
  var fallback = { offline: "无法连接本地服务", failed: "请求未能完成", timeout: "请求超时，请重试" };

  /* 请求上限。推演与智能体调用都可能耗时较久，取值要明显宽于正常耗时 */
  var TIMEOUT_MS = 60000;

  function configure(messages) {
    if (messages) {
      fallback.offline = messages.offline || fallback.offline;
      fallback.failed = messages.failed || fallback.failed;
      fallback.timeout = messages.timeout || fallback.timeout;
    }
  }

  function request(method, path, payload) {
    var options = { method: method, headers: { "Content-Type": "application/json" } };
    if (payload !== undefined) { options.body = JSON.stringify(payload); }

    var timer = null;
    if (typeof AbortController !== "undefined") {
      var controller = new AbortController();
      options.signal = controller.signal;
      timer = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);
    }
    function done() {
      if (timer !== null) { clearTimeout(timer); timer = null; }
    }

    return fetch(PREFIX + path, options).catch(function (error) {
      if (error && error.name === "AbortError") { throw new Error(fallback.timeout); }
      throw new Error(fallback.offline);
    }).then(function (response) {
      return response.text().then(function (text) {
        var body = null;
        if (text) {
          try { body = JSON.parse(text); } catch (err) { body = null; }
        }
        if (!response.ok || !body || !body.ok) {
          var error = (body && body.error) || {};
          var message = error.message || (fallback.failed + "（状态码 " + response.status + "）");
          var problem = new Error(message);
          problem.code = error.code || null;
          problem.field = error.field || null;
          problem.status = response.status;
          throw problem;
        }
        return body.data;
      });
    }).then(function (data) {
      done();
      return data;
    }, function (error) {
      done();
      throw error;
    });
  }

  global.App = global.App || {};
  global.App.Api = {
    configure: configure,
    get: function (path) { return request("GET", path); },
    post: function (path, payload) { return request("POST", path, payload === undefined ? {} : payload); },
    put: function (path, payload) { return request("PUT", path, payload === undefined ? {} : payload); },
    del: function (path) { return request("DELETE", path); }
  };
})(window);
