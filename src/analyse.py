"""Step 1: Restriction grid, population density (Census 2022), simplified SORA 2.5 ground risk,
socio-spatial indicators and per-cell export for in-browser routing.

Usage: python src/analyse.py <osm_restrictions.geojson> <data_out.json> <zensus_population.zip> <zensus_social.zip>
Study area (BBOX), H3 resolution, drone class and cost weights are set at the top of this file.
Comments are partly in German.
"""
import json, sys, heapq, math
import geopandas as gpd, pandas as pd, h3
from shapely.geometry import Polygon, Point, LineString, mapping

SRC = sys.argv[1]; OUT = sys.argv[2]; ZENSUS = sys.argv[3] if len(sys.argv) > 3 else None; SOZ = sys.argv[4] if len(sys.argv) > 4 else None
RES = 10                      # H3 ~ 66 m Kantenlänge
SPEED_KMH = 60                # Annahme Reisegeschwindigkeit
BBOX = (52.60, 13.44, 52.71, 13.63)

g = gpd.read_file(SRC).to_crs(25833)
def tag(r, k): return r[k] if k in r and pd.notna(r[k]) else None

# --- Restriktionsklassen (vereinfacht, angelehnt an § 21h LuftVO) ---
# cost: 1 frei | 3 Schutzgebiet | 4 Gewerbe/Industrie | 6 Wohngebiet | 10 Verkehrs-/Energietrasse (100 m) | 20 Krankenhaus (100 m) | inf Naturschutzgebiet
rules = []
for _, r in g.iterrows():
    geom = r.geometry
    lu, hw, rw, pw, le, bd, am = (tag(r,k) for k in ["landuse","highway","railway","power","leisure","boundary","amenity"])
    pc = tag(r, "protect_class")
    if le == "nature_reserve" or (bd == "protected_area" and pc == "4"):
        rules.append((geom, math.inf, "Naturschutzgebiet"))
    elif bd == "protected_area":
        rules.append((geom, 3, "sonstiges Schutzgebiet"))
    elif am == "hospital" and geom.geom_type != "Point":
        rules.append((geom.buffer(100), 20, "Krankenhaus +100 m"))
    elif hw or rw or pw:
        lbl = {"motorway":"Autobahn","primary":"Hauptstraße"}.get(hw, "Bahn" if rw else "Stromleitung")
        rules.append((geom.buffer(100), 10, f"{lbl} +100 m"))
    elif lu == "residential":
        rules.append((geom, 6 if not ZENSUS else 1.01, "Wohngebiet"))
    elif lu in ("industrial","commercial","retail"):
        rules.append((geom, 4, "Gewerbe/Industrie"))
R = gpd.GeoDataFrame([{"cost":c,"label":l} for _,c,l in rules], geometry=[x for x,_,_ in rules], crs=25833)

# --- Hexgitter ---
poly = Polygon([(BBOX[1],BBOX[0]),(BBOX[3],BBOX[0]),(BBOX[3],BBOX[2]),(BBOX[1],BBOX[2])])
cells = list(h3.geo_to_cells(h3.geo_to_h3shape(mapping(poly)), RES))
hexes = gpd.GeoDataFrame({"h3":cells}, geometry=[Polygon([(lng,lat) for lat,lng in h3.cell_to_boundary(c)]) for c in cells], crs=4326).to_crs(25833)
j = gpd.sjoin(hexes, R, how="left", predicate="intersects")
j = j.reset_index(drop=True); j["cost"] = j["cost"].fillna(1)
idx = j.groupby("h3")["cost"].idxmax()
best = j.loc[idx, ["h3","cost","label"]].set_index("h3")
hexes = hexes.set_index("h3").join(best)
hexes["label"] = hexes["label"].fillna("frei")

