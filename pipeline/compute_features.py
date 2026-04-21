# compute_features.py
# Computes the full feature matrix for all 393k road segments
# Output: features_real.parquet — feed this to gnn_pipeline.py
#
# Hardware acceleration:
#   CPU  — uses all 20 logical cores (13th-gen i7, mp.Pool)
#   GPU  — RTX 4060 via CuPy for batched Hata path-loss & RSRP accumulation
#          Falls back to NumPy automatically if CUDA / CuPy is unavailable.

import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox
import rasterio
import math
import multiprocessing as mp
from pathlib import Path
from rasterio.merge import merge
from shapely.geometry import LineString, Point, shape as geo_shape
from shapely.strtree import STRtree
from scipy.spatial import KDTree
import h3
import json
import warnings
warnings.filterwarnings('ignore')

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
GEOJSON_DIR = PROJECT_ROOT / "geojson"


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]

# ── GPU SETUP ─────────────────────────────────────────────────────────────────
try:
    import cupy as cp
    cp.cuda.Device(0).compute_capability
    USE_GPU = True
    print("[GPU] RTX 4060 detected — CuPy enabled for RF batch math.")
except Exception:
    cp = np
    USE_GPU = False
    print("[GPU] CuPy not available — falling back to NumPy.")

# ── CONFIG ────────────────────────────────────────────────────────────────────
GRAPH_PATH      = _first_existing(
    DATA_DIR / "bangalore_graph.graphml",
    PROJECT_ROOT / "bangalore_graph.graphml",
)
BUILDINGS_PATH  = _first_existing(
    GEOJSON_DIR / "bangalore_buildings.geojson",
    PROJECT_ROOT / "bangalore_buildings.geojson",
)
OOKLA_PATH      = _first_existing(
    DATA_DIR / "ookla_q4_2024/2024-10-01_performance_fixed_tiles.parquet",
    PROJECT_ROOT / "ookla_q4_2024/2024-10-01_performance_fixed_tiles.parquet",
)
SRTM_TILES      = [
    _first_existing(DATA_DIR / "N12E077.hgt", PROJECT_ROOT / "N12E077.hgt"),
    _first_existing(DATA_DIR / "N13E077.hgt", PROJECT_ROOT / "N13E077.hgt"),
]
TOWER_FILES     = {
    'jio':    _first_existing(DATA_DIR / "towers_jio.parquet", PROJECT_ROOT / "towers_jio.parquet"),
    'airtel': _first_existing(DATA_DIR / "towers_airtel.parquet", PROJECT_ROOT / "towers_airtel.parquet"),
    'vi':     _first_existing(DATA_DIR / "towers_vi.parquet", PROJECT_ROOT / "towers_vi.parquet"),
    'bsnl':   _first_existing(DATA_DIR / "towers_bsnl.parquet", PROJECT_ROOT / "towers_bsnl.parquet"),
}
OUT_PATH = DATA_DIR / "features_real.parquet"

# Using half the logical cores to keep the system responsive.
# Raise N_WORKERS toward mp.cpu_count() (20) once things are stable.
# Using half the logical cores to keep the system responsive.
# Raise N_WORKERS toward mp.cpu_count() (20) once things are stable.
N_WORKERS  = 16
CHUNKSIZE  = 500
FLUSH_EVERY = 10_000   # write partial parquet every N records to cap RAM

BBOX = {'lat_min': 12.834, 'lat_max': 13.139,
        'lon_min': 77.469, 'lon_max': 77.748}

ROAD_TYPE_ENC = {
    'motorway': 0, 'motorway_link': 0,
    'trunk': 1,    'trunk_link': 1,
    'primary': 2,  'primary_link': 2,
    'secondary': 3,'secondary_link': 3,
    'tertiary': 4, 'residential': 4, 'unclassified': 4,
    'service': 5,  'living_street': 5,
}
SPEED_MAP  = {0: 100, 1: 80, 2: 60, 3: 40, 4: 30, 5: 15}
TECH_MULT  = {'NR': 1.0, 'LTE': 0.75, 'HSPA': 0.4, 'GSM': 0.1}

# ── STEP 1: LOAD EVERYTHING ───────────────────────────────────────────────────
print("[1/6] Loading graph, buildings, towers, SRTM...")

G = ox.load_graphml(GRAPH_PATH)
edge_list = list(G.edges(data=True))
print(f"  Graph: {len(edge_list)} edges")

# Buildings
print("  Loading buildings...")
with open(BUILDINGS_PATH) as f:
    bdata = json.load(f)

