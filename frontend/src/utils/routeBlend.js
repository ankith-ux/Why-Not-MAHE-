export function getRouteDuration(route) {
    return route?.traffic_adjusted_eta_seconds || route?.eta_seconds || route?.duration || 0;
}

export function getRouteBaseDuration(route) {
    return route?.base_eta_seconds || route?.duration || getRouteDuration(route);
}

export function getRouteDistance(route) {
    return route?.distance_meters || route?.distance || 0;
}

export function getRouteConnectivity(route) {
    return route?.connectivity_score ?? 0;
}

export function getRouteDeadZoneCount(route) {
    return route?.dead_zone_count || 0;
}

export function getRouteDeadZoneDuration(route) {
    return route?.dead_zones?.reduce(
        (total, zone) => total + (zone.duration_seconds || 0),
        0,
    ) || 0;
}

export function getRouteTrafficDelay(route) {
    return route?.traffic_delay_seconds || 0;
}

export function getRouteActiveConditions(route) {
    return route?.active_conditions || [];
}

export function getRouteSignalProfile(route) {
    return route?.signal_profile || [];
}

export function estimateExpectedBandwidth(score = 0, dominantBand = "LTE_900") {
    const bandPeakMbps = {
        '5G_NR': 220,
        'LTE_2300': 80,
        'LTE_900': 30,
        GSM: 1.5,
    };

    const peak = bandPeakMbps[dominantBand] ?? 30;
    const quality = Math.max(0, Math.min(score, 100)) / 100;
    let bandwidth = peak * (quality ** 1.85);

    if (score < 25) {
        bandwidth *= 0.25;
    }

    return Number(Math.max(0.1, bandwidth).toFixed(1));
}

export function getSignalProfilePointForProgress(profile, progress) {
    if (!Array.isArray(profile) || profile.length === 0) return null;

    const normalizedProgress = Math.max(0, Math.min(progress ?? 0, 1));
    const currentIndex = profile.findIndex(
        (point) => normalizedProgress <= (point.progress_end ?? 1)
    );
    const safeIndex = currentIndex >= 0 ? currentIndex : profile.length - 1;
    const currentPoint = profile[safeIndex];
    const nextPoint = profile[Math.min(safeIndex + 1, profile.length - 1)];

    if (!currentPoint || !nextPoint || currentPoint === nextPoint) {
        return currentPoint || null;
    }

    const rangeStart = Number(currentPoint.progress_start ?? 0);
    const rangeEnd = Number(currentPoint.progress_end ?? rangeStart);
    const rangeSpan = Math.max(rangeEnd - rangeStart, 0.0001);
    const blend = Math.max(0, Math.min((normalizedProgress - rangeStart) / rangeSpan, 1));

    const currentScore = Number(currentPoint.score ?? 0);
    const nextScore = Number(nextPoint.score ?? currentScore);
    const currentBandwidth = Number(
        currentPoint.expected_bandwidth_mbps ?? estimateExpectedBandwidth(currentScore, currentPoint.dominant_band)
    );
    const nextBandwidth = Number(
        nextPoint.expected_bandwidth_mbps ?? estimateExpectedBandwidth(nextScore, nextPoint.dominant_band)
    );
    const currentPenalty = Number(currentPoint.traffic_eta_penalty ?? 0);
    const nextPenalty = Number(nextPoint.traffic_eta_penalty ?? currentPenalty);

    return {
        ...currentPoint,
        score: Number((currentScore + (nextScore - currentScore) * blend).toFixed(1)),
        expected_bandwidth_mbps: Number(
            (currentBandwidth + (nextBandwidth - currentBandwidth) * blend).toFixed(1)
        ),
        traffic_eta_penalty: Number(
            (currentPenalty + (nextPenalty - currentPenalty) * blend).toFixed(4)
        ),
        dominant_band: blend >= 0.5 ? (nextPoint.dominant_band || currentPoint.dominant_band) : currentPoint.dominant_band,
    };
}

export function getSignalQualityLabel(score = 0) {
    if (score >= 80) return 'Excellent';
    if (score >= 60) return 'Good';
    if (score >= 35) return 'Fair';
    if (score >= 25) return 'Weak';
    return 'Dead Zone';
}

export function getPreferredRouteIndex(routes, alpha) {
    if (!routes?.[0]) return 0;
    if (!routes?.[1]) return 0;

    return alpha > 0.5 ? 1 : 0;
}

export function getSelectedRouteMetrics(routes, alpha) {
    const selectedRoute = routes?.[getPreferredRouteIndex(routes, alpha)] || routes?.[0];

    if (!selectedRoute) {
        return {
            durationSecs: 0,
            distanceMeters: 0,
            connectivityScore: 0,
            deadZoneCount: 0,
            dropDurationSeconds: 0,
            dominantBand: "5G_NR",
            signalProfile: [],
        };
    }

    return {
        durationSecs: getRouteDuration(selectedRoute),
        baseDurationSecs: getRouteBaseDuration(selectedRoute),
        distanceMeters: getRouteDistance(selectedRoute),
        connectivityScore: getRouteConnectivity(selectedRoute),
        deadZoneCount: getRouteDeadZoneCount(selectedRoute),
        dropDurationSeconds: getRouteDeadZoneDuration(selectedRoute),
        dominantBand: selectedRoute.dominant_band || "5G_NR",
        trafficDelaySeconds: getRouteTrafficDelay(selectedRoute),
        activeConditions: getRouteActiveConditions(selectedRoute),
        eventWarnings: selectedRoute.event_warnings || [],
        signalProfile: getRouteSignalProfile(selectedRoute),
    };
}
