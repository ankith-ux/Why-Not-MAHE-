import geopandas as gpd
import matplotlib.pyplot as plt

gdf = gpd.read_file("scored_segments.geojson")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

operators = ["jio_score", "airtel_score", "vi_score", "bsnl_score"]
for ax, col in zip(axes.flatten(), operators):
    gdf.plot(column=col, cmap="RdYlGn", legend=True, linewidth=2, ax=ax)
    ax.set_title(col)
    ax.axis("off")

plt.tight_layout()
plt.savefig("operator_scores.png", dpi=150, bbox_inches="tight")  # ← saves file
plt.show()