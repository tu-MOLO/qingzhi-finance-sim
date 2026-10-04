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
    /* 纵向格线落在有月份标签的位置，横轴刻度才有对应的月份可对照 */
    labels.forEach(function (item) {
      out += '<line x1="' + item[0].toFixed(1) + '" y1="' + PADT + '" x2="' + item[0].toFixed(1) +
        '" y2="' + (VH - PADB) + '" stroke="' + gridColor + '" stroke-width="1"/>';
    });
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
        ink + '" text-anchor="' + (item[2] || "middle") + '">' +
        Fmt.escapeHtml(item[1]) + "</text>";
    });
    return out;
  }

  /* 横轴刻度的步长只在几个整齐的月份数里挑，使标签不超过六处。
     原先固定取第 1、24、48 月与末月，间隔忽长忽短，末月的标签还会被画布裁掉。 */
  var MONTH_STEPS = [1, 2, 3, 6, 12, 24, 36, 60, 120];

  function monthTicks(count) {
    if (count <= 1) { return [0]; }
    var step = MONTH_STEPS[MONTH_STEPS.length - 1];
    for (var i = 0; i < MONTH_STEPS.length; i++) {
      if ((count - 1) / MONTH_STEPS[i] <= 5) { step = MONTH_STEPS[i]; break; }
    }
    var marks = [];
    for (var mark = 0; mark < count - 1; mark += step) { marks.push(mark); }
    var last = count - 1;
    /* 末月离前一个刻度太近就顶掉它，免得两个标签叠在一起 */
    if (last - marks[marks.length - 1] < step * 0.6) { marks.pop(); }
    marks.push(last);
    return marks;
  }

  /* 横轴月份刻度。末月用右对齐，文字才不会被画布右缘切掉 */
  function monthLabels(count) {
    return monthTicks(count).map(function (mark) {
      return [px(mark, count - 1), Catalog.text("chart.axis.month", { n: mark + 1 }),
        mark === count - 1 ? "end" : "middle"];
    });
  }

  function svg(height, label, inner, spec) {
    return '<svg viewBox="0 0 ' + VW + " " + height + '" role="img" aria-label="' +
      Fmt.escapeHtml(label) + '"' + cursorAttr(height, spec) + ">" + inner + "</svg>";
  }

  /* 悬停读数随图存放：各月的数值编进属性，鼠标事件在挂载时才绑。
     放在属性里而不是模块变量，重绘换掉 innerHTML 后自然失效，不必手工清理。 */
  function cursorAttr(height, spec) {
    if (!spec) { return ""; }
    spec.vh = height;
    return ' data-cursor="' + Fmt.escapeHtml(JSON.stringify(spec)) + '"';
  }

  /* 单位在渲染时现取，不在模块载入时缓存：文案要等界面文案下发后才就位 */
  function readUnit(format) {
    if (format === "percent") { return Fmt.units.percent; }
    if (format === "month") { return Fmt.units.month; }
    return Fmt.units.wan;
  }

  function readValue(format, value) {
    if (format === "percent") { return Fmt.percent(value); }
    if (format === "month") { return Fmt.decimal(value, 1); }
    return Fmt.tenThousand(value);
  }

  /* 读数与刻度同一套换算。区间只写一次单位，百分比不留空格 */
  function readText(format, raw) {
    var unit = readUnit(format);
    if (raw instanceof Array) {
      return readValue(format, raw[0]) + "–" + readValue(format, raw[1]) +
        (format === "percent" ? "" : " " + unit);
    }
    return readValue(format, raw) + (format === "percent" ? "" : " " + unit);
  }

  /* 两条同长序列逐月配成区间，供分位带这类上下界的读数使用 */
  function pairs(low, high) {
    return low.map(function (value, index) { return [value, high[index]]; });
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
    return svg(VH, Catalog.text("chart.band.title"), inner, {
      months: months,
      max: max,
      format: "wan",
      rows: [
        { name: Catalog.text("chart.band.legend.range"), color: token("--chart-band", "#EBB6B7"),
          values: pairs(p10, p90) },
        { name: Catalog.text("chart.band.legend.median"), color: token("--chart-line", "#B4121A"),
          values: p50 }
      ]
    });
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
    /* 读数给每层的当月金额，累积值相减才是这一层自己的厚度 */
    var rows = order.map(function (account, index) {
      var values = [];
      for (var m = 0; m < count; m++) {
        var lower = index > 0 ? cumulative[m][order[index - 1].code] : 0;
        values.push(cumulative[m][account.code] - lower);
      }
      return { name: account.name, color: account.color, values: values };
    });
    return svg(VH, Catalog.text("chart.accounts.title"),
      axes(max, monthLabels(count), token("--chart-grid", "#EAE8EB"),
        Fmt.units.wan) + paths,
      { months: count, max: max, format: "wan", rows: rows });
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
    /* 日历的纵轴是安全垫厚度，按原值保留一位小数，不换算成万元 */
    var out = axes(max, monthLabels(count), grid, Fmt.units.month, function (value) {
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

    return svg(VH + 18, Catalog.text("chart.capacity.title"), out, {
      months: count,
      max: max,
      format: "month",
      rows: [{ name: Catalog.text("chart.capacity.legend.cushion"), color: line, values: values }]
    });
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
    return svg(VH + 18, Catalog.text("chart.paths.title"), out, {
      months: months,
      max: max,
      format: "wan",
      rows: [{ name: Catalog.text("chart.paths.legend.median"),
        color: token("--chart-line", "#B4121A"), values: sim.balancePercentiles.p50 }]
    });
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
    return svg(VH + 18, Catalog.text("chart.reach.title"), out, {
      months: months,
      max: 1,
      format: "percent",
      rows: list.map(function (item, index) {
        return { name: item.name, color: reachColor(index), values: item.curve };
      })
    });
  }

  /* ---------------------------------------------------------- 悬停读数

     刻度只有四五处，具体某个月落在多少读不出来。鼠标移到图上时，
     在最接近的那个月画一条竖线并列出当月的各条数值。
     竖线与读数框都压在图上且不吃鼠标事件，否则指针一进框就会触发
     mouseleave，画面来回闪。 */

  function mountCursors() {
    Array.prototype.forEach.call(document.querySelectorAll("svg[data-cursor]"), function (node) {
      if (node.dataset.cursorBound) { return; }
      var spec = null;
      try { spec = JSON.parse(node.getAttribute("data-cursor")); } catch (error) { spec = null; }
      if (!spec || !spec.months || !spec.rows || !spec.rows.length) { return; }
      node.dataset.cursorBound = "1";
      bindCursor(node, spec);
    });
  }

  function bindCursor(node, spec) {
    var box = node.parentElement;
    if (!box) { return; }
    /* 重绘只在同一张图上换 svg，旧的两层还留在盒子里，先清掉 */
    Array.prototype.slice.call(box.children).forEach(function (child) {
      if (child.classList.contains("cc-layer") || child.classList.contains("cc-tip")) {
        box.removeChild(child);
      }
    });
    box.classList.add("chart-live");

    var layer = document.createElement("div");
    layer.className = "cc-layer";
    layer.hidden = true;
    var line = document.createElement("i");
    line.className = "cc-line";
    line.style.top = (PADT / spec.vh * 100) + "%";
    line.style.height = ((VH - PADB - PADT) / spec.vh * 100) + "%";
    layer.appendChild(line);

    /* 每行一个圆点、区间行两个，随光标改位置，不逐月预建 */
    var dots = spec.rows.map(function (row) {
      var slots = row.values[0] instanceof Array ? 2 : 1;
      var list = [];
      for (var i = 0; i < slots; i++) {
        var dot = document.createElement("i");
        dot.className = "cc-dot";
        dot.style.background = row.color;
        layer.appendChild(dot);
        list.push(dot);
      }
      return list;
    });

    var tip = document.createElement("div");
    tip.className = "cc-tip";
    tip.hidden = true;
    box.appendChild(layer);
    box.appendChild(tip);

    /* 读数框与图共用同一个盒子。盒子被整体重绘、或别处误删了这一层时，
       下一次移动就把它补回来——否则线和点还在动，数字却悄悄没了 */
    function ensureAttached() {
      if (layer.parentElement !== box) { box.appendChild(layer); }
      if (tip.parentElement !== box) { box.appendChild(tip); }
    }

    function tipHtml(index) {
      var html = '<div class="cc-h">' +
        Fmt.escapeHtml(Catalog.text("chart.axis.month", { n: index + 1 })) + "</div>";
      spec.rows.forEach(function (row) {
        var raw = row.values[index];
        if (raw === null || raw === undefined) { return; }
        html += '<div class="cc-r"><i class="cc-swatch" style="background:' +
          Fmt.escapeHtml(row.color) + '"></i><span class="cc-k">' + Fmt.escapeHtml(row.name) +
          '</span><span class="cc-v">' + Fmt.escapeHtml(readText(spec.format, raw)) +
          "</span></div>";
      });
      return html;
    }

    function onMove(event) {
      var rect = node.getBoundingClientRect();
      if (!rect.width) { return; }
      var ratio = spec.months <= 1 ? 0 :
        ((event.clientX - rect.left) * VW / rect.width - PADL) / (VW - PADL - PADR);
      var index = Math.round(Math.min(1, Math.max(0, ratio)) * (spec.months - 1));
      var x = px(index, spec.months - 1);
      var left = (x / VW * 100) + "%";
      /* 先把读数填好再摆线点：万一后续哪一步出错，数值也已经在了 */
      ensureAttached();
      tip.innerHTML = tipHtml(index);
      tip.hidden = false;
      layer.hidden = false;
      line.style.left = left;
      spec.rows.forEach(function (row, rowIndex) {
        var raw = row.values[index];
        dots[rowIndex].forEach(function (dot, slot) {
          var value = Number(raw instanceof Array ? raw[slot] : raw) || 0;
          dot.style.left = left;
          dot.style.top = (py(value, spec.max, spec.min) / spec.vh * 100) + "%";
        });
      });
      /* 贴到右缘时把读数框翻到光标左侧，免得被卡片裁掉 */
      if (x > VW * 0.58) {
        tip.style.left = "auto";
        tip.style.right = ((VW - x) / VW * 100) + "%";
        tip.classList.add("cc-flip");
      } else {
        tip.style.right = "auto";
        tip.style.left = left;
        tip.classList.remove("cc-flip");
      }
    }

    function onLeave() {
      layer.hidden = true;
      tip.hidden = true;
    }

    node.addEventListener("mousemove", onMove);
    node.addEventListener("mouseleave", onLeave);
  }

  global.App = global.App || {};
  global.App.Charts = {
    band: band,
    mountCursors: mountCursors,
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