building_polys   = []
building_heights = []
for feat in bdata['features']:
    try:
        poly = geo_shape(feat['geometry'])
        if poly.is_valid:
            building_polys.append(poly)
            building_heights.append(float(feat['properties'].get('height', 10.0)))
    except Exception:
        continue
print(f"  Buildings: {len(building_polys)}")
building_tree = STRtree(building_polys)

# Towers
towers        = {}
tower_kdtrees = {}
tower_arrays  = {}
for carrier, path in TOWER_FILES.items():
    df = pd.read_parquet(path)
    towers[carrier]       = df
    coords                = df[['lat', 'lon']].values
    tower_kdtrees[carrier] = KDTree(coords)
    tower_arrays[carrier]  = coords
    print(f"  {carrier}: {len(df)} towers")

all_tower_df     = pd.concat(
    [df.assign(carrier=c) for c, df in towers.items()], ignore_index=True
)
all_tower_coords = all_tower_df[['lat', 'lon']].values
all_tower_kdtree = KDTree(all_tower_coords)

# SRTM elevation
print("  Loading SRTM tiles...")
srtm_datasets         = [rasterio.open(t) for t in SRTM_TILES]
srtm_mosaic, srtm_tfm = merge(srtm_datasets)
srtm_mosaic           = srtm_mosaic[0]

def sample_elevation(lat, lon):
    try:
        row, col = rasterio.transform.rowcol(srtm_tfm, lon, lat)
        row = max(0, min(row, srtm_mosaic.shape[0] - 1))
        col = max(0, min(col, srtm_mosaic.shape[1] - 1))
        val = float(srtm_mosaic[row, col])
        return val if val > -9000 else 900.0
    except Exception:
        return 900.0

# OOKLA labels
print("  Loading OOKLA labels...")
ookla_df = pd.read_parquet(OOKLA_PATH)
print("  Parsing OOKLA WKT tiles...")
ookla_df['geometry'] = gpd.GeoSeries.from_wkt(ookla_df['tile'])
ookla = gpd.GeoDataFrame(ookla_df, geometry='geometry', crs="EPSG:4326")
ookla = ookla.cx[BBOX['lon_min']:BBOX['lon_max'],
                 BBOX['lat_min']:BBOX['lat_max']].copy()
ookla['avg_d_kbps'] = pd.to_numeric(ookla['avg_d_kbps'], errors='coerce').fillna(0)
# Keep raw kbps — log normalisation happens in gnn_pipeline.py so labels have real variance
print(f"  OOKLA tiles in Bangalore: {len(ookla)}")
ookla_tree = STRtree(ookla.geometry)

# ── GPU BATCH: HATA PATH LOSS ─────────────────────────────────────────────────
def hata_path_loss_batch(freq_arr, dist_arr, bs_height=30.0, ms_height=1.5):
    """
    Vectorised Okumura-Hata for arrays.
    Always uses NumPy inside worker processes (CuPy is main-process only,
    forking a CUDA context into child processes causes crashes/memory bloat).
    """
    freq = np.asarray(freq_arr, dtype=np.float32)
    dist = np.maximum(np.asarray(dist_arr, dtype=np.float32), 0.01)
    a_hm = (1.1 * np.log10(freq) - 0.7) * ms_height - \
           (1.56 * np.log10(freq) - 0.8)
    L = (69.55 + 26.16 * np.log10(freq)
         - 13.82 * math.log10(bs_height)
         - a_hm
         + (44.9 - 6.55 * math.log10(bs_height)) * np.log10(dist))
    return L

def haversine_km(lat1, lon1, lat2, lon2):
    R     = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a     = (math.sin(d_lat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))

# ── STEP 2: SVF RAY CASTING ───────────────────────────────────────────────────
def compute_svf(lat, lon, n_rays=36, ray_len=200):
    lat_per_m = 1 / 111000
    lon_per_m = 1 / 91000
    unblocked = 0
    for i in range(n_rays):
        angle   = (2 * math.pi * i) / n_rays
        end_lat = lat + math.cos(angle) * ray_len * lat_per_m
        end_lon = lon + math.sin(angle) * ray_len * lon_per_m
        ray     = LineString([(lon, lat), (end_lon, end_lat)])
        hits    = building_tree.query(ray)
        blocked = any(ray.intersects(building_polys[idx]) for idx in hits)
        if not blocked:
            unblocked += 1
    return unblocked / n_rays

