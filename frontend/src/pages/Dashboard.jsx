import { useEffect, useMemo, useRef, useState } from "react";

import { CheckStrip } from "../components/charts.jsx";
import { AnimatedNumber, Badge, Button, Empty, Kbd, Segmented, Skeleton, StatusGlyph } from "../components/ui.jsx";
import { daysUntil, displayStatus, formatMs, formatPct, formatTime, hostOf, timeAgo } from "../format.js";
import { Link } from "../router.jsx";
import { useLive, useNow } from "../store.jsx";

const FILTERS = ["all", "up", "degraded", "down", "maintenance", "paused"];
const HEADLINE = {
  ok: { text: "All systems operational", tone: "up" },
  degraded: { text: "Some endpoints are slow", tone: "degraded" },
  down: { text: "Outage in progress", tone: "down" },
};

function MiniSpark({ values, tone = "accent", height = 28 }) {
  const clean = values.filter((v) => v != null);
  if (clean.length < 2) return <div className="minispark" style={{ height }} />;
  const max = Math.max(...clean);
  const min = Math.min(...clean);
  const span = max - min || 1;
  const step = 100 / (values.length - 1);
  let d = "";
  values.forEach((v, i) => {
    if (v == null) return;
    d += `${d ? "L" : "M"}${(i * step).toFixed(2)},${(height - 2 - ((v - min) / span) * (height - 6)).toFixed(2)}`;
  });
  return (
    <svg className={`minispark tone-stroke-${tone}`} viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ height }}>
      <path d={d} fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Bucket every endpoint's recent checks into a global success-rate and latency trend. */
function useFleetTrend(recent, buckets = 24) {
  return useMemo(() => {
    const all = Object.values(recent)
      .flat()
      .map((c) => ({ ...c, t: Date.parse(c.checked_at.endsWith("Z") ? c.checked_at : `${c.checked_at}Z`) }))
      .filter((c) => !Number.isNaN(c.t))
      .sort((a, b) => a.t - b.t);
    if (all.length < 4) return { success: [], latency: [] };
    const t0 = all[0].t;
    const span = Math.max(1, all[all.length - 1].t - t0);
    const groups = Array.from({ length: buckets }, () => []);
    for (const c of all) groups[Math.min(buckets - 1, Math.floor(((c.t - t0) / span) * buckets))].push(c);
    const success = groups.map((g) => (g.length ? (100 * g.filter((c) => c.is_success).length) / g.length : null));
    const latency = groups.map((g) => {
      const ms = g.filter((c) => c.is_success && c.response_time_ms != null).map((c) => c.response_time_ms);
      if (!ms.length) return null;
      ms.sort((a, b) => a - b);
      return ms[Math.floor(ms.length / 2)];
    });
    return { success, latency };
  }, [recent, buckets]);
}

function EndpointRow({ endpoint, summary, checks, now }) {
  const status = displayStatus(endpoint, now);
  const last = checks[checks.length - 1];
  const sslDays = daysUntil(endpoint.ssl_expires_at, now);
  const [flash, setFlash] = useState(false);
  const lastId = useRef(last?.id);

  useEffect(() => {
    if (last?.id !== undefined && lastId.current !== undefined && last.id !== lastId.current) {
      setFlash(true);
      const timer = setTimeout(() => setFlash(false), 900);
      lastId.current = last.id;
      return () => clearTimeout(timer);
    }
    lastId.current = last?.id;
    return undefined;
  }, [last?.id]);

  return (
    <Link to={`/endpoints/${endpoint.id}`} className={`row status-${status}${flash ? " row-flash" : ""}`}>
      <span className="row-glyph">
        <StatusGlyph status={status} />
      </span>
      <span className="row-name">
        <span className="row-title">
          {endpoint.name}
          {status === "maintenance" && <Badge tone="maintenance">maintenance</Badge>}
          {status === "paused" && <Badge>paused</Badge>}
          {sslDays !== null && sslDays < 30 && <Badge tone={sslDays < 7 ? "down" : "degraded"}>TLS {sslDays}d</Badge>}
        </span>
        <span className="row-sub">
          <span className="method">{endpoint.method}</span>
          {hostOf(endpoint.url)}
        </span>
      </span>
      <span className="row-strip">
        <CheckStrip checks={checks} />
      </span>
      <span className={`row-num${last && !last.is_success ? " tone-down" : ""}`}>
        {last ? (last.is_success ? formatMs(last.response_time_ms) : last.status_code || "ERR") : "–"}
      </span>
      <span className="row-num">{formatPct(summary?.uptime_pct)}</span>
      <span className="row-num muted">{formatMs(summary?.p95_latency_ms)}</span>
      <span className="row-time muted">{timeAgo(endpoint.last_checked_at, now)}</span>
      <span className="row-chevron">›</span>
    </Link>
  );
}

