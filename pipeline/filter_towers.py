# filter_towers.py — run from inside archive/
import pandas as pd

BBOX = {'lat_min': 12.834, 'lat_max': 13.139, 
        'lon_min': 77.469, 'lon_max': 77.748}

# MNC → carrier mapping for India
MNC_MAP = {
    # MCC 404
    50: 'jio',
    45: 'airtel',
    49: 'airtel',
    10: 'airtel',
    20: 'vi',
    1:  'bsnl',
    7:  'bsnl',
    # MCC 405 (circle-based)
    861: 'jio',
    860: 'jio',
    859: 'jio',
    858: 'jio',
    857: 'jio',
    803: 'airtel',
    810: 'airtel',
    845: 'vi',
    846: 'vi',
    847: 'vi',
    800: 'bsnl',
    801: 'bsnl',
    86:  'vi',
    844: 'vi',
    848: 'vi',
    849: 'vi',
    850: 'vi',
    34:  'bsnl',
}

# Radio → frequency MHz defaults
FREQ_MAP = {
    'jio':    {'NR': 3500, 'LTE': 2300, 'HSPA': 2100, 'GSM': 900},
    'airtel': {'NR': 3500, 'LTE': 1800, 'HSPA': 2100, 'GSM': 900},
    'vi':     {'NR': 3500, 'LTE': 900,  'HSPA': 2100, 'GSM': 900},
    'bsnl':   {'NR': 3500, 'LTE': 850,  'HSPA': 2100, 'GSM': 900},
}

dfs = []
for fname in ['404.csv', '405.csv']:
    print(f"Loading {fname}...")
    df = pd.read_csv(fname)
    # rename columns to standard names
    df = df.rename(columns={'long': 'lon', 'sample': 'samples'})
    dfs.append(df)

df = pd.concat(dfs, ignore_index=True)
print(f"Total India towers: {len(df)}")

# Filter to Bangalore bounding box
df = df[
    (df['lat'] >= BBOX['lat_min']) & (df['lat'] <= BBOX['lat_max']) &
    (df['lon'] >= BBOX['lon_min']) & (df['lon'] <= BBOX['lon_max'])
]
print(f"Bangalore towers: {len(df)}")
print(df['mnc'].value_counts())

# Split by carrier — aggregate all matching MNCs per carrier
carrier_dfs = {'jio': [], 'airtel': [], 'vi': [], 'bsnl': []}

for mnc, carrier in MNC_MAP.items():
    subset = df[df['mnc'] == mnc].copy()
    if len(subset) > 0:
        subset['carrier'] = carrier
        freq_defaults = FREQ_MAP[carrier]
        subset['freq_mhz'] = subset['radio'].map(freq_defaults).fillna(1800).astype(int)
        carrier_dfs[carrier].append(subset)

for carrier, parts in carrier_dfs.items():
    if not parts:
        print(f"WARNING: no towers for {carrier} — skipping")
        continue
    cdf = pd.concat(parts, ignore_index=True)
    cdf = cdf[['lat','lon','radio','freq_mhz','range','samples','carrier','mnc','mcc']].copy()
    cdf.to_parquet(f"towers_{carrier}.parquet", index=False)
    print(f"  {carrier}: {len(cdf)} towers → towers_{carrier}.parquet")

print("\nDone. Tower files written to current directory.")