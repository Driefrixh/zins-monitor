// Variables used by Scriptable.
// These must be at the very top of the file. Comments must be translated.
// icon-color: deep-blue; icon-glyph: chart-line;

// ---------------------------------------------------------------------------
// Zins-Widget
// Liest die von der GitHub Action erzeugte latest.json und zeigt die
// Rendite 10-jaehriger AAA-Staatsanleihen auf dem Homescreen.
//
// Einrichtung: die drei Konstanten unten anpassen, Skript in Scriptable
// speichern, dann auf dem Homescreen ein Scriptable-Widget hinzufuegen
// und dieses Skript auswaehlen.
// ---------------------------------------------------------------------------

const GITHUB_USER = "DEIN-GITHUB-NAME";
const GITHUB_REPO = "zins-monitor";
const GITHUB_BRANCH = "main";

const DATA_URL =
  `https://raw.githubusercontent.com/${GITHUB_USER}/${GITHUB_REPO}` +
  `/${GITHUB_BRANCH}/data/latest.json`;

// Farblogik aus Kreditnehmersicht: steigende Zinsen sind schlecht.
const COLOR_UP = "e5484d";
const COLOR_DOWN = "30a46c";
const COLOR_FLAT = "8b8d98";

const CACHE_FILE = "zins_latest_cache.json";

// ---------------------------------------------------------------------------
// Daten laden (mit lokalem Cache als Offline-Fallback)
// ---------------------------------------------------------------------------

async function loadData() {
  const fm = FileManager.local();
  const cachePath = fm.joinPath(fm.cacheDirectory(), CACHE_FILE);

  try {
    // Query-Parameter umgeht den CDN-Cache von raw.githubusercontent.com
    const req = new Request(`${DATA_URL}?t=${Date.now()}`);
    req.timeoutInterval = 15;
    const data = await req.loadJSON();
    fm.writeString(cachePath, JSON.stringify(data));
    return { data, stale: false };
  } catch (e) {
    if (fm.fileExists(cachePath)) {
      return { data: JSON.parse(fm.readString(cachePath)), stale: true };
    }
    throw e;
  }
}

// ---------------------------------------------------------------------------
// Hilfsfunktionen
// ---------------------------------------------------------------------------

function de(value, digits = 2) {
  return value.toFixed(digits).replace(".", ",");
}

function deltaColor(bp) {
  if (bp > 0.5) return COLOR_UP;
  if (bp < -0.5) return COLOR_DOWN;
  return COLOR_FLAT;
}

