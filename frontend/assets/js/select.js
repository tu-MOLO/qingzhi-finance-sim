/* 下拉框外观。原生 select 的展开面板由系统绘制，圆角、阴影都改不动；
   这里保留原生 select 作为数据与事件源，另画一个按钮和浮层接管外观：
   选中的值仍然写回原生 select 并派发 change，下游逻辑无需改动。 */
(function (global) {
  "use strict";

  var App = global.App = global.App || {};
  var opened = null;

  var CARET =
    '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false">' +
    '<path d="M2.4 4.4 6 8l3.6-3.6" fill="none" stroke="currentColor" stroke-width="1.6" ' +
    'stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function children(node) { return Array.prototype.slice.call(node.children); }

  function isInside(wrap, target) {
    return target && wrap.contains(target);
  }

  function close() {
    if (!opened) { return; }
    opened.wrap.classList.remove("open");
    opened.button.setAttribute("aria-expanded", "false");
    opened = null;
  }

  function syncLabel(entry) {
    var selected = entry.select.selectedOptions && entry.select.selectedOptions.length
      ? entry.select.selectedOptions[0]
      : entry.select.options[0];
    var text = selected ? (selected.textContent || "").trim() : "";
    if (!text) { text = entry.select.getAttribute("data-placeholder") || ""; }
    entry.text.textContent = text;
    entry.button.classList.toggle("is-empty", !text);
  }

  function syncDisabled(entry) {
    entry.button.disabled = Boolean(entry.select.disabled);
    entry.wrap.classList.toggle("is-disabled", Boolean(entry.select.disabled));
    if (entry.select.disabled) { close(); }
  }

  /* 菜单按原生结构重建，optgroup 原样保留成小标题 */
  function fill(entry) {
    var menu = entry.menu;
    menu.innerHTML = "";
    entry.items = [];

    function addOption(option) {
      var node = document.createElement("div");
      node.className = "cselect-opt";
      node.setAttribute("role", "option");
      node.dataset.value = option.value;
      node.textContent = (option.textContent || "").trim();
      menu.appendChild(node);
      entry.items.push(node);
    }

    children(entry.select).forEach(function (child) {
      var tag = child.tagName;
      if (tag === "OPTGROUP") {
        var group = document.createElement("div");
        group.className = "cselect-group";
        group.textContent = child.getAttribute("label") || "";
        menu.appendChild(group);
        children(child).forEach(addOption);
        return;
      }
      if (tag === "OPTION") { addOption(child); }
    });

    entry.active = -1;
    markSelected(entry);
  }

  function markSelected(entry) {
    var value = entry.select.value;
    entry.items.forEach(function (node) {
      var on = node.dataset.value === value;
      node.setAttribute("aria-selected", String(on));
      node.classList.toggle("is-on", on);
      if (on && entry.active < 0) {
        entry.active = entry.items.indexOf(node);
        highlight(entry);
      }
    });
  }

  function highlight(entry) {
    entry.items.forEach(function (node, index) {
      node.classList.toggle("is-active", index === entry.active);
    });
    var node = entry.items[entry.active];
    if (node && node.scrollIntoView) { node.scrollIntoView({ block: "nearest" }); }
  }

  function move(entry, step) {
    if (!entry.items.length) { return; }
    var next = entry.active + step;
    if (next < 0) { next = 0; }
    if (next > entry.items.length - 1) { next = entry.items.length - 1; }
    entry.active = next;
    highlight(entry);
  }

  function choose(entry, index) {
    var node = entry.items[index];
    if (!node) { return; }
    entry.select.value = node.dataset.value;
    syncLabel(entry);
    markSelected(entry);
    close();
    entry.select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function open(entry) {
    if (entry.select.disabled) { return; }
    if (opened && opened !== entry) { close(); }
    entry.wrap.classList.add("open");
    entry.button.setAttribute("aria-expanded", "true");
    opened = entry;
    markSelected(entry);
    if (entry.active < 0) { entry.active = 0; }
    highlight(entry);
  }

  function mountOne(select) {
    if (!select || select.dataset.cselect === "1") { return null; }
    select.dataset.cselect = "1";

    var wrap = document.createElement("div");
    wrap.className = "cselect";
    if (select.classList.contains("compact")) { wrap.classList.add("compact"); }
    select.classList.add("cselect-native");
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "cselect-btn";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.innerHTML = '<span class="cselect-text"></span><span class="cselect-caret">' + CARET + "</span>";

    var menu = document.createElement("div");
    menu.className = "cselect-menu";
    menu.setAttribute("role", "listbox");

    wrap.appendChild(button);
    wrap.appendChild(menu);

    var entry = {
      select: select,
      wrap: wrap,
      button: button,
      menu: menu,
      text: button.querySelector(".cselect-text"),
      items: [],
      active: -1
    };

    button.addEventListener("click", function () {
      if (opened === entry) { close(); return; }
      open(entry);
    });

    button.addEventListener("keydown", function (event) {
      var key = event.key;
      if (key === "ArrowDown" || key === "ArrowUp") {
        event.preventDefault();
        if (opened !== entry) { open(entry); return; }
        move(entry, key === "ArrowDown" ? 1 : -1);
        return;
      }
      if (key === "Enter" || key === " " || key === "Spacebar") {
        event.preventDefault();
        if (opened !== entry) { open(entry); return; }
        choose(entry, entry.active);
        return;
      }
      if (key === "Escape") { close(); button.focus(); return; }
      if (key === "Tab") { close(); }
    });

    menu.addEventListener("mousedown", function (event) {
      var node = event.target.closest ? event.target.closest(".cselect-opt") : null;
      if (!node) { return; }
      event.preventDefault();
      choose(entry, entry.items.indexOf(node));
      button.focus();
    });

    select.addEventListener("change", function () {
      syncLabel(entry);
      markSelected(entry);
    });

    fill(entry);
    syncLabel(entry);
    syncDisabled(entry);

    /* 代码直接赋值 select.value 不会触发 change，这里在实例上接管写入，
       让按钮文字跟着走，调用方不必记得同步 */
    var nativeValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
    if (nativeValue && nativeValue.set) {
      Object.defineProperty(select, "value", {
        configurable: true,
        get: function () { return nativeValue.get.call(select); },
        set: function (next) {
          nativeValue.set.call(select, next);
          syncLabel(entry);
          markSelected(entry);
        }
      });
    }

    /* 选项由各视图异步填充，结构一变就重建菜单，不需要各处主动通知 */
    if (global.MutationObserver) {
      var observer = new MutationObserver(function () {
        fill(entry);
        syncLabel(entry);
        syncDisabled(entry);
      });
      observer.observe(select, { childList: true, subtree: true, attributes: true });
    }

    return entry;
  }

  function mount(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll("select");
    Array.prototype.forEach.call(nodes, function (select) { mountOne(select); });
  }

  document.addEventListener("mousedown", function (event) {
    if (!opened) { return; }
    if (!isInside(opened.wrap, event.target)) { close(); }
  });

  document.addEventListener("focusin", function (event) {
    if (!opened) { return; }
    if (!isInside(opened.wrap, event.target)) { close(); }
  });

  window.addEventListener("resize", close);
  document.addEventListener("scroll", function (event) {
    if (!opened) { return; }
    if (isInside(opened.wrap, event.target)) { return; }
    close();
  }, true);

  App.Select = { mount: mount, close: close };
})(window);
