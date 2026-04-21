# cv_demo.py
import requests
from PIL import Image
from io import BytesIO
import torch
import numpy as np
import json
import os
from pathlib import Path
from transformers import SegformerImageProcessor, SegformerForSemanticSegmentation

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


FEATURES_SYNTH_PATH = _first_existing(
    DATA_DIR / "features_synthetic.parquet",
    SCRIPT_DIR / "features_synthetic.parquet",
)
CV_DEMO_OUT = SCRIPT_DIR / "cv_demo_segment.json"

MAPILLARY_TOKEN  = os.getenv("MAPILLARY_TOKEN", "")
SEGMENT_OSM_ID   = "780853199"
SEGMENT_COORDS   = [12.924909644114436, 77.58993710216282]
MAPILLARY_IDS    = ["485784672764267", "2569959863298910", "466943704532607"]

# ── STEP 1: Fetch images ──────────────────────────────────────────────────────
def fetch_image(image_id):
    if not MAPILLARY_TOKEN:
        raise RuntimeError("Set MAPILLARY_TOKEN in your environment before running this script")

    url  = f"https://graph.mapillary.com/{image_id}?fields=thumb_2048_url&access_token={MAPILLARY_TOKEN}"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    
    if 'thumb_2048_url' not in data:
        print(f"  ERROR for {image_id}: {data}")
        return None
    
    img_bytes = requests.get(data['thumb_2048_url'], timeout=30).content
    img = Image.open(BytesIO(img_bytes)).convert('RGB')
    img.save(SCRIPT_DIR / f"mapillary_{image_id}.jpg")  # save so you can verify what was fetched
    print(f"  Fetched {image_id} — size {img.size}")
    return img

# ── STEP 2: Run SegFormer segmentation ───────────────────────────────────────
def compute_camera_svf(image_ids):
    print("\nLoading SegFormer model (downloading ~200MB on first run)...")
    processor = SegformerImageProcessor.from_pretrained("nvidia/segformer-b2-finetuned-ade-512-512")
    model     = SegformerForSemanticSegmentation.from_pretrained("nvidia/segformer-b2-finetuned-ade-512-512")
    model.eval()
    if torch.cuda.is_available():
        model = model.cuda()
        print("  Running on RTX 4060")

    sky_fractions  = []
    tree_fractions = []

    for img_id in image_ids:
        print(f"\nProcessing {img_id}...")
        img = fetch_image(img_id)
        if img is None:
            continue

        inputs = processor(images=img, return_tensors="pt")
        if torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            logits = model(**inputs).logits  # (1, 150, H/4, W/4)

        seg_map = logits.argmax(dim=1).squeeze().cpu()

        # ADE20K class indices
        sky_pct   = (seg_map == 2).float().mean().item()
        tree_pct  = (seg_map == 4).float().mean().item()
        build_pct = (seg_map == 1).float().mean().item()

        sky_fractions.append(sky_pct)
        tree_fractions.append(tree_pct)
        print(f"  sky={sky_pct:.3f}  tree={tree_pct:.3f}  building={build_pct:.3f}")

    camera_svf = min(sky_fractions)  # worst case = most obstructed view
    print(f"\nCamera SVF across 3 images: {sky_fractions}")
    print(f"Using minimum (worst case): {camera_svf:.3f}")
    return camera_svf, np.mean(tree_fractions)

# ── STEP 3: Hata obstruction correction ──────────────────────────────────────
def hata_rsrp_from_svf(svf, building_density, base_rsrp=-75.0):
    obstruction_db = 10 * (1 - svf) * building_density * 20
    return base_rsrp - obstruction_db

# ── STEP 4: Pull geometric SVF from synthetic parquet (real later) ────────────
def get_geometric_svf(osm_way_id):
    import pandas as pd
    df = pd.read_parquet(FEATURES_SYNTH_PATH)
    row = df[df['osm_way_id'] == osm_way_id]
    if row.empty:
        print(f"Way ID {osm_way_id} not in parquet — using fallback values")
        return 0.72, 0.45, 55.0  # geometric_svf, building_density, ookla_label
    r = row.iloc[0]
    return float(r['svf']), float(r['building_density']), float(r['rsrp_label']) if not np.isnan(r['rsrp_label']) else 55.0

def normalize_rsrp_to_score(rsrp_dbm):
    """Convert dBm (-140 to -44) to 0-100 scale"""
    return max(0, min(100, (rsrp_dbm + 140) / 96 * 100))

def score_to_rsrp_dbm(score_0_100):
    """Convert 0-100 normalized score back to dBm"""
    return (score_0_100 / 100) * 96 - 140

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== CV DEMO — 26th Main Road, Jayanagar ===\n")

    geometric_svf, building_density, ground_truth = get_geometric_svf(SEGMENT_OSM_ID)
    print(f"Geometric SVF (from map data):  {geometric_svf:.3f}")
    print(f"Building density:               {building_density:.3f}")
    print(f"Ground truth RSRP (OOKLA tile): {ground_truth:.1f}")

    camera_svf, avg_tree = compute_camera_svf(MAPILLARY_IDS)

    geom_rsrp   = hata_rsrp_from_svf(geometric_svf, building_density)
    camera_rsrp = hata_rsrp_from_svf(camera_svf,    building_density)

    # convert ground truth from 0-100 score to dBm so units match
    ground_truth_dbm = score_to_rsrp_dbm(ground_truth)  # 55.0 → -87.2 dBm

    result = {
        "osm_way_id":              SEGMENT_OSM_ID,
        "segment_coords":          SEGMENT_COORDS,
        "road_name":               "26th Main Road, Jayanagar",
        "mapillary_image_ids":     MAPILLARY_IDS,
        "geometric_svf":           round(geometric_svf, 3),
        "camera_svf":              round(camera_svf, 3),
        "geometric_rsrp_estimate": round(geom_rsrp, 2),
        "camera_rsrp_estimate":    round(camera_rsrp, 2),
        "ground_truth_rsrp":       round(ground_truth_dbm, 2),
        "geometric_error_db":      round(abs(geom_rsrp   - ground_truth_dbm), 2),
        "camera_error_db":         round(abs(camera_rsrp - ground_truth_dbm), 2)
    }

    with CV_DEMO_OUT.open("w") as f:
        json.dump(result, f, indent=2)

    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2))
    print(f"\nGeometric SVF {geometric_svf:.2f} → RSRP estimate {geom_rsrp:.1f} dBm")
    print(f"Camera SVF    {camera_svf:.2f} → RSRP estimate {camera_rsrp:.1f} dBm")
    print(f"Ground truth:                    {ground_truth_dbm:.1f} dBm")
    print(f"Error reduction: {result['geometric_error_db'] - result['camera_error_db']:.2f} dB")