const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function normalizeCarrier(carrier) {
    return carrier === 'vodafone' ? 'vi' : carrier;
}

function getCarrierMockTiles(allCarriers, carrier) {
    const normalizedCarrier = normalizeCarrier(carrier);
    return allCarriers[normalizedCarrier]
        || allCarriers[carrier]
        || (normalizedCarrier === 'vi' ? allCarriers.vodafone : null)
        || allCarriers.composite
        || [];
}

function distanceKm(a, b) {
    if (!a || !b) return Infinity;

    const [lng1, lat1] = a;
    const [lng2, lat2] = b;
    const toRad = (degrees) => degrees * Math.PI / 180;
    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);
    const h = Math.sin(dLat / 2) ** 2
        + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;

    return 6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function routeMatchesRequest(route, originCoords, destCoords) {
    const coords = route?.geometry?.coordinates;
    if (!Array.isArray(coords) || coords.length < 2) return false;

    const start = coords[0];
    const end = coords[coords.length - 1];

    // OSRM snaps to nearby roads, so allow a small tolerance around the requested points.
    return distanceKm(start, originCoords) <= 5 && distanceKm(end, destCoords) <= 5;
}

function routeSignature(route) {
    const coords = route?.geometry?.coordinates || [];
    if (coords.length === 0) return '';

    const first = coords[0];
    const mid = coords[Math.floor(coords.length / 2)];
    const last = coords[coords.length - 1];

    return [first, mid, last]
        .map(coord => coord.map(value => value.toFixed(3)).join(','))
        .join('|');
}

function uniqueRoutes(routes) {
    const seen = new Set();

    return routes.filter(route => {
        const signature = routeSignature(route);
        if (!signature || seen.has(signature)) return false;
        seen.add(signature);
        return true;
    });
}

function getRouteMidpoint(originCoords, destCoords) {
    return [
        (originCoords[0] + destCoords[0]) / 2,
        (originCoords[1] + destCoords[1]) / 2,
    ];
}

function getTileCoord(tile) {
    if (!Array.isArray(tile?.center) || tile.center.length < 2) return null;
    return [tile.center[1], tile.center[0]];
}

function scoreRouteWithTiles(route, tiles) {
    const coords = route?.geometry?.coordinates || [];
    if (coords.length === 0 || !Array.isArray(tiles) || tiles.length === 0) return 70;

    const stride = Math.max(1, Math.floor(coords.length / 35));
    const sampled = coords.filter((_, index) => index % stride === 0);
    let total = 0;
    let count = 0;

    sampled.forEach(coord => {
        let nearest = null;
        let nearestDistance = Infinity;

        tiles.forEach(tile => {
            const tileCoord = getTileCoord(tile);
            if (!tileCoord) return;

            const dist = distanceKm(coord, tileCoord);
            if (dist < nearestDistance) {
                nearestDistance = dist;
                nearest = tile;
            }
        });

        if (nearest && nearestDistance <= 3) {
            total += Number(nearest.score ?? 70);
            count += 1;
        }
    });

    return count > 0 ? Math.round(total / count) : 70;
}

function pickProviderViaPoints(tiles, originCoords, destCoords) {
    if (!Array.isArray(tiles) || tiles.length === 0) return [];

    const midpoint = getRouteMidpoint(originCoords, destCoords);
    const tripDistance = distanceKm(originCoords, destCoords);
    const maxMidpointDistance = Math.max(5, tripDistance * 0.45);

    return tiles
        .map(tile => ({ tile, coord: getTileCoord(tile), score: Number(tile.score ?? 0) }))
        .filter(({ coord, score }) => (
            coord
            && score >= 65
            && distanceKm(coord, midpoint) <= maxMidpointDistance
            && distanceKm(coord, originCoords) >= 1.5
            && distanceKm(coord, destCoords) >= 1.5
        ))
        .sort((a, b) => {
            const scoreDelta = b.score - a.score;
            if (scoreDelta !== 0) return scoreDelta;
            return distanceKm(a.coord, midpoint) - distanceKm(b.coord, midpoint);
        })
        .slice(0, 5)
        .map(({ coord }) => coord);
}