# ── STEP 3: RF SCORE (GPU-accelerated inner loop) ─────────────────────────────
def compute_rf_score(lat, lon, carrier, svf, building_density, radius_km=5.0):
    df    = towers[carrier]
    kdt   = tower_kdtrees[carrier]
    idxs  = kdt.query_ball_point([lat, lon], radius_km / 111.0)
    if not idxs:
        return 20.0

    tx_power = 46.0
    ant_gain = 15.0

    rows     = df.iloc[idxs]
    t_lats   = rows['lat'].values.astype(float)
    t_lons   = rows['lon'].values.astype(float)
    freqs    = rows['freq_mhz'].values.astype(float)
    radios   = rows['radio'].astype(str).values
    samples  = np.minimum(rows.get('samples', pd.Series(np.ones(len(rows)))).values.astype(float), 100) / 100

    # Distances (CPU; fast enough for ~dozens of towers per segment)
    d_lat    = lat - t_lats
    d_lon    = lon - t_lons
    dists_km = np.sqrt((d_lat * 111) ** 2 + (d_lon * 91) ** 2)

    # Hata on GPU (or NumPy)
    L        = hata_path_loss_batch(freqs, dists_km)
    rsrp_db  = tx_power + ant_gain - L

    mults    = np.array([TECH_MULT.get(r, 0.4) for r in radios])
    linear   = np.sum(10 ** (rsrp_db / 10) * mults * samples)

    if linear <= 0:
        return 20.0

    rsrp_dbm  = 10 * math.log10(linear)
    rsrp_dbm -= 15 * (1 - svf)   # Building shadow: 0–15 dB (realistic sub-6GHz)
    score     = (rsrp_dbm + 140) / 96 * 100
    return float(np.clip(score, 0, 100))

# ── STEP 4: TERRAIN LOS ───────────────────────────────────────────────────────
def compute_terrain_shadow(seg_lat, seg_lon, seg_elev):
    idxs        = all_tower_kdtree.query([seg_lat, seg_lon], k=1)
    nearest_idx = idxs[1] if isinstance(idxs[1], (int, np.integer)) else idxs[1][0]
    tower_row   = all_tower_df.iloc[nearest_idx]
    t_lat  = float(tower_row['lat'])
    t_lon  = float(tower_row['lon'])
    t_elev = sample_elevation(t_lat, t_lon) + 30.0

    for i in range(1, 11):
        frac         = i / 11
        s_lat        = seg_lat + frac * (t_lat - seg_lat)
        s_lon        = seg_lon + frac * (t_lon - seg_lon)
        terrain_elev = sample_elevation(s_lat, s_lon)
        los_elev     = seg_elev + frac * (t_elev - seg_elev)
        if terrain_elev > los_elev + 5:
            return 1
    return 0

# ── STEP 5: OOKLA LABEL LOOKUP ────────────────────────────────────────────────
def get_ookla_label(lat, lon):
    """Returns raw avg_d_kbps. Log normalisation is applied in gnn_pipeline.py."""
    pt   = Point(lon, lat)
    hits = ookla_tree.query(pt)
    for idx in hits:
        if ookla.geometry.iloc[idx].contains(pt):
            return float(ookla['avg_d_kbps'].iloc[idx])
    return np.nan