# --- Zensus 2022: Einwohnerdichte (Bodenrisiko) ---
hexes["ew"] = 0.0; hexes["dichte"] = 0.0; dens_hex = None
if ZENSUS:
    import zipfile
    from pyproj import Transformer
    z = zipfile.ZipFile(ZENSUS)
    name = [n for n in z.namelist() if "100m" in n.lower() and n.lower().endswith(".csv")][0]
    tr = Transformer.from_crs(4326, 3035, always_xy=True)
    xs, ys = zip(*[tr.transform(lo, la) for la in (BBOX[0], BBOX[2]) for lo in (BBOX[1], BBOX[3])])
    parts = []
    for ch in pd.read_csv(z.open(name), sep=";", dtype=str, chunksize=500_000, encoding="latin-1"):
        cx = [c for c in ch.columns if "x_mp" in c.lower()][0]; cy = [c for c in ch.columns if "y_mp" in c.lower()][0]
        cp = [c for c in ch.columns if "einwohner" in c.lower()][0]
        x = pd.to_numeric(ch[cx], errors="coerce"); y = pd.to_numeric(ch[cy], errors="coerce")
        m = (x >= min(xs)-100) & (x <= max(xs)+100) & (y >= min(ys)-100) & (y <= max(ys)+100)
        if m.any(): parts.append(pd.DataFrame({"x": x[m], "y": y[m], "ew": pd.to_numeric(ch.loc[m, cp], errors="coerce").fillna(0)}))
    zc = pd.concat(parts); print("Zensus-Zellen im Raum:", len(zc), "Einwohner:", int(zc.ew.sum()))
    back = Transformer.from_crs(3035, 4326, always_xy=True)
    lon, lat = back.transform(zc.x.values, zc.y.values)
    zc["h9"] = [h3.latlng_to_cell(a, b, RES-1) for a, b in zip(lat, lon)]
    p9 = zc.groupby("h9").ew.sum()
    a9 = h3.average_hexagon_area(RES-1, "km^2"); a10 = h3.average_hexagon_area(RES, "km^2")
    d9 = (p9 / a9).to_dict()
    hexes["dichte"] = [d9.get(h3.cell_to_parent(c, RES-1), 0.0) for c in hexes.index]
    hexes["ew"] = hexes["dichte"] * a10
    def dcost(d):  # grob nach SORA-Dichteklassen
        return 1 if d < 5 else 1.5 if d < 50 else 3 if d < 500 else 6 if d < 5000 else 10
    hexes["cost"] = [max(c, dcost(d)) if not math.isinf(c) else c for c, d in zip(hexes["cost"], hexes["dichte"])]
    cls = lambda d: "< 50" if d < 50 else "50–500" if d < 500 else "500–5.000" if d < 5000 else "> 5.000"
    dens_hex = gpd.GeoDataFrame({"klasse": [cls(v) for v in p9.values / a9], "dichte": (p9.values / a9).round(0)},
        geometry=[Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in p9.index], crs=4326)
    dens_hex = dens_hex[dens_hex.dichte >= 50]
cost = hexes["cost"].to_dict()

# --- Hub & Ziele ---
def find(name):
    m = g[g["name"] == name]
    return m.to_crs(4326).geometry.iloc[0].centroid
hub_name = "HELIOS Klinikum Berlin Buch"
targets = ["Heine Apotheke","Luisen Apotheke","Apotheke Schönow","Bären-Apotheke","Pelikan-Apotheke","Immanuel Klinikum Bernau Herzzentrum Brandenburg"]
hub = find(hub_name)
hub_c = h3.latlng_to_cell(hub.y, hub.x, RES)

# --- Dijkstra auf dem Hexgitter ---
step_km = h3.average_hexagon_edge_length(RES, "km") * math.sqrt(3)
def route(src, dst):
    dist = {src:0}; prev = {}; pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst: break
        if d > dist[u]: continue
        for v in h3.grid_ring(u, 1):
            if v not in cost: continue
            cv = cost[v] if v != dst else 1
            if math.isinf(cv): continue
            nd = d + step_km * (cost.get(u,1) if not math.isinf(cost.get(u,1)) else 1 + cv) / 2
            if nd < dist.get(v, math.inf):
                dist[v] = nd; prev[v] = u; heapq.heappush(pq, (nd, v))
    path = [dst]
    while path[-1] != src: path.append(prev[path[-1]])
    return path[::-1]

