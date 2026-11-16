#!/usr/bin/env bash
# Rebuilds docs/index.html from the raw data in data/raw.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
python src/analyse.py   data/raw/osm_restrictions.geojson build/data_base.json \
                        data/raw/zensus2022_population_100m.zip data/raw/zensus2022_social_100m.zip
python src/buildings.py data/raw/osm_buildings.geojson.zip build/data_base.json build/data.json
python src/build_html.py build/data.json docs/index.html
