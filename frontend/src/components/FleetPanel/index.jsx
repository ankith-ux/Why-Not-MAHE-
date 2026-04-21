import { useStore } from '../../store';

export default function FleetPanel() {
    const { fleetAlerts } = useStore();

    if (fleetAlerts.length === 0) return null;

    return (
        <div className="absolute right-6 top-32 w-80 bg-black/60 backdrop-blur-3xl border border-white/10 rounded-3xl p-5 shadow-[0_20px_50px_rgba(0,0,0,0.5)] flex flex-col gap-4 z-50 transition-all">
            <div className="flex items-center gap-3 border-b border-white/10 pb-3">
                <div className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
                </div>
                <h3 className="text-white font-bold tracking-widest uppercase text-sm">Live Fleet Telemetry</h3>
            </div>
            
            <div className="flex flex-col gap-2 max-h-64 overflow-y-auto pr-2 custom-scrollbar">
                {fleetAlerts.map((alert, i) => (
                    <div key={i} className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 flex flex-col gap-1 shadow-inner shadow-red-500/5 transition-all animate-in slide-in-from-right-4 duration-300">
                        <div className="flex justify-between items-center">
                            <span className="text-red-400 font-bold text-[10px] tracking-wider uppercase px-2 py-0.5 bg-red-500/20 rounded-md">{alert.vehicle_id}</span>
                            <span className="text-slate-400 text-[10px] font-mono">{new Date(alert.timestamp).toLocaleTimeString()}</span>
                        </div>
                        <span className="text-white text-sm font-semibold tracking-wide mt-1">{alert.alert}</span>
                        <span className="text-slate-500 text-[9px] font-mono mt-0.5">LAT: {alert.lat.toFixed(4)} | LNG: {alert.lng.toFixed(4)}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}