def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, [a[0],a[1],b[0],b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*6371*math.asin(math.sqrt(h))

routes = []; kpis = []; paths_w = {}; lines_c = {}
for t in targets:
    p = find(t); tc = h3.latlng_to_cell(p.y, p.x, RES)
    path = route(hub_c, tc)
    paths_w[t] = path
    coords = [h3.cell_to_latlng(c) for c in path]
    length = sum(hav(coords[i], coords[i+1]) for i in range(len(coords)-1))
    direct = hav((hub.y, hub.x), (p.y, p.x))
    labels = [hexes.loc[c, "label"] for c in path]
    res_share = sum(l == "Wohngebiet" for l in labels) / len(labels)
    crossings = sum(1 for i in range(1,len(labels)) if labels[i].endswith("+100 m") and not labels[i-1].endswith("+100 m"))
    # Luftlinie: Anteil über Wohngebiet / durch NSG
    line = LineString([(hub.x,hub.y),(p.x,p.y)])
    pts = [line.interpolate(f, normalized=True) for f in [i/200 for i in range(201)]]
    lc = [h3.latlng_to_cell(q.y,q.x,RES) for q in pts]
    lines_c[t] = lc
    direct_nsg = any(math.isinf(cost.get(c,1)) for c in lc)
    direct_res = sum(hexes.loc[c,"label"]=="Wohngebiet" for c in lc if c in cost)/len(lc)
    ew_route = hexes.loc[list(dict.fromkeys(path)), "ew"].sum()
    ew_luft = hexes.loc[[c for c in dict.fromkeys(lc) if c in cost], "ew"].sum()
    short = t.replace(" Herzzentrum Brandenburg","")
    kpis.append(dict(ziel=short, luftlinie_km=round(direct,2), route_km=round(length,2),
        umweg=round(length/direct,2), flugzeit_min=round(length/SPEED_KMH*60,1),
        wohn_route=round(res_share*100), wohn_luftlinie=round(direct_res*100),
        querungen=crossings, ew_route=int(round(ew_route, -1)), ew_luftlinie=int(round(ew_luft, -1)), luftlinie_durch_nsg=direct_nsg))
    routes.append(dict(ziel=short, coords=[[lng,lat] for lat,lng in coords], target=[p.x,p.y]))


# --- SORA 2.5 (vereinfacht): iGRC je Wabe und Minimax-Routing ---
# Spalte: max. Abmessung <= 3 m, max. Geschwindigkeit <= 35 m/s (typische Lieferdrohne)
def igrc(d):
    return 3 if d < 5 else 4 if d < 50 else 5 if d < 500 else 6 if d < 5000 else 7 if d < 50000 else 8
sora = None
if ZENSUS:
    cell_i = {c: igrc(d) for c, d in hexes["dichte"].items()}
    # Fußabdruck = Zelle + 1 Ring (~115 m) als Näherung für Contingency Volume + Ground Risk Buffer (1:1 bei ~100 m Flughöhe)
    fp = {c: max(cell_i.get(n, cell_i[c]) for n in h3.grid_disk(c, 1)) for c in cell_i}
    TERM_K = 3   # Start-/Landezone ~350 m: gesondert ausgewiesen
    def route_allowed(src, dst, allowed):
        dist = {src: 0}; prev = {}; pq = [(0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst: break
            if d > dist[u]: continue
            for v in h3.grid_ring(u, 1):
                if v not in allowed: continue
                cv = cost[v] if v != dst else 1
                if math.isinf(cv): continue
                cu = cost.get(u, 1); cu = 1 if math.isinf(cu) else cu
                nd = d + step_km * (cu + cv) / 2
                if nd < dist.get(v, math.inf):
                    dist[v] = nd; prev[v] = u; heapq.heappush(pq, (nd, v))
        if dst not in prev and dst != src: return None
        path = [dst]
        while path[-1] != src: path.append(prev[path[-1]])
        return path[::-1]
    sora_routes = []; sora_kpi = []; paths_s = {}
    for t in targets:
        p = find(t); tc = h3.latlng_to_cell(p.y, p.x, RES)
        term = set(h3.grid_disk(hub_c, TERM_K)) | set(h3.grid_disk(tc, TERM_K))
        found = None
        for T in range(3, 9):
            allowed = {c for c in cost if (fp[c] <= T or c in term)}
            path = route_allowed(hub_c, tc, allowed)
            if path: found = (T, path); break
        T, path = found
        paths_s[t] = path
        coords = [h3.cell_to_latlng(c) for c in path]
        length = sum(hav(coords[i], coords[i+1]) for i in range(len(coords)-1))
        line = LineString([(hub.x, hub.y), (p.x, p.y)])
        lc = list(dict.fromkeys(h3.latlng_to_cell(q.y, q.x, RES) for q in [line.interpolate(f/200, normalized=True) for f in range(201)]))
        luft_i = max(fp[c] for c in lc if c in fp and c not in term)
        term_i = max(max(fp[c] for c in h3.grid_disk(hub_c, TERM_K) if c in fp), max(fp[c] for c in h3.grid_disk(tc, TERM_K) if c in fp))
        short = t.replace(" Herzzentrum Brandenburg", "")
        ew = hexes.loc[list(dict.fromkeys(path)), "ew"].sum()
        sora_kpi.append(dict(ziel=short, igrc_luftlinie=luft_i, igrc_route=T, igrc_terminal=term_i,
                             route_km=round(length, 2), umweg=round(length / hav((hub.y, hub.x), (p.y, p.x)), 2), ew=int(round(ew, -1))))
        sora_routes.append(dict(ziel=short, coords=[[lng, lat] for lat, lng in coords]))
    # Fläche je iGRC-Klasse (Fußabdruck)
    fp_share = pd.Series(fp).value_counts(normalize=True).sort_index().mul(100).round(1).to_dict()
    fp_gdf = gpd.GeoDataFrame({"igrc": list(fp.values())},
        geometry=[Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in fp], crs=4326)
    fp_gdf = fp_gdf.dissolve(by="igrc").reset_index()
    fp_gdf["geometry"] = fp_gdf.geometry.simplify(0.00005)
    sora = dict(kpi=sora_kpi, routes=sora_routes, share={int(k): v for k, v in fp_share.items()},
                layer=json.loads(fp_gdf.to_json()))
    print(pd.DataFrame(sora_kpi).to_string(index=False)); print("iGRC-Flächenanteile:", fp_share)

# --- Sozialräumliche Zensus-Merkmale + Gebäudehöhen-Schätzung ---
soz = None
if SOZ and ZENSUS:
    import zipfile
    zz = zipfile.ZipFile(SOZ)
    def rd(n):
        df = pd.read_csv(zz.open(n + ".csv"), sep=";", dtype=str, encoding="latin-1")
        df["x"] = pd.to_numeric(df["x_mp_100m"]); df["y"] = pd.to_numeric(df["y_mp_100m"])
        return df
    num = lambda v: pd.to_numeric(v.str.replace(",", ".", regex=False), errors="coerce")
    base = zc[["x", "y", "ew", "h9"]].copy()
    u = rd("ue65"); u["a65"] = num(u["AnteilUeber65"])
    a = rd("auslaender"); a["aus"] = num(a["AnteilAuslaender"])
    m = rd("miete"); m["miete"] = num(m["durchschnMieteQM"])
    gb = rd("gebaeude")
    typ = {"FreiEFH": 9, "EFH_DHH": 9, "EFH_Reihenhaus": 9, "Freist_ZFH": 9, "ZFH_DHH": 9, "ZFH_Reihenhaus": 9,
           "AndererGebaeudetyp": 10, "MFH_3bis6Wohnungen": 12, "MFH_7bis12Wohnungen": 15, "MFH_13undmehrWohnungen": 24}
    for c in typ: gb[c] = num(gb[c]).fillna(0)
    gb["h_max"] = gb.apply(lambda r: max([h for c, h in typ.items() if r[c] > 0], default=float("nan")), axis=1)
    gb["n13"] = gb["MFH_13undmehrWohnungen"]
    b = base.merge(u[["x","y","a65"]], on=["x","y"], how="left").merge(a[["x","y","aus"]], on=["x","y"], how="left") \
            .merge(m[["x","y","miete"]], on=["x","y"], how="left").merge(gb[["x","y","h_max","n13"]], on=["x","y"], how="left")
    b["ew65"] = b.ew * b.a65 / 100; b["ewaus"] = b.ew * b.aus / 100
    b["ew_a65"] = b.ew.where(b.a65.notna(), 0); b["ew_aus"] = b.ew.where(b.aus.notna(), 0)
    b["mw"] = b.miete * b.ew; b["ew_m"] = b.ew.where(b.miete.notna(), 0)
    g9 = b.groupby("h9").agg(ew=("ew","sum"), ew65=("ew65","sum"), ew_a65=("ew_a65","sum"), ewaus=("ewaus","sum"),
                              ew_aus=("ew_aus","sum"), mw=("mw","sum"), ew_m=("ew_m","sum"), h_max=("h_max","max"), n13=("n13","sum"))
    g9["a65"] = (g9.ew65 / g9.ew_a65 * 100).where(g9.ew_a65 > 0)
    g9["aus"] = (g9.ewaus / g9.ew_aus * 100).where(g9.ew_aus > 0)
    g9["miete"] = (g9.mw / g9.ew_m).where(g9.ew_m > 0)
    # Erreichbarkeit: Luftliniendistanz zur nächsten Apotheke (nur Apotheken im Ausschnitt -> Randzellen überschätzt)
    ph = [(r.geometry.centroid.y, r.geometry.centroid.x) for _, r in g.to_crs(4326).iterrows() if r.get("amenity") == "pharmacy"]
    g9["apo_km"] = [min(hav(h3.cell_to_latlng(c), p) for p in ph) for c in g9.index]
    g9["ew65_fern"] = g9.ew65.where(g9.apo_km > 1, 0)
    # Terzile (einwohnergewichtet) für Verteilungsbilanz, auf Wabe-10 übertragen
    def tercile(col, hi=False):
        v = g9[[col, "ew"]].dropna().sort_values(col, ascending=not hi)
        cum = v.ew.cumsum() / v.ew.sum()
        return set(v.index[cum <= 1/3])
    low_rent = tercile("miete"); high_aus = tercile("aus", hi=True); high_65 = tercile("a65", hi=True)
    def bilanz(paths):
        cells = {c for p in paths for c in p}
        ew_tot = sum(hexes.loc[c, "ew"] for c in cells if c in hexes.index)
        share = lambda S: round(100 * sum(hexes.loc[c, "ew"] for c in cells if h3.cell_to_parent(c, RES-1) in S) / ew_tot) if ew_tot else None
        return dict(ew=int(round(ew_tot, -1)), miete_unten=share(low_rent), aus_oben=share(high_aus), a65_oben=share(high_65))
    # Basis: Anteil an allen EW (mit Wert) -> per Konstruktion ~33 %, aber wegen Lücken neu berechnen
    allc = [c for c in hexes.index]
    base_b = bilanz([allc])
    vb = dict(luftlinie=bilanz(lines_c.values()), gewichtet=bilanz(paths_w.values()), sora=bilanz(paths_s.values()), raum=base_b)
    # Gebäudehöhe entlang Routen
    hmax = g9.h_max.to_dict()
    def route_h(p): 
        vals = [hmax.get(h3.cell_to_parent(c, RES-1)) for c in p]; vals = [v for v in vals if v == v and v is not None]
        return max(vals) if vals else None
    for k in kpis:
        t = [x for x in targets if x.startswith(k["ziel"])][0]
        k["h_route"] = route_h(paths_w[t]); k["h_luft"] = route_h([c for c in lines_c[t] if c in cost])
    soz_g = gpd.GeoDataFrame(g9[["ew","a65","aus","miete","h_max","n13","apo_km","ew65_fern"]].round(1).reset_index(),
        geometry=[Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in g9.index], crs=4326)
    soz_g = soz_g[soz_g.ew >= 10]
    soz = dict(layer=json.loads(soz_g.drop(columns="h9").to_json()), bilanz=vb,
               ew65_fern=int(g9.ew65_fern.sum()), ew65=int(g9.ew65.sum()))
    print("Verteilungsbilanz:", vb); print("65+ gesamt / >1km Apotheke:", soz["ew65"], soz["ew65_fern"])
    print("Höhenklassen (Waben):", g9.h_max.value_counts().to_dict())

# --- Export je Wabe für Routing im Browser (v5) ---
LABELS = sorted(hexes["label"].unique())
cells_out = []
if ZENSUS and SOZ:
    for c, r in hexes.iterrows():
        p = h3.cell_to_parent(c, RES-1)
        fl = (1 if p in low_rent else 0) | (2 if p in high_aus else 0) | (4 if p in high_65 else 0)
        hm = hmax.get(p); hm = 0 if hm is None or hm != hm else hm
        cc = cost[c]
        cells_out.append([c, -1 if math.isinf(cc) else round(cc, 2), fp[c], round(r["ew"], 1), LABELS.index(r["label"]), fl, hm])

area = hexes["label"].value_counts(normalize=True).mul(100).round(1).to_dict()
out_hex = hexes[hexes["cost"] > 1].to_crs(4326)
data = dict(
    hub=dict(name=hub_name, lnglat=[hub.x, hub.y]),
    routes=routes, kpis=kpis, area=area, n_cells=len(hexes), speed=SPEED_KMH,
    sora=sora, soz=soz, cells=cells_out, labels=LABELS, res=RES, step_km=step_km,
    dens=json.loads(dens_hex.to_json()) if dens_hex is not None else None, ew_gesamt=int(hexes.ew.sum()) if ZENSUS else None,
    hex=json.loads(out_hex.reset_index()[["label","geometry"]].to_json()),
    pois=[dict(name=r["name"], typ=r["amenity"], lnglat=[r.geometry.centroid.x, r.geometry.centroid.y])
          for _, r in g.to_crs(4326).iterrows() if pd.notna(r.get("amenity")) and pd.notna(r.get("name"))],
)
json.dump(data, open(OUT, "w"), separators=(",",":"))
print(pd.DataFrame(kpis).to_string(index=False)); print(area); print(len(hexes), "Zellen")
