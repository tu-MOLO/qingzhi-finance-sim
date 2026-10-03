/* 四张图表。全部手绘 SVG，不依赖任何外部绘图库。
   颜色从设计变量读取，文案从文案表读取，账户配色从接口下发的账户定义读取。 */
(function (global) {
  "use strict";

  var Catalog = global.App.Catalog;
  var Fmt = global.App.Format;

  var VW = 520;
  var VH = 210;
  var PADL = 44;
  var PADR = 12;
  /* 顶部预留一行单位标签的高度，否则单位会压在第一个刻度值上 */
  var PADT = 24;
  var PADB = 26;

  function token(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (value || "").trim() || fallback;
  }

  function px(index, count) {
    return PADL + (VW - PADL - PADR) * (count <= 1 ? 0 : index / (count - 1));
  }

  function py(value, max, min) {
    var low = min || 0;
    return VH - PADB - (VH - PADT - PADB) * ((value - low) / Math.max(1e-9, max - low));
  }

  /* 纵轴刻度。unitText 为这组刻度的单位，只标在最上方刻度上方一处，不逐格重复；
     tickText 为刻度数值的格式化函数，缺省按万元换算。 */
  function axes(max, labels, gridColor, unitText, tickText) {
    var count = 4;
    var format = typeof tickText === "function" ? tickText : Fmt.tenThousand;
    var ink = token("--ink-300", "#A8A5AC");
    var out = "";
    for (var i = 0; i <= count; i++) {
      var value = max * i / count;
      var y = py(value, max);
      out += '<line x1="' + PADL + '" y1="' + y.toFixed(1) + '" x2="' + (VW - PADR) +
        '" y2="' + y.toFixed(1) + '" stroke="' + gridColor + '" stroke-width="1"/>';
      out += '<text x="' + (PADL - 8) + '" y="' + (y + 4).toFixed(1) +
        '" font-size="10" fill="' + ink + '" text-anchor="end">' +
        Fmt.escapeHtml(format(value)) + "</text>";
    }
    if (unitText) {
      out += '<text x="' + (PADL - 8) + '" y="' + (py(max, max) - 8).toFixed(1) +
        '" font-size="9" fill="' + ink + '" text-anchor="end">' +
        Fmt.escapeHtml(unitText) + "</text>";
    }
    labels.forEach(function (item) {
      out += '<text x="' + item[0].toFixed(1) + '" y="' + (VH - 8) + '" font-size="10" fill="' +
        ink + '" text-anchor="middle">' + Fmt.escapeHtml(item[1]) + "</text>";
    });
    return out;
  }

  /* 横轴刻度只取有效范围内的月份 */
  function monthLabels(count) {
    var marks = [0, 23, 47, count - 1].filter(function (value, index, array) {
      return value >= 0 && value < count && array.indexOf(value) === index;
    });
    return marks.map(function (mark) {
      return [px(mark, count - 1), Catalog.text("chart.axis.month", { n: mark + 1 })];
    });
  }

  function svg(height, label, inner) {
    return '<svg viewBox="0 0 ' + VW + " " + height + '" role="img" aria-label="' +
      Fmt.escapeHtml(label) + '">' + inner + "</svg>";
  }

  function band(sim) {
    var months = sim.months;
    var p10 = sim.balancePercentiles.p10;
    var p50 = sim.balancePercentiles.p50;
    var p90 = sim.balancePercentiles.p90;
    var max = Math.max.apply(null, p90.concat([1]));
    var top = "";
    var middle = "";
    var bottom = "";
    for (var i = 0; i < months; i++) {
      top += (i ? "L" : "M") + px(i, months - 1).toFixed(1) + " " + py(p90[i], max).toFixed(1);
      middle += (i ? "L" : "M") + px(i, months - 1).toFixed(1) + " " + py(p50[i], max).toFixed(1);
    }
    for (var j = months - 1; j >= 0; j--) {
      bottom += "L" + px(j, months - 1).toFixed(1) + " " + py(p10[j], max).toFixed(1);
    }
    var inner = axes(max, monthLabels(months), token("--chart-grid", "#EAE8EB"),
      Fmt.units.wan) +
      '<path d="' + top + bottom + 'Z" fill="' + token("--chart-band", "#EBB6B7") + '" opacity="0.55"/>' +
      '<path d="' + middle + '" fill="none" stroke="' + token("--chart-line", "#B4121A") +
      '" stroke-width="2" stroke-linejoin="round"/>';
    return svg(VH, Catalog.text("chart.band.title"), inner);
  }

  function goalColor(probability) {
    if (probability >= 0.7) { return token("--red-600", "#B4121A"); }
    if (probability >= 0.4) { return token("--red-500", "#C8161D"); }
    return token("--red-200", "#EBB6B7");
  }

  function goals(results) {
    var height = results.length * 44 + 26;
    var start = 132;
    var end = VW - 64;
    var out = "";
    results.forEach(function (item, index) {
      var y = 14 + index * 44;
      var width = (end - start) * item.hitProbability;
      var timing = item.hitMonthP50 === null || item.hitMonthP50 === undefined
        ? Catalog.text("chart.goals.unreached")
        : Catalog.text("chart.goals.timing", { n: Math.round(item.hitMonthP50) });
      out += '<text x="' + (start - 10) + '" y="' + (y + 13) + '" font-size="11.5" fill="' +
        token("--ink-700", "#3A3840") + '" text-anchor="end">' + Fmt.escapeHtml(item.name) + "</text>";
      out += '<rect x="' + start + '" y="' + (y + 2) + '" width="' + (end - start) +
        '" height="14" rx="2" fill="' + token("--ink-50", "#F4F3F5") + '"/>';
      out += '<rect x="' + start + '" y="' + (y + 2) + '" width="' + Math.max(1, width).toFixed(1) +
        '" height="14" rx="2" fill="' + goalColor(item.hitProbability) + '"/>';
      out += '<text x="' + (end + 8) + '" y="' + (y + 13) + '" font-size="12" fill="' +
        token("--ink-900", "#17161A") + '">' + Fmt.percent(item.hitProbability) + "%</text>";
      out += '<text x="' + start + '" y="' + (y + 31) + '" font-size="10.5" fill="' +
        token("--ink-300", "#A8A5AC") + '">' +
        Fmt.escapeHtml(Catalog.text("chart.goals.label", {
          wan: Fmt.tenThousand(item.amount), due: item.dueMonth
        })) + Fmt.escapeHtml(timing) + "</text>";
    });
    return svg(height, Catalog.text("chart.goals.title"), out);
  }

  /* 堆叠面积：按账户定义中的顺序自下而上叠加 */
  function accounts(allocation, months) {
    /* 原先写死最多画 96 个月，推演设为 120 时会静默截掉后段，
       画面与前文的推演时长对不上。横轴刻度本就只取四处，全量画不影响可读性。 */
    var count = months;
    var order = allocation.accounts || [];
    if (!order.length) { return '<div class="empty"></div>'; }

    var cumulative = [];
    var max = 1;
    for (var i = 0; i < count; i++) {
      var sum = 0;
      var row = {};
      order.forEach(function (account) {
        sum += Number(allocation.series[account.code][i]) || 0;
        row[account.code] = sum;
      });
      cumulative.push(row);
      max = Math.max(max, sum);
    }

    var paths = "";
    for (var level = order.length - 1; level >= 0; level--) {
      var code = order[level].code;
      var path = "";
      for (var m = 0; m < count; m++) {
        path += (m ? "L" : "M") + px(m, count - 1).toFixed(1) + " " +
          py(cumulative[m][code], max).toFixed(1);
      }
      for (var n = count - 1; n >= 0; n--) {
        var lower = level > 0 ? cumulative[n][order[level - 1].code] : 0;
        path += "L" + px(n, count - 1).toFixed(1) + " " + py(lower, max).toFixed(1);
      }
      paths += '<path d="' + path + 'Z" fill="' + order[level].color + '"/>';
    }
    return svg(VH, Catalog.text("chart.accounts.title"),
      axes(max, monthLabels(count), token("--chart-grid", "#EAE8EB"),
        Fmt.units.wan) + paths);
  }

  /* 容量日历：安全垫厚度折线，虚线上方为应急金目标 */
  function capacity(data, emergencyMonths) {
    var calendar = data.calendar || [];
    if (!calendar.length) { return '<div class="empty"></div>'; }
    var count = calendar.length;
    var values = calendar.map(function (item) { return item.cushionMonths; });
    var max = Math.max(emergencyMonths * 1.6, Math.max.apply(null, values), 0.1);
    var grid = token("--chart-grid", "#EAE8EB");
    var line = token("--chart-line", "#B4121A");
    var marks = [0, 11, count - 1].filter(function (value, index, array) {
      return value >= 0 && value < count && array.indexOf(value) === index;
    }).map(function (mark) {
      return [px(mark, count - 1), Catalog.text("chart.axis.month", { n: mark + 1 })];
    });
    /* 日历的纵轴是安全垫厚度，按原值保留一位小数，不换算成万元 */
    var out = axes(max, marks, grid, Fmt.units.month, function (value) {
      return value.toFixed(1);
    });

    out += '<line x1="' + PADL + '" y1="' + py(emergencyMonths, max).toFixed(1) + '" x2="' + (VW - PADR) +
      '" y2="' + py(emergencyMonths, max).toFixed(1) + '" stroke="' + line +
      '" stroke-width="1" stroke-dasharray="5 4"/>';

    var path = "";
    for (var k = 0; k < count; k++) {
      path += (k ? "L" : "M") + px(k, count - 1).toFixed(1) + " " + py(values[k], max).toFixed(1);
    }
    out += '<path d="' + path + "L" + px(count - 1, count - 1).toFixed(1) + " " + py(0, max).toFixed(1) +
      "L" + PADL + " " + py(0, max).toFixed(1) + 'Z" fill="' + line + '" opacity="0.10"/>';
    out += '<path d="' + path + '" fill="none" stroke="' + line + '" stroke-width="2" stroke-linejoin="round"/>';

    (data.dipMonths || []).forEach(function (month) {
      var index = month - 1;
      if (index >= 0 && index < count) {
        out += '<circle cx="' + px(index, count - 1).toFixed(1) + '" cy="' +
          py(values[index], max).toFixed(1) + '" r="3" fill="#fff" stroke="' + line + '" stroke-width="1.5"/>';
      }
    });

    out += '<text x="' + (PADL + 6) + '" y="' + (py(emergencyMonths, max) - 6).toFixed(1) +
      '" font-size="10" fill="' + line + '">' +
      Fmt.escapeHtml(Catalog.text("chart.capacity.target", { n: emergencyMonths })) + "</text>";

    /* 日历只画前 count 个月，与结论区的推演总时长不是同一尺度，图下补一句说明 */
    out += '<text x="' + PADL + '" y="' + (VH + 12) + '" font-size="10" fill="' +
      token("--ink-300", "#A8A5AC") + '">' +
      Fmt.escapeHtml(Catalog.text("chart.capacity.range_note", { n: count })) + "</text>";

    return svg(VH + 18, Catalog.text("chart.capacity.title"), out);
  }

  /* ---------------------------------------------------------- 逐路径明细

     分位带只说「中间那一半落在哪」，看不出单条路径会不会中途崩掉。
     下面三张图直接把路径本身摆出来：一条线是一条可能的走法。

     坐标换算沿用 px/py，折线类与上方的累积图共用同一套内边距。 */

  function chartWidth(count) {
    return (VW - PADR - PADL) / Math.max(1, count);
  }

  /* 路径样本：按期终余额等距抽出的若干条真实路径，加一条中位路径作参照。
     样本线用区间色浅描一笔，中位线用主色压过画面，避免两者抢视觉重心。 */
  function paths(sim) {
    var samples = sim.pathSamples || [];
    if (!samples.length) { return '<div class="empty"></div>'; }
    var months = sim.months;
    var max = 1;
    samples.forEach(function (item) {
      item.series.forEach(function (value) { max = Math.max(max, Number(value) || 0); });
    });
    (sim.balancePercentiles.p50 || []).forEach(function (value) {
      max = Math.max(max, Number(value) || 0);
    });

    var grid = token("--chart-grid", "#EAE8EB");
    var ink300 = token("--ink-300", "#A8A5AC");
    var out = axes(max, monthLabels(months), grid, Fmt.units.wan);

    samples.forEach(function (item) {
      var line = "";
      for (var i = 0; i < months; i++) {
        line += (i ? "L" : "M") + px(i, months - 1).toFixed(1) + " " +
          py(Number(item.series[i]) || 0, max).toFixed(1);
      }
      out += '<path d="' + line + '" fill="none" stroke="' +
        token("--chart-band", "#EBB6B7") + '" stroke-width="1" opacity="0.85"/>';
    });

    var middle = "";
    for (var m = 0; m < months; m++) {
      middle += (m ? "L" : "M") + px(m, months - 1).toFixed(1) + " " +
        py(Number(sim.balancePercentiles.p50[m]) || 0, max).toFixed(1);
    }
    out += '<path d="' + middle + '" fill="none" stroke="' + token("--chart-line", "#B4121A") +
      '" stroke-width="2" stroke-linejoin="round"/>';

    /* 样本里若有路径被清零过，就在图内点一句，说明浅色线为什么会贴底 */
    var grounded = samples.filter(function (item) {
      return item.series.some(function (value) { return (Number(value) || 0) <= 0; });
    }).length;
    if (grounded) {
      out += '<text x="' + PADL + '" y="' + (VH + 12) + '" font-size="10" fill="' + ink300 + '">' +
        Fmt.escapeHtml(Catalog.text("chart.paths.grounded", { n: Fmt.number(grounded) })) +
        "</text>";
    }
    return svg(VH + 18, Catalog.text("chart.paths.title"), out);
  }

  /* 期末余额分布：把全部路径的期末余额分格计数。
     纵轴是路径条数而不是钱，因此不复用 axes 的万元刻度格式。 */
  function histogram(payload, percentiles) {
    var buckets = (payload && payload.buckets) || [];
    if (!buckets.length) { return '<div class="empty"></div>'; }
    var maxCount = buckets.reduce(function (best, item) {
      return Math.max(best, Number(item.count) || 0);
    }, 1);
    var grid = token("--chart-grid", "#EAE8EB");
    var line = token("--chart-line", "#B4121A");
    var ink300 = token("--ink-300", "#A8A5AC");
    var out = "";
    for (var i = 0; i <= 4; i++) {
      var value = maxCount * i / 4;
      var y = py(value, maxCount);
      out += '<line x1="' + PADL + '" y1="' + y.toFixed(1) + '" x2="' + (VW - PADR) +
        '" y2="' + y.toFixed(1) + '" stroke="' + grid + '" stroke-width="1"/>';
      out += '<text x="' + (PADL - 8) + '" y="' + (y + 4).toFixed(1) +
        '" font-size="10" fill="' + ink300 + '" text-anchor="end">' +
        Fmt.escapeHtml(Fmt.number(Math.round(value))) + "</text>";
    }
    out += '<text x="' + (PADL - 8) + '" y="' + (py(maxCount, maxCount) - 8).toFixed(1) +
      '" font-size="9" fill="' + ink300 + '" text-anchor="end">' +
      Fmt.escapeHtml(Fmt.units.path) + "</text>";

    var slot = chartWidth(buckets.length);
    buckets.forEach(function (item, index) {
      var left = PADL + slot * index;
      var top = py(Number(item.count) || 0, maxCount);
      if (Number(item.count) > 0) {
        out += '<rect x="' + (left + 1).toFixed(1) + '" y="' + top.toFixed(1) +
          '" width="' + Math.max(1, slot - 2).toFixed(1) + '" height="' +
          Math.max(1, VH - PADB - top).toFixed(1) + '" fill="' +
          token("--chart-band", "#EBB6B7") + '"/>';
      }
    });

    /* 中位线：整幅图的结论落点，用主色竖线加标签，不看图例也能读出来 */
    var low = Number(payload.minValue) || 0;
    var high = Number(payload.maxValue) || 0;
    var median = Number((percentiles || {}).p50);
    if (high > low && isFinite(median)) {
      var cx = PADL + (VW - PADR - PADL) * Math.min(1, Math.max(0, (median - low) / (high - low)));
      out += '<line x1="' + cx.toFixed(1) + '" y1="' + PADT + '" x2="' + cx.toFixed(1) +
        '" y2="' + (VH - PADB) + '" stroke="' + line + '" stroke-width="1" stroke-dasharray="5 4"/>';
      out += '<text x="' + Math.min(cx + 6, VW - PADR - 46).toFixed(1) + '" y="' + (PADT + 4) +
        '" font-size="10" fill="' + line + '">' +
        Fmt.escapeHtml(Catalog.text("chart.hist.median",
          { wan: Fmt.tenThousand(median) })) + "</text>";
    }

    var marks = [0, Math.floor(buckets.length / 2), buckets.length - 1]
      .filter(function (value, index, array) { return array.indexOf(value) === index; });
    marks.forEach(function (index) {
      var item = buckets[index];
      out += '<text x="' + (PADL + slot * (index + 0.5)).toFixed(1) + '" y="' + (VH - 8) +
        '" font-size="10" fill="' + ink300 + '" text-anchor="middle">' +
        Fmt.escapeHtml(Fmt.tenThousand(item.from)) + "</text>";
    });
    return svg(VH, Catalog.text("chart.hist.title"), out);
  }

  /* 累计达成的配色。最多支持五个目标，超出部分循环使用；图例从同一处取值，
     不会出现曲线与图例各配一套颜色的情况。 */
  var REACH_PALETTE = ["--red-600", "--ink-700", "--red-800", "--ink-500", "--ink-900"];

  function reachColor(index) {
    return token(REACH_PALETTE[index % REACH_PALETTE.length], "#B4121A");
  }

  /* 累计达成：按月累加「已经攒够」的路径占比，到到期月的高度就是达成概率。
     每个目标一条线，到期月处点一个实心点，读图的人不必去对比两条曲线。 */
  function reach(curves, months) {
    /* 曲线与图例共用同一份次序与同一个上限，读图时颜色才对得上人 */
    var list = (curves || []).slice(0, REACH_PALETTE.length);
    if (!list.length) { return '<div class="empty"></div>'; }
    var grid = token("--chart-grid", "#EAE8EB");
    var ink300 = token("--ink-300", "#A8A5AC");
    var out = axes(1, monthLabels(months), grid, Fmt.units.percent, function (value) {
      return Fmt.percent(value) + Fmt.units.percent;
    });

    list.forEach(function (item, index) {
      var color = reachColor(index);
      var path = "";
      for (var i = 0; i < months; i++) {
        path += (i ? "L" : "M") + px(i, months - 1).toFixed(1) + " " +
          py(Number(item.curve[i]) || 0, 1).toFixed(1);
      }
      out += '<path d="' + path + '" fill="none" stroke="' + color +
        '" stroke-width="2" stroke-linejoin="round"' +
        (index >= 3 ? ' stroke-dasharray="6 3"' : "") + "/>";
      var due = Math.min(months - 1, Math.max(0, Number(item.dueMonth) - 1));
      out += '<circle cx="' + px(due, months - 1).toFixed(1) + '" cy="' +
        py(Number(item.curve[due]) || 0, 1).toFixed(1) + '" r="3.5" fill="' + color + '"/>';
    });

    out += '<text x="' + PADL + '" y="' + (VH + 12) + '" font-size="10" fill="' + ink300 + '">' +
      Fmt.escapeHtml(Catalog.text("chart.reach.dot_note")) + "</text>";
    return svg(VH + 18, Catalog.text("chart.reach.title"), out);
  }

  global.App = global.App || {};
  global.App.Charts = {
    band: band,
    paths: paths,
    histogram: histogram,
    reach: reach,
    goals: goals,
    accounts: accounts,
    capacity: capacity,
    goalColor: goalColor,
    reachColor: reachColor,
    reachLimit: REACH_PALETTE.length
  };
})(window);
