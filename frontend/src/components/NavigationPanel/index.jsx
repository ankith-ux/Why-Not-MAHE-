import { useState, useEffect } from 'react';
import { useStore } from '../../store';
import {
    getPreferredRouteIndex,
    getSelectedRouteMetrics,
    getSignalQualityLabel,
} from '../../utils/routeBlend';

const HOUR_MS = 60 * 60 * 1000;

export default function NavigationPanel() {
    const {
        alpha,
        isNavigating,
        setIsNavigating,
        navProgress,
        dynamicRouteData,
        simulationHoursAhead,
        currentNavSignal,
    } = useStore();
    const [currentTime, setCurrentTime] = useState(
        () => new Date(Date.now() + simulationHoursAhead * HOUR_MS)
    );

    // Keep the ETA fresh while navigation progress is animating, using the simulated clock.
    useEffect(() => {
        const updateCurrentTime = () => {
            setCurrentTime(new Date(Date.now() + simulationHoursAhead * HOUR_MS));
        };

        updateCurrentTime();
        const timer = setInterval(updateCurrentTime, isNavigating ? 1000 : 60000);
        return () => clearInterval(timer);
    }, [isNavigating, simulationHoursAhead]);

    // Use dynamic OSRM data if available, otherwise fallback to mock values
    const hasRouteData = dynamicRouteData && dynamicRouteData.length > 0;
    const routeUnavailable = Array.isArray(dynamicRouteData) && dynamicRouteData.length === 0;
    const preferredRouteIndex = getPreferredRouteIndex(dynamicRouteData, alpha);
    const preferRouteA = preferredRouteIndex === 0;
    let totalEtaMins = 28;
    let totalEtaSeconds = totalEtaMins * 60;
    let totalDistanceKm = 12.4;

    // Backend Intelligence Metrics
    let connectivityScore = 95;
    let deadZoneCount = 0;
    let dominantBand = "5G_NR";
    let trafficDelaySeconds = 0;
    let activeConditions = [];

    if (dynamicRouteData && dynamicRouteData.length > 0) {
        const selectedMetrics = getSelectedRouteMetrics(dynamicRouteData, alpha);

        totalDistanceKm = Number((selectedMetrics.distanceMeters / 1000).toFixed(1));
        totalEtaSeconds = Math.max(60, selectedMetrics.durationSecs);
        totalEtaMins = Math.max(1, Math.round(totalEtaSeconds / 60));
        connectivityScore = Math.round(selectedMetrics.connectivityScore);
        deadZoneCount = selectedMetrics.deadZoneCount;
        dominantBand = selectedMetrics.dominantBand || "5G_NR";
        trafficDelaySeconds = selectedMetrics.trafficDelaySeconds || 0;
        activeConditions = selectedMetrics.activeConditions || [];
    }

    const primaryCondition = activeConditions[0] || null;
    const trafficDelayMins = trafficDelaySeconds > 0 ? Math.max(1, Math.round(trafficDelaySeconds / 60)) : 0;
    const trafficSummary = primaryCondition
        ? primaryCondition.type === 'venue_event'
            ? `${primaryCondition.reason} near ${primaryCondition.label}`
            : `${primaryCondition.reason} at ${primaryCondition.label}`
        : null;

    // Dynamic values based on navProgress
    const remainingEtaSeconds = Math.max(0, totalEtaSeconds * (1 - navProgress));
    const currentEtaMins = Math.max(0, Math.ceil(remainingEtaSeconds / 60));
    const currentDistKm = Math.max(0, totalDistanceKm * (1 - navProgress)).toFixed(1);

    const displayedEtaSeconds = isNavigating ? remainingEtaSeconds : totalEtaSeconds;
    const arrivalTime = new Date(currentTime.getTime() + displayedEtaSeconds * 1000);
    const arrivalString = arrivalTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // Static Navigation Status
    let instructionTitle = "Active Navigation";
    let instructionSub = "Monitoring 5G Signal Strength...";
    let icon = "M13 10V3L4 14h7v7l9-11h-7z"; // lightning bolt

    if (trafficSummary) {
        instructionSub = trafficSummary;
    }

    if (isNavigating) {
        const liveBandwidth = currentNavSignal?.expectedBandwidthMbps ?? null;
        const liveScore = Math.round(currentNavSignal?.score ?? connectivityScore);
        const liveBand = currentNavSignal?.dominantBand || dominantBand;
        const liveQuality = getSignalQualityLabel(liveScore);
        const bandwidthToneClass = liveScore < 25
            ? 'text-red-400'
            : liveScore < 40
                ? 'text-orange-300'
                : liveScore < 65
                    ? 'text-amber-300'
                    : 'text-emerald-300';

        return (
            <div className="absolute bottom-10 left-1/2 -translate-x-1/2 z-10 w-[26rem] bg-[#0f172a]/95 backdrop-blur-3xl border border-white/20 rounded-[2rem] p-6 shadow-[0_20px_50px_rgba(0,0,0,0.5)] flex flex-col gap-4 transition-all">
                <div className="flex items-center gap-5">
                    <div className="bg-emerald-500/20 p-4 rounded-2xl border border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.2)]">
                        <svg className="w-10 h-10 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d={icon}></path></svg>
                    </div>
                    <div>
                        <h2 className="text-white font-bold text-3xl tracking-wide">{instructionTitle}</h2>
                        <p className="text-emerald-400 text-sm font-bold tracking-widest uppercase mt-1">{instructionSub}</p>
                    </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                    <div className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
                        <span className="block text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-1">
                            Bandwidth
                        </span>
                        <span className={`text-2xl font-bold ${bandwidthToneClass}`}>
                            {liveBandwidth !== null ? liveBandwidth.toFixed(1) : '--'}
                        </span>
                        <span className="ml-1 text-xs font-semibold text-slate-400">Mbps</span>
                    </div>
                    <div className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
                        <span className="block text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-1">
                            Signal
                        </span>
                        <span className="text-2xl font-bold text-white">{liveScore}</span>
                        <span className="ml-1 text-xs font-semibold text-slate-400">/100</span>
                    </div>
                    <div className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
                        <span className="block text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-1">
                            Link
                        </span>
                        <span className="block text-sm font-bold text-blue-300 truncate">{liveBand}</span>
                        <span className="block text-[11px] font-semibold text-slate-400 mt-1">{liveQuality}</span>
                    </div>
                </div>

                <div className="flex justify-between items-end mt-2 pt-5 border-t border-white/10">
                    <div className="flex gap-4 items-baseline">
                        <span className={`font-bold text-3xl ${preferRouteA ? 'text-emerald-400' : 'text-blue-400'}`}>{currentEtaMins} <span className="text-base font-normal text-slate-400">min</span></span>
                        <span className="text-slate-300 font-semibold">{currentDistKm} km</span>
                        <span className="text-slate-400 font-medium">ETA {arrivalString}</span>
                    </div>
                    <button
                        onClick={() => setIsNavigating(false)}
                        className="bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/30 px-6 py-3 rounded-xl text-sm font-bold transition-all uppercase tracking-widest"
                    >
                        Exit
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="absolute bottom-10 left-1/2 -translate-x-1/2 z-10 w-[28rem] bg-black/40 backdrop-blur-xl border border-white/10 rounded-3xl p-6 shadow-2xl flex flex-col gap-4 transition-all">

            {/* Standard Navigation Info */}
            <div className="flex justify-between items-start">
                <div className="flex flex-col">
                    <span className={`text-4xl font-bold tracking-tight ${preferRouteA ? 'text-emerald-400' : 'text-blue-400'}`}>
                        {totalEtaMins} <span className="text-xl font-medium text-slate-400">min</span>
                    </span>
                    <span className="text-slate-400 font-medium mt-1">({totalDistanceKm} km) • Arrive at {arrivalString}</span>
                    {trafficDelayMins > 0 && (
                        <span className="text-xs font-semibold text-amber-300 mt-1">
                            Traffic-aware ETA includes +{trafficDelayMins} min
                            {primaryCondition ? ` near ${primaryCondition.label}` : ''}
                        </span>
                    )}
                </div>
            </div>

            {trafficSummary && (
                <div className="bg-amber-500/10 text-amber-200 rounded-xl px-3 py-2 border border-amber-400/15 text-[11px] leading-relaxed">
                    Monitoring {trafficSummary}.
                </div>
            )}

            {/* Backend Connectivity Intelligence Metrics */}
            <div className="flex justify-between items-center bg-black/50 rounded-xl p-3 border border-white/5 mt-1">
                <div className="flex flex-col items-center flex-1">
                    <span className="text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-1">Signal Score</span>
                    <span className={`text-xl font-bold ${connectivityScore < 50 ? 'text-red-400' : connectivityScore < 80 ? 'text-amber-400' : 'text-emerald-400'}`}>{connectivityScore}<span className="text-sm text-slate-400">/100</span></span>
                </div>
                <div className="flex flex-col items-center flex-1 border-l border-r border-white/10 px-2">
                    <span className="text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-1">Dead Zones</span>
                    <span className={`text-xl font-bold ${deadZoneCount > 0 ? 'text-red-400' : 'text-emerald-400'}`}>{deadZoneCount}</span>
                </div>
                <div className="flex flex-col items-center flex-1">
                    <span className="text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-1">Network</span>
                    <span className="text-lg font-bold text-blue-400 mt-0.5">{dominantBand}</span>
                </div>
            </div>

            <button
                onClick={() => setIsNavigating(true)}
                disabled={!hasRouteData}
                className={`w-full py-4 mt-2 rounded-2xl font-bold text-lg text-white shadow-lg transition-all uppercase tracking-widest disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400 disabled:shadow-none ${preferRouteA ? 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-900/50' : 'bg-blue-600 hover:bg-blue-500 shadow-blue-900/50'
                    }`}
            >
                {hasRouteData ? 'Start Navigation' : routeUnavailable ? 'Route Unavailable' : 'Loading Route...'}
            </button>
        </div>
    );
}
