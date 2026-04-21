import { useStore } from '../../store';

export default function PersonaPanel() {
    const { alpha, setAlpha, personaPreset, setPersonaPreset } = useStore();

    const personas = [
        { id: 'fleet_ota', label: '🚚 Fleet OTA (Software Update)', targetAlpha: 0.05 },
        { id: 'it_shuttle', label: '🚌 IT Shuttle', targetAlpha: 0.3 },
        { id: 'default', label: '🚗 Standard Car', targetAlpha: 0.5 },
        { id: 'ride_hailing', label: '🚕 Ride Hailing', targetAlpha: 0.8 },
        { id: 'emergency', label: '🚑 Ambulance', targetAlpha: 0.95 }
    ];

    return (
        <div className="absolute bottom-6 left-6 z-10 w-80 bg-black/60 backdrop-blur-2xl border border-white/10 rounded-3xl p-6 shadow-2xl flex flex-col gap-5">
            <div className="flex justify-between items-center border-b border-white/10 pb-3">
                <h3 className="text-base font-bold text-white tracking-wide">Vehicle Persona</h3>
                <span className="text-[10px] px-3 py-1 bg-white/10 text-slate-300 rounded-full font-bold tracking-widest border border-white/10">ALPHA PRESET</span>
            </div>

            <div className="relative">
                <select
                    value={personaPreset}
                    onChange={(e) => {
                        const p = personas.find(p => p.id === e.target.value);
                        if (p) {
                            setPersonaPreset(p.id);
                            setAlpha(p.targetAlpha);
                        }
                    }}
                    className="w-full appearance-none bg-white/5 border border-white/10 hover:border-white/20 hover:bg-white/10 transition-all text-white text-sm font-bold py-3.5 px-4 rounded-xl cursor-pointer outline-none"
                >
                    <option value="custom" className="bg-slate-900 text-white py-2">
                        🎛️ Custom
                    </option>
                    {personas.map(p => (
                        <option key={p.id} value={p.id} className="bg-slate-900 text-white py-2">
                            {p.label}
                        </option>
                    ))}
                </select>
                <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                </div>
            </div>

            <div className="pt-2">
                <div className="flex justify-between text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">
                    <span className="flex items-center gap-2"><span className="w-2 h-2 bg-emerald-500 rounded-sm"></span>Signal</span>
                    <span className="flex items-center gap-2">Speed<span className="w-2 h-2 bg-blue-500 rounded-sm"></span></span>
                </div>

                <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value={alpha}
                    onChange={(e) => {
                        setPersonaPreset('custom');
                        setAlpha(parseFloat(e.target.value));
                    }}
                    className="w-full h-2 bg-white/20 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow-[0_0_10px_rgba(255,255,255,0.5)] transition-all"
                />

                <div className="mt-4 flex justify-center">
                    <div className="bg-white/5 px-4 py-1.5 rounded-full border border-white/10">
                        <span className="font-mono text-[10px] font-bold text-slate-300">ALPHA (A) = {alpha.toFixed(2)}</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