export const api = {
    // Fetch H3 heatmap tiles — backend first, mock fallback
    async heatTiles(west = 77.4, south = 12.8, east = 77.8, north = 13.2, carrier = "composite") {
        const backendCarrier = normalizeCarrier(carrier);
        try {
            const url = `${BASE_URL}/api/heat/tiles?west=${west}&south=${south}&east=${east}&north=${north}&carrier=${backendCarrier}`;
            const res = await fetch(url);
            const data = await res.json();
            
            // If backend returned tiles, use them. Otherwise fallback to carrier-specific mock.
            if (data.tiles && data.tiles.length > 0) {
                return data.tiles;
            }
            console.warn("Backend returned 0 tiles, using carrier-specific mock");
            const fallback = await fetch('/mock/heat_tiles_by_carrier.json');
            const allCarriers = await fallback.json();
            return getCarrierMockTiles(allCarriers, carrier);
        } catch (error) {
            console.error("Backend offline, falling back to carrier-specific mock");
            try {
                const fallback = await fetch('/mock/heat_tiles_by_carrier.json');
                const allCarriers = await fallback.json();
                return getCarrierMockTiles(allCarriers, carrier);
            } catch {
                const fallback = await fetch('/mock/heat_tiles.json');
                return await fallback.json();
            }
        }
    },

    // Score routes — uses backend scoring + OSRM for real geometry
    async scoreRoutes(
        originCoords,
        destCoords,
        alpha = 0.5,
        carrier = "composite",
        persona = "it_shuttle",
        timestamp = null,
        weatherScenario = 'live',
    ) {
        const backendCarrier = normalizeCarrier(carrier);
        if (!originCoords || !destCoords) {
            const fallback = await fetch('/mock/route_response.json');
            return await fallback.json();
        }

        // Helper for strict timeouts so the UI never hangs
        const fetchWithTimeout = async (url, options = {}, timeout = 2500) => {
            const controller = new AbortController();
            const id = setTimeout(() => controller.abort(), timeout);
            const response = await fetch(url, { ...options, signal: controller.signal });
            clearTimeout(id);
            return response;
        };

        console.log(`[ROUTING] Fetching OSRM and Backend data in PARALLEL for ${backendCarrier}...`);

        // Fetch OSRM Geometry (Timeout: 2.5s)
        const fetchOSRM = async () => {
            try {
                const res = await fetchWithTimeout(
                    `https://router.project-osrm.org/route/v1/driving/${originCoords[0]},${originCoords[1]};${destCoords[0]},${destCoords[1]}?overview=full&geometries=geojson&alternatives=3`
                );
                const data = await res.json();
                if (data.code === 'Ok' && data.routes.length > 0) return data.routes;
            } catch (e) {
                console.warn("[ROUTING] OSRM Primary failed, trying backup...");
                try {
                    const res = await fetchWithTimeout(
                        `https://routing.openstreetmap.de/routed-car/route/v1/driving/${originCoords[0]},${originCoords[1]};${destCoords[0]},${destCoords[1]}?overview=full&geometries=geojson&alternatives=3`
                    );
                    const data = await res.json();
                    if (data.code === 'Ok' && data.routes.length > 0) return data.routes;
                } catch (err) {
                    console.error("[ROUTING] All OSRM mirrors failed.");
                }
            }
            return null;
        };

        const fetchOSRMVia = async (viaCoord) => {
            const coords = `${originCoords[0]},${originCoords[1]};${viaCoord[0]},${viaCoord[1]};${destCoords[0]},${destCoords[1]}`;
            const path = `/route/v1/driving/${coords}?overview=full&geometries=geojson&alternatives=false`;
            const urls = [
                `https://router.project-osrm.org${path}`,
                `https://routing.openstreetmap.de/routed-car${path}`,
            ];

            for (const url of urls) {
                try {
                    const res = await fetchWithTimeout(url);
                    const data = await res.json();
                    if (data.code === 'Ok' && data.routes.length > 0) return data.routes[0];
                } catch {
                    // Try the next OSRM mirror.
                }
            }

            return null;
        };

        // Fetch Backend Intelligence
        const fetchBackend = async () => {
            try {
                const res = await fetchWithTimeout(`${BASE_URL}/api/route/score`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        origin: { lat: originCoords[1], lng: originCoords[0] }, 
                        destination: { lat: destCoords[1], lng: destCoords[0] },
                        alpha,
                        carrier: backendCarrier,
                        persona,
                        timestamp: timestamp || new Date().toISOString(),
                        weather_scenario: weatherScenario,
                    })
                }, 5000); // Backend gets a bit more time
                return await res.json();
            } catch (e) {
                console.warn("[ROUTING] Backend scoring unavailable");
                return null;
            }
        };

        // RUN BOTH IN PARALLEL FOR MAXIMUM SPEED
        const [osrmRoutes, backendData, carrierTiles] = await Promise.all([
            fetchOSRM(),
            fetchBackend(),
            api.heatTiles(
                Math.min(originCoords[0], destCoords[0]) - 0.08,
                Math.min(originCoords[1], destCoords[1]) - 0.08,
                Math.max(originCoords[0], destCoords[0]) + 0.08,
                Math.max(originCoords[1], destCoords[1]) + 0.08,
                backendCarrier,
            ),
        ]);

        let validOsrmRoutes = Array.isArray(osrmRoutes)
            ? osrmRoutes.filter(route => routeMatchesRequest(route, originCoords, destCoords))
            : [];
        validOsrmRoutes = uniqueRoutes(validOsrmRoutes);

        if (validOsrmRoutes.length < 2) {
            const viaPoints = pickProviderViaPoints(carrierTiles, originCoords, destCoords);

            for (const viaPoint of viaPoints) {
                const viaRoute = await fetchOSRMVia(viaPoint);
                if (!viaRoute || !routeMatchesRequest(viaRoute, originCoords, destCoords)) continue;

                validOsrmRoutes = uniqueRoutes([...validOsrmRoutes, viaRoute]);
                if (validOsrmRoutes.length >= 2) break;
            }
        }

        const validBackendRoutes = Array.isArray(backendData?.routes)
            ? backendData.routes.filter(route => routeMatchesRequest(route, originCoords, destCoords))
            : [];

        // Step 3: MERGE — Use OSRM geometry + Backend intelligence
        if (validOsrmRoutes.length > 0 && validBackendRoutes.length > 0) {
            const mergedRoutes = validBackendRoutes.map((backendRoute, i) => {
                const osrmRoute = validOsrmRoutes[i] || validOsrmRoutes[0];
                const geometry = osrmRoute.geometry || backendRoute.geometry;
                const baseEtaSeconds = Math.round(
                    osrmRoute.duration
                    ?? backendRoute.base_eta_seconds
                    ?? backendRoute.duration
                    ?? backendRoute.eta_seconds
                    ?? 0
                );
                const backendEtaSeconds = Math.round(
                    backendRoute.traffic_adjusted_eta_seconds
                    ?? backendRoute.eta_seconds
                    ?? baseEtaSeconds
                );
                const trafficDelaySeconds = Math.max(
                    0,
                    Math.round(
                        backendRoute.traffic_delay_seconds
                        ?? (backendEtaSeconds - baseEtaSeconds)
                    )
                );

                return {
                    ...backendRoute,
                    geometry: geometry,
                    distance: osrmRoute.distance,       // Real OSRM distance in meters
                    duration: osrmRoute.duration,       // Real OSRM duration in seconds
                    distance_meters: osrmRoute.distance,
                    base_eta_seconds: baseEtaSeconds,
                    traffic_delay_seconds: trafficDelaySeconds,
                    traffic_adjusted_eta_seconds: backendEtaSeconds,
                    eta_seconds: backendEtaSeconds,
                    connectivity_score: backendRoute.connectivity_score ?? scoreRouteWithTiles(osrmRoute, carrierTiles),
                    dead_zones: backendRoute.dead_zones || [],
                    dead_zone_count: backendRoute.dead_zone_count || backendRoute.dead_zones?.length || 0,
                    active_conditions: backendRoute.active_conditions || [],
                    event_warnings: backendRoute.event_warnings || [],
                    signal_profile: backendRoute.signal_profile || [],
                };
            });

            // If OSRM gave us an alternative route but backend didn't, add it
            if (mergedRoutes.length < 2 && validOsrmRoutes.length >= 2) {
                const alt = validOsrmRoutes[1];
                mergedRoutes.push({
                    ...mergedRoutes[0],
                    geometry: alt.geometry,
                    distance: alt.distance,
                    duration: alt.duration,
                    distance_meters: alt.distance,
                    base_eta_seconds: alt.duration,
                    traffic_delay_seconds: 0,
                    traffic_adjusted_eta_seconds: alt.duration,
                    eta_seconds: alt.duration,
                    connectivity_score: Math.max(30, (mergedRoutes[0].connectivity_score || 50) - 15),
                    dead_zones: [],
                    dead_zone_count: 0,
                    active_conditions: [],
                    event_warnings: [],
                    signal_profile: [],
                });
            }

            return {
                ...backendData,
                routes: mergedRoutes
            };
        }

        if (validOsrmRoutes.length > 0) {
            console.warn("[ROUTING] Backend scoring unavailable. Using OSRM road geometry with neutral signal metrics.");
            return {
                route_cache_key: null,
                routes: validOsrmRoutes.map((route) => ({
                    geometry: route.geometry,
                    distance: route.distance,
                    duration: route.duration,
                    distance_meters: route.distance,
                    base_eta_seconds: route.duration,
                    traffic_delay_seconds: 0,
                    traffic_adjusted_eta_seconds: route.duration,
                    eta_seconds: route.duration,
                    connectivity_score: scoreRouteWithTiles(route, carrierTiles),
                    dead_zones: [],
                    dead_zone_count: 0,
                    dominant_band: "5G_NR",
                    blended_rank_score: route.duration || 0,
                    active_conditions: [],
                    event_warnings: [],
                    signal_profile: [],
                })),
            };
        }

        console.warn("[ROUTING] No OSRM road geometry matched the requested origin/destination.");
        return {
            route_cache_key: null,
            routes: []
        };
    },

    // Fast <100ms Re-rank using cached key
    async rerankRoutes(routeCacheKey, alpha) {
        try {
            const res = await fetch(`${BASE_URL}/api/route/rerank`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ route_cache_key: routeCacheKey, alpha })
            });
            return await res.json();
        } catch (error) {
            console.error("Backend offline, cannot rerank");
            return null;
        }
    },

    // Natural Language Segment Explanation
    async explainSegment(osm_way_id) {
        try {
            const res = await fetch(`${BASE_URL}/api/segment/${osm_way_id}/explain`);
            if (!res.ok) return null;
            return await res.json();
        } catch (error) {
            return null;
        }
    }
};
