import { useCallback, useEffect, useState } from "react";

import { api } from "../api.js";
import { Badge, Button, Empty, Segmented } from "../components/ui.jsx";
import { formatDateTime, formatTime, parseTime, timeAgo } from "../format.js";
import { Link } from "../router.jsx";
import { useLive, useLiveEvents, useNow, useToasts } from "../store.jsx";

const KINDS = [
  { value: "", label: "All" },
  { value: "down", label: "Down" },
  { value: "recovered", label: "Recovered" },
  { value: "latency_anomaly", label: "Anomaly" },
  { value: "ssl_expiring", label: "TLS" },
];
const KIND_ICON = { down: "●", recovered: "✓", latency_anomaly: "◆", ssl_expiring: "⚿" };
const PAGE = 40;

function dayLabel(value) {
  const date = parseTime(value);
  if (!date) return "";
  const today = new Date();
  const yesterday = new Date(Date.now() - 86400000);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
}

export function Alerts() {
  const { endpoints } = useLive();
  const { push } = useToasts();
  const now = useNow(5000);
  const [kind, setKind] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [fresh, setFresh] = useState(new Set());

  const load = useCallback(
    async (offset = 0) => {
      setLoading(true);
      const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
      if (kind) params.set("kind", kind);
      if (openOnly) params.set("unresolved", "true");
      try {
        const page = await api(`/api/v1/alerts?${params}`);
        setItems((list) => (offset ? [...list, ...page.items] : page.items));
        setTotal(page.total);
      } catch (e) {
        push({ kind: "error", title: "Could not load alerts", message: e.message });
      } finally {
        setLoading(false);
      }
    },
    [kind, openOnly, push],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  useLiveEvents((event) => {
    if (event.type !== "alert") return;
    setFresh((s) => new Set(s).add(event.data.id));
    load(0);
  });

  const resolve = async (alert) => {
    try {
      const updated = await api(`/api/v1/alerts/${alert.id}/resolve`, { method: "POST" });
      setItems((list) => list.map((a) => (a.id === updated.id ? updated : a)));
    } catch (e) {
      push({ kind: "error", title: "Could not resolve", message: e.message });
    }
  };

  let lastDay = null;
  return (
    <div className="page page-narrow">
      <header className="page-header">
        <div>
          <h1>Alerts</h1>
          <p className="muted">{total} alerts · new ones arrive instantly</p>
        </div>
      </header>
      <div className="list-toolbar plain">
        <Segmented size="sm" value={kind} onChange={setKind} options={KINDS} />
        <Segmented
          size="sm"
          value={openOnly ? "open" : "all"}
          onChange={(v) => setOpenOnly(v === "open")}
          options={[
            { value: "all", label: "Everything" },
            { value: "open", label: "Open only" },
          ]}
        />
      </div>

      <section className="list-card">
        {items.length === 0 && !loading ? (
          <Empty icon="🔕" title="Inbox zero">
            Alerts fire when an endpoint goes down, recovers, slows down abnormally or its TLS certificate is about to
            expire.
          </Empty>
        ) : (
          items.map((a) => {
            const day = dayLabel(a.created_at);
            const header = day !== lastDay ? day : null;
            lastDay = day;
            const open = !a.resolved_at && a.kind !== "recovered";
            return (
              <div key={a.id}>
                {header && <div className="group-label">{header}</div>}
                <div className={`inbox-row sev-${a.severity}${fresh.has(a.id) ? " row-flash" : ""}`}>
                  <span className={`inbox-icon kind-${a.kind}`}>{KIND_ICON[a.kind] || "•"}</span>
                  <div className="inbox-main">
                    <div className="inbox-message">{a.message}</div>
                    <div className="inbox-meta">
                      <Link to={`/endpoints/${a.endpoint_id}`} className="chip-link">
                        {endpoints[a.endpoint_id]?.name || `#${a.endpoint_id}`}
                      </Link>
                      <span title={formatDateTime(a.created_at)}>
                        {formatTime(a.created_at)} · {timeAgo(a.created_at, now)}
                      </span>
                      {a.notified && <span>✉ notified</span>}
                    </div>
                  </div>
                  <div className="inbox-side">
                    {open ? <Badge tone="down">open</Badge> : <Badge>resolved</Badge>}
                    {open && (
                      <Button size="sm" onClick={() => resolve(a)}>
                        Resolve
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </section>
      {items.length < total && (
        <div className="center">
          <Button onClick={() => load(items.length)} loading={loading}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
