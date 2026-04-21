import MapContainer from './components/Map/MapContainer';
import PersonaPanel from './components/PersonaPanel';
import TelemetryHUD from './components/TelemetryHUD';
import NavigationPanel from './components/NavigationPanel';
import RouteSearch from './components/RouteSearch';
import FleetPanel from './components/FleetPanel';
import TimeTravelPanel from './components/TimeTravelPanel';

function App() {
  return (
    <div className="relative w-screen h-screen overflow-hidden bg-black">
      <RouteSearch />
      <MapContainer />
      <FleetPanel />
      <TimeTravelPanel />
      <PersonaPanel />
      <TelemetryHUD />
      <NavigationPanel />
    </div>
  )
}

export default App;
