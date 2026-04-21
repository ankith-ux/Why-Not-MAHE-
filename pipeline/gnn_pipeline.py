# gnn_pipeline.py
# Run with: python3 gnn_pipeline.py

import torch
import torch.nn.functional as F
import numpy as np
import pandas as pd
import osmnx as ox
import json
from pathlib import Path
from torch_geometric.data import Data
from torch_geometric.nn import SAGEConv, GraphNorm
from sklearn.preprocessing import StandardScaler
import pickle

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
GEOJSON_DIR = PROJECT_ROOT / "geojson"


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]

# ── CONFIG ────────────────────────────────────────────────────────────────────
FEATURES_PATH = _first_existing(
    DATA_DIR / "features_real.parquet",
    PROJECT_ROOT / "features_real.parquet",
)
GRAPH_PATH    = _first_existing(
    DATA_DIR / "bangalore_graph.graphml",
    PROJECT_ROOT / "bangalore_graph.graphml",
)
MODEL_OUT     = DATA_DIR / "best_model.pt"
SCALER_OUT    = DATA_DIR / "scaler.pkl"
GEOJSON_OUT   = GEOJSON_DIR / "scored_segments.geojson"
EPOCHS        = 2000
LR            = 0.001
PATIENCE      = 120
HIDDEN        = 128
DROPOUT       = 0.4

FEATURE_COLS = [
    'svf', 'jio_rf_score', 'airtel_rf_score', 'vi_rf_score', 'bsnl_rf_score',
    'elevation', 'slope', 'road_type_enc', 'segment_length', 'dominant_band_enc'
]
# ── END CONFIG ────────────────────────────────────────────────────────────────


