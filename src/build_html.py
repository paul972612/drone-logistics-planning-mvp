"""Step 3: Inline data, routing engine and h3-js into a single self-contained HTML map.

Usage: python src/build_html.py <data.json> <out.html>
"""
import json, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(sys.argv[1]))
for k in ["routes", "kpis", "pois"]: d.pop(k, None)          # fixed demo routes are not used in the interactive map
if d.get("sora"): d["sora"].pop("routes", None); d["sora"].pop("kpi", None)
t = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
eng = open(os.path.join(HERE, "engine.js"), encoding="utf-8").read().replace('if (typeof module !== "undefined") module.exports = { buildEngine };', "")
h3 = open(os.path.join(HERE, "vendor", "h3-js.umd.js"), encoding="utf-8").read()
out = t.replace("__ENGINE__", eng).replace("__DATA__", json.dumps(d, separators=(",", ":"))).replace("__H3__", h3)
open(sys.argv[2], "w", encoding="utf-8").write(out)
print(f"written {sys.argv[2]} ({len(out)/1e6:.1f} MB)")