function deltaText(bp) {
  const sign = bp > 0.5 ? "▲ +" : bp < -0.5 ? "▼ −" : "▬ ±";
  return `${sign}${de(Math.abs(bp), 1)} Bp`;
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

// ---------------------------------------------------------------------------
// Sparkline
// ---------------------------------------------------------------------------

function sparkline(values, width, height, hexColor) {
  const ctx = new DrawContext();
  ctx.size = new Size(width, height);
  ctx.opaque = false;
  ctx.respectScreenScale = true;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;

  const px = (i) => (i / (values.length - 1)) * (width - 2 * pad) + pad;
  const py = (v) => height - pad - ((v - min) / span) * (height - 2 * pad);

  // Flaeche unter der Linie
  const area = new Path();
  area.move(new Point(px(0), py(values[0])));
  values.forEach((v, i) => area.addLine(new Point(px(i), py(v))));
  area.addLine(new Point(px(values.length - 1), height));
  area.addLine(new Point(px(0), height));
  area.closeSubpath();
  ctx.setFillColor(new Color(hexColor, 0.14));
  ctx.addPath(area);
  ctx.fillPath();

  // Linie
  const line = new Path();
  line.move(new Point(px(0), py(values[0])));
  values.forEach((v, i) => line.addLine(new Point(px(i), py(v))));
  ctx.setStrokeColor(new Color(hexColor, 1));
  ctx.setLineWidth(2);
  ctx.addPath(line);
  ctx.strokePath();

  // Punkt am aktuellen Wert
  const r = 3;
  const lastX = px(values.length - 1);
  const lastY = py(values[values.length - 1]);
  ctx.setFillColor(new Color(hexColor, 1));
  ctx.fillEllipse(new Rect(lastX - r, lastY - r, r * 2, r * 2));

  return ctx.getImage();
}

// ---------------------------------------------------------------------------
// Widget-Aufbau
// ---------------------------------------------------------------------------

function buildWidget(payload, stale) {
  const family = config.widgetFamily || "medium";
  const lead = payload.series[payload.lead];
  const d1 = lead.deltas["1T"] ?? 0;
  const accent = deltaColor(d1);

  const w = new ListWidget();
  w.setPadding(14, 16, 14, 16);
  w.backgroundColor = Color.dynamic(new Color("ffffff"), new Color("14161a"));
  w.url = `https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y`;

  // Kopfzeile
  const head = w.addStack();
  head.centerAlignContent();
  const title = head.addText(
    family === "small" ? "Rendite 10J" : "Rendite Bundesanleihen 10J"
  );
  title.font = Font.mediumSystemFont(11);
  title.textColor = new Color("8b8d98");
  head.addSpacer();
  const day = head.addText(formatDate(payload.date) + (stale ? " ⚠︎" : ""));
  day.font = Font.systemFont(10);
  day.textColor = new Color("8b8d98");

  w.addSpacer(family === "small" ? 4 : 6);

  // Hauptwert
  const main = w.addStack();
  main.bottomAlignContent();
  const value = main.addText(de(lead.value) + " %");
  value.font = Font.boldSystemFont(family === "small" ? 30 : 36);
  value.textColor = Color.dynamic(new Color("11181c"), new Color("f1f3f5"));
  main.addSpacer(8);
  const delta = main.addText(deltaText(d1));
  delta.font = Font.semiboldSystemFont(13);
  delta.textColor = new Color(accent);

  w.addSpacer(family === "small" ? 6 : 8);

  // Sparkline
  const values = payload.spark.values;
  if (values && values.length > 2) {
    const img = w.addImage(
      sparkline(values, family === "small" ? 130 : 300, family === "small" ? 34 : 52, accent)
    );
    img.applyFittingContentMode();
  }

  if (family === "small") {
    w.addSpacer(4);
    const foot = w.addText(`1M ${deltaText(lead.deltas["1M"] ?? 0)}`);
    foot.font = Font.systemFont(10);
    foot.textColor = new Color("8b8d98");
  } else {
    w.addSpacer(8);

    // Zeile: Veraenderungen ueber verschiedene Zeitraeume
    const row = w.addStack();
    ["1W", "1M", "3M", "1J"].forEach((h, i) => {
      if (!(h in lead.deltas)) return;
      if (i > 0) row.addSpacer();
      const cell = row.addStack();
      cell.layoutVertically();
      const l = cell.addText(h);
      l.font = Font.systemFont(9);
      l.textColor = new Color("8b8d98");
      const v = cell.addText(deltaText(lead.deltas[h]));
      v.font = Font.semiboldSystemFont(11);
      v.textColor = new Color(deltaColor(lead.deltas[h]));
    });

    if (family === "large") {
      w.addSpacer(10);
      Object.keys(payload.series).forEach((sid) => {
        if (sid === payload.lead) return;
        const s = payload.series[sid];
        const r = w.addStack();
        r.centerAlignContent();
        const l = r.addText(s.label);
        l.font = Font.systemFont(12);
        l.textColor = new Color("8b8d98");
        r.addSpacer();
        const v = r.addText(de(s.value) + " %");
        v.font = Font.semiboldSystemFont(12);
        v.textColor = Color.dynamic(new Color("11181c"), new Color("f1f3f5"));
        r.addSpacer(8);
        const dd = r.addText(deltaText(s.deltas["1T"] ?? 0));
        dd.font = Font.systemFont(11);
        dd.textColor = new Color(deltaColor(s.deltas["1T"] ?? 0));
        w.addSpacer(3);
      });
    }
  }

  w.refreshAfterDate = new Date(Date.now() + 60 * 60 * 1000);
  return w;
}

function errorWidget(message) {
  const w = new ListWidget();
  w.setPadding(14, 16, 14, 16);
  const t = w.addText("Zinsdaten nicht verfügbar");
  t.font = Font.semiboldSystemFont(13);
  w.addSpacer(4);
  const m = w.addText(String(message));
  m.font = Font.systemFont(10);
  m.textColor = new Color("8b8d98");
  return w;
}

// ---------------------------------------------------------------------------

let widget;
try {
  const { data, stale } = await loadData();
  widget = buildWidget(data, stale);
} catch (e) {
  widget = errorWidget(e.message);
}

if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  await widget.presentMedium();
}
Script.complete();
