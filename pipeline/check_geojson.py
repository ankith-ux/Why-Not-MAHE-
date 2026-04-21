import geopandas as gpd
import matplotlib.pyplot as plt
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


GEOJSON_PATH = _first_existing(
    PROJECT_ROOT / "geojson/scored_segments.geojson",
    PROJECT_ROOT / "scored_segments.geojson",
)
PLOT_OUT = PROJECT_ROOT / "geojson/operator_scores.png"

gdf = gpd.read_file(GEOJSON_PATH)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

operators = ["jio_score", "airtel_score", "vi_score", "bsnl_score"]
for ax, col in zip(axes.flatten(), operators):
    gdf.plot(column=col, cmap="RdYlGn", legend=True, linewidth=2, ax=ax)
    ax.set_title(col)
    ax.axis("off")

plt.tight_layout()
PLOT_OUT.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(PLOT_OUT, dpi=150, bbox_inches="tight")  # ← saves file
plt.show()