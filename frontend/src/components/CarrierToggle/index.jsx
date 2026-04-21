import { useStore } from '../../store';

export default function CarrierToggle() {
    const { carrier, setCarrier } = useStore();

    const carriers = [
        { id: 'composite', label: 'All Networks' },
        { id: 'jio', label: 'Jio 5G/4G' },
        { id: 'airtel', label: 'Airtel 5G' },
        { id: 'vi', label: 'Vi' },
        { id: 'bsnl', label: 'BSNL' }
    ];

    return (
        <div className="absolute top-6 left-6 z-10 bg-black/40 backdrop-blur-xl border border-white/10 rounded-2xl p-4 shadow-2xl">
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-widest mb-3">Network Provider</label>
            <select
                value={carrier}
                onChange={(e) => setCarrier(e.target.value)}
                className="w-48 bg-white/5 border border-white/10 text-slate-200 text-sm rounded-xl focus:ring-1 focus:ring-slate-400 focus:border-slate-400 block p-2.5 outline-none cursor-pointer transition-all hover:bg-white/10"
            >
                {carriers.map(c => (
                    <option key={c.id} value={c.id} className="bg-slate-900">{c.label}</option>
                ))}
            </select>
        </div>
    );
}