function FeedItem({ event }) {
  const { type, data } = event;
  if (type === "check") {
    const r = data.result;
    const tone = r.is_success ? (r.error_type === "slow" ? "degraded" : "up") : "down";
    return (
      <li className="feed-item">
        <StatusGlyph status={tone} size={8} />
        <Link to={`/endpoints/${data.endpoint_id}`} className="feed-name">
          {data.endpoint_name}
        </Link>
        <span className="feed-detail">
          {r.status_code ?? r.error_type} · {formatMs(r.response_time_ms)}
          {r.attempts > 1 && ` · ${r.attempts}×`}
          {r.is_anomaly && " · anomaly"}
        </span>
        <span className="feed-time">{formatTime(r.checked_at)}</span>
      </li>
    );
  }
  if (type === "status_changed") {
    return (
      <li className="feed-item feed-change">
        <span className="feed-arrow">⇄</span>
        <span className="feed-name">{data.endpoint_name}</span>
        <span className="feed-detail">
          {data.previous} → <strong className={`tone-${data.current}`}>{data.current}</strong>
        </span>
        <span className="feed-time">{formatTime(event.ts)}</span>
      </li>
    );
  }
  if (type === "alert") {
    return (
      <li className={`feed-item feed-alert sev-${data.severity}`}>
        <span className="feed-arrow">▲</span>
        <span className="feed-detail wide">{data.message}</span>
        <span className="feed-time">{formatTime(data.created_at)}</span>
      </li>
    );
  }
  return null;
}

