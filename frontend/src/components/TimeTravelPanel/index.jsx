import { useStore } from '../../store';

const MAX_SIMULATION_HOURS = 24 * 7;
const HOUR_MS = 60 * 60 * 1000;

function formatOffset(hoursAhead) {
    if (hoursAhead === 0) return 'Live';

    const days = Math.floor(hoursAhead / 24);
    const hours = hoursAhead % 24;

    if (days === 0) return `+${hours}h`;
    if (hours === 0) return `+${days}d`;
    return `+${days}d ${hours}h`;
}

export default function TimeTravelPanel() {
    const {
        simulationHoursAhead,
        setSimulationHoursAhead,
        isNavigating,
    } = useStore();

    const simulatedNow = new Date(Date.now() + simulationHoursAhead * HOUR_MS);
    const simulatedDateLabel = simulatedNow.toLocaleString([], {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });

    return (
        <div className="absolute top-24 left-6 z-20 w-80 bg-black/60 backdrop-blur-2xl border border-white/10 rounded-3xl p-5 shadow-2xl flex flex-col gap-4">
            <div className="flex justify-between items-center border-b border-white/10 pb-3">
                <div className="flex flex-col">
                    <h3 className="text-white font-bold tracking-wide">Time Simulator</h3>
                    <span className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mt-1">
                        Route scoring preview
                    </span>
                </div>
                <span className="text-[10px] px-3 py-1 bg-amber-500/10 text-amber-300 rounded-full font-bold tracking-widest border border-amber-400/15">
                    {formatOffset(simulationHoursAhead)}
                </span>
            </div>

            <div className="bg-white/5 rounded-2xl border border-white/5 p-4 flex flex-col gap-3">
                <div className="flex justify-between items-end gap-3">
                    <div>
                        <span className="block text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-1">
                            Simulated Time
                        </span>
                        <span className="text-slate-100 font-semibold">{simulatedDateLabel}</span>
                    </div>
                    <button
                        type="button"
                        onClick={() => setSimulationHoursAhead(0)}
                        className="text-xs font-bold text-slate-300 hover:text-white transition-colors px-3 py-1.5 rounded-full border border-white/10 hover:border-white/20 bg-white/5 disabled:opacity-40"
                        disabled={simulationHoursAhead === 0 || isNavigating}
                    >
                        Reset
                    </button>
                </div>

                <input
                    type="range"
                    min="0"
                    max={MAX_SIMULATION_HOURS}
                    step="1"
                    value={simulationHoursAhead}
                    onChange={(e) => setSimulationHoursAhead(Number(e.target.value))}
                    disabled={isNavigating}
                    className="w-full h-2 bg-white/15 rounded-lg appearance-none cursor-pointer disabled:cursor-not-allowed [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-amber-300 [&::-webkit-slider-thumb]:shadow-[0_0_14px_rgba(252,211,77,0.55)]"
                />

                <div className="flex justify-between text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                    <span>Now</span>
                    <span>+7 Days</span>
                </div>
            </div>

            <p className="text-[11px] text-slate-400 leading-relaxed">
                {isNavigating
                    ? 'Exit navigation to rescore routes for a different time.'
                    : 'Move the slider to preview weekday peaks, match windows, and future route delays.'}
            </p>
        </div>
    );
}
