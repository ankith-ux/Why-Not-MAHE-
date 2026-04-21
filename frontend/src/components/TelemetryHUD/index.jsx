import { useStore } from '../../store';
import {
    getSelectedRouteMetrics,
} from '../../utils/routeBlend';

const WEATHER_OPTIONS = [
    { value: 'live', label: 'Live Weather' },
    { value: 'clear', label: 'Clear' },
    { value: 'cloudy', label: 'Cloudy' },
    { value: 'light_rain', label: 'Light Rain' },
    { value: 'heavy_rain', label: 'Heavy Rain' },
    { value: 'thunderstorm', label: 'Thunderstorm' },
];

function formatWeatherLabel(value = 'clear') {
    return value
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function TelemetryHUD() {
    const {
        alpha,
        carrier,
        setCarrier,
        dynamicRouteData,
        weatherScenario,
        setWeatherScenario,
        weatherConditions,
    } = useStore();
    const selectedMetrics = getSelectedRouteMetrics(dynamicRouteData, alpha);
    const isDanger = selectedMetrics.deadZoneCount > 0;
    const dropDurationSeconds = selectedMetrics.dropDurationSeconds;
    const weatherLabel = formatWeatherLabel(weatherConditions?.condition || weatherScenario);
    const weatherSourceLabel = weatherConditions?.source === 'simulation'
        ? 'Simulated'
        : weatherConditions?.source === 'fallback'
            ? 'Fallback'
            : 'Live';
    const weatherAdjusted = Boolean(
        weatherConditions && !['clear', 'cloudy'].includes(weatherConditions.condition)
    );

    return (
        <div className="absolute top-6 right-6 z-10 w-[17rem] bg-black/60 backdrop-blur-2xl border border-white/10 rounded-2xl p-4 shadow-2xl flex flex-col gap-3">
            
            {/* Header */}
            <div className="flex justify-between items-center border-b border-white/10 pb-2.5">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Route Telemetry</span>
                <span className={`flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest px-2 py-1 rounded-full ${
                    isDanger ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${isDanger ? 'bg-red-500 animate-pulse' : 'bg-emerald-500'}`}></span>
                    {isDanger ? 'Warning' : 'Secure'}
                </span>
            </div>

            {/* Status Message */}
            <div className="flex flex-col gap-0.5">
                <h3 className={`text-base font-semibold tracking-wide ${isDanger ? 'text-white' : 'text-slate-200'}`}>
                    {isDanger ? 'Drop Predicted' : '5G Continuous'}
                </h3>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                    {isDanger 
                        ? 'Vehicle intersects high-probability dead zone. Media buffers likely.' 
                        : 'Route optimized to maintain continuous high-bandwidth connectivity.'}
                </p>
            </div>

            <div className={`rounded-xl p-3 border ${weatherAdjusted ? 'bg-sky-500/10 border-sky-400/20' : 'bg-white/5 border-white/5'}`}>
                <div className="flex justify-between items-center">
                    <span className="text-[8px] text-slate-500 uppercase tracking-widest font-bold">Weather</span>
                    <span className="text-[9px] font-bold uppercase tracking-widest text-slate-400">{weatherSourceLabel}</span>
                </div>
                <div className="flex items-end justify-between gap-3 mt-2">
                    <span className={`text-sm font-bold ${weatherAdjusted ? 'text-sky-300' : 'text-slate-200'}`}>
                        {weatherLabel}
                    </span>
                    <span className="text-[10px] text-slate-500 font-medium">
                        Signal only
                    </span>
                </div>
                <p className="text-[10px] text-slate-500 mt-2 leading-relaxed">
                    Weather reduces connectivity and bandwidth, but does not add traffic delay.
                </p>
            </div>

            {/* Stats & Carrier Grid */}
            <div className="grid grid-cols-2 gap-2 mt-1">
                <div className="bg-white/5 rounded-xl p-2 border border-white/5">
                    <span className="block text-[8px] text-slate-500 uppercase tracking-widest mb-1 font-bold">Drop Duration</span>
                    <span className={`font-mono text-base ${isDanger ? 'text-red-400' : 'text-slate-300'}`}>
                        {isDanger ? `${Math.round(dropDurationSeconds)} sec` : '0 sec'}
                    </span>
                </div>
                
                {/* Combined Carrier Toggle */}
                <div className="bg-white/5 rounded-xl p-2 border border-white/5 relative">
                    <span className="block text-[8px] text-slate-500 uppercase tracking-widest mb-1 font-bold">Network Profile</span>
                    <select 
                        value={carrier}
                        onChange={(e) => setCarrier(e.target.value)}
                        className="w-full bg-transparent text-slate-300 hover:text-white text-xs font-bold outline-none cursor-pointer appearance-none"
                    >
                        <option value="composite" className="bg-slate-900">All Networks</option>
                        <option value="jio" className="bg-slate-900">Jio 5G</option>
                        <option value="airtel" className="bg-slate-900">Airtel 5G</option>
                        <option value="vi" className="bg-slate-900">Vi</option>
                        <option value="bsnl" className="bg-slate-900">BSNL</option>
                    </select>
                    {/* Tiny dropdown arrow */}
                    <div className="absolute right-2 bottom-2.5 pointer-events-none text-slate-500">
                        <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M19 9l-7 7-7-7"></path></svg>
                    </div>
                </div>
            </div>

            <div className="bg-white/5 rounded-xl p-2 border border-white/5 relative">
                <span className="block text-[8px] text-slate-500 uppercase tracking-widest mb-1 font-bold">Weather Scenario</span>
                <select
                    value={weatherScenario}
                    onChange={(e) => setWeatherScenario(e.target.value)}
                    className="w-full bg-transparent text-slate-300 hover:text-white text-xs font-bold outline-none cursor-pointer appearance-none"
                >
                    {WEATHER_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value} className="bg-slate-900">
                            {option.label}
                        </option>
                    ))}
                </select>
                <div className="absolute right-2 bottom-2.5 pointer-events-none text-slate-500">
                    <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M19 9l-7 7-7-7"></path></svg>
                </div>
            </div>

        </div>
    );
}
