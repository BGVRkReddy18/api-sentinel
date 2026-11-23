import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api.js";
import { LineChart, UptimeBars } from "../components/charts.jsx";
import { EmailChips, EndpointForm } from "../components/EndpointForm.jsx";
import { Badge, Button, Empty, Menu, Modal, Segmented, StatusGlyph, StatusPill, Tabs } from "../components/ui.jsx";
import {
  daysUntil,
  displayStatus,
  formatDateTime,
  formatDuration,
  formatMs,
  formatPct,
  formatTime,
  isInMaintenance,
  timeAgo,
  timeUntil,
} from "../format.js";
import { navigate } from "../router.jsx";
import { useLive, useLiveEvents, useNow, useToasts } from "../store.jsx";

const RANGES = {
  "1h": { hours: 1, bucket: "minute" },
  "6h": { hours: 6, bucket: "minute" },
  "24h": { hours: 24, bucket: "hour" },
  "7d": { hours: 168, bucket: "hour" },
};

function useAsync(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const reload = useCallback(async () => {
    try {
      const data = await loader();
      setState({ data, error: null, loading: false });
    } catch (error) {
      setState({ data: null, error: error.message, loading: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return [state, reload];
}

function Metric({ label, value, tone }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-value${tone ? ` tone-${tone}` : ""}`}>{value}</div>
    </div>
  );
}

function AlertContacts({ endpoint, onSaved }) {
  const { meta } = useLive();
  const { push } = useToasts();
  const [emails, setEmails] = useState(endpoint.alert_emails || []);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const dirty = JSON.stringify(emails) !== JSON.stringify(endpoint.alert_emails || []);

  useEffect(() => setEmails(endpoint.alert_emails || []), [endpoint.alert_emails]);

  const save = async () => {
    setSaving(true);
    try {
      onSaved(await api(`/api/v1/endpoints/${endpoint.id}`, { method: "PATCH", body: { alert_emails: emails } }));
      push({ kind: "success", title: "Alert contacts saved", message: `${emails.length} recipient(s)` });
    } catch (e) {
      push({ kind: "error", title: "Could not save", message: e.message });
    } finally {
      setSaving(false);
    }
  };
  const test = async () => {
    setTesting(true);
    try {
      const result = await api(`/api/v1/endpoints/${endpoint.id}/test-alert`, { method: "POST" });
      push({ kind: "success", title: "Test email sent", message: result.sent_to.join(", ") });
    } catch (e) {
      push({ kind: "error", title: "Test email failed", message: e.message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="panel-section">
      <div className="section-title">
        <h4>Alert contacts</h4>
        {meta && (
          <Badge tone={meta.email_enabled ? "up" : "degraded"}>
            {meta.email_enabled ? `email via ${meta.email_provider}` : "email not configured"}
          </Badge>
        )}
      </div>
      <p className="muted small">
        These people get an email when {endpoint.name} goes down, recovers, slows down abnormally or its TLS
        certificate is about to expire.
      </p>
      <EmailChips value={emails} onChange={setEmails} />
      <div className="row-actions">
        <Button variant="primary" size="sm" onClick={save} loading={saving} disabled={!dirty}>
          Save contacts
        </Button>
        <Button size="sm" onClick={test} loading={testing} disabled={dirty || !emails.length || !meta?.email_enabled}>
          Send test email
        </Button>
      </div>
    </div>
  );
}

export function EndpointPanel({ id, onClose }) {
  const endpointId = Number(id);
  const { endpoints, summary, upsertEndpoint, refreshSummary, loaded } = useLive();
  const { push } = useToasts();
  const now = useNow(1000);
  const endpoint = endpoints[endpointId];
  const stats = summary[endpointId];

  const [tab, setTab] = useState("overview");
  const [range, setRange] = useState("6h");
  const [checks, setChecks] = useState([]);
  const [checking, setChecking] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [closing, setClosing] = useState(false);
  const refreshTimer = useRef(null);

  const close = useCallback(() => {
    setClosing(true);
    setTimeout(onClose, 180);
  }, [onClose]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape" && !editing && !confirmDelete) close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, editing, confirmDelete]);

  const [trend, reloadTrend] = useAsync(
    () =>
      api(
        `/api/v1/analytics/endpoints/${endpointId}/timeseries?hours=${RANGES[range].hours}&bucket=${RANGES[range].bucket}`,
      ),
    [endpointId, range],
  );
  const [uptime, reloadUptime] = useAsync(
    () => api(`/api/v1/analytics/endpoints/${endpointId}/uptime-daily?days=30`),
    [endpointId],
  );
  const [incidents, reloadIncidents] = useAsync(
    () => api(`/api/v1/analytics/endpoints/${endpointId}/incidents?hours=168&limit=20`),
    [endpointId],
  );
  const [errors, reloadErrors] = useAsync(
    () => api(`/api/v1/analytics/endpoints/${endpointId}/errors?hours=24`),
    [endpointId],
  );
  const [alerts, reloadAlerts] = useAsync(() => api(`/api/v1/alerts?endpoint_id=${endpointId}&limit=20`), [endpointId]);

  useEffect(() => {
    api(`/api/v1/endpoints/${endpointId}/results?limit=100&hours=24`)
      .then((page) => setChecks(page.items))
      .catch(() => setChecks([]));
  }, [endpointId]);

  useLiveEvents((event) => {
    if (event.data?.endpoint_id !== endpointId) return;
    if (event.type === "check") {
      setChecks((list) => [event.data.result, ...list.filter((c) => c.id !== event.data.result.id)].slice(0, 100));
      if (!refreshTimer.current) {
        refreshTimer.current = setTimeout(() => {
          refreshTimer.current = null;
          reloadTrend();
          reloadErrors();
          reloadIncidents();
        }, 10000);
      }
    }
    if (event.type === "alert") {
      reloadAlerts();
      reloadUptime();
    }
  });
  useEffect(() => () => clearTimeout(refreshTimer.current), []);

  const shell = (content) => (
    <div className={`drawer-overlay${closing ? " closing" : ""}`} onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <aside className="drawer" role="dialog" aria-modal="true">
        {content}
      </aside>
    </div>
  );

  if (!endpoint) {
    return shell(
      <Empty icon={loaded ? "?" : "◷"} title={loaded ? "Endpoint not found" : "Loading…"}>
        {loaded && <Button onClick={close}>Close</Button>}
      </Empty>,
    );
  }

  const status = displayStatus(endpoint, now);
  const sslDays = daysUntil(endpoint.ssl_expires_at, now);
  const inMaintenance = isInMaintenance(endpoint, now);
  const openAlerts = (alerts.data?.items || []).filter((a) => !a.resolved_at && a.kind !== "recovered").length;

  const act = async (fn, success) => {
    try {
      const result = await fn();
      if (result && result.id === endpointId) upsertEndpoint(result);
      if (success) push({ kind: "success", ...success });
    } catch (e) {
      push({ kind: "error", title: "Action failed", message: e.message });
    }
  };

  const runCheck = async () => {
    setChecking(true);
    try {
      const r = await api(`/api/v1/endpoints/${endpointId}/check`, { method: "POST" });
      push({
        kind: r.is_success ? "success" : "error",
        title: r.is_success ? "Check passed" : "Check failed",
        message: r.is_success ? `HTTP ${r.status_code} in ${formatMs(r.response_time_ms)}` : r.error_message || r.error_type,
      });
    } catch (e) {
      push({ kind: "error", title: "Check failed to run", message: e.message });
    } finally {
      setChecking(false);
    }
  };

  const maintenance = (minutes) =>
    act(
      () =>
        api(`/api/v1/endpoints/${endpointId}/maintenance`, {
          method: "POST",
          body: { minutes, reason: "Scheduled maintenance" },
        }),
      { title: "Maintenance started", message: `Alerts muted for ${formatDuration(minutes * 60)}` },
    );

  const remove = async () => {
    try {
      await api(`/api/v1/endpoints/${endpointId}`, { method: "DELETE" });
      push({ kind: "info", title: "Endpoint deleted", message: endpoint.name });
      refreshSummary();
      navigate("/");
    } catch (e) {
      push({ kind: "error", title: "Delete failed", message: e.message });
      setConfirmDelete(false);
    }
  };

  const liveData = [...checks].reverse().map((c) => ({
    t: c.checked_at,
    latency: c.is_success ? c.response_time_ms : null,
    failed: !c.is_success,
    failLabel: c.error_message || c.error_type,
  }));
  const trendData = (trend.data || []).map((p) => ({ t: p.bucket, avg: p.avg_latency_ms, p95: p.p95_latency_ms }));

  return shell(
    <>
      <header className="drawer-header">
        <div className="drawer-title">
          <StatusGlyph status={status} size={12} />
          <div>
            <h2>{endpoint.name}</h2>
            <a className="mono muted small drawer-url" href={endpoint.url} target="_blank" rel="noreferrer">
              {endpoint.method} {endpoint.url}
            </a>
          </div>
        </div>
        <button type="button" className="icon-btn" onClick={close} aria-label="Close">
          ✕
        </button>
      </header>

      <div className="drawer-toolbar">
        <StatusPill status={status} />
        <span className="muted small">
          checked {timeAgo(endpoint.last_checked_at, now)} · every {endpoint.interval_seconds}s
        </span>
        {inMaintenance && <Badge tone="maintenance">{timeUntil(endpoint.maintenance_until, now)} left</Badge>}
        <div className="spacer" />
        <Button variant="primary" size="sm" onClick={runCheck} loading={checking}>
          Run check
        </Button>
        <Button size="sm" onClick={() => setEditing(true)}>
          Edit
        </Button>
        <Menu
          trigger={({ toggle }) => (
            <Button size="sm" onClick={toggle} aria-label="More actions">
              •••
            </Button>
          )}
          items={[
            {
              icon: endpoint.is_active ? "⏸" : "▶",
              label: endpoint.is_active ? "Pause monitoring" : "Resume monitoring",
              onSelect: () =>
                act(() => api(`/api/v1/endpoints/${endpointId}`, { method: "PATCH", body: { is_active: !endpoint.is_active } }), {
                  title: endpoint.is_active ? "Paused" : "Resumed",
                  message: endpoint.name,
                }),
            },
            inMaintenance
              ? {
                  icon: "✓",
                  label: "End maintenance",
                  onSelect: () =>
                    act(() => api(`/api/v1/endpoints/${endpointId}/maintenance`, { method: "DELETE" }), {
                      title: "Maintenance ended",
                      message: "Alerts are active again",
                    }),
                }
              : { icon: "◐", label: "Maintenance · 1 hour", onSelect: () => maintenance(60) },
            ...(inMaintenance ? [] : [{ icon: "◑", label: "Maintenance · 24 hours", onSelect: () => maintenance(1440) }]),
            "divider",
            { icon: "✕", label: "Delete endpoint", danger: true, onSelect: () => setConfirmDelete(true) },
          ]}
        />
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "overview", label: "Overview" },
          { value: "checks", label: "Checks", count: checks.length },
          { value: "alerts", label: "Alerts", count: openAlerts },
          { value: "settings", label: "Settings" },
        ]}
      />

      <div className="drawer-body">
        {tab === "overview" && (
          <>
            <div className="metrics">
              <Metric label="Uptime 24h" value={formatPct(stats?.uptime_pct)} tone={stats?.uptime_pct < 99 ? "down" : undefined} />
              <Metric label="p50" value={formatMs(stats?.p50_latency_ms)} />
              <Metric label="p95" value={formatMs(stats?.p95_latency_ms)} />
              <Metric label="p99" value={formatMs(stats?.p99_latency_ms)} />
              <Metric label="Anomalies" value={stats?.anomalies ?? "–"} tone={stats?.anomalies ? "degraded" : undefined} />
            </div>

            <div className="panel-section">
              <div className="section-title">
                <h4>Response time</h4>
                <span className="live-tag">
                  <span className="live-dot" /> Live
                </span>
              </div>
              <LineChart
                data={liveData}
                series={[{ key: "latency", label: "response time", color: "var(--accent)" }]}
                markFailures
                height={190}
                emptyText="Waiting for the first check…"
              />
            </div>

            <div className="panel-section">
              <div className="section-title">
                <h4>Latency trend</h4>
                <Segmented
                  size="sm"
                  value={range}
                  onChange={setRange}
                  options={Object.keys(RANGES).map((r) => ({ value: r, label: r }))}
                />
              </div>
              {trend.error ? (
                <p className="muted small">{trend.error}</p>
              ) : (
                <LineChart
                  data={trendData}
                  series={[
                    { key: "avg", label: "average", color: "var(--accent)" },
                    { key: "p95", label: "p95", color: "var(--yellow)" },
                  ]}
                  height={190}
                />
              )}
            </div>

            <div className="panel-section">
              <div className="section-title">
                <h4>Uptime · 30 days</h4>
              </div>
              {uptime.error ? <p className="muted small">{uptime.error}</p> : <UptimeBars days={uptime.data || []} height={36} />}
            </div>

            <div className="two-col">
              <div className="panel-section">
                <div className="section-title">
                  <h4>Incidents · 7d</h4>
                </div>
                {(incidents.data || []).length === 0 ? (
                  <p className="muted small">No outages. ✓</p>
                ) : (
                  <ul className="timeline">
                    {incidents.data.map((i) => (
                      <li key={i.started_at} className={i.ongoing ? "ongoing" : ""}>
                        <div className="timeline-title">
                          {i.ongoing ? "Ongoing" : "Resolved"} · {i.failed_checks} failed checks
                        </div>
                        <div className="muted small">
                          {formatDateTime(i.started_at)} · {formatDuration(i.duration_seconds)}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="panel-section">
                <div className="section-title">
                  <h4>Failure modes · 24h</h4>
                </div>
                {(errors.data || []).length === 0 ? (
                  <p className="muted small">No errors. ✓</p>
                ) : (
                  <ul className="bars">
                    {errors.data.map((e) => {
                      const max = Math.max(...errors.data.map((x) => x.count));
                      return (
                        <li key={e.error_type}>
                          <div className="bars-label">
                            <span>{e.error_type.replace("_", " ")}</span>
                            <strong>{e.count}</strong>
                          </div>
                          <div className="bars-track">
                            <div className={`bars-fill err-${e.error_type}`} style={{ width: `${(100 * e.count) / max}%` }} />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          </>
        )}

        {tab === "checks" && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Result</th>
                  <th>Code</th>
                  <th className="num">Latency</th>
                  <th className="num">Tries</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c) => (
                  <tr key={c.id} className={c.is_success ? "" : "row-fail"}>
                    <td className="mono">{formatTime(c.checked_at)}</td>
                    <td>
                      <span className="inline-status">
                        <StatusGlyph status={!c.is_success ? "down" : c.error_type === "slow" ? "degraded" : "up"} size={8} />
                        {!c.is_success ? "failed" : c.error_type === "slow" ? "slow" : "ok"}
                      </span>
                    </td>
                    <td className="mono">{c.status_code ?? "–"}</td>
                    <td className="num mono">{formatMs(c.response_time_ms)}</td>
                    <td className="num">{c.attempts}</td>
                    <td className="muted small wrap">
                      {c.is_anomaly && <Badge tone="degraded">anomaly z={c.anomaly_score?.toFixed(1)}</Badge>}{" "}
                      {c.in_maintenance && <Badge tone="maintenance">maintenance</Badge>} {c.error_message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {checks.length === 0 && <Empty icon="◷" title="No checks in the last 24h" />}
          </div>
        )}

        {tab === "alerts" &&
          ((alerts.data?.items || []).length === 0 ? (
            <Empty icon="🔕" title="No alerts yet" />
          ) : (
            <ul className="alert-list">
              {alerts.data.items.map((a) => (
                <li key={a.id} className={`sev-${a.severity}`}>
                  <div>{a.message}</div>
                  <div className="muted small">
                    {timeAgo(a.created_at, now)} · {a.kind.replace("_", " ")}
                    {a.notified ? " · notified" : ""}
                    {a.resolved_at && a.kind !== "recovered" ? " · resolved" : ""}
                  </div>
                </li>
              ))}
            </ul>
          ))}

        {tab === "settings" && (
          <>
            <AlertContacts endpoint={endpoint} onSaved={upsertEndpoint} />
            <div className="panel-section">
              <div className="section-title">
                <h4>Configuration</h4>
                <Button size="sm" onClick={() => setEditing(true)}>
                  Edit
                </Button>
              </div>
              <dl className="config">
                <dt>Expected</dt>
                <dd>
                  HTTP {endpoint.expected_status}
                  {endpoint.expected_body_contains && <> · body contains “{endpoint.expected_body_contains}”</>}
                </dd>
                <dt>Latency SLO</dt>
                <dd>{endpoint.max_latency_ms ? `${endpoint.max_latency_ms} ms` : "not set"}</dd>
                <dt>Policy</dt>
                <dd>
                  every {endpoint.interval_seconds}s · timeout {endpoint.timeout_seconds}s · {endpoint.max_retries} retries
                </dd>
                <dt>Visibility</dt>
                <dd>{endpoint.is_public ? "Public status page" : "Private"}</dd>
                <dt>TLS</dt>
                <dd>
                  {endpoint.ssl_error
                    ? `error: ${endpoint.ssl_error}`
                    : endpoint.ssl_expires_at
                      ? `valid until ${formatDateTime(endpoint.ssl_expires_at)} (${sslDays} days)`
                      : endpoint.url.startsWith("https")
                        ? "not checked yet"
                        : "n/a (http)"}
                </dd>
                <dt>Created</dt>
                <dd>{formatDateTime(endpoint.created_at)}</dd>
              </dl>
            </div>
          </>
        )}
      </div>

      {editing && <EndpointForm endpoint={endpoint} onClose={() => setEditing(false)} />}
      {confirmDelete && (
        <Modal
          title={`Delete ${endpoint.name}?`}
          onClose={() => setConfirmDelete(false)}
          width={420}
          footer={
            <>
              <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
              <Button variant="danger" onClick={remove}>
                Delete permanently
              </Button>
            </>
          }
        >
          <p>This stops monitoring and permanently deletes its check history and alerts.</p>
        </Modal>
      )}
    </>,
  );
}