# ── MODEL ─────────────────────────────────────────────────────────────────────
class NeuralPathGNN(torch.nn.Module):
    def __init__(self, in_channels=13, hidden=HIDDEN, dropout=DROPOUT):
        super().__init__()
        # Use max aggregation to avoid washing out strong features like RF signal
        self.conv1  = SAGEConv(in_channels, hidden, aggr='max')
        self.norm1  = GraphNorm(hidden)
        
        # 2 layers are sufficient for geographical features (avoids over-smoothing and OOM)
        self.conv2  = SAGEConv(hidden, hidden, aggr='max')
        self.norm2  = GraphNorm(hidden)
        
        self.lin1   = torch.nn.Linear(hidden, hidden // 2)
        self.lin2   = torch.nn.Linear(hidden // 2, 1)
        self.drop   = dropout

    def forward(self, x, edge_index):
        h1 = self.conv1(x, edge_index)
        h1 = F.relu(self.norm1(h1))
        h1 = F.dropout(h1, p=self.drop, training=self.training)
        
        h2 = self.conv2(h1, edge_index)
        h2 = F.relu(self.norm2(h2))
        h2 = h2 + h1 # Skip connection
        h2 = F.dropout(h2, p=self.drop, training=self.training)
        
        out = F.relu(self.lin1(h2))
        return torch.sigmoid(self.lin2(out)).squeeze() * 100.0


# ── LABEL NORMALISATION ───────────────────────────────────────────────────────
def normalise_labels(series):
    """
    Convert raw Ookla kbps to a spread 0-100 score.
    Uses data-driven percentile normalisation on log scale so the output
    always spans the full 0-100 range regardless of the city's speed tier.
    p2  → 0  (clips very slow outliers)
    p98 → 100 (clips very fast outliers)
    """
    kbps    = pd.to_numeric(series, errors='coerce').fillna(0).clip(lower=0)
    log_val = np.log10(kbps + 1)
    valid   = log_val[log_val > 0]
    p2      = np.percentile(valid, 2)
    p98     = np.percentile(valid, 98)
    return ((log_val - p2) / (p98 - p2) * 100).clip(0, 100)


# ── DATA LOADER ───────────────────────────────────────────────────────────────
def build_pyg_graph(features_path, graph_path):
    print("[1/4] Loading features and graph...")
    df = pd.read_parquet(features_path)
    G  = ox.load_graphml(graph_path)

    def edge_key(u, v, data):
        oid = data.get('osmid', f"{u}_{v}")
        return str(oid[0]) if isinstance(oid, list) else str(oid)

    edge_list = list(G.edges(data=True))
    assert len(edge_list) == len(df), (
        f"Edge count mismatch: graph {len(edge_list)} vs parquet {len(df)}."
    )
    way_to_idx = {edge_key(u, v, d): i for i, (u, v, d) in enumerate(edge_list)}
    print(f"    {len(df)} segments loaded.")

    # ── Labels: mean RF coverage score ──────────────────────────────────────────
    # The GNN's job is spatial smoothing + propagation of coverage scores.
    rf_cols = ['jio_rf_score', 'airtel_rf_score', 'vi_rf_score', 'bsnl_rf_score']
    df['rsrp_label'] = df[rf_cols].mean(axis=1)
    labeled_mask = df['rsrp_label'] > 0
    labels       = df['rsrp_label'][labeled_mask]
    print(f"    Labels: mean RF score ({labeled_mask.sum()} labeled, "
          f"{(~labeled_mask).sum()} unlabeled)")
    print(f"    Label distribution — "
          f"min:{labels.min():.1f}  p25:{labels.quantile(.25):.1f}  "
          f"median:{labels.median():.1f}  p75:{labels.quantile(.75):.1f}  "
          f"max:{labels.max():.1f}")

    print("    --- Diagnostic: Feature→Label Correlation ---")
    for rf_col in ['jio_rf_score', 'airtel_rf_score', 'vi_rf_score', 'bsnl_rf_score',
                   'elevation', 'svf', 'segment_length']:
        rf_vals = df[rf_col][labeled_mask]
        corr = np.corrcoef(rf_vals, labels)[0, 1]
        print(f"    Pearson corr {rf_col:20s} vs label: {corr:+.4f}")
    print("    -----------------------------------------------")

    # Node features
    X      = df[FEATURE_COLS].fillna(0).values.astype(np.float32)
    scaler = StandardScaler()
    scaler.fit(X[labeled_mask.values])
    X_norm = scaler.transform(X)
    SCALER_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(SCALER_OUT, 'wb') as f:
        pickle.dump(scaler, f)

    y = df['rsrp_label'].values.astype(np.float32)

    print("[2/4] Building edges (same-OSM-way chain adjacency)...")
    way_to_segs = {}
    for i, (u, v, data) in enumerate(edge_list):
        oid = data.get('osmid', f"{u}_{v}")
        way_id = str(oid[0]) if isinstance(oid, list) else str(oid)
        way_to_segs.setdefault(way_id, []).append(i)

    src, dst = [], []
    for segs in way_to_segs.values():
        for k in range(len(segs) - 1):
            src.append(segs[k]);     dst.append(segs[k + 1])
            src.append(segs[k + 1]); dst.append(segs[k])

    edge_index = torch.tensor([src, dst], dtype=torch.long)
    print(f"    {edge_index.shape[1]} graph edges built.")

    lats = df['midpoint_lat'].values
    lons = df['midpoint_lon'].values
    lv   = labeled_mask.values

    # ── Spatial Grid Split (20x20 Block CV) ───────────────
    # Prevents data leakage by putting entire blocks in the same split,
    # but maintains geographical diversity avoiding extreme domain shift.
    lat_min, lat_max = lats.min(), lats.max()
    lon_min, lon_max = lons.min(), lons.max()
    
    grid_lat = np.floor((lats - lat_min) / (lat_max - lat_min + 1e-6) * 20).astype(int)
    grid_lon = np.floor((lons - lon_min) / (lon_max - lon_min + 1e-6) * 20).astype(int)
    
    cells = grid_lat * 20 + grid_lon
    
    # Randomly assign the 400 grid cells to Train/Val/Test
    np.random.seed(42)
    cell_assignments = np.random.choice([0, 1, 2], size=400, p=[0.8, 0.1, 0.1])
    
    assignments = cell_assignments[cells]
    
    train_mask = torch.tensor((assignments == 0) & lv, dtype=torch.bool)
    val_mask   = torch.tensor((assignments == 1) & lv, dtype=torch.bool)
    test_mask  = torch.tensor((assignments == 2) & lv, dtype=torch.bool)

    print(f"    Train: {train_mask.sum()} | "
          f"Val: {val_mask.sum()} | "
          f"Test: {test_mask.sum()}")

    data = Data(
        x          = torch.tensor(X_norm, dtype=torch.float),
        edge_index = edge_index,
        y          = torch.tensor(y, dtype=torch.float),
        train_mask = train_mask,
        val_mask   = val_mask,
        test_mask  = test_mask,
    )
    return data, scaler, df, G, edge_list


# ── TRAINING ──────────────────────────────────────────────────────────────────
def train(data):
    device = torch.device('cuda')
    print(f"[3/4] Training on {torch.cuda.get_device_name(0)}...")
    model = NeuralPathGNN(in_channels=len(FEATURE_COLS)).to(device)
    opt   = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, patience=15, factor=0.5)
    data  = data.to(device)

    best_val_mae = float('inf')
    best_epoch   = 0
    patience_cnt = 0

    for epoch in range(1, EPOCHS + 1):
        model.train()
        opt.zero_grad()
        out  = model(data.x, data.edge_index)
        mask = data.train_mask & ~torch.isnan(data.y)
        # Huber loss: less sensitive to the few very-low-speed outliers than MSE
        loss = F.huber_loss(out[mask], data.y[mask], delta=10.0)
        loss.backward()
        opt.step()

        if epoch % 10 == 0:
            model.eval()
            with torch.no_grad():
                out = model(data.x, data.edge_index)
                vm  = data.val_mask & ~torch.isnan(data.y)
                val_mae = torch.abs(out[vm] - data.y[vm]).mean().item()
            sched.step(val_mae)

            print(f"  Epoch {epoch:03d} | loss {loss.item():.3f} | "
                  f"val MAE {val_mae:.3f} | lr {opt.param_groups[0]['lr']:.5f}")

            if val_mae < best_val_mae:
                best_val_mae = val_mae
                best_epoch   = epoch
                patience_cnt = 0
                MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
                torch.save(model.state_dict(), MODEL_OUT)
            else:
                patience_cnt += 1
                if patience_cnt >= PATIENCE:
                    print(f"  Early stop at epoch {epoch} — "
                          f"best epoch {best_epoch}, MAE {best_val_mae:.3f}")
                    break

    print(f"  Best val MAE: {best_val_mae:.3f}")
    model.load_state_dict(torch.load(MODEL_OUT, weights_only=True))
    return model


# ── INFERENCE + EXPORT ────────────────────────────────────────────────────────
def export_geojson(model, data, df, G, edge_list):
    print("[4/4] Running inference and exporting GeoJSON...")
    device = next(model.parameters()).device
    model.eval()
    with torch.no_grad():
        scores = model(data.x.to(device), data.edge_index.to(device)).cpu().numpy()

    df = df.copy()
    
    # ── Use raw model scores directly ─────────────────────────────
    # Model outputs are already 0-100 (sigmoid * 100). ~75% of segments
    # have no tower data → score near 0 (genuine dead zones for routing).
    # Percentile stretching breaks on this bimodal distribution.
    df['composite_score'] = np.clip(scores, 0, 100)

    print(f"  Raw score distribution: "
          f"min={scores.min():.1f}  mean={scores.mean():.1f}  "
          f"p25={np.percentile(scores,25):.1f}  median={np.median(scores):.1f}  "
          f"p75={np.percentile(scores,75):.1f}  max={scores.max():.1f}")
    # Show distribution for segments that actually have RF data
    has_rf = df[['jio_rf_score','airtel_rf_score','vi_rf_score','bsnl_rf_score']].mean(axis=1) > 0
    print(f"  Covered segments ({has_rf.sum()}/{len(df)}): "
          f"mean={scores[has_rf].mean():.1f}  "
          f"p25={np.percentile(scores[has_rf],25):.1f}  "
          f"p75={np.percentile(scores[has_rf],75):.1f}")

    mean_rf = df[['jio_rf_score','airtel_rf_score','vi_rf_score','bsnl_rf_score']].mean(axis=1)
    mean_rf = mean_rf.replace(0, 1)
    for carrier, col in [('jio','jio_rf_score'), ('airtel','airtel_rf_score'),
                          ('vi','vi_rf_score'),   ('bsnl','bsnl_rf_score')]:
        ratio = (df[col] / mean_rf).clip(0.5, 1.5)
        df[f'{carrier}_score'] = (df['composite_score'] * ratio).clip(0, 100)

    df['confidence'] = (~df['rsrp_label'].isna()).astype(float) * 0.35 + 0.6

    band_map = {0: 'GSM', 1: 'HSPA', 2: 'LTE', 3: 'NR'}

    features = []
    for i, (u, v, edata) in enumerate(edge_list):
        row  = df.iloc[i]
        geom = edata.get('geometry')
        if geom is None:
            coords = [[G.nodes[u]['x'], G.nodes[u]['y']],
                      [G.nodes[v]['x'], G.nodes[v]['y']]]
        else:
            coords = [[lon, lat] for lon, lat in geom.coords]

        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "osm_way_id":          str(row['osm_way_id']),
                "composite_score":     round(float(row['composite_score']), 2),
                "jio_score":           round(float(row['jio_score']), 2),
                "airtel_score":        round(float(row['airtel_score']), 2),
                "vi_score":            round(float(row['vi_score']), 2),
                "bsnl_score":          round(float(row['bsnl_score']), 2),
                "confidence":          round(float(row['confidence']), 2),
                "dominant_band":       band_map.get(int(row['dominant_band_enc']), 'LTE'),
                "svf":                 round(float(row['svf']), 3),
                "terrain_shadow":      int(row['terrain_shadow']),
                "traversal_time_secs": round(float(row['traversal_time_secs']), 1),
                "segment_length":      round(float(row['segment_length']), 1),
            }
        })

    geojson = {"type": "FeatureCollection", "features": features}
    GEOJSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(GEOJSON_OUT, 'w') as f:
        json.dump(geojson, f)
    print(f"  Exported {len(features)} segments → {GEOJSON_OUT}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    data, scaler, df, G, edge_list = build_pyg_graph(FEATURES_PATH, GRAPH_PATH)
    model = train(data)
    export_geojson(model, data, df, G, edge_list)
    print("Pipeline complete.")