// Routing-Engine (läuft im Browser; in Node testbar)
function buildEngine(D, h3) {
  const N = D.cells.length, idx = new Map();
  const cost = new Float64Array(N), fp = new Uint8Array(N), ew = new Float64Array(N),
        lab = new Uint8Array(N), fl = new Uint8Array(N), hm = new Float32Array(N), ho = new Float32Array(N), ids = new Array(N);
  D.cells.forEach((c, i) => { ids[i] = c[0]; idx.set(c[0], i); cost[i] = c[1] < 0 ? Infinity : c[1];
    fp[i] = c[2]; ew[i] = c[3]; lab[i] = c[4]; fl[i] = c[5]; hm[i] = c[6]; ho[i] = c[7] || 0; });
  const nbCache = new Array(N);
  const nb = i => nbCache[i] || (nbCache[i] = h3.gridDisk(ids[i], 1).filter(x => x !== ids[i] && idx.has(x)).map(x => idx.get(x)));
  const isBuffer = D.labels.map(l => l.endsWith("+100 m"));
  const STEP = D.step_km;
  const ll = i => h3.cellToLatLng(ids[i]);
  function hav(a, b) { const R = Math.PI / 180, dLa = (b[0] - a[0]) * R, dLo = (b[1] - a[1]) * R;
    const h = Math.sin(dLa / 2) ** 2 + Math.cos(a[0] * R) * Math.cos(b[0] * R) * Math.sin(dLo / 2) ** 2; return 12742 * Math.asin(Math.sqrt(h)); }
  function heap() { const a = []; return {
    push(p, v) { a.push([p, v]); let i = a.length - 1; while (i > 0) { const j = (i - 1) >> 1; if (a[j][0] <= a[i][0]) break; [a[i], a[j]] = [a[j], a[i]]; i = j; } },
    pop() { const top = a[0], last = a.pop(); if (a.length) { a[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let m = i;
      if (l < a.length && a[l][0] < a[m][0]) m = l; if (r < a.length && a[r][0] < a[m][0]) m = r; if (m === i) break; [a[i], a[m]] = [a[m], a[i]]; i = m; } } return top; },
    get size() { return a.length; } }; }
  function dijkstra(s, t, term, allowed) {
    const dist = new Float64Array(N).fill(Infinity), prev = new Int32Array(N).fill(-1), q = heap();
    dist[s] = 0; q.push(0, s);
    const c = i => { const v = cost[i]; return v === Infinity ? (term.has(i) ? 20 : Infinity) : v; };
    while (q.size) { const [d, u] = q.pop(); if (u === t) break; if (d > dist[u]) continue;
      for (const v of nb(u)) { if (allowed && !allowed(v)) continue; const cv = v === t ? 1 : c(v); if (cv === Infinity) continue;
        const cu = c(u) === Infinity ? 1 : c(u), nd = d + STEP * (cu + cv) / 2;
        if (nd < dist[v]) { dist[v] = nd; prev[v] = u; q.push(nd, v); } } }
    if (s !== t && prev[t] < 0) return null;
    const p = [t]; while (p[p.length - 1] !== s) p.push(prev[p[p.length - 1]]); return p.reverse();
  }
  const len = p => { let L = 0; for (let i = 1; i < p.length; i++) L += hav(ll(p[i - 1]), ll(p[i])); return L; };
  const uniq = p => [...new Set(p)];
  function stats(p, term) {
    const u = uniq(p), core = u.filter(i => !term.has(i));
    let e = 0, q = 0, h = 0, h2 = 0; u.forEach(i => { e += ew[i]; h = Math.max(h, hm[i]); h2 = Math.max(h2, ho[i]); });
    for (let k = 1; k < p.length; k++) if (isBuffer[lab[p[k]]] && !isBuffer[lab[p[k - 1]]]) q++;
    return { km: len(p), ew: e, igrc: core.length ? Math.max(...core.map(i => fp[i])) : null, q, h, h2 };
  }
  function route(a, b, speed) {   // a,b = [lat,lng]
    const sid = h3.latLngToCell(a[0], a[1], D.res), tid = h3.latLngToCell(b[0], b[1], D.res);
    if (!idx.has(sid) || !idx.has(tid)) return { error: "Punkt liegt außerhalb des Untersuchungsraums." };
    const s = idx.get(sid), t = idx.get(tid);
    if (h3.gridDistance(sid, tid) < 4) return { error: "Start und Ziel liegen zu nah beieinander (< ca. 400 m)." };
    const term = new Set([...h3.gridDisk(sid, 3), ...h3.gridDisk(tid, 3)].filter(x => idx.has(x)).map(x => idx.get(x)));
    const w = dijkstra(s, t, term);
    if (!w) return { error: "Keine Route gefunden." };
    // Luftlinie
    const line = []; for (let k = 0; k <= 200; k++) { const f = k / 200; const c = h3.latLngToCell(a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), D.res); if (idx.has(c)) line.push(idx.get(c)); }
    const direct = hav(a, b), sw = stats(w, term), sl = stats(uniq(line), term);
    sl.km = direct;
    const termI = Math.max(...[...term].map(i => fp[i]));
    // SORA-Alternative: niedrigste Streckenklasse mit max. 1,5× Länge der gewichteten Route
    let alt = null;
    for (let T = 3; T < sw.igrc; T++) {
      const p = dijkstra(s, t, term, i => fp[i] <= T || term.has(i));
      if (p && len(p) <= 1.5 * sw.km) { alt = { path: p, ...stats(p, term) }; break; }
    }
    return { path: w, line: uniq(line), w: sw, l: sl, termI, alt, direct, min: sw.km / speed * 60,
             coords: w.map(i => ll(i)), altCoords: alt ? alt.path.map(i => ll(i)) : null };
  }
  function bilanz(paths) {
    const u = new Set(paths.flat()); let tot = 0, r = 0, au = 0, o = 0;
    u.forEach(i => { tot += ew[i]; if (fl[i] & 1) r += ew[i]; if (fl[i] & 2) au += ew[i]; if (fl[i] & 4) o += ew[i]; });
    const pc = x => tot ? Math.round(100 * x / tot) : null;
    return { ew: Math.round(tot / 10) * 10, miete_unten: pc(r), aus_oben: pc(au), a65_oben: pc(o) };
  }
  return { route, bilanz };
}
if (typeof module !== "undefined") module.exports = { buildEngine };
