import { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import './App.css'
import ROUTE_DESCRIPTIONS from './routeDescriptions'

// --- 1. STABLE MAP CONTROLLER ---
function MapController({ center, zoom, bounds }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) {
      map.flyToBounds(bounds, { padding: [50, 50], duration: 1.5 });
    } else if (center) {
      map.flyTo(center, zoom || 15, { duration: 1.5 });
    }
  }, [center, zoom, bounds, map]);
  return null;
}

// --- 2. ROUTE CLEANER ---
const getCleanRouteName = (id) => {
  if (!id) return "N/A";
  const s = String(id);
  // Format: "1 27A c a" -> extract second part "27A"
  const parts = s.split(' ');
  if (parts.length >= 2) {
    return parts[1].toUpperCase();
  }
  // Fallback for other formats
  return s.includes('-') ? s.split('-')[1]?.toUpperCase() : s.includes('_') ? s.split('_')[0] : s;
};

// --- 2b. ROUTE DESCRIPTION LOOKUP ---
const getRouteDescription = (routeCode) => {
  if (!routeCode) return "";
  const clean = getCleanRouteName(routeCode);
  return ROUTE_DESCRIPTIONS[clean] || "";
};

// --- 3. DELAY-BASED COLOR FUNCTION ---
const getDelayColor = (delayMinutes) => {
  const delay = parseFloat(delayMinutes) || 0;
  if (delay < 0) return '#a855f7';    // Purple - Early
  if (delay <= 2) return '#00ccff';   // Cyan - On-time
  if (delay <= 5) return '#00ff88';   // Green - Minor
  if (delay <= 10) return '#ffcc00';  // Yellow - Moderate
  if (delay <= 20) return '#ff6600';  // Orange - Severe
  return '#ff0044';                    // Red - Critical
};

// --- 4. DELAY LOOKUP MAP BUILDER ---
const buildDelayMaps = (delays) => {
  const byTripId = {};
  const byCleanRoute = {};
  
  delays.forEach(d => {
    byTripId[d.route_id] = {
      delay: d.avg_delay_minutes,
      category: d.delay_category,
      trend: d.trend,
      trendChange: d.trend_change_minutes
    };
    
    const cleanName = getCleanRouteName(d.route_id);
    if (!byCleanRoute[cleanName] || Math.abs(d.avg_delay_minutes) > Math.abs(byCleanRoute[cleanName].delay)) {
      byCleanRoute[cleanName] = {
        delay: d.avg_delay_minutes,
        category: d.delay_category,
        trend: d.trend,
        trendChange: d.trend_change_minutes
      };
    }
  });
  
  return { byTripId, byCleanRoute };
};

const getVehicleDelayInfo = (bus, delayMaps) => {
  if (delayMaps.byTripId[bus.trip_id]) {
    return delayMaps.byTripId[bus.trip_id];
  }
  if (delayMaps.byTripId[bus.route_id]) {
    return delayMaps.byTripId[bus.route_id];
  }
  const cleanRoute = getCleanRouteName(bus.route_id);
  if (delayMaps.byCleanRoute[cleanRoute]) {
    return delayMaps.byCleanRoute[cleanRoute];
  }
  return { delay: 0, category: 'on_time', trend: 'stable', trendChange: null };
};

// --- 5. FORMAT DELAY TEXT ---
const formatDelay = (delay) => {
  const d = parseFloat(delay) || 0;
  if (d < 0) return `${d.toFixed(1)}m (early)`;
  if (d === 0) return 'On-time';
  return `+${d.toFixed(1)}m`;
};

// --- 6. TREND INDICATOR COMPONENT ---
const TrendIndicator = ({ trend, change }) => {
  if (!trend || trend === 'new') {
    return <span className="trend-indicator trend-new" title="New trip">●</span>;
  }
  
  if (trend === 'worsening') {
    return (
      <span className="trend-indicator trend-worsening" title={`Worsening: +${change}m vs 30min ago`}>
        ↑
      </span>
    );
  }
  
  if (trend === 'improving') {
    return (
      <span className="trend-indicator trend-improving" title={`Improving: ${change}m vs 30min ago`}>
        ↓
      </span>
    );
  }
  
  return (
    <span className="trend-indicator trend-stable" title="Stable">
      →
    </span>
  );
};

// --- 7. SUMMARY TREND INDICATOR ---
const SummaryTrendIndicator = ({ change }) => {
  if (change === null || change === undefined || change === 0) {
    return null;
  }
  
  if (change > 0) {
    return <span className="summary-trend trend-up">+{change}</span>;
  }
  
  return <span className="summary-trend trend-down">{change}</span>;
};

