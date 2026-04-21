import { useStore } from '../../store';
import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import { cellToBoundary, cellToLatLng } from 'h3-js';
import { useDebounce } from 'use-debounce';
import { api } from '../../api/client';
import { H3_COLOR_EXPRESSION } from '../../constants/colors';
import {
    estimateExpectedBandwidth,
    getSignalProfilePointForProgress,
    getPreferredRouteIndex,
    getRouteConnectivity,
    getRouteDuration,
} from '../../utils/routeBlend';

const NAVIGATION_PROGRESS_STEP = 0.08;

function pickDisplayRoutes(routes) {
    if (!Array.isArray(routes) || routes.length === 0) {
        return [];
    }

    if (routes.length === 1) {
        return [routes[0], routes[0]];
    }

    const indexedRoutes = routes.map((route, index) => ({ route, index }));

    const connectivitySorted = [...indexedRoutes].sort((a, b) => {
        const connectivityDelta = getRouteConnectivity(b.route) - getRouteConnectivity(a.route);
        if (connectivityDelta !== 0) return connectivityDelta;

        const deadZoneDelta = (a.route.dead_zone_count || 0) - (b.route.dead_zone_count || 0);
        if (deadZoneDelta !== 0) return deadZoneDelta;

        return getRouteDuration(a.route) - getRouteDuration(b.route);
    });

    const speedSorted = [...indexedRoutes].sort((a, b) => {
        const durationDelta = getRouteDuration(a.route) - getRouteDuration(b.route);
        if (durationDelta !== 0) return durationDelta;

        return getRouteConnectivity(b.route) - getRouteConnectivity(a.route);
    });

    const connectivityRoute = connectivitySorted[0];
    const speedRoute = speedSorted[0];
    const signalRoute = connectivityRoute.index === speedRoute.index
        ? connectivitySorted.find(({ index }) => index !== speedRoute.index) || connectivityRoute
        : connectivityRoute;

    return [signalRoute.route, speedRoute.route];
}

function normalizeDisplayRoutePair(signalRoute, speedRoute) {
    if (!signalRoute) return [];

    return [signalRoute, speedRoute || signalRoute];
}

function getDeadZoneFeature(zone, index) {
    const coordinates = zone?.geometry?.coordinates;

    if (!coordinates?.length) return null;

    return {
        type: 'Feature',
        properties: {
            osm_way_id: zone.osm_way_id || '',
            duration_seconds: zone.duration_seconds || 0,
            length_meters: zone.length_meters || 0,
            prefetch_mb_required: zone.prefetch_mb_required || 0,
            index,
        },
        geometry: { type: 'LineString', coordinates },
    };
}

function getDeadZoneFeatures(route) {
    return route?.dead_zones?.map(getDeadZoneFeature).filter(Boolean) || [];
}

function getLiveSignalColor(score = 0) {
    if (score >= 85) return '#3b82f6';
    if (score >= 65) return '#22c55e';
    if (score >= 40) return '#facc15';
    if (score >= 25) return '#f97316';
    return '#ef4444';
}

function buildLiveSignalSnapshot(route, progress = 0) {
    const profilePoint = getSignalProfilePointForProgress(route?.signal_profile, progress);

    if (profilePoint) {
        const score = Math.round(profilePoint.score ?? route?.connectivity_score ?? 0);
        const dominantBand = profilePoint.dominant_band || route?.dominant_band || 'LTE_900';
        return {
            score,
            dominantBand,
            expectedBandwidthMbps: profilePoint.expected_bandwidth_mbps
                ?? estimateExpectedBandwidth(score, dominantBand),
            trafficEtaPenalty: profilePoint.traffic_eta_penalty || 0,
            color: getLiveSignalColor(score),
        };
    }

    const fallbackScore = Math.round(route?.connectivity_score ?? 50);
    const fallbackBand = route?.dominant_band || 'LTE_900';

    return {
        score: fallbackScore,
        dominantBand: fallbackBand,
        expectedBandwidthMbps: estimateExpectedBandwidth(fallbackScore, fallbackBand),
        trafficEtaPenalty: 0,
        color: getLiveSignalColor(fallbackScore),
    };
}

