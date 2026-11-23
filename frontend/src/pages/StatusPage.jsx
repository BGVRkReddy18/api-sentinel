import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api.js";
import { UptimeBars } from "../components/charts.jsx";
import { Empty, StatusDot } from "../components/ui.jsx";
import { formatDateTime, formatDuration, formatPct, parseTime } from "../format.js";
import { useLiveEvents } from "../store.jsx";

const OVERALL = {
  operational: { label: "All systems operational", tone: "up" },
  degraded: { label: "Some systems are slow", tone: "degraded" },
  partial_outage: { label: "Partial outage", tone: "down" },
  major_outage: { label: "Major outage", tone: "down" },
  maintenance: { label: "Scheduled maintenance in progress", tone: "maintenance" },
};
const SERVICE_LABEL = {
  up: "Operational",
  degraded: "Degraded performance",
  down: "Outage",
  maintenance: "Maintenance",
  unknown: "Pending",
};

export function StatusPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  const load = useCallback(async () => {
    try {
      setData(await api("/api/v1/status"));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 60000);
    return () => clearInterval(interval);
  }, [load]);

  // Status changes push instantly over the WebSocket (debounced refetch).
  useLiveEvents((event) => {
    if (event.type !== "status_changed" && event.type !== "alert") return;
    clearTimeout(timer.current);
    timer.current = setTimeout(load, 1500);
  });

  const overall = OVERALL[data?.overall] || OVERALL.operational;

  return (
    <div className="status-page">
      <header className="status-header">
        <div className="brand">🛡️ API Sentinel</div>
        <a href="/" className="muted small">
          Dashboard →
        </a>
      </header>
      {error ? (
        <Empty icon="⚠" title="Status unavailable">
          {error}
        </Empty>
      ) : !data ? (
        <Empty icon="⏳" title="Loading status…" />
      ) : (
        <>
          <div className={`status-banner tone-bg-${overall.tone}`}>
            <StatusDot status={overall.tone} pulse={overall.tone === "down"} />
            {overall.label}
          </div>

          <section className="status-services">
            {data.services.length === 0 && <Empty title="No public services yet" />}
            {data.services.map((s) => (
              <div key={s.id} className="status-service">
                <div className="status-service-head">
                  <span className="status-name">{s.name}</span>
                  <span className={`tone-${s.status}`}>
                    <StatusDot status={s.status} /> {SERVICE_LABEL[s.status] || s.status}
                  </span>
                </div>
                <UptimeBars days={s.days} height={34} />
                <div className="muted small">{formatPct(s.uptime_pct, 3)} uptime over 90 days</div>
              </div>
            ))}
          </section>

          <section className="status-incidents">
            <h2>Recent incidents</h2>
            {data.incidents.length === 0 ? (
              <p className="muted">No incidents in the last 14 days.</p>
            ) : (
              data.incidents.map((i) => {
                const started = parseTime(i.started_at);
                const resolved = parseTime(i.resolved_at);
                return (
                  <article key={`${i.service}-${i.started_at}`} className="status-incident">
                    <div className="status-incident-title">
                      <strong>{i.service}</strong>{" "}
                      {resolved ? (
                        <span className="tone-up">Resolved</span>
                      ) : (
                        <span className="tone-down">Investigating</span>
                      )}
                    </div>
                    <div className="small">{i.message}</div>
                    <div className="muted small">
                      {formatDateTime(i.started_at)}
                      {resolved && started && ` · lasted ${formatDuration((resolved - started) / 1000)}`}
                    </div>
                  </article>
                );
              })
            )}
          </section>
          <footer className="muted small center">Updated {formatDateTime(data.generated_at)} · live</footer>
        </>
      )}
    </div>
  );
}
