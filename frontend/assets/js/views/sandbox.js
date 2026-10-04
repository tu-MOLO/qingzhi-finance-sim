/* 沙盘推演页：结论层、四张图表、三档情景与二选一方案。 */
(function (global) {
  "use strict";

  var Api = global.App.Api;
  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;
  var Charts = global.App.Charts;

  var state = { result: null, chosen: null, busy: false };

  function el(id) { return document.getElementById(id); }

  /* 凡是按目标罗列的地方都走这个次序，图例、图表、情景、概览才对得上 */
  function byPriority(list) {
    return (list || []).slice().sort(function (a, b) {
      return (Number(a.priority) || 0) - (Number(b.priority) || 0);
    });
  }

  /* 累计达成曲线的次序与截断上限。图表与图例都从这里取，两处的线与色才对得上 */
  function reachCurves(sim) {
    return byPriority(sim.reachCurves).slice(0, Charts.reachLimit || 5);
  }

  /* ---------------------------------------------------------- 图例 */

  function renderLegends(result) {
    var sim = result.simulation;
    var accountColors = {};
    (result.allocation.accounts || []).forEach(function (item) { accountColors[item.code] = item.color; });

    /* 图例与图表同一个顺序，两处的先后才对得上 */
    el("goal-legend").innerHTML = byPriority(result.simulation.goalResults)
      .map(function (goal) {
      return '<span><i class="swatch" style="background:' + Charts.goalColor(goal.hitProbability) +
        '"></i>' + Fmt.escapeHtml(goal.name) + " " + Fmt.percent(goal.hitProbability) + "%</span>";
    }).join("");

    el("account-legend").innerHTML = (result.allocation.accounts || []).map(function (item) {
      return '<span><i class="swatch" style="background:' + item.color + '"></i>' +
        Fmt.escapeHtml(item.name) + "</span>";
    }).join("");

    /* 路径样本的图例顺带交代抽了多少条，读图者知道这只是抽样不是全部 */
    el("paths-legend").innerHTML =
      '<span><i class="swatch" style="background:' +
      Fmt.escapeHtml("var(--chart-band)") + '"></i>' +
      Fmt.escapeHtml(Catalog.text("chart.paths.legend.sample", {
        n: Fmt.number((sim.pathSamples || []).length), total: Fmt.number(sim.paths)
      })) + "</span>" +
      '<span><i class="swatch" style="background:' +
      Fmt.escapeHtml("var(--chart-line)") + '"></i>' +
      Fmt.escapeHtml(Catalog.text("chart.paths.legend.median")) + "</span>";

    /* 累计达成曲线的图例按目标逐个列出，颜色与曲线同源同序，不会各配一套 */
    el("reach-legend").innerHTML = reachCurves(sim).map(function (item, index) {
      return '<span><i class="swatch" style="background:' +
        Fmt.escapeHtml(Charts.reachColor(index)) + '"></i>' +
        Fmt.escapeHtml(Catalog.text("chart.reach.legend.goal",
          { name: item.name, due: Fmt.number(item.dueMonth) })) + "</span>";
    }).join("");

    el("sw-band-range").style.background = "";
    el("sw-band-median").style.background = "";
    el("capacity-legend").innerHTML =
      '<span><i class="swatch" style="background:' + Charts.goalColor(1) + '"></i>' +
      Fmt.escapeHtml(Catalog.text("chart.capacity.legend.cushion")) + "</span>" +
      '<span><i class="swatch" style="background:' + Fmt.escapeHtml("var(--chart-grid)") + '"></i>' +
      Fmt.escapeHtml(Catalog.text("chart.capacity.legend.target")) + "</span>";
  }

  /* 三档情景：每个目标各一行，悲观、基准、乐观并列。
     原先只给首要目标的一组数，其余目标的波动幅度无从比较。 */
  function renderScenario(scenarios, goals) {
    var orders = ["pessimistic", "base", "optimistic"];
    var names = {};
    Catalog.items("scenario").forEach(function (item) { names[item.code] = item.name; });

    function cells(goal) {
      return orders.map(function (code) {
        var bucket = scenarios ? scenarios[code] : null;
        var value = bucket ? bucket[goal.goalId] : null;
        return "<b>" + (value === null || value === undefined
          ? Fmt.escapeHtml(Catalog.text("chart.scenario.none"))
          : Fmt.percent(value) + "%") + "</b>";
      }).join("");
    }

    el("scenario").innerHTML =
      '<div class="scen-title">' + Fmt.escapeHtml(Catalog.text("chart.goals.scenario_title")) + "</div>" +
      '<div class="scen-row scen-head"><span>' +
      Fmt.escapeHtml(Catalog.text("chart.scenario.goal")) + "</span>" +
      orders.map(function (code) {
        return "<span>" + Fmt.escapeHtml(names[code] || code) + "</span>";
      }).join("") + "</div>" +
      goals.map(function (goal) {
        return '<div class="scen-row"><span class="sn">' + Fmt.escapeHtml(goal.name) +
          "</span>" + cells(goal) + "</div>";
      }).join("");
  }

  /* ---------------------------------------------------------- 结论层 */

  function renderVerdict(result) {
    var sim = result.simulation;
    var ordered = byPriority(sim.goalResults);
    var primary = ordered[0];
    var median = primary.hitMonthP50;
    var capacity = result.capacity.current;

    el("v1").innerHTML = Fmt.percent(primary.hitProbability) + "<small>" +
      Fmt.escapeHtml(Fmt.units.percent) + "</small>";
    /* 副标题先讲首要目标，再把其余目标一并列出：只给一个数会让人以为只算了一个目标 */
    el("v1s").textContent = Catalog.text("verdict.hit_note",
      { n: Fmt.number(Math.round(primary.hitProbability * 100)), goal: primary.name }) +
      (ordered.length > 1
        ? "；" + Catalog.text("verdict.hit_others", {
          goals: ordered.slice(1).map(function (goal) {
            return goal.name + " " + Fmt.percent(goal.hitProbability) + Fmt.units.percent;
          }).join("、")
        })
        : "");

    if (median === null || median === undefined) {
      el("v2").textContent = Catalog.text("verdict.not_reached");
      el("v2s").textContent = Catalog.text("chart.goals.unreached");
    } else {
      var delay = Math.max(0, Math.round(median - primary.dueMonth));
      el("v2").innerHTML = delay + "<small>" + Fmt.escapeHtml(Fmt.units.month) + "</small>";
      el("v2s").textContent = delay > 0
        ? Catalog.text("verdict.delay_note",
          { median: Fmt.number(Math.round(median)), due: Fmt.number(Math.round(primary.dueMonth)),
            delay: Fmt.number(delay) })
        : Catalog.text("verdict.delay_none", { median: Fmt.number(Math.round(median)) });
    }

    el("v3").innerHTML = Fmt.escapeHtml(capacity.level);
    el("v3s").textContent = Catalog.text("verdict.capacity_note",
      { cushion: Fmt.decimal(capacity.cushionMonths, 1), cap: Fmt.percent(capacity.finalCap) });

    /* 脚注四组数字原来全是裸值，逐个补上标签与单位 */
    el("vfoot").textContent = Catalog.text("verdict.footnote", {
      paths: Fmt.number(sim.paths),
      months: Fmt.number(sim.months),
      monthUnit: Fmt.units.month,
      balance: Fmt.amount(sim.medianEndBalance),
      deficitMonths: Fmt.number(sim.deficitTotal),
      deficitPaths: Fmt.number(sim.deficitPaths),
      seed: String(sim.seed)
    });
    el("chart-note").textContent = Catalog.text("chart.note", {
      paths: Fmt.number(sim.paths),
      months: Fmt.number(sim.months),
      monthUnit: Fmt.units.month,
      seed: String(sim.seed)
    });

    renderDeficit(sim);
    markExplainable();
  }

  /* 把结论与断流提示里出现的自造词标成可点，解释不必离开当前页面 */
  function markExplainable() {
    var Explain = global.App.Explain;
    if (!Explain) { return; }
    ["v1s", "v2s", "v3s"].forEach(function (id) {
      var node = el(id);
      if (node && node.textContent) { node.innerHTML = Explain.mark(node.textContent); }
    });
    var deficit = el("v-deficit");
    if (deficit && !deficit.hidden) {
      deficit.innerHTML = Explain.mark(deficit.textContent);
    }
  }

  /* 断流提示：把断流最集中的月份回写到结论层 */
  function renderDeficit(sim) {
    var box = el("v-deficit");
    var total = Number(sim.deficitTotal) || 0;
    var paths = Number(sim.deficitPaths) || 0;
    if (!total && !paths) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    var peaks = sim.deficitPeakMonths || [];
    var sample = peaks.length
      ? "　" + Fmt.escapeHtml(Catalog.text("verdict.deficit_sample")) + '：<span class="months">' +
        peaks.slice(0, 8).map(function (item) {
          return Catalog.text("fmt.month_ordinal", { n: Fmt.number(item.month) });
        }).join("、") +
        (peaks.length > 8 ? " …" : "") + "</span>"
      : "";
    box.innerHTML = "<b>" + Fmt.escapeHtml(Catalog.text("verdict.deficit")) + "　</b>" +
      Fmt.escapeHtml(Catalog.text("verdict.deficit_detail",
        { count: Fmt.number(total), paths: Fmt.number(paths) })) + sample;
    box.hidden = false;
  }

  /* 目标缺口：每个目标距离按期达成还差多少 */
  function renderGaps(result) {
    var gaps = result.gaps || [];
    var box = el("goal-gaps");
    if (!gaps.length) { box.innerHTML = ""; return; }
    box.innerHTML = gaps.map(function (item) {
      var gap = Number(item.gapAmount) || 0;
      var value = gap > 0 ? Fmt.amount(gap) : Catalog.text("goal.covered");
      return '<div class="gap-item"><span>' + Fmt.escapeHtml(item.name || "") + "　" +
        Fmt.escapeHtml(Catalog.text("goal.gap")) + '</span><span class="gv">' +
        Fmt.escapeHtml(value) + "</span></div>";
    }).join("");
  }

  /* ---------------------------------------------------------- 结论解读 */

  function insightSnapshot(result) {
    var current = result.capacity.current;
    var snapshot = result.snapshot || {};
    return {
      primaryGoal: snapshot.primaryGoal || null,
      /* 全部目标一起交给解读，否则它只会讲排在最前的那个 */
      goals: snapshot.goals || [],
      capacity: {
        level: current.level, finalCap: current.finalCap,
        cushionMonths: current.cushionMonths, dipMonths: result.capacity.dipMonths
      },
      scenarios: result.scenarios,
      allocation: {
        accounts: result.allocation.accounts, order: result.allocation.order,
        series: result.allocation.series, emergencyTarget: result.allocation.emergencyTarget,
        conservationOk: result.allocation.conservationOk, priorityOk: result.allocation.priorityOk
      }
    };
  }

  /* 目标概览：数字直接取自推演结果，不经过智能体。
     解读无论成不成，这一块都在——多个目标的处境不该因为解读失败而全部消失。 */
  function goalSummaryHtml() {
    if (!state.result) { return ""; }
    var goals = byPriority(state.result.simulation.goalResults);
    if (!goals.length) { return ""; }
    var gaps = {};
    (state.result.gaps || []).forEach(function (item) { gaps[item.goalId] = item.gapAmount; });
    return '<div class="gs-title">' + Fmt.escapeHtml(Catalog.text("insight.goal_summary",
      { n: Fmt.number(goals.length) })) + "</div>" +
      '<div class="gs-list">' + goals.map(function (goal) {
        var gap = Number(gaps[goal.goalId]) || 0;
        var tone = (goal.hitProbability || 0) < 0.5 ? " low" : "";
        return '<div class="gs-item' + tone + '">' +
          '<span class="gn">' + Fmt.escapeHtml(goal.name) + "</span>" +
          '<span class="gp">' + Fmt.percent(goal.hitProbability) + "%</span>" +
          '<span class="gg">' + Fmt.escapeHtml(gap > 0
            ? Catalog.text("insight.goal_gap", { amount: Fmt.amount(gap) })
            : Catalog.text("goal.covered")) + "</span></div>";
      }).join("") + "</div>";
  }

  /* 结论解读由智能体产出。推演结束后自动跑一次，让解读跟着结论一起出现。
     智能体不可用时退回到目标概览，区块照常在场，只是没有那段话。 */
  function runInsight(options) {
    var silent = Boolean(options && options.silent);
    if (!state.result) {
      if (!silent) { global.App.Main.toast(Catalog.message("status.agent_prompt_missing")); }
      return Promise.resolve();
    }
    var button = el("run-insight");
    if (!silent) {
      button.disabled = true;
      el("insight-body").className = "";
      el("insight-body").innerHTML = '<div class="empty">' +
        Fmt.escapeHtml(Catalog.message("status.agent_insight")) + "</div>";
    }
    el("insight-sec").hidden = false;
    return Api.post("/agents/plan_insight/run", { snapshot: insightSnapshot(state.result) })
      .then(renderInsight)
      .catch(function (error) {
        /* 静默失败不弹提示，但概览仍然留下：数字是推演算出来的，不依赖智能体 */
        el("insight-body").className = "";
        el("insight-body").innerHTML = goalSummaryHtml() +
          '<div class="insight-sub">' + Fmt.escapeHtml(Catalog.text("insight.unavailable")) + "</div>";
        if (!silent) { global.App.Main.toast(error.message, "error"); }
      })
      .then(function () { button.disabled = false; });
  }

  function renderInsight(data) {
    var output = data.output || {};
    var points = output.points || [];
    var model = data.provider === "openai_compat";
    /* 容器在空态时挂着 empty 类（居中且灰），正式内容渲染前必须摘掉，否则整块文字都会飘到中间 */
    el("insight-body").className = "";
    /* 英文缩写 ms 混在中文界面里格格不入，全站统一改为中文秒数与执行轨迹 */
    var foot = [
      Catalog.text("insight.provider"),
      Catalog.text(model ? "term.agent.provider.model" : "term.agent.provider.rule"),
      data.degraded ? Catalog.text("explain.degraded") : "",
      Catalog.text("explain.elapsed", { seconds: secondsOf(data.elapsedMs) })
    ].filter(Boolean).join("　·　");

    el("insight-body").innerHTML =
      goalSummaryHtml() +
      '<div class="insight-sub">' + Fmt.escapeHtml(Catalog.text("insight.headline")) + "</div>" +
      '<div class="insight-headline">' + Fmt.escapeHtml(output.headline || "") + "</div>" +
      (points.length
        ? '<div class="insight-sub">' + Fmt.escapeHtml(Catalog.text("insight.points")) + "</div>" +
          '<ul class="insight-points">' + points.map(function (item) {
            return "<li>" + Fmt.escapeHtml(item) + "</li>";
          }).join("") + "</ul>"
        : "") +
      (output.riskNote
        ? '<div class="insight-sub">' + Fmt.escapeHtml(Catalog.text("insight.risk")) + "</div>" +
          '<div class="insight-risk">' + Fmt.escapeHtml(output.riskNote) + "</div>"
        : "") +
      '<div class="insight-foot">' + Fmt.escapeHtml(foot) + "</div>" +
      traceHtml(data.steps || []);
  }

  /* 毫秒换成带一位小数的秒，取值极小时不显示成 0.0 */
  function secondsOf(ms) {
    var value = Number(ms) || 0;
    /* 本地规则常在几毫秒内返回，显示「0.0 秒」既不好看也不像话 */
    return value < 100 ? "<0.1" : (value / 1000).toFixed(1);
  }

  /* 结论解读同样智能体生成，把三段式执行轨迹一并摊开 */
  function traceHtml(steps) {
    if (!steps.length) { return ""; }
    return '<div class="trace-head">' + Fmt.escapeHtml(Catalog.text("explain.trace")) + "</div>" +
      '<ul class="trace-list">' + steps.map(function (step) {
        return '<li><span class="ts">' + Fmt.escapeHtml(step.title || step.ref || "") + "</span>" +
          '<span class="tv">' + Fmt.escapeHtml(step.detail || step.status || "") + "</span></li>";
      }).join("") + "</ul>";
  }

  /* ---------------------------------------------------------- 方案 */

  function renderPlans(plan, fromCache) {
    var primary = plan.plans[0];
    var secondary = plan.plans[1];
    var chosen = state.chosen;
    var goal = plan.goal || {};
    var base = plan.baseProbability;

    var first;
    if (primary.keepCurrent) {
      first = "<h4>" + Fmt.escapeHtml(primary.title) + "</h4>" +
        '<div class="pnum">' + Fmt.escapeHtml(Catalog.text("verdict.keep_current")) + "</div><p>" +
        Fmt.escapeHtml(primary.message) + "</p>";
    } else if (primary.feasible) {
      /* 差额的正负代表每月少花还是多花，原来取了绝对值把方向抹掉了 */
      first = "<h4>" + Fmt.escapeHtml(primary.title) + "</h4>" +
        '<div class="pnum">' + Fmt.number(primary.treatMonthly) + "<small>" +
        Fmt.escapeHtml(Fmt.units.perMonth) + "</small></div><p>" +
        Fmt.escapeHtml(Catalog.text(primary.deltaAmount <= 0 ? "plan.delta_less" : "plan.delta_more",
          { amount: Fmt.number(Math.abs(primary.deltaAmount)), unit: Fmt.units.yuan })) + "<br>" +
        Fmt.escapeHtml(Catalog.text("plan.prob_range", {
          goal: goal.name || "", from: Fmt.percent(base), to: Fmt.percent(primary.achievedProbability),
          unit: Fmt.units.percent
        })) + "</p>";
    } else {
      first = "<h4>" + Fmt.escapeHtml(primary.title) + "</h4>" +
        '<div class="pnum">' + Fmt.escapeHtml(Catalog.text("verdict.infeasible")) + "</div><p>" +
        Fmt.escapeHtml(primary.message) + "</p>";
    }

    /* 延后月数在哨兵情形下只能说是「至少」，不能直接给确定值；
       说明句也要同步口径，不能前脚说至少、后脚又写成确定月数 */
    var delayBody = secondary.beyondHorizon
      ? '<span class="pnum-pre">' + Fmt.escapeHtml(Catalog.text("plan.delay_prefix")) + "</span>" +
        Fmt.number(secondary.delayMonths) + "<small>" + Fmt.escapeHtml(Fmt.units.month) + "</small>"
      : Fmt.number(secondary.delayMonths) + "<small>" + Fmt.escapeHtml(Fmt.units.month) + "</small>";
    var noteKey = secondary.beyondHorizon ? "plan.p2_note_at_least" : "plan.p2_note";
    var second = "<h4>" + Fmt.escapeHtml(secondary.title) + "</h4>" +
      '<div class="pnum">' + delayBody + "</div><p>" +
      Fmt.escapeHtml(Catalog.text(noteKey, {
        amount: Fmt.number(secondary.treatMonthly), unit: Fmt.units.perMonth,
        delay: Fmt.number(secondary.delayMonths), monthUnit: Fmt.units.month
      })) + "</p>";

    el("plans").innerHTML =
      '<button class="plan' + (chosen === "p1" ? " chosen" : "") + '" data-plan="p1"' +
      (primary.keepCurrent || !primary.feasible ? " disabled" : "") + ">" +
      '<div class="ptag">' + Fmt.escapeHtml(Catalog.text("plan.label.compress")) + "</div>" +
      first + "</button>" +
      '<button class="plan' + (chosen === "p2" ? " chosen" : "") + '" data-plan="p2">' +
      '<div class="ptag">' + Fmt.escapeHtml(Catalog.text("plan.label.postpone")) + "</div>" +
      second + "</button>";

    el("plans").querySelectorAll(".plan").forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.disabled) { return; }
        applyPlan(button.getAttribute("data-plan"), primary);
      });
    });

    var tag = el("plan-tag");
    if (primary.keepCurrent) { tag.textContent = Catalog.text("plan.tag.keep"); }
    else if (primary.feasible) { tag.textContent = Catalog.text("plan.tag.feasible"); }
    else { tag.textContent = Catalog.text("plan.tag.infeasible"); }
    tag.title = fromCache ? Catalog.text("plan.cache_hit") : "";
  }

  function applyPlan(type, primary) {
    if (type !== "p1" || !primary.feasible || primary.keepCurrent) { return; }
    state.chosen = type;
    el("budget-treat").value = primary.treatMonthly;
    el("recalc").classList.add("on");
    global.App.Main.run({ silent: true, keepChoice: true });
  }

  function loadPlanFor(goalId) {
    el("recalc").classList.add("on");
    return Api.post("/simulation/plan", {
      profile: global.App.ProfileView.readProfile(),
      goalId: goalId
    }).then(function (plan) {
      state.chosen = null;
      renderPlans(plan, plan.cacheHit);
    }).catch(function (error) {
      global.App.Main.toast(error.message, "error");
    }).then(function () {
      el("recalc").classList.remove("on");
    });
  }

  /* ---------------------------------------------------------- 渲染 */

  function render(result) {
    state.result = result;
    var sim = result.simulation;
    var ordered = byPriority(sim.goalResults);

    renderVerdict(result);

    el("chart-band").innerHTML = Charts.band(sim);
    el("chart-paths").innerHTML = Charts.paths(sim);
    el("chart-hist").innerHTML = Charts.histogram(sim.endBalanceHistogram, sim.endBalancePercentiles);
    el("chart-goals").innerHTML = Charts.goals(ordered);
    el("chart-reach").innerHTML = Charts.reach(reachCurves(sim), sim.months);
    el("chart-accounts").innerHTML = Charts.accounts(result.allocation, sim.months);
    el("chart-capacity").innerHTML = Charts.capacity(result.capacity, emergencyMonths());
    /* 图表刚换过 svg，读数层要重新挂一次 */
    Charts.mountCursors();
    renderLegends(result);
    renderScenario(result.scenarios, ordered);

    var disclaimer = result.disclaimer || {};
    el("disclaimer").innerHTML = "<b>" + Fmt.escapeHtml(disclaimer.title || "") + "　</b>" +
      Fmt.escapeHtml(disclaimer.body || "");

    el("goal-pick").innerHTML = ordered.map(function (goal) {
      return '<option value="' + Fmt.escapeHtml(goal.goalId) + '">' + Fmt.escapeHtml(goal.name) +
        "</option>";
    }).join("");

    renderPlans(result.plan, result.pathsReused);
    renderGaps(result);

    el("insight-sec").hidden = false;
    el("insight-body").innerHTML = '<div class="empty">' +
      Fmt.escapeHtml(Catalog.text("insight.empty")) + "</div>";
  }

  /* 应急金目标月数取自参数表，随配置目录一起下发 */
  function emergencyMonths() {
    return Number(Catalog.state.parameters["emergency_months"]) || 0;
  }

  function goalResults() {
    return state.result ? state.result.simulation.goalResults : [];
  }

  function init() {
    el("goal-pick").addEventListener("change", function () {
      var goalId = el("goal-pick").value;
      if (goalId) { loadPlanFor(goalId); }
    });
    el("run-insight").addEventListener("click", function () { runInsight(); });
    el("insight-sec").hidden = true;
  }

  global.App = global.App || {};
  global.App.SandboxView = {
    init: init,
    render: render,
    goalResults: goalResults,
    runInsight: runInsight,
    resetChoice: function () { state.chosen = null; },
    clear: function () { state.result = null; }
  };
})(window);