export default function MapContainer() {
    const {
        alpha,
        isNavigating,
        originCoords,
        destinationCoords,
        dynamicRouteData,
        setDynamicRouteData,
        carrier,
        persona,
        simulationHoursAhead,
        weatherScenario,
        addFleetAlerts,
        fleetAlerts,
        setRouteCacheKey,
        setCurrentNavSignal,
        setWeatherConditions,
    } = useStore();
    const mapContainer = useRef(null);
    const map = useRef(null);
    const routeGeometry = useRef(null);
    const animationFrame = useRef(null);
    const wsRef = useRef(null);
    const [mapLoaded, setMapLoaded] = React.useState(false);
    const [debouncedSimulationHoursAhead] = useDebounce(simulationHoursAhead, 250);

    const clearMapRoutes = () => {
        routeGeometry.current = null;
        setDynamicRouteData([]);
        setCurrentNavSignal(null);
        setWeatherConditions(null);

        if (!map.current?.getSource('route-a')) return;

        const emptyLine = { type: 'Feature', geometry: { type: 'LineString', coordinates: [] } };
        const emptyFC = { type: 'FeatureCollection', features: [] };

        map.current.getSource('route-a').setData(emptyLine);
        map.current.getSource('route-b').setData(emptyLine);
        map.current.getSource('dead-zones').setData(emptyFC);
        map.current.getSource('car').setData({ type: 'Feature', geometry: { type: 'Point', coordinates: [77.5946, 12.9716] } });
    };

    // Helper function to update map sources with backend route data
    const updateMapWithRoutes = (routes) => {
        const displayRoutes = pickDisplayRoutes(routes);
        if (displayRoutes.length === 0) return;

        const [connectivityRoute, speedRoute] = displayRoutes;
        const displayMetricRoutes = normalizeDisplayRoutePair(connectivityRoute, speedRoute);
        const coordsA = connectivityRoute.geometry.coordinates;

        const deadZoneFeatures = getDeadZoneFeatures(connectivityRoute);

        // Update the global ref for rendering
        routeGeometry.current = {
            routes: [
                {
                    geometry: connectivityRoute.geometry,
                    dead_zones: connectivityRoute.dead_zones || [],
                    signal_profile: connectivityRoute.signal_profile || [],
                    connectivity_score: connectivityRoute.connectivity_score,
                    dominant_band: connectivityRoute.dominant_band,
                },
                {
                    geometry: speedRoute.geometry,
                    dead_zones: speedRoute.dead_zones || [],
                    signal_profile: speedRoute.signal_profile || [],
                    connectivity_score: speedRoute.connectivity_score,
                    dominant_band: speedRoute.dominant_band,
                }
            ]
        };

        // Keep summaries and rendered paths tied to the same selected routes.
        setDynamicRouteData(displayMetricRoutes);

        // Update Maplibre Sources Dynamically!
        if (map.current.getSource('route-a')) {
            map.current.getSource('route-a').setData(routeGeometry.current.routes[0].geometry);
            map.current.getSource('route-b').setData(routeGeometry.current.routes[1].geometry);
            map.current.getSource('dead-zones').setData({ type: 'FeatureCollection', features: deadZoneFeatures });

            // Reset car to start
            map.current.getSource('car').setData({ type: 'Feature', geometry: { type: 'Point', coordinates: coordsA[0] } });
        }
    };

    // --- FLEET WEBSOCKET CONTROLLER ---
    useEffect(() => {
        const ws = new WebSocket("ws://127.0.0.1:8000/ws/fleet/stream");
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "fleet_telemetry" && data.alerts && data.alerts.length > 0) {
                    addFleetAlerts(data.alerts);
                }
            } catch (err) { console.error("WS parse error", err); }
        };
        wsRef.current = ws;
        return () => ws.close();
    }, [addFleetAlerts]);

    // Render Fleet Alerts to Map
    useEffect(() => {
        if (!map.current || !map.current.isStyleLoaded() || !map.current.getSource('fleet-alerts')) return;

        // Only show latest 10 alerts on map so it's not overwhelming
        const features = fleetAlerts.slice(0, 10).map(alert => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [alert.lng, alert.lat] }
        }));

        map.current.getSource('fleet-alerts').setData({
            type: 'FeatureCollection',
            features: features
        });
    }, [fleetAlerts]);

    useEffect(() => {
        if (map.current) return;

        map.current = new maplibregl.Map({
            container: mapContainer.current,
            style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
            center: [77.5946, 12.9716],
            zoom: 12
        });

        map.current.on('load', async () => {
            try {
                // ═══════════════════════════════════════════════════
                // 1. INITIALIZE EMPTY SOURCES & LAYERS
                // ═══════════════════════════════════════════════════
                const emptyFC = { type: 'FeatureCollection', features: [] };
                const emptyLine = { type: 'Feature', geometry: { type: 'LineString', coordinates: [] } };

                map.current.addSource('heatmap', { type: 'geojson', data: emptyFC });
                map.current.addSource('heatmap-points', { type: 'geojson', data: emptyFC });
                map.current.addLayer({
                    id: 'coverage-heat',
                    type: 'heatmap',
                    source: 'heatmap-points',
                    paint: {
                        'heatmap-weight': [
                            'interpolate', ['linear'], ['get', 'score'],
                            0, 0.08,
                            45, 0.4,
                            75, 0.82,
                            100, 1
                        ],
                        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 10, 0.48, 13, 1.1, 16, 1.7],
                        'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 10, 18, 13, 28, 16, 42],
                        'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 10, 0.48, 13, 0.58, 16, 0.72],
                        'heatmap-color': [
                            'interpolate', ['linear'], ['heatmap-density'],
                            0, 'rgba(15,23,42,0)',
                            0.18, 'rgba(239,68,68,0.2)',
                            0.36, 'rgba(249,115,22,0.34)',
                            0.56, 'rgba(250,204,21,0.46)',
                            0.76, 'rgba(187,247,208,0.56)',
                            1, 'rgba(74,222,128,0.68)'
                        ],
                    }
                });
                map.current.addLayer({
                    id: 'heatmap-fill',
                    type: 'fill',
                    source: 'heatmap',
                    paint: {
                        'fill-color': H3_COLOR_EXPRESSION,
                        'fill-opacity': ['interpolate', ['linear'], ['zoom'], 10, 0.07, 13, 0.11, 16, 0.18]
                    }
                });
                map.current.addLayer({
                    id: 'heatmap-border',
                    type: 'line',
                    source: 'heatmap',
                    layout: { 'line-join': 'round', 'line-cap': 'round' },
                    paint: {
                        'line-color': H3_COLOR_EXPRESSION,
                        'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0, 13, 0.45, 16, 1.1],
                        'line-opacity': ['interpolate', ['linear'], ['zoom'], 11, 0, 13, 0.2, 16, 0.42]
                    }
                });

                // ═══════════════════════════════════════════════════
                // 2. SIGNAL TOWER MARKERS
                // ═══════════════════════════════════════════════════
                map.current.addSource('towers', { type: 'geojson', data: emptyFC });

                // Outer glow ring — color-coded by signal quality
                map.current.addLayer({
                    id: 'tower-glow', type: 'circle', source: 'towers',
                    paint: {
                        'circle-radius': 0,
                        'circle-blur': 0.6,
                        'circle-opacity': 0,
                        'circle-color': [
                            'interpolate', ['linear'], ['get', 'score'],
                            0, '#ef4444',   // Red = dead zone
                            30, '#f97316',  // Orange = weak
                            60, '#eab308',  // Yellow = moderate
                            80, '#22c55e',  // Green = good
                            100, '#3b82f6'  // Blue = excellent
                        ]
                    }
                });

                // Inner white core dot (the "tower" icon)
                map.current.addLayer({
                    id: 'tower-core', type: 'circle', source: 'towers',
                    paint: {
                        'circle-radius': 0,
                        'circle-color': '#ffffff',
                        'circle-opacity': 0
                    }
                });

                // Tower click popup
                map.current.on('click', 'tower-core', (e) => {
                    const score = e.features[0].properties.score;
                    const quality = score >= 80 ? '5G Excellent' : score >= 60 ? '4G Good' : score >= 30 ? 'LTE Weak' : '⚠️ Dead Zone';
                    const color = score >= 80 ? '#3b82f6' : score >= 60 ? '#22c55e' : score >= 30 ? '#f97316' : '#ef4444';
                    new maplibregl.Popup({ closeButton: true, closeOnClick: true, className: 'neural-popup' })
                        .setLngLat(e.lngLat)
                        .setHTML(`<div style="padding:10px;font-family:sans-serif;color:#fff;background:#0f172a;border-radius:8px;">
                            <strong style="color:${color};font-size:11px;text-transform:uppercase;letter-spacing:1px;">${quality}</strong>
                            <p style="font-size:22px;font-weight:bold;margin:4px 0;">${score}<span style="font-size:12px;color:#94a3b8">/100</span></p>
                            <p style="font-size:10px;color:#64748b;">Signal strength at this tower location</p>
                        </div>`)
                        .addTo(map.current);
                });
                map.current.on('mouseenter', 'tower-core', () => { map.current.getCanvas().style.cursor = 'pointer'; });
                map.current.on('mouseleave', 'tower-core', () => { map.current.getCanvas().style.cursor = ''; });

                // ═══════════════════════════════════════════════════
                // 3. ROUTE LAYERS (empty — populated by useEffects)
                // ═══════════════════════════════════════════════════

                // Route A (Green — Signal Optimized)
                map.current.addSource('route-a', { type: 'geojson', data: emptyLine });
                map.current.addLayer({
                    id: 'route-a-glow', type: 'line', source: 'route-a', layout: { 'line-join': 'round', 'line-cap': 'round' },
                    paint: { 'line-color': '#22c55e', 'line-width': 12, 'line-blur': 10, 'line-opacity': 0.4, 'line-opacity-transition': { duration: 600 }, 'line-width-transition': { duration: 600 } }
                });
                map.current.addLayer({
                    id: 'route-a-line', type: 'line', source: 'route-a', layout: { 'line-join': 'round', 'line-cap': 'round' },
                    paint: { 'line-color': '#4ade80', 'line-width': 4, 'line-opacity-transition': { duration: 600 }, 'line-width-transition': { duration: 600 } }
                });

                // Route B (Blue — Speed Optimized)
                map.current.addSource('route-b', { type: 'geojson', data: emptyLine });
                map.current.addLayer({
                    id: 'route-b-glow', type: 'line', source: 'route-b', layout: { 'line-join': 'round', 'line-cap': 'round' },
                    paint: { 'line-color': '#3b82f6', 'line-width': 12, 'line-blur': 10, 'line-opacity': 0.3, 'line-opacity-transition': { duration: 600 }, 'line-width-transition': { duration: 600 } }
                });
                map.current.addLayer({
                    id: 'route-b-line', type: 'line', source: 'route-b', layout: { 'line-join': 'round', 'line-cap': 'round' },
                    paint: { 'line-color': '#60a5fa', 'line-width': 4, 'line-opacity-transition': { duration: 600 }, 'line-width-transition': { duration: 600 } }
                });

                // ═══════════════════════════════════════════════════
                // 4. DEAD ZONES (Red — No Connectivity)
                // ═══════════════════════════════════════════════════
                map.current.addSource('dead-zones', { type: 'geojson', data: emptyFC });
                map.current.addLayer({
                    id: 'dead-zones-glow', type: 'line', source: 'dead-zones', layout: { 'line-join': 'round', 'line-cap': 'round' },
                    paint: { 'line-color': '#ef4444', 'line-width': 14, 'line-blur': 12, 'line-opacity': 0.6, 'line-opacity-transition': { duration: 600 } }
                });
                map.current.addLayer({
                    id: 'dead-zones-line', type: 'line', source: 'dead-zones', layout: { 'line-join': 'round', 'line-cap': 'round' },
                    paint: { 'line-color': '#f87171', 'line-width': 5, 'line-dasharray': [1.5, 2], 'line-opacity-transition': { duration: 600 } }
                });

                // ═══════════════════════════════════════════════════
                // 5. VEHICLE MARKER
                // ═══════════════════════════════════════════════════
                map.current.addSource('car', {
                    type: 'geojson',
                    data: { type: 'Feature', geometry: { type: 'Point', coordinates: [77.5946, 12.9716] } }
                });
                map.current.addLayer({
                    id: 'car-pulse', type: 'circle', source: 'car',
                    paint: { 'circle-color': '#3b82f6', 'circle-radius': 16, 'circle-opacity': 0, 'circle-blur': 0.5, 'circle-opacity-transition': { duration: 500 } }
                });
                map.current.addLayer({
                    id: 'car-core', type: 'circle', source: 'car',
                    paint: { 'circle-color': '#ffffff', 'circle-radius': 5, 'circle-opacity': 0, 'circle-opacity-transition': { duration: 500 } }
                });

                // ═══════════════════════════════════════════════════
                // 6. FLEET ALERTS LAYER
                // ═══════════════════════════════════════════════════
                map.current.addSource('fleet-alerts', { type: 'geojson', data: emptyFC });
                map.current.addLayer({
                    id: 'fleet-alerts-glow', type: 'circle', source: 'fleet-alerts',
                    paint: { 'circle-color': '#ef4444', 'circle-radius': 14, 'circle-blur': 0.8, 'circle-opacity': 0.8 }
                });
                map.current.addLayer({
                    id: 'fleet-alerts-core', type: 'circle', source: 'fleet-alerts',
                    paint: { 'circle-color': '#ffffff', 'circle-radius': 4, 'circle-opacity': 1 }
                });

                // ═══════════════════════════════════════════════════
                // 7. CLICK HANDLERS
                // ═══════════════════════════════════════════════════
                map.current.on('click', 'dead-zones-glow', async (e) => {
                    const feature = e.features[0];
                    if (!feature) return;
                    const featureProps = feature.properties || {};
                    const osmWayId = featureProps['osm_way_id'];
                    const durationSeconds = Number(featureProps['duration_seconds'] || 0);
                    const lengthMeters = Number(featureProps['length_meters'] || 0);
                    const prefetchMb = Number(featureProps['prefetch_mb_required'] || 0);
                    const detailRows = [
                        lengthMeters > 0 ? `${Math.round(lengthMeters)} m affected` : null,
                        durationSeconds > 0 ? `${Math.round(durationSeconds)} sec expected impact` : null,
                        prefetchMb > 0 ? `${prefetchMb.toFixed(1)} MB prefetch recommended` : null,
                    ].filter(Boolean);
                    const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, className: 'neural-popup' })
                        .setLngLat(e.lngLat)
                        .setHTML(`<div style="padding:10px;font-family:sans-serif;color:#fff;background:#0f172a;border-radius:8px;">
                                    <strong style="color:#ef4444;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Dead Zone</strong>
                                    ${osmWayId ? '<p style="font-size:13px;margin-top:5px;color:#94a3b8;">Loading segment explanation...</p>' : ''}
                                  </div>`)
                        .addTo(map.current);
                    const result = osmWayId ? await api.explainSegment(osmWayId) : null;
                    const explanation = result?.explanation || result?.reason;
                    popup.setHTML(`<div style="padding:10px;font-family:sans-serif;color:#fff;background:#0f172a;border-radius:8px;max-width:250px;">
                                    <strong style="color:#ef4444;font-size:12px;text-transform:uppercase;letter-spacing:1px;">${osmWayId ? `Sector ${osmWayId}` : 'Dead Zone'}</strong>
                                    ${explanation ? `<p style="font-size:13px;margin-top:5px;line-height:1.4;">${explanation}</p>` : ''}
                                    ${detailRows.length > 0 ? `<p style="font-size:12px;margin-top:7px;line-height:1.4;color:#94a3b8;">${detailRows.join('<br/>')}</p>` : ''}
                                  </div>`);
                });

                map.current.on('mouseenter', 'dead-zones-glow', () => { map.current.getCanvas().style.cursor = 'pointer'; });
                map.current.on('mouseleave', 'dead-zones-glow', () => { map.current.getCanvas().style.cursor = ''; });

                setMapLoaded(true);
            } catch (err) { console.error("Map init error:", err); }
        });
    }, []);

    // --- CARRIER CHANGE: Refresh heatmap + towers ---
    useEffect(() => {
        if (!mapLoaded || !map.current) return;
        if (!map.current.getSource('heatmap') || !map.current.getSource('heatmap-points') || !map.current.getSource('towers')) return;

        const refreshCarrierData = async () => {
            console.log(`[MAP] Refreshing data for carrier: ${carrier}`);
            let tileData = await api.heatTiles(77.4, 12.8, 77.8, 13.2, carrier);
            if (!Array.isArray(tileData)) tileData = tileData.tiles || [];

            console.log(`[MAP] Received ${tileData.length} tiles for ${carrier}`);

            // Rebuild soft heat coverage. Hex fills stay subtle; the point layer gives the heatmap feel.
            const heatFeatures = tileData.map(tile => {
                const h3Id = tile.h3_id || tile.h3 || tile.id;
                if (!h3Id) return null;
                try {
                    const coords = cellToBoundary(h3Id, true);
                    if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) {
                        coords.push(coords[0]);
                    }
                    return {
                        type: 'Feature',
                        properties: { score: tile.score || 50, confidence: tile.confidence || 0.8 },
                        geometry: { type: 'Polygon', coordinates: [coords] }
                    };
                } catch { return null; }
            }).filter(Boolean);

            map.current.getSource('heatmap').setData({ type: 'FeatureCollection', features: heatFeatures });

            // Rebuild tower/heat points from the carrier-provided tile centers first.
            const towerFeatures = tileData
                .map(tile => {
                    const h3Id = tile.h3_id || tile.h3 || tile.id;
                    const tileCenter = Array.isArray(tile.center) && tile.center.length >= 2
                        ? [tile.center[1], tile.center[0]]
                        : null;
                    try {
                        const [lat, lng] = tileCenter ? [tileCenter[1], tileCenter[0]] : cellToLatLng(h3Id);
                        return {
                            type: 'Feature',
                            properties: { score: tile.score || 50 },
                            geometry: { type: 'Point', coordinates: [lng, lat] }
                        };
                    } catch { return null; }
                })
                .filter(Boolean);

            map.current.getSource('heatmap-points').setData({ type: 'FeatureCollection', features: towerFeatures });
            map.current.getSource('towers').setData({ type: 'FeatureCollection', features: towerFeatures });
        };

        refreshCarrierData();
    }, [carrier, mapLoaded]);

    // --- FULL BACKEND ROUTING CONTROLLER ---
    useEffect(() => {
        if (!mapLoaded || !map.current || !originCoords || !destinationCoords) return;

        const fetchDynamicRoutes = async () => {
            try {
                const simulatedTimestamp = new Date(
                    Date.now() + debouncedSimulationHoursAhead * 60 * 60 * 1000
                ).toISOString();
                const data = await api.scoreRoutes(
                    originCoords,
                    destinationCoords,
                    alpha,
                    carrier,
                    persona,
                    simulatedTimestamp,
                    weatherScenario,
                );
                if (data && data.routes && data.routes.length > 0) {
                    setWeatherConditions(data.weather_conditions || null);
                    if (data.route_cache_key) {
                        setRouteCacheKey(data.route_cache_key);
                    }
                    updateMapWithRoutes(data.routes);
                    const bounds = new maplibregl.LngLatBounds();
                    bounds.extend(originCoords);
                    bounds.extend(destinationCoords);
                    map.current.fitBounds(bounds, { padding: 150, duration: 1500 });
                } else {
                    clearMapRoutes();
                }
            } catch (err) { console.error("Dynamic Routing Error:", err); }
        };

        if (!isNavigating) fetchDynamicRoutes();
        // Alpha changes should only update route emphasis/metrics locally; refetching geometry on every slider move makes the ETA feel laggy.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [originCoords, destinationCoords, carrier, persona, debouncedSimulationHoursAhead, weatherScenario, isNavigating, mapLoaded]); // EXCLUDE ALPHA

    // --- SMOOTH INTERPOLATION CONTROLLER ---
    useEffect(() => {
        if (!mapLoaded || !map.current) return;

        const preferSignalRoute = alpha <= 0.5;
        try {
            const routeAOpacity = preferSignalRoute ? 1 : 0.14;
            const routeAWidth = preferSignalRoute ? 4.5 : 2;
            const routeAGlow = preferSignalRoute ? 0.4 : 0.05;
            const deadZoneOpacity = preferSignalRoute ? 1 : 0;
            const deadZoneGlow = preferSignalRoute ? 0.6 : 0;
            const routeBOpacity = preferSignalRoute ? 0.14 : 1;
            const routeBWidth = preferSignalRoute ? 2 : 4.5;
            const routeBGlow = preferSignalRoute ? 0.05 : 0.3;

            map.current.setPaintProperty('route-a-line', 'line-opacity', routeAOpacity);
            map.current.setPaintProperty('route-a-line', 'line-width', routeAWidth);
            map.current.setPaintProperty('route-a-glow', 'line-opacity', routeAGlow);

            map.current.setPaintProperty('dead-zones-line', 'line-opacity', deadZoneOpacity);
            map.current.setPaintProperty('dead-zones-glow', 'line-opacity', deadZoneGlow);

            map.current.setPaintProperty('route-b-line', 'line-opacity', routeBOpacity);
            map.current.setPaintProperty('route-b-line', 'line-width', routeBWidth);
            map.current.setPaintProperty('route-b-glow', 'line-opacity', routeBGlow);

            // Dynamically update car color if it exists
            if (map.current.getLayer('car-pulse')) {
                const preferredRouteIndex = getPreferredRouteIndex(dynamicRouteData, alpha);
                map.current.setPaintProperty('car-pulse', 'circle-color', preferredRouteIndex === 0 ? '#22c55e' : '#3b82f6');
            }
        } catch (err) {
            console.warn("Route style update skipped:", err);
        }
    }, [alpha, dynamicRouteData, mapLoaded]);

    // --- NAVIGATION CAMERA CONTROLLER & CAR ANIMATION ---
    useEffect(() => {
        if (!map.current || !routeGeometry.current) return;
        let timeoutId;

        const initialRouteIndex = getPreferredRouteIndex(
            useStore.getState().dynamicRouteData,
            useStore.getState().alpha,
        );

        if (isNavigating) {
            const initialRoute = routeGeometry.current.routes[initialRouteIndex];
            const initialSignal = buildLiveSignalSnapshot(initialRoute, 0);

            // 1. Show the car marker
            map.current.setPaintProperty('car-core', 'circle-opacity', 1);
            map.current.setPaintProperty('car-pulse', 'circle-opacity', 0.6);
            map.current.setPaintProperty('car-pulse', 'circle-color', initialSignal.color);
            useStore.getState().setCurrentNavSignal(initialSignal);

            // 2. Fly the camera in
            map.current.flyTo({
                center: initialRoute.geometry.coordinates[0],
                zoom: 16.5,
                pitch: 65,
                bearing: 30,
                essential: true,
                duration: 2000
            });

            // 3. Start driving the car down the road!
            let i = 0;

            const drive = () => {
                // Dynamically check the slider state every single frame!
                const currentAlpha = useStore.getState().alpha;
                const currentRouteIndex = getPreferredRouteIndex(useStore.getState().dynamicRouteData, currentAlpha);
                const activeRoute = routeGeometry.current.routes[currentRouteIndex];
                const coords = activeRoute.geometry.coordinates;

                // Ensure we don't crash if they switch to a route with fewer coordinates
                if (Math.floor(i) >= coords.length - 1) {
                    i = coords.length - 1.1;
                }

                if (i < coords.length - 1) {
                    const idx = Math.floor(i);
                    const fraction = i - idx;

                    const p1 = coords[idx];
                    const p2 = coords[idx + 1];

                    // Linear interpolation for perfectly smooth movement across frames
                    const lng = p1[0] + (p2[0] - p1[0]) * fraction;
                    const lat = p1[1] + (p2[1] - p1[1]) * fraction;
                    const currentCoord = [lng, lat];

                    map.current.getSource('car').setData({
                        type: 'Feature',
                        geometry: { type: 'Point', coordinates: currentCoord }
                    });

                    // Use jumpTo to prevent camera animation conflicts (this fixes the jitter!)
                    map.current.jumpTo({ center: currentCoord });

                    // Update progress so UI updates dynamically
                    const progress = Math.min(i / Math.max(coords.length - 1, 1), 1);
                    const liveSignal = buildLiveSignalSnapshot(activeRoute, progress);
                    map.current.setPaintProperty('car-pulse', 'circle-color', liveSignal.color);
                    useStore.getState().setCurrentNavSignal(liveSignal);
                    useStore.getState().setNavProgress(progress);

                    i += NAVIGATION_PROGRESS_STEP;
                    animationFrame.current = requestAnimationFrame(drive);
                } else {
                    useStore.getState().setCurrentNavSignal(buildLiveSignalSnapshot(activeRoute, 1));
                    useStore.getState().setNavProgress(1); // Arrived
                }
            };

            // Wait for the flyTo animation to finish before hitting the gas
            timeoutId = setTimeout(() => { drive(); }, 2000);

        } else {
            // Hide the car
            map.current.setPaintProperty('car-core', 'circle-opacity', 0);
            map.current.setPaintProperty('car-pulse', 'circle-opacity', 0);
            if (animationFrame.current) cancelAnimationFrame(animationFrame.current);
            useStore.getState().setCurrentNavSignal(null);

            // Zoom back out to the city view
            map.current.flyTo({
                center: [77.5946, 12.9716],
                zoom: 12,
                pitch: 0,
                bearing: 0,
                essential: true,
                duration: 2000
            });
        }

        // Cleanup function to absolutely guarantee the car stops when they hit Exit
        return () => {
            clearTimeout(timeoutId);
            if (animationFrame.current) cancelAnimationFrame(animationFrame.current);
            if (!useStore.getState().isNavigating) {
                useStore.getState().setCurrentNavSignal(null);
            }
        };
    }, [isNavigating]);

    const recenterMap = () => {
        if (map.current) map.current.flyTo({ center: [77.5946, 12.9716], zoom: 12, pitch: 0, bearing: 0, essential: true });
    };

    return (
        <>
            <div ref={mapContainer} className="w-screen h-screen" />

            {!isNavigating && (
                <button
                    onClick={recenterMap}
                    className="absolute bottom-10 right-6 z-10 bg-black/40 backdrop-blur-xl hover:bg-white/10 text-slate-200 text-sm font-medium py-3 px-6 rounded-2xl shadow-2xl border border-white/10 transition-all flex items-center gap-2"
                >
                    📍 Recenter
                </button>
            )}
        </>
    );
}
