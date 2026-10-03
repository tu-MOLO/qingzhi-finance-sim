/* 目标与收入页。下拉选项、字段标签、收入来源的可填字段均由配置目录决定。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;

  var state = { archetypes: [], currentId: null, dirty: false, timer: null,
    dragRow: null, moved: false };

  function el(id) { return document.getElementById(id); }

  /* ---------------------------------------------------------- 下拉与表头 */

  function fillSelect(node, typeCode, selected) {
    node.innerHTML = Catalog.items(typeCode).map(function (item) {
      var chosen = item.code === selected ? " selected" : "";
      return '<option value="' + Fmt.escapeHtml(item.code) + '"' + chosen + ">" +
        Fmt.escapeHtml(item.name) + "</option>";
    }).join("");
  }

  function renderGoalHead() {
    var labels = ["", Catalog.text("field.goal.name"), Catalog.text("field.goal.amount"),
      Catalog.text("field.goal.due"), Catalog.text("field.goal.priority"), ""];
    el("goal-head").innerHTML = labels.map(function (text) {
      return "<span>" + Fmt.escapeHtml(text) + "</span>";
    }).join("");
  }

  /* ---------------------------------------------------------- 收入来源 */

  function sourceFields(definition, values) {
    var attributes = definition.attributes || {};
    var fields;
    if (definition.code === "living") {
      /* 家庭支持只填一个金额，且与基础信息联动 */
      fields = [["amount_low", Catalog.text("field.living_cost"), true]];
    } else {
      fields = [];
      if (attributes.has_probability) {
        fields.push(["probability", Catalog.text("field.source.probability"), false]);
      }
      fields.push(["amount_low", Catalog.text("field.source.amount_low"), false]);
      fields.push(["amount_high", Catalog.text("field.source.amount_high"), false]);
      if (attributes.has_window) {
        fields.push(["start_month", Catalog.text("field.source.start_month"), false]);
        fields.push(["end_month", Catalog.text("field.source.end_month"), false]);
      }
      if (attributes.has_interrupt) {
        fields.push(["interrupt_prob", Catalog.text("field.source.interrupt"), false]);
      }
    }
    /* 统一在这里包成字段对象，任何分支提前返回都会让标签与取值落空 */
    return fields.map(function (item) {
      return { key: item[0], label: item[1], mirrorLiving: item[2], value: values[item[0]] };
    });
  }

  /* 窗口字段没有值时给一个落在推演范围内的默认值。
     未勾选或刚勾选的来源若留着 0 月份，会被判成填写错误 */
  function fieldDefault(key) {
    if (key === "start_month") { return 1; }
    if (key === "end_month") { return Number(el("months").value) || 1; }
    return 0;
  }

  /* 未打开的项目不参与推演，数值一并锁住：改了也不生效，索性不让改 */
  function lockFields(block, on) {
    block.querySelectorAll(".src-field").forEach(function (input) { input.disabled = !on; });
  }

  function renderSources(sourceMap) {
    var definitions = Catalog.items("income_source");
    el("sources").innerHTML = definitions.map(function (definition) {
      var values = sourceMap[definition.code] || {};
      var attributes = definition.attributes || {};
      var deterministic = attributes.distribution === "fixed";
      var enabled = deterministic ? true : values.enabled === true;
      var fields = sourceFields(definition, values);
      var inputs = fields.map(function (field) {
        var value = field.value === undefined || field.value === null
          ? fieldDefault(field.key) : field.value;
        return '<div><label>' + Fmt.escapeHtml(field.label) + "</label>" +
          '<input type="number" class="src-field" data-key="' + Fmt.escapeHtml(field.key) + '"' +
          (field.mirrorLiving ? ' data-mirror="living"' : "") +
          (enabled ? "" : " disabled") +
          ' value="' + Fmt.escapeHtml(value) + '"></div>';
      }).join("");
      var toggle = deterministic
        ? '<span class="tag">' + Fmt.escapeHtml(Catalog.text("field.source.deterministic")) + "</span>" +
          '<span class="switch"><input type="checkbox" checked disabled><i></i></span>'
        : '<span class="switch"><input type="checkbox" class="src-on"' +
          (enabled ? " checked" : "") + "><i></i></span>";
      return '<div class="src' + (enabled ? "" : " off") + '" data-kind="' +
        Fmt.escapeHtml(definition.code) + '">' +
        '<div class="src-top"><span class="src-name">' + Fmt.escapeHtml(definition.name) + "</span>" +
        toggle + '</div><div class="src-grid">' + inputs + "</div></div>";
    }).join("");

    el("sources").querySelectorAll(".src-on").forEach(function (box) {
      box.addEventListener("change", function () {
        var block = box.closest(".src");
        block.classList.toggle("off", !box.checked);
        lockFields(block, box.checked);
        onChange();
      });
    });
    /* 镜像框反向写回基础信息，方向反过来同样成立。
       先于 onChange 注册，保证同一次输入先把值写过去再重算预览。 */
    el("sources").querySelectorAll('[data-mirror="living"]').forEach(function (input) {
      input.addEventListener("input", function () {
        el("living").value = input.value;
      });
    });
    el("sources").querySelectorAll("input[type=number]").forEach(function (input) {
      input.addEventListener("input", onChange);
    });
    syncLiving();
  }

  /* 生活费以基础信息为唯一口径，来源行里的金额跟随它，避免两处数值打架。
     正在输入的那一边不覆盖，否则光标会被自己的输入追平。 */
  function syncLiving() {
    var living = el("living").value;
    el("sources").querySelectorAll('[data-mirror="living"]').forEach(function (input) {
      if (input === document.activeElement || input.value === living) { return; }
      input.value = living;
    });
  }

  /* ---------------------------------------------------------- 目标 */

  function renderGoals(goals) {
    var dragLabel = Catalog.text("field.goal.drag");
    el("goals").innerHTML = goals.map(function (goal, index) {
      var deleteLabel = Catalog.text("button.delete_goal");
      return '<div class="goal-row">' +
        '<span class="ord" tabindex="0" role="button" title="' + Fmt.escapeHtml(dragLabel) +
        '" aria-label="' + Fmt.escapeHtml(dragLabel) + '">' +
        String(index + 1).padStart(2, "0") + "</span>" +
        '<input class="g-name" type="text" maxlength="20" value="' + Fmt.escapeHtml(goal.name) + '">' +
        '<input class="g-amount" type="number" min="1" step="500" value="' + Fmt.escapeHtml(goal.amount) + '">' +
        '<input class="g-due" type="number" min="1" step="1" value="' + Fmt.escapeHtml(goal.due_month) + '">' +
        '<input class="g-prio" type="number" min="1" step="1" value="' + Fmt.escapeHtml(goal.priority) + '">' +
        '<button class="del" title="' + Fmt.escapeHtml(deleteLabel) + '" aria-label="' +
        Fmt.escapeHtml(deleteLabel) + '">×</button></div>';
    }).join("");

    el("goals").querySelectorAll(".del").forEach(function (button) {
      button.addEventListener("click", function () {
        if (el("goals").querySelectorAll(".goal-row").length <= 1) {
          global.App.Main.toast(Catalog.message("validation.need_one_goal"));
          return;
        }
        button.closest(".goal-row").remove();
        syncOrder();
        onStructuralChange();
      });
    });
    el("goals").querySelectorAll("input").forEach(function (input) {
      input.addEventListener("input", onChange);
    });
    el("goals").querySelectorAll(".g-prio").forEach(bindPriority);
    /* 行是新建的，拖拽与键盘移动的绑定跟着重建一次 */
    bindGoalOrder();
    syncOrder();
  }

  /* 左侧序号是把手：按住它才把整行设成可拖，行内输入框照常能选字。
     拖过哪一行就落到它的上半或下半，松手后序号与优先级一起重排。 */
  function bindGoalOrder() {
    var box = el("goals");
    box.querySelectorAll(".goal-row").forEach(function (row) { bindGoalRow(box, row); });
  }

  function bindGoalRow(box, row) {
    var grip = row.querySelector(".ord");
    grip.addEventListener("pointerdown", function () { row.draggable = true; });
    /* 按下去却没拖动时立刻收回，免得之后在行里选字被当成拖拽 */
    grip.addEventListener("pointerup", function () { row.draggable = false; });
    grip.addEventListener("keydown", function (event) {
      var step = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
      if (!step) { return; }
      event.preventDefault();
      var rows = Array.prototype.slice.call(box.querySelectorAll(".goal-row"));
      var target = rows[rows.indexOf(row) + step];
      if (!target) { return; }
      box.insertBefore(row, step < 0 ? target : target.nextSibling);
      syncOrder();
      onStructuralChange();
      grip.focus();
    });

    row.addEventListener("dragstart", function (event) {
      state.dragRow = row;
      state.moved = false;
      row.classList.add("dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        /* Firefox 不设数据就不会启动拖拽 */
        event.dataTransfer.setData("text/plain", row.querySelector(".g-name").value || "");
      }
    });
    row.addEventListener("dragover", function (event) {
      if (!state.dragRow || state.dragRow === row) { return; }
      event.preventDefault();
      if (event.dataTransfer) { event.dataTransfer.dropEffect = "move"; }
      placeBeside(box, row, event.clientY);
    });
    row.addEventListener("drop", function (event) {
      if (state.dragRow) { event.preventDefault(); }
    });
    row.addEventListener("dragend", function () {
      var dragged = state.dragRow || row;
      dragged.classList.remove("dragging");
      dragged.draggable = false;
      state.dragRow = null;
      if (!state.moved) { return; }
      state.moved = false;
      syncOrder();
      onStructuralChange();
    });
  }

  /* 落在行的上半还是下半决定插到它前面还是后面；已经到位就不动，避免来回抖 */
  function placeBeside(box, row, clientY) {
    var rect = row.getBoundingClientRect();
    var after = clientY > rect.top + rect.height / 2;
    if (after ? row.nextElementSibling === state.dragRow
              : row.previousElementSibling === state.dragRow) { return; }
    box.insertBefore(state.dragRow, after ? row.nextElementSibling : row);
    state.moved = true;
  }

  /* 顺序即优先级：序号与优先级始终同步，且不小于 1 */
  function syncOrder() {
    el("goals").querySelectorAll(".goal-row").forEach(function (row, index) {
      row.querySelector(".ord").textContent = String(index + 1).padStart(2, "0");
      var prio = row.querySelector(".g-prio");
      prio.value = index + 1;
      prio.removeAttribute("aria-invalid");
    });
  }

  /* 手改优先级时不接受小于 1 的值：改回 1 并说明原因 */
  function bindPriority(input) {
    input.addEventListener("change", function () {
      var value = Math.round(Number(input.value));
      if (!isFinite(value) || value < 1) {
        input.value = 1;
        input.setAttribute("aria-invalid", "true");
        global.App.Main.toast(Catalog.message("validation.priority_floor"), "error");
      } else {
        input.removeAttribute("aria-invalid");
        input.value = value;
      }
      onChange();
    });
  }

  /* 到期月份的上界是推演时长：时长调短后，超出范围的目标一律收到新时长上，
     否则保存时必然报一条「到期月份超出推演范围」 */
  function clampGoalDue() {
    var months = Number(el("months").value) || 0;
    if (months <= 0) { return; }
    el("goals").querySelectorAll(".g-due").forEach(function (input) {
      if (Number(input.value) > months) { input.value = months; }
    });
  }

  /* ---------------------------------------------------------- 支出项 */

  function gradeAttributes(code) {
    var found = Catalog.items("grade").filter(function (item) { return item.code === code; })[0];
    return (found && found.attributes) || {};
  }

  /* 年级决定收入结构的默认值：哪些来源启用、窗口落在哪一段 */
  function applyGradeDefaults() {
    var windows = gradeAttributes(el("grade").value).income_windows || {};
    el("sources").querySelectorAll(".src").forEach(function (block) {
      var kind = block.getAttribute("data-kind");
      if (kind === "living" || kind === "scholarship") { return; }
      var window = windows[kind];
      var toggle = block.querySelector(".src-on");
      if (window) {
        toggle.checked = true;
        block.classList.remove("off");
        block.querySelectorAll(".src-field").forEach(function (input) {
          var key = input.getAttribute("data-key");
          if (key === "start_month") { input.value = window[0]; }
          if (key === "end_month") { input.value = window[1]; }
        });
      } else {
        toggle.checked = false;
        block.classList.add("off");
      }
      /* 窗口跟着年级变，锁定状态也要跟着变，否则刚启用的来源改不了数值 */
      lockFields(block, toggle.checked);
    });
    onChange();
  }

  function renderExpenses(expenseMap) {
    var definitions = Catalog.items("expense_category");
    el("expenses").innerHTML = definitions.map(function (definition) {
      var attributes = definition.attributes || {};
      var values = expenseMap[definition.code] || {
        amount: attributes.default_amount || 0,
        growth_rate: attributes.default_growth || 0,
        enabled: true
      };
      var essential = !!attributes.essential;
      var enabled = values.enabled !== false;
      return '<div class="src' + (enabled ? "" : " off") + '" data-kind="' +
        Fmt.escapeHtml(definition.code) + '">' +
        '<div class="src-top"><span class="src-name">' + Fmt.escapeHtml(definition.name) + "</span>" +
        '<span class="tag">' + Fmt.escapeHtml(Catalog.text(
          essential ? "field.expense.essential" : "field.expense.discretionary")) + "</span>" +
        '<span class="switch"><input type="checkbox" class="src-on"' +
        (enabled ? " checked" : "") + "><i></i></span></div>" +
        '<div class="src-grid">' +
        '<div><label>' + Fmt.escapeHtml(Catalog.text("field.expense.amount")) + "</label>" +
        '<input type="number" class="src-field" data-key="amount" min="0" step="50"' +
        (enabled ? "" : " disabled") + ' value="' +
        Fmt.escapeHtml(values.amount) + '"></div>' +
        '<div><label>' + Fmt.escapeHtml(Catalog.text("field.expense.growth")) + "</label>" +
        '<input type="number" class="src-field" data-key="growth_rate" min="0" max="0.2" step="0.01"' +
        (enabled ? "" : " disabled") + ' value="' +
        Fmt.escapeHtml(values.growth_rate) + '"></div>' +
        "</div></div>";
    }).join("");

    el("expenses").querySelectorAll(".src-on").forEach(function (box) {
      box.addEventListener("change", function () {
        var block = box.closest(".src");
        block.classList.toggle("off", !box.checked);
        lockFields(block, box.checked);
        onChange();
      });
    });
    el("expenses").querySelectorAll(".src-field").forEach(function (input) {
      input.addEventListener("input", onChange);
    });
  }

  function readExpenses() {
    var out = [];
    el("expenses").querySelectorAll(".src").forEach(function (block) {
      var item = { category: block.getAttribute("data-kind") };
      var toggle = block.querySelector(".src-on");
      item.enabled = toggle ? toggle.checked : true;
      block.querySelectorAll(".src-field").forEach(function (input) {
        var value = Number(input.value);
        item[input.getAttribute("data-key")] = isNaN(value) ? 0 : value;
      });
      out.push(item);
    });
    return out;
  }

  /* ---------------------------------------------------------- 读写 */

  function readSources() {
    var out = [];
    el("sources").querySelectorAll(".src").forEach(function (block) {
      var kind = block.getAttribute("data-kind");
      var item = { source_type: kind, enabled: kind === "living" };
      var toggle = block.querySelector(".src-on");
      if (toggle) { item.enabled = toggle.checked; }
      block.querySelectorAll(".src-field").forEach(function (input) {
        var value = Number(input.value);
        item[input.getAttribute("data-key")] = isNaN(value) ? 0 : value;
      });
      if (kind === "living") {
        var living = Number(el("living").value) || 0;
        item.amount_low = living;
        item.amount_mid = living;
        item.amount_high = living;
        item.probability = 1;
        item.interrupt_prob = 0;
        item.start_month = 1;
        item.end_month = Number(el("months").value) || 0;
      }
      if (item.amount_high === undefined) { item.amount_high = item.amount_low || 0; }
      if (item.amount_mid === undefined || isNaN(item.amount_mid)) {
        item.amount_mid = ((item.amount_low || 0) + (item.amount_high || 0)) / 2;
      }
      out.push(item);
    });
    return out;
  }

  function readGoals() {
    return Array.prototype.map.call(el("goals").querySelectorAll(".goal-row"), function (row, index) {
      return {
        goal_id: "g" + (index + 1),
        name: row.querySelector(".g-name").value.trim(),
        amount: Number(row.querySelector(".g-amount").value) || 0,
        due_month: Number(row.querySelector(".g-due").value) || 0,
        priority: Math.max(1, Math.round(Number(row.querySelector(".g-prio").value)) || index + 1)
      };
    });
  }

  function readProfile() {
    return {
      profile_id: "custom",
      name: "custom",
      grade: el("grade").value,
      living_cost: Number(el("living").value) || 0,
      living_growth: Number(el("growth").value) || 0,
      initial_balance: Number(el("initial").value) || 0,
      risk_appetite: el("appetite").value,
      months: Number(el("months").value) || 0,
      paths: Catalog.state.settings["simulation.default_paths"],
      seed: Catalog.state.settings["simulation.default_seed"],
      income_sources: readSources(),
      expenses: readExpenses(),
      goals: readGoals(),
      budget: {
        growth_monthly: Number(el("budget-growth").value) || 0,
        treat_monthly: Number(el("budget-treat").value) || 0
      }
    };
  }

  function applyProfile(profile, bindGrade) {
    /* 内置财务画像不绑定年级，加载时保留用户当前选择，随后按年级重算窗口；
       用户档案记录了保存时的年级，加载时恢复。 */
    if (bindGrade && profile.grade) { el("grade").value = profile.grade; }
    el("living").value = profile.living_cost;
    el("initial").value = profile.initial_balance;
    el("growth").value = profile.living_growth;
    el("appetite").value = profile.risk_appetite || "";
    el("months").value = profile.months;
    el("budget-growth").value = profile.budget.growth_monthly;
    el("budget-treat").value = profile.budget.treat_monthly;

    var map = {};
    (profile.income_sources || []).forEach(function (item) { map[item.source_type] = item; });
    renderSources(map);

    var expenseMap = {};
    (profile.expenses || []).forEach(function (item) { expenseMap[item.category] = item; });
    renderExpenses(expenseMap);

    /* 先按优先级排一遍，行顺序与优先级从加载起就是同一件事 */
    renderGoals((profile.goals || []).slice().sort(function (a, b) {
      return (Number(a.priority) || 0) - (Number(b.priority) || 0);
    }).map(function (goal) {
      return {
        name: goal.name, amount: goal.amount,
        due_month: goal.due_month, priority: goal.priority
      };
    }));
    onChange();
  }

  /* ---------------------------------------------------------- 预览 */

  function refreshPreview() {
    return Api.post("/profile/preview", { profile: readProfile() }).then(function (data) {
      el("bal-available").textContent = Fmt.amount(data.available);
      el("bal-available").className = "v " + (data.within_budget ? "pos" : "neg");
      el("bal-need").textContent = Fmt.amount(data.need_monthly);
      el("bal-income").textContent = Fmt.amount(data.expected_income);
      el("bal-emergency").textContent = Fmt.amount(data.emergency_target);
      el("bal-note").textContent = data.within_budget
        ? Catalog.text("balance.note")
        : Catalog.text("balance.negative");
      el("bal-note").style.color = data.within_budget ? "" : "var(--red-700)";
      /* 结余预览对外回传，三问起步据此反推悦己预算，不在前端重算收入口径 */
      return data;
    }).catch(function () {
      /* 预览失败不打断填写，提交推演时会给出明确提示 */
      return null;
    });
  }

  function onChange() {
    syncLiving();
    clearTimeout(state.timer);
    state.timer = setTimeout(refreshPreview, 260);
  }

  /* 目标增删属于结构性改动，直接触发重新推演 */
  function onStructuralChange() {
    onChange();
    if (global.App.Main.hasResult()) {
      clearTimeout(state.timer);
      state.timer = setTimeout(function () { global.App.Main.silentRun(); }, 260);
    }
  }

  /* 假设参数：把推演依赖的概率与增长率摆出来，标注性质与来源 */
  function renderAssumptions() {
    var rows = Catalog.state.parameterRows || [];
    /* 与推演假设面板共用同一套比率判定与格式化，两处口径一致 */
    var ParamValue = global.App.ParamValue;
    el("param-note").innerHTML = rows.filter(function (row) {
      return row.key && row.enabled !== false;
    }).map(function (row) {
      var unit = ParamValue.unitText(row);
      var tone = row.property_name || row.property || "";
      var source = row.source || "";
      return '<div class="param-item"><span class="pk">' + Fmt.escapeHtml(row.name) + "</span>" +
        '<span class="pv">' + Fmt.escapeHtml(ParamValue.valueText(row, row.value_base)) +
        (unit ? " " + Fmt.escapeHtml(unit) : "") + "</span>" +
        '<span class="pt">' + Fmt.escapeHtml(tone) +
        (source ? " · " + Fmt.escapeHtml(source) : "") + "</span></div>";
    }).join("");
  }

  /* ---------------------------------------------------------- 初始化 */

  function init() {
    fillSelect(el("grade"), "grade", "");
    fillSelect(el("appetite"), "risk_appetite", "");
    renderGoalHead();
    renderGoals([{ name: "", amount: 0, due_month: 12, priority: 1 }]);
    renderExpenses({});
    renderAssumptions();

    /* 推演时长的默认值来自配置，家庭支持取全国基准值，画像加载后会覆盖 */
    el("months").value = Number(Catalog.state.settings["simulation.default_months"]) || 0;
    el("living").value = Number(Catalog.state.parameters["national_living_cost"]) || 0;
    /* 首屏那条目标的默认到期月份同样受推演时长约束 */
    clampGoalDue();
    ["living", "growth", "initial", "budget-growth", "budget-treat"]
      .forEach(function (id) { el(id).addEventListener("input", onChange); });
    /* 推演时长变了要把目标的到期月份一起收敛，所以单独绑定 */
    el("months").addEventListener("input", function () {
      clampGoalDue();
      onChange();
    });
    el("grade").addEventListener("change", function () {
      applyGradeDefaults();
      onChange();
    });
    el("appetite").addEventListener("change", onChange);

    /* 行间的空隙不属于任何一行，落在那里时接到末尾 */
    el("goals").addEventListener("dragover", function (event) {
      if (!state.dragRow || event.target !== el("goals")) { return; }
      event.preventDefault();
      if (el("goals").lastElementChild === state.dragRow) { return; }
      el("goals").appendChild(state.dragRow);
      state.moved = true;
    });

    el("add-goal").addEventListener("click", function () {
      var goals = readGoals();
      var limit = Catalog.state.settings["limits.max_goals"] || goals.length;
      if (goals.length >= limit) {
        global.App.Main.toast(Catalog.message("validation.max_goals"));
        return;
      }
      var defaultDue = Number(Catalog.state.settings["limits.default_goal_due_month"]) || 1;
      var months = Number(el("months").value) || 0;
      goals.push({
        name: "",
        amount: Number(Catalog.state.settings["limits.default_goal_amount"]) || 0,
        /* 新建目标的默认到期月份不越过当前的推演时长 */
        due_month: months > 0 ? Math.min(defaultDue, months) : defaultDue,
        priority: goals.length + 1
      });
      renderGoals(goals.map(function (goal, index) {
        return { name: goal.name, amount: goal.amount, due_month: goal.due_month, priority: index + 1 };
      }));
      onStructuralChange();
    });

    el("run").addEventListener("click", function () { global.App.Main.run(); });
    el("load-archetype").addEventListener("click", loadArchetype);
    el("profile-name").placeholder = Catalog.text("field.profile_name");
    el("save-profile").addEventListener("click", saveProfile);
    el("delete-profile").addEventListener("click", deleteProfile);

    return loadArchetypes();
  }

  function loadArchetypes() {
    return Api.get("/archetypes").then(function (data) {
      state.archetypes = (data.archetypes || []).filter(function (item) { return item.enabled; });
      renderArchetypeSelect();
      return loadArchetype();
    });
  }

  /* 画像下拉分两组：内置财务画像，以及用户自己保存的档案 */
  function renderArchetypeSelect() {
    var builtin = state.archetypes.filter(function (item) { return item.kind !== "user"; });
    var saved = state.archetypes.filter(function (item) { return item.kind === "user"; });
    var html = "";
    if (builtin.length) {
      html += '<optgroup label="' + Fmt.escapeHtml(Catalog.text("archetype.group_builtin")) + '">' +
        builtin.map(optionHtml).join("") + "</optgroup>";
    }
    if (saved.length) {
      html += '<optgroup label="' + Fmt.escapeHtml(Catalog.text("archetype.group_saved")) + '">' +
        saved.map(optionHtml).join("") + "</optgroup>";
    }
    el("archetype").innerHTML = html;
    /* 存档变动后保持选中项不变 */
    if (state.currentId) { el("archetype").value = state.currentId; }
  }

  function optionHtml(item) {
    return '<option value="' + Fmt.escapeHtml(item.archetype_id) + '">' +
      Fmt.escapeHtml(item.name) + "</option>";
  }

  function loadArchetype() {
    var id = el("archetype").value;
    if (!id) { return Promise.resolve(); }
    state.currentId = id;
    var item = state.archetypes.filter(function (a) { return a.archetype_id === id; })[0];
    var isBuiltin = !item || item.kind !== "user";
    return Api.get("/archetypes/" + encodeURIComponent(id) + "/profile").then(function (data) {
      applyProfile(data.profile, !isBuiltin);
      /* 财务画像不绑定年级：加载后按用户当前年级重算收入窗口，消除「研一却挂着大三窗口」的错位 */
      if (isBuiltin) { applyGradeDefaults(); }
      global.App.Main.toast(data.profile.name);
      return data.profile;
    }).catch(function (error) {
      global.App.Main.toast(error.message || Catalog.message("status.archetype_missing"), "error");
      return null;
    });
  }

  /* 把当前表单保存为用户自己的财务档案，与内置画像分开存放 */
  function saveProfile() {
    var name = el("profile-name").value.trim();
    if (!name) {
      global.App.Main.toast(Catalog.message("validation.profile_name_required"));
      return Promise.resolve();
    }
    var profile = readProfile();
    profile.archetype_id = "user_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    profile.name = name;
    profile.kind = "user";
    return Api.post("/archetypes", profile).then(function () {
      el("profile-name").value = "";
      state.currentId = profile.archetype_id;
      return loadArchetypes();
    }).then(function () {
      global.App.Main.toast(Catalog.text("archetype.saved"));
    }).catch(function (error) {
      global.App.Main.toast(error.message, "error");
    });
  }

  function deleteProfile() {
    var id = el("archetype").value;
    if (!id) { return Promise.resolve(); }
    var item = state.archetypes.filter(function (a) { return a.archetype_id === id; })[0];
    if (!item || item.kind !== "user") {
      global.App.Main.toast(Catalog.message("validation.builtin_not_deletable"), "error");
      return Promise.resolve();
    }
    return Api.del("/archetypes/" + encodeURIComponent(id)).then(function () {
      state.currentId = null;
      return loadArchetypes();
    }).then(function () {
      global.App.Main.toast(Catalog.text("archetype.deleted"));
    }).catch(function (error) {
      global.App.Main.toast(error.message, "error");
    });
  }

  global.App = global.App || {};
  global.App.ProfileView = {
    init: init,
    readProfile: readProfile,
    applyProfile: applyProfile,
    render: renderSources,
    refreshPreview: refreshPreview,
    archetype: loadArchetype,
    currentArchetypeId: function () { return el("archetype").value; }
  };
})(window);
