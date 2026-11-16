"""Step 2: OSM buildings -> height per building (OSM height tag, building:levels x 3 m, or type default),
compact delta-encoded footprints for the 3D view, and max. building height per H3 cell.

Usage: python src/buildings.py <osm_buildings.geojson|.zip> <data_in.json> <data_out.json>
Accepts Overpass JSON (out geom) or GeoJSON exported from overpass-turbo.
"""
import json, sys, re, math, collections
import h3
SRC, DATA_IN, DATA_OUT = sys.argv[1:4]
D = json.load(open(DATA_IN))
RES = D["res"]
if SRC.endswith(".zip"):
    import zipfile
    _z = zipfile.ZipFile(SRC); osm = json.load(_z.open([n for n in _z.namelist() if n.endswith((".geojson", ".json"))][0]))
else:
    osm = json.load(open(SRC, encoding="utf-8"))
if "features" in osm:   # GeoJSON aus overpass-turbo -> in Overpass-Struktur umwandeln
    els = []
    for f in osm["features"]:
        g = f.get("geometry") or {}
        rings = [g["coordinates"][0]] if g.get("type") == "Polygon" else [p[0] for p in g.get("coordinates", [])] if g.get("type") == "MultiPolygon" else []
        for r in rings:
            els.append({"type": "way", "tags": f.get("properties", {}), "geometry": [{"lon": x, "lat": y} for x, y in r]})
    osm = {"elements": els}
TYP = {  # Standardhöhen (m), wenn weder height noch building:levels vorhanden
 "garage":3,"garages":3,"shed":3,"carport":3,"hut":3,"roof":4,"kiosk":3,"container":3,"greenhouse":3,"allotment_house":3,"cabin":3,"toilets":3,"service":3,"transformer_tower":6,
 "house":8,"detached":8,"semidetached_house":8,"terrace":9,"bungalow":4,"farm":8,"residential":11,"apartments":14,"dormitory":12,
 "commercial":9,"retail":7,"supermarket":7,"office":12,"industrial":9,"warehouse":9,"manufacture":9,"hangar":10,
 "hospital":18,"school":11,"kindergarten":6,"university":14,"public":11,"civic":10,"government":12,"church":15,"chapel":8,
 "sports_hall":10,"train_station":8,"barn":8,"farm_auxiliary":6,"stable":6,"construction":8,"yes":7}
def num(v):
    if v is None: return None
    m = re.match(r"\s*([0-9]+(?:[.,][0-9]+)?)", str(v))
    return float(m.group(1).replace(",", ".")) if m else None
out, cellmax, src_n = [], collections.defaultdict(float), collections.Counter()
for el in osm.get("elements", []):
    if el.get("type") != "way" or "geometry" not in el: continue
    tg = el.get("tags", {}); g = el["geometry"]
    if len(g) < 4: continue
    h = num(tg.get("height")); s = 0
    if h is None or h <= 0 or h > 300:
        lv = num(tg.get("building:levels"))
        if lv is not None and 0 < lv < 60:
            h = lv * 3.0 + (num(tg.get("roof:levels")) or 0) * 2.5 + 1.0; s = 1
        else:
            h = TYP.get(tg.get("building"), 7); s = 2
            # sehr kleine Grundflächen -> Nebengebäude
            if s == 2 and tg.get("building") == "yes":
                lat0 = g[0]["lat"]; kx = 111320 * math.cos(math.radians(lat0)); ky = 110540
                A = abs(sum((g[i]["lon"]*kx)*(g[i+1]["lat"]*ky) - (g[i+1]["lon"]*kx)*(g[i]["lat"]*ky) for i in range(len(g)-1))) / 2
                if A < 40: h = 3
    src_n[s] += 1
    # Delta-Kodierung (1e-5 Grad ~ 1 m)
    pts = [(round(p["lon"]*1e5), round(p["lat"]*1e5)) for p in g]
    enc = [pts[0][0], pts[0][1]]
    for i in range(1, len(pts)): enc += [pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]]
    out.append([round(h, 1), s, enc])
    for p in g[::max(1, len(g)//6)] + [g[0]]:
        c = h3.latlng_to_cell(p["lat"], p["lon"], RES); cellmax[c] = max(cellmax[c], h)
# max. OSM-Höhe je Wabe in Zellexport (Index 7)
for c in D["cells"]:
    hv = cellmax.get(c[0], 0.0); c.append(round(hv, 1)) if len(c) == 7 else c.__setitem__(7, round(hv, 1))
n = sum(src_n.values())
D["bld"] = out
D["bld_stats"] = dict(n=n, tag=src_n[0], levels=src_n[1], typ=src_n[2], max=round(max(o[0] for o in out), 1) if out else 0,
                      top=sorted(((o[0]) for o in out), reverse=True)[:5])
json.dump(D, open(DATA_OUT, "w"), separators=(",", ":"))
print(D["bld_stats"], "Waben mit Gebäuden:", len(cellmax))