# ── STEP 6: PER-EDGE WORKER  (runs in a child process) ───────────────────────
def process_edge(idx):
    u, v, edata = edge_list[idx]

    osmid  = edata.get('osmid', f"{u}_{v}")
    way_id = str(osmid[0]) if isinstance(osmid, list) else str(osmid)

    if 'geometry' in edata:
        coords   = list(edata['geometry'].coords)
        mid      = coords[len(coords) // 2]
        lat, lon = mid[1], mid[0]
    else:
        lat = G.nodes[u]['y']
        lon = G.nodes[u]['x']

    rtype = edata.get('highway', 'residential')
    if isinstance(rtype, list):
        rtype = rtype[0]
    road_enc   = ROAD_TYPE_ENC.get(rtype, 5)
    speed_kmph = SPEED_MAP[road_enc]

    length    = float(edata.get('length', 50))
    traversal = length / (speed_kmph / 3.6)

    elev  = sample_elevation(lat, lon)
    slope = 0.0
    if 'geometry' in edata:
        coords = list(edata['geometry'].coords)
        if len(coords) >= 2:
            start_elev = sample_elevation(coords[0][1],  coords[0][0])
            end_elev   = sample_elevation(coords[-1][1], coords[-1][0])
            slope      = abs(end_elev - start_elev) / max(length, 1) * 100

    svf              = compute_svf(lat, lon)
    building_density = 1.0 - svf
    veg_fraction     = 0.3 if road_enc >= 4 else 0.1

    jio_rf    = compute_rf_score(lat, lon, 'jio',    svf, building_density)
    airtel_rf = compute_rf_score(lat, lon, 'airtel', svf, building_density)
    vi_rf     = compute_rf_score(lat, lon, 'vi',     svf, building_density)
    bsnl_rf   = compute_rf_score(lat, lon, 'bsnl',   svf, building_density)

    kdt_hits = all_tower_kdtree.query_ball_point([lat, lon], 0.01)
    if kdt_hits:
        radios    = all_tower_df.iloc[kdt_hits]['radio'].value_counts()
        top_radio = radios.index[0] if len(radios) > 0 else 'LTE'
    else:
        top_radio = 'LTE'
    band_enc = {'GSM': 0, 'HSPA': 1, 'LTE': 2, 'NR': 3}.get(top_radio, 2)

    terrain_shadow = compute_terrain_shadow(lat, lon, elev)
    if terrain_shadow:
        jio_rf    *= 0.4
        airtel_rf *= 0.4
        vi_rf     *= 0.4
        bsnl_rf   *= 0.4

    rsrp_label = get_ookla_label(lat, lon)

    return {
        'osm_way_id':          way_id,
        'midpoint_lat':        lat,
        'midpoint_lon':        lon,
        'svf':                 float(svf),
        'building_density':    float(building_density),
        'veg_fraction':        float(veg_fraction),
        'open_terrain_score':  float(svf),
        'jio_rf_score':        float(jio_rf),
        'airtel_rf_score':     float(airtel_rf),
        'vi_rf_score':         float(vi_rf),
        'bsnl_rf_score':       float(bsnl_rf),
        'elevation':           float(elev),
        'slope':               float(slope),
        'terrain_shadow':      int(terrain_shadow),
        'road_type_enc':       int(road_enc),
        'segment_length':      float(length),
        'traversal_time_secs': float(traversal),
        'dominant_band_enc':   int(band_enc),
        'avg_d_kbps':          float(rsrp_label) if not np.isnan(rsrp_label) else np.nan,
    }

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from tqdm import tqdm
    import os

    print(f"\n[2/6] Computing features for {len(edge_list)} segments")
    print(f"       Workers  : {N_WORKERS} CPU cores  (fork — shared CoW memory)")
    print(f"       GPU      : {'RTX 4060 (CuPy)' if USE_GPU else 'disabled in workers (fork+CUDA unsafe)'}")
    print(f"       Chunksize: {CHUNKSIZE}")
    print(f"       Flush    : every {FLUSH_EVERY} records\n")

    # 'fork' = workers inherit parent memory via copy-on-write — no 18x duplication.
    # CUDA is NOT used inside workers; CuPy stays in the main process only.
    ctx = mp.get_context('fork')

    part_files = []
    batch_num  = 0
    records    = []

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    def flush(records, batch_num):
        path = Path(f"{OUT_PATH}.part{batch_num}")
        pd.DataFrame(records).to_parquet(path, index=False)
        part_files.append(path)
        print(f"  → flushed batch {batch_num} ({len(records)} records) to {path}")
        return []

    with ctx.Pool(processes=N_WORKERS) as pool:
        for res in tqdm(
            pool.imap_unordered(process_edge, range(len(edge_list)), chunksize=CHUNKSIZE),
            total=len(edge_list),
            unit='seg',
        ):
            records.append(res)
            if len(records) >= FLUSH_EVERY:
                records = flush(records, batch_num)
                batch_num += 1

    if records:
        flush(records, batch_num)

    print(f"\n[3/6] Merging {len(part_files)} partial files → {OUT_PATH}...")
    df_out = pd.concat([pd.read_parquet(p) for p in part_files], ignore_index=True)
    df_out.to_parquet(OUT_PATH, index=False)

    for p in part_files:
        os.remove(p)

    labeled = df_out['avg_d_kbps'].notna().sum()
    print("Done.")
    print(f"  Segments : {len(df_out)}")
    print(f"  Labeled  : {labeled} ({100 * labeled / len(df_out):.1f}%)")
    print(f"  SVF mean : {df_out['svf'].mean():.3f}")
    print(f"  Jio RF   : {df_out['jio_rf_score'].mean():.1f}")
    print(f"  Ookla kbps median: {df_out['avg_d_kbps'].median():.0f}")
    print(f"\nNow run: python3 gnn_pipeline.py")