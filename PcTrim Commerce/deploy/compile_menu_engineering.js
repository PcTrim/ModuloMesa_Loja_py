#!/usr/bin/env node
/** Regenera menu-engineering.bundle.js a partir do JSX fonte. Rode após editar menu-engineering.js */
const fs = require("fs");
const vm = require("vm");
const https = require("https");

const ROOT = __dirname.replace(/[\\/]deploy$/, "");
const SRC = `${ROOT}/static/menu-engineering/menu-engineering.js`;
const OUT = `${ROOT}/static/menu-engineering/menu-engineering.bundle.js`;
const BABEL_URL = "https://unpkg.com/@babel/standalone@7.26.9/babel.min.js";

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => resolve(data));
    }).on("error", reject);
  });
}

(async () => {
  const source = fs.readFileSync(SRC, "utf8");
  const babelSrc = await get(BABEL_URL);
  const ctx = { console };
  vm.createContext(ctx);
  vm.runInContext(babelSrc, ctx);
  const out = ctx.Babel.transform(source, { presets: ["react"] }).code;
  fs.writeFileSync(OUT, out, "utf8");
  console.log(`==> ${OUT} (${out.length} bytes)`);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