function App() {
  const [vehicles, setVehicles] = useState([]);
  const [allDelays, setAllDelays] = useState([]);
  const [filteredDelays, setFilteredDelays] = useState([]);
  const [selectedID, setSelectedID] = useState(null);
  const [filterRoute, setFilterRoute] = useState("ALL");
  const [filterCategory, setFilterCategory] = useState("ALL");
  const [mapState, setMapState] = useState({ center: [53.3498, -6.2603], zoom: 12, bounds: null });
  const [offlineAlert, setOfflineAlert] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [delaySummary, setDelaySummary] = useState([]);
  const [showGhosts, setShowGhosts] = useState(false);

  // FETCH ALL DATA
  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        
        const [vRes, allDelaysRes, summaryRes] = await Promise.all([
          axios.get('http://127.0.0.1:8000/vehicles'),
          axios.get('http://127.0.0.1:8000/delays?limit=10000'),
          axios.get('http://127.0.0.1:8000/delays/summary')
        ]);
        
        setVehicles(vRes.data || []);
        setAllDelays(allDelaysRes.data || []);
        setDelaySummary(summaryRes.data || []);
      } catch (e) {
        console.error("Fetch Error", e);
        setError(e.message || "Failed to connect to API");
      } finally {
        setIsLoading(false);
      }
    };
    fetchData();
    const inv = setInterval(fetchData, 30000);
    return () => clearInterval(inv);
  }, []);

  // FETCH FILTERED DELAYS when category changes
  useEffect(() => {
    const fetchFilteredDelays = async () => {
      try {
        if (filterCategory === "ALL") {
          setFilteredDelays(allDelays);
        } else {
          const res = await axios.get(`http://127.0.0.1:8000/delays?category=${filterCategory.toLowerCase()}&limit=5000`);
          setFilteredDelays(res.data || []);
        }
      } catch (e) {
        console.error("Fetch Filtered Error", e);
        setFilteredDelays(allDelays);
      }
    };
    
    if (allDelays.length > 0) {
      fetchFilteredDelays();
    }
  }, [filterCategory, allDelays]);

  const delayMaps = useMemo(() => buildDelayMaps(allDelays), [allDelays]);

  const sortedFilteredDelays = useMemo(() => {
    let delays = [...filteredDelays];
    
    // Filter out ghost trips if showGhosts is false
    if (!showGhosts) {
      delays = delays.filter(d => 
        vehicles.some(v => v.route_id === d.route_id || v.trip_id === d.route_id)
      );
    }
    
    return delays.sort((a, b) => {
      const order = { critical: 0, severe: 1, moderate: 2, minor: 3, on_time: 4, early: 5 };
      const orderA = order[a.delay_category] ?? 6;
      const orderB = order[b.delay_category] ?? 6;
      if (orderA !== orderB) {
        return orderA - orderB;
      }
      return Math.abs(b.avg_delay_minutes) - Math.abs(a.avg_delay_minutes);
    });
  }, [filteredDelays, showGhosts, vehicles]);

  const handleDelayClick = (row) => {
    setSelectedID(row.route_id);
    setOfflineAlert(null);

    const matches = vehicles.filter(v => v.route_id === row.route_id || v.trip_id === row.route_id);

    if (matches.length > 0) {
      if (matches.length === 1) {
        setMapState({ center: [matches[0].latitude, matches[0].longitude], zoom: 15, bounds: null });
      } else {
        const lats = matches.map(m => m.latitude), lons = matches.map(m => m.longitude);
        setMapState({ center: null, zoom: null, bounds: [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]] });
      }
    } else if (row.last_lat != null && row.last_lon != null) {
      setOfflineAlert(row.route_id);
      setMapState({ center: [row.last_lat, row.last_lon], zoom: 15, bounds: null });
    } else {
      setOfflineAlert(`${row.route_id} (no position data available)`);
    }
  };

  const liveDots = useMemo(() => {
    let filtered = vehicles;
    
    if (filterRoute !== "ALL") {
      filtered = filtered.filter(v => getCleanRouteName(v.route_id) === filterRoute);
    }
    
    if (filterCategory !== "ALL") {
      filtered = filtered.filter(v => {
        const delayInfo = getVehicleDelayInfo(v, delayMaps);
        return delayInfo.category === filterCategory.toLowerCase();
      });
    }
    
    if (selectedID) {
      const selectedFiltered = filtered.filter(v => v.route_id === selectedID || v.trip_id === selectedID);
      return selectedFiltered.length > 0 ? selectedFiltered : filtered;
    }
    
    return filtered;
  }, [vehicles, selectedID, filterRoute, filterCategory, delayMaps]);

  const ghostDots = useMemo(() => {
    return filteredDelays.filter(d => {
      const hasLiveVehicle = vehicles.some(v => v.route_id === d.route_id || v.trip_id === d.route_id);
      const matchesRouteFilter = filterRoute === "ALL" || getCleanRouteName(d.route_id) === filterRoute;
      return !hasLiveVehicle && d.last_lat != null && d.last_lon != null && matchesRouteFilter;
    });
  }, [vehicles, filteredDelays, filterRoute]);

  const getSummaryCount = (category) => {
    const found = delaySummary.find(s => s.delay_category === category);
    return found ? found.count : 0;
  };

  const getMappableCount = (category) => {
    const found = delaySummary.find(s => s.delay_category === category);
    return found ? found.mappable_count : 0;
  };

  const getSummaryChange = (category) => {
    const found = delaySummary.find(s => s.delay_category === category);
    return found ? found.change : null;
  };

  const totalTrips = useMemo(() => {
    return delaySummary.reduce((sum, s) => sum + (s.count || 0), 0);
  }, [delaySummary]);

  const ghostCount = useMemo(() => {
    return filteredDelays.filter(d => 
      !vehicles.some(v => v.route_id === d.route_id || v.trip_id === d.route_id)
    ).length;
  }, [filteredDelays, vehicles]);

  // Calculate trend counts
  const trendCounts = useMemo(() => {
    const counts = { worsening: 0, improving: 0, stable: 0, new: 0 };
    allDelays.forEach(d => {
      if (d.trend && counts[d.trend] !== undefined) {
        counts[d.trend]++;
      }
    });
    return counts;
  }, [allDelays]);

  if (isLoading) {
    return (
      <div className="dashboard-container">
        <div className="loading-overlay">
          <div className="loading-spinner"></div>
          <h2>Connecting to Dublin Transit Network...</h2>
          <p>Fetching live vehicle positions</p>
        </div>
      </div>
    );
  }

  if (error && vehicles.length === 0) {
    return (
      <div className="dashboard-container">
        <div className="error-overlay">
          <div className="error-icon">⚠️</div>
          <h2>Connection Failed</h2>
          <p>{error}</p>
          <p className="error-hint">Make sure the API server is running at http://127.0.0.1:8000</p>
          <button onClick={() => window.location.reload()} className="retry-btn">Retry Connection</button>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-container">
      <nav className="navbar">
        <div className="brand">
          <h1>Dublin Mobility <span className="highlight">Command Center</span></h1>
        </div>
        <div className="nav-status">
          {error && <span className="status-warning">⚠️ Update failed - showing cached data</span>}
          <span className="status-live">● LIVE</span>
        </div>
        <div className="filter-controls">
          <select 
            value={filterCategory} 
            onChange={(e) => { setFilterCategory(e.target.value); setSelectedID(null); }} 
            className="route-select category-select"
          >
            <option value="ALL">All Status ({totalTrips})</option>
            <option value="early">🟣 Early ({getSummaryCount('early')})</option>
            <option value="on_time">🔵 On-time ({getSummaryCount('on_time')})</option>
            <option value="minor">🟢 Minor ({getSummaryCount('minor')})</option>
            <option value="moderate">🟡 Moderate ({getSummaryCount('moderate')})</option>
            <option value="severe">🟠 Severe ({getSummaryCount('severe')})</option>
            <option value="critical">🔴 Critical ({getSummaryCount('critical')})</option>
          </select>
          
          <select 
            value={filterRoute} 
            onChange={(e) => { setFilterRoute(e.target.value); setSelectedID(null); }} 
            className="route-select route-filter-select"
          >
            <option value="ALL">All Routes</option>
            {[...new Set(vehicles.map(v => getCleanRouteName(v.route_id)))].sort((a, b) => {
              // Sort numerically where possible
              const aNum = parseInt(a);
              const bNum = parseInt(b);
              if (!isNaN(aNum) && !isNaN(bNum)) return aNum - bNum;
              if (!isNaN(aNum)) return -1;
              if (!isNaN(bNum)) return 1;
              return a.localeCompare(b);
            }).map(r => (
              <option key={r} value={r}>
                {r} {ROUTE_DESCRIPTIONS[r] ? `(${ROUTE_DESCRIPTIONS[r]})` : ''}
              </option>
            ))}
          </select>
        </div>
      </nav>

      <div className="content-wrapper">
        <aside className="sidebar">
          <div className="sidebar-header">
            <h2>Fleet Status</h2>
            <div className="delay-stats">
              <span className="stat early" title={`${getMappableCount('early')} on map`}>
                {getSummaryCount('early')} Early ({getMappableCount('early')})
                <SummaryTrendIndicator change={getSummaryChange('early')} />
              </span>
              <span className="stat on-time" title={`${getMappableCount('on_time')} on map`}>
                {getSummaryCount('on_time')} On-time ({getMappableCount('on_time')})
                <SummaryTrendIndicator change={getSummaryChange('on_time')} />
              </span>
              <span className="stat minor" title={`${getMappableCount('minor')} on map`}>
                {getSummaryCount('minor')} Minor ({getMappableCount('minor')})
                <SummaryTrendIndicator change={getSummaryChange('minor')} />
              </span>
              <span className="stat moderate" title={`${getMappableCount('moderate')} on map`}>
                {getSummaryCount('moderate')} Moderate ({getMappableCount('moderate')})
                <SummaryTrendIndicator change={getSummaryChange('moderate')} />
              </span>
              <span className="stat severe" title={`${getMappableCount('severe')} on map`}>
                {getSummaryCount('severe')} Severe ({getMappableCount('severe')})
                <SummaryTrendIndicator change={getSummaryChange('severe')} />
              </span>
              <span className="stat critical" title={`${getMappableCount('critical')} on map`}>
                {getSummaryCount('critical')} Critical ({getMappableCount('critical')})
                <SummaryTrendIndicator change={getSummaryChange('critical')} />
              </span>
            </div>
            
            {/* Trend Summary */}
            <div className="trend-summary">
              <span className="trend-stat worsening">↑ {trendCounts.worsening} worsening</span>
              <span className="trend-stat improving">↓ {trendCounts.improving} improving</span>
              <span className="trend-stat stable">→ {trendCounts.stable} stable</span>
            </div>
            
            <div className="legend">
              <span className="legend-item"><span className="dot" style={{background: '#a855f7'}}></span>Early</span>
              <span className="legend-item"><span className="dot" style={{background: '#00ccff'}}></span>On-time</span>
              <span className="legend-item"><span className="dot" style={{background: '#ff0044'}}></span>Critical</span>
              <span className="legend-item"><span className="dot ghost-dot"></span>Offline</span>
            </div>

            <div className="ghost-toggle">
              <button 
                onClick={() => setShowGhosts(!showGhosts)}
                className={`ghost-toggle-btn ${showGhosts ? 'active' : ''}`}
              >
                👻 {showGhosts ? 'Hide' : 'Show'} Offline Trips ({ghostCount})
              </button>
            </div>
          </div>
          <div className="table-wrapper">
            <table>
              <thead><tr><th>Trip (Route)</th><th>Delay</th><th>Trend</th></tr></thead>
              <tbody>
                {sortedFilteredDelays.map((row) => {
                  const isGhost = !vehicles.some(v => v.route_id === row.route_id || v.trip_id === row.route_id);
                  const color = getDelayColor(row.avg_delay_minutes);
                  const routeDesc = getRouteDescription(row.route_id);
                  return (
                    <tr 
                      key={row.route_id} 
                      onClick={() => handleDelayClick(row)} 
                      className={`${selectedID === row.route_id ? 'active-row' : ''} ${isGhost ? 'ghost-row' : ''}`}
                    >
                      <td>
                        <div className="trip-id-text">
                          {isGhost && <span className="ghost-badge">👻</span>}
                          {row.route_id}
                        </div>
                        <div className="route-subtext">
                          Route {getCleanRouteName(row.route_id)}
                          {routeDesc && <span className="route-desc"> • {routeDesc}</span>}
                          {row.delay_category && (
                            <span className={`category-badge ${row.delay_category}`}>
                              {row.delay_category}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="time-cell" style={{ color }}>
                        {formatDelay(row.avg_delay_minutes)}
                      </td>
                      <td className="trend-cell">
                        <TrendIndicator trend={row.trend} change={row.trend_change_minutes} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </aside>

        <main className="map-container">
          <MapContainer center={[53.3498, -6.2603]} zoom={12} style={{ height: "100%", width: "100%" }}>
            <MapController center={mapState.center} zoom={mapState.zoom} bounds={mapState.bounds} />
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />

            {/* LIVE VEHICLE DOTS */}
            {liveDots.map(bus => {
              const delayInfo = getVehicleDelayInfo(bus, delayMaps);
              const color = getDelayColor(delayInfo.delay);
              const isSelected = selectedID === bus.route_id || selectedID === bus.trip_id;
              const routeDesc = getRouteDescription(bus.route_id);
              
              return (
                <CircleMarker 
                  key={bus.vehicle_id} 
                  center={[bus.latitude, bus.longitude]} 
                  radius={isSelected ? 10 : 5} 
                  pathOptions={{ 
                    color: '#000', 
                    weight: isSelected ? 2 : 1, 
                    fillColor: color, 
                    fillOpacity: 0.9 
                  }}
                >
                  <Popup>
                    <strong>Route {getCleanRouteName(bus.route_id)}</strong>
                    {routeDesc && <><br/><em style={{fontSize: '0.85em', color: '#aaa'}}>{routeDesc}</em></>}
                    <br/>
                    Trip ID: {bus.trip_id || bus.route_id}<br/>
                    Delay: <span style={{color}}>{formatDelay(delayInfo.delay)}</span><br/>
                    Status: <span className={`category-badge ${delayInfo.category}`}>{delayInfo.category}</span><br/>
                    Trend: <TrendIndicator trend={delayInfo.trend} change={delayInfo.trendChange} />
                    <br/>
                    <em>🟢 Live GPS</em>
                  </Popup>
                </CircleMarker>
              );
            })}

            {/* GHOST DOTS */}
            {ghostDots.map(g => {
              const isSelected = selectedID === g.route_id;
              const color = getDelayColor(g.avg_delay_minutes);
              const routeDesc = getRouteDescription(g.route_id);
              
              return (
                <CircleMarker 
                  key={`ghost-${g.route_id}`} 
                  center={[g.last_lat, g.last_lon]} 
                  radius={isSelected ? 12 : 6} 
                  pathOptions={{ 
                    color: isSelected ? '#fff' : color, 
                    weight: 2, 
                    fillColor: color, 
                    fillOpacity: 0.4, 
                    dashArray: '4,4' 
                  }}
                >
                  <Popup>
                    <strong>👻 {getCleanRouteName(g.route_id)} - OFFLINE</strong>
                    {routeDesc && <><br/><em style={{fontSize: '0.85em', color: '#aaa'}}>{routeDesc}</em></>}
                    <br/>
                    Trip ID: {g.route_id}<br/>
                    Last Delay: <span style={{color}}>{formatDelay(g.avg_delay_minutes)}</span><br/>
                    Status: <span className={`category-badge ${g.delay_category}`}>{g.delay_category}</span><br/>
                    Trend: <TrendIndicator trend={g.trend} change={g.trend_change_minutes} />
                    <br/>
                    <em>⚪ Last known position</em>
                  </Popup>
                </CircleMarker>
              );
            })}
          </MapContainer>

          {offlineAlert && (
            <div className="warning-dialog">
              <strong>⚠️ Network Alert</strong>
              <p>Trip <span className="alert-route">{offlineAlert}</span> is currently offline.</p>
              <p className="alert-subtext">Showing last known position. Vehicle may have completed route or lost GPS signal.</p>
              <button onClick={() => setOfflineAlert(null)}>Dismiss</button>
            </div>
          )}

          <div className="map-legend">
            <div className="legend-title">Delay Status</div>
            <div className="legend-row"><span className="legend-color" style={{background: '#a855f7'}}></span> Early (ahead)</div>
            <div className="legend-row"><span className="legend-color" style={{background: '#00ccff'}}></span> On-time (0-2m)</div>
            <div className="legend-row"><span className="legend-color" style={{background: '#00ff88'}}></span> Minor (2-5m)</div>
            <div className="legend-row"><span className="legend-color" style={{background: '#ffcc00'}}></span> Moderate (5-10m)</div>
            <div className="legend-row"><span className="legend-color" style={{background: '#ff6600'}}></span> Severe (10-20m)</div>
            <div className="legend-row"><span className="legend-color" style={{background: '#ff0044'}}></span> Critical (20m+)</div>
            <div className="legend-divider"></div>
            <div className="legend-title">Trends</div>
            <div className="legend-row"><span className="trend-indicator trend-worsening">↑</span> Worsening</div>
            <div className="legend-row"><span className="trend-indicator trend-improving">↓</span> Improving</div>
            <div className="legend-row"><span className="trend-indicator trend-stable">→</span> Stable</div>
            <div className="legend-divider"></div>
            <div className="legend-row"><span className="legend-color solid-border"></span> Live GPS</div>
            <div className="legend-row"><span className="legend-color dashed-border"></span> Offline</div>
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;