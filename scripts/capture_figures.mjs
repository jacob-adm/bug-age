// Capture article figures from the built explorer page with headless Chrome (DevTools protocol).
//   node scripts/capture_figures.mjs dist/explorer/index.html article/figures
// Each figure is a clip of one element, in light theme, at 1280px wide, 2x pixel density.
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [page, outDir] = process.argv.slice(2);
const FIGURES = [
  // [file, target, CSS selector of the element to clip]
  ["overview-tokenizers.png", "tokenizers", "#overview"],
  ["timeline-tokenizers.png", "tokenizers", "#timeline .figure"],
  ["heatmap-tokenizers.png", "tokenizers", "#heatmap"],
  ["overview-rust-sdk.png", "rust-sdk", "#overview"],
];

const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${port}`,
  "--force-prefers-reduced-motion", "--blink-settings=preferredColorScheme=1", "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 50; i++) {
    try { const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); const p = list.find(t => t.type === "page"); if (p) return p; } catch {}
    await sleep(200);
  }
  throw new Error("Chrome did not start");
}

try {
  const ws = new WebSocket((await target()).webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener("open", r, { once: true }));
  let id = 0; const waiting = new Map();
  ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); } });
  const send = (method, params = {}) => new Promise((ok, bad) => { const n = ++id; waiting.set(n, m => m.error ? bad(new Error(method + ": " + m.error.message)) : ok(m.result)); ws.send(JSON.stringify({ id: n, method, params })); });
  const evaluate = async expr => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;

  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 2, mobile: false });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }, { name: "prefers-reduced-motion", value: "reduce" }] });
  await send("Page.enable");
  mkdirSync(outDir, { recursive: true });
  for (const [file, name, selector] of FIGURES) {
    await send("Page.navigate", { url: "file://" + resolve(page) });
    await sleep(1500);
    await evaluate(`document.querySelector('#switch [data-name="${name}"]')?.click(); document.fonts.ready.then(() => true)`);
    await sleep(300);
    const box = await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
      return { x: r.left + scrollX - 8, y: r.top + scrollY - 8, width: r.width + 16, height: r.height + 16 }; })()`);
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { ...box, scale: 1 } });
    writeFileSync(`${outDir}/${file}`, Buffer.from(shot.data, "base64"));
    console.log(`${file}: ${Math.round(box.width)}x${Math.round(box.height)} css px`);
  }
  ws.close();
} finally {
  chrome.kill();
}