export function Dashboard({ onNewEndpoint }) {
  const { endpoints, summary, recent, feed, loaded, loadError, openAlerts, checksPerMinute } = useLive();
  const now = useNow(1000);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const searchRef = useRef(null);
  const trend = useFleetTrend(recent);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "/" && !/input|textarea|select/i.test(document.activeElement?.tagName || "")) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const list = useMemo(() => Object.values(endpoints).sort((a, b) => a.name.localeCompare(b.name)), [endpoints]);
  const counts = useMemo(() => {
    const c = Object.fromEntries(FILTERS.map((f) => [f, 0]));
    for (const e of list) {
      c.all += 1;
      const s = displayStatus(e, now);
      c[s] = (c[s] || 0) + 1;
    }
    return c;
  }, [list, now]);

  const visible = list
    .filter((e) => {
      const status = displayStatus(e, now);
      if (filter !== "all" && status !== filter) return false;
      const q = query.trim().toLowerCase();
      return !q || e.name.toLowerCase().includes(q) || e.url.toLowerCase().includes(q);
    })
    .sort((a, b) => {
      const rank = { down: 0, degraded: 1, unknown: 2, maintenance: 3, up: 4, paused: 5 };
      return rank[displayStatus(a, now)] - rank[displayStatus(b, now)] || a.name.localeCompare(b.name);
    });

  const summaries = Object.values(summary);
  const uptimes = summaries.map((s) => s.uptime_pct).filter((v) => v != null);
  const avgUptime = uptimes.length ? uptimes.reduce((a, b) => a + b, 0) / uptimes.length : null;
  const p95s = summaries
    .map((s) => s.p95_latency_ms)
    .filter((v) => v != null)
    .sort((a, b) => a - b);
  const medianP95 = p95s.length ? p95s[Math.floor(p95s.length / 2)] : null;
  const active = counts.all - counts.paused;
  const headline = counts.down ? HEADLINE.down : counts.degraded ? HEADLINE.degraded : HEADLINE.ok;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Overview</h1>
          <p className={`headline tone-${headline.tone}`}>
            <StatusGlyph status={headline.tone} size={8} /> {headline.text}
            <span className="muted"> · {list.length} endpoints monitored</span>
          </p>
        </div>
        <Button variant="primary" onClick={onNewEndpoint}>
          New endpoint <Kbd>N</Kbd>
        </Button>
      </header>

      <section className="stats">
        <div className="stat">
          <div className="stat-label">Uptime · 24h</div>
          <div className="stat-value">
            <AnimatedNumber value={avgUptime} format={(v) => `${v.toFixed(2)}%`} />
          </div>
          <MiniSpark values={trend.success} tone="up" />
        </div>
        <div className="stat">
          <div className="stat-label">Median p95 latency</div>
          <div className="stat-value">
            <AnimatedNumber value={medianP95} format={(v) => formatMs(v)} />
          </div>
          <MiniSpark values={trend.latency} tone="accent" />
        </div>
        <div className="stat">
          <div className="stat-label">Healthy</div>
          <div className="stat-value">
            <span className={counts.down ? "tone-down" : ""}>
              <AnimatedNumber value={counts.up} />
            </span>
            <span className="stat-of">/{active}</span>
          </div>
          <div className="stat-foot muted">
            {counts.down} down · {counts.degraded} degraded
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Checks / min</div>
          <div className="stat-value">
            <AnimatedNumber value={checksPerMinute} />
          </div>
          <div className="stat-foot">
            <span className="live-dot" /> streaming
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Open alerts</div>
          <div className={`stat-value${openAlerts ? " tone-degraded" : ""}`}>
            <AnimatedNumber value={openAlerts} />
          </div>
          <div className="stat-foot muted">
            <Link to="/alerts">View all →</Link>
          </div>
        </div>
      </section>

      <div className="overview-grid">
        <section className="list-card">
          <div className="list-toolbar">
            <Segmented
              size="sm"
              value={filter}
              onChange={setFilter}
              options={FILTERS.filter((f) => f === "all" || counts[f]).map((f) => ({
                value: f,
                label: f[0].toUpperCase() + f.slice(1),
                count: counts[f],
              }))}
            />
            <div className="search">
              <span className="search-icon">⌕</span>
              <input
                ref={searchRef}
                placeholder="Filter endpoints"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <Kbd>/</Kbd>
            </div>
          </div>

          <div className="row row-head">
            <span />
            <span>Endpoint</span>
            <span>Last 40 checks</span>
            <span className="row-num">Last</span>
            <span className="row-num">Uptime</span>
            <span className="row-num">p95</span>
            <span className="row-time">Checked</span>
            <span />
          </div>

          {!loaded ? (
            [1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="row">
                <span />
                <Skeleton height={14} width="70%" />
                <Skeleton height={22} />
              </div>
            ))
          ) : loadError ? (
            <Empty icon="⚠" title="Could not load endpoints">
              {loadError}
            </Empty>
          ) : visible.length === 0 ? (
            <Empty icon="◌" title={list.length ? "No endpoints match" : "Nothing monitored yet"}>
              {list.length ? (
                "Try a different filter."
              ) : (
                <Button variant="primary" onClick={onNewEndpoint}>
                  Add your first endpoint
                </Button>
              )}
            </Empty>
          ) : (
            visible.map((e) => (
              <EndpointRow key={e.id} endpoint={e} summary={summary[e.id]} checks={recent[e.id] || []} now={now} />
            ))
          )}
        </section>

        <aside className="activity">
          <div className="activity-header">
            <h3>Activity</h3>
            <span className="live-tag">
              <span className="live-dot" /> Live
            </span>
          </div>
          {feed.length === 0 ? (
            <Empty icon="◷" title="Waiting for checks">
              Results stream in here the moment each check finishes.
            </Empty>
          ) : (
            <ul className="feed">
              {feed.map((event) => (
                <FeedItem key={event.id} event={event} />
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}

