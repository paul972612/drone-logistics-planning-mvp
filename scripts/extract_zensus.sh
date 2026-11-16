#!/usr/bin/env bash
# Cuts the nationwide Census 2022 100 m grid CSVs (zensus2022.de, "Gitterdaten") to the study area.
# Bounds are the study-area BBOX (WGS84 52.60-52.71 N, 13.44-13.63 E) in EPSG:3035 (+200 m margin).
# Usage: scripts/extract_zensus.sh <Zensus2022_..._100m-Gitter.csv> <out.csv>
set -euo pipefail
XMIN=4553203; XMAX=4567042; YMIN=3282073; YMAX=3295326
awk -F';' -v a=$XMIN -v b=$XMAX -v c=$YMIN -v d=$YMAX 'NR==1 || ($2>=a && $2<=b && $3>=c && $3<=d)' "$1" > "$2"
# population -> zip as zensus2022_population_100m.zip (file name must contain "100m")
# social     -> ue65.csv, auslaender.csv, miete.csv, gebaeude.csv zipped as zensus2022_social_100m.zip
