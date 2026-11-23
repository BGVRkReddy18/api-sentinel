import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api.js";

const LiveContext = createContext(null);
const ToastContext = createContext(null);

const RECENT_PER_ENDPOINT = 40;
const FEED_SIZE = 80;

// ------------------------------------------------------------------ toasts

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (toast) => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-4), { id, kind: "info", ...toast }]);
      setTimeout(() => dismiss(id), toast.duration ?? 6000);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ push, dismiss, toasts }), [push, dismiss, toasts]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToasts() {
  return useContext(ToastContext);
}

// ------------------------------------------------------------------ live data

function indexById(items) {
  const map = {};
  for (const item of items) map[item.id] = item;
  return map;
}

export function LiveProvider({ children }) {
  const { push: toast } = useToasts();
  const [endpoints, setEndpoints] = useState({});
  const [summary, setSummary] = useState({});
  const [recent, setRecent] = useState({});
  const [feed, setFeed] = useState([]);
  const [meta, setMeta] = useState(null);
  const [connection, setConnection] = useState("connecting");
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [openAlerts, setOpenAlerts] = useState(0);
  const [checksPerMinute, setChecksPerMinute] = useState(0);

  const listeners = useRef(new Set());
  const checkTimes = useRef([]);

  const refreshSummary = useCallback(async () => {
    try {
      const rows = await api("/api/v1/analytics/summary?hours=24");
      const map = {};
      for (const row of rows) map[row.endpoint_id] = row;
      setSummary(map);
    } catch {
      /* percentile analytics need PostgreSQL; the UI degrades gracefully without them */
    }
  }, []);

  const refreshAlerts = useCallback(async () => {
    try {
      const page = await api("/api/v1/alerts?unresolved=true&limit=1");
      setOpenAlerts(page.total);
    } catch {
      /* ignore */
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [page, recentRows] = await Promise.all([
        api("/api/v1/endpoints?limit=500"),
        api(`/api/v1/analytics/recent?per_endpoint=${RECENT_PER_ENDPOINT}`),
      ]);
      setEndpoints(indexById(page.items));
      const map = {};
      for (const row of recentRows) map[row.endpoint_id] = row.checks;
      setRecent(map);
      setLoadError(null);
      setLoaded(true);
    } catch (error) {
      setLoadError(error.message);
      setLoaded(true);
    }
    refreshSummary();
    refreshAlerts();
  }, [refreshSummary, refreshAlerts]);

  const handleEvent = useCallback(
    (event) => {
      const { type, data } = event;
      if (type === "check") {
        const { endpoint_id: id, result } = data;
        checkTimes.current.push(Date.now());
        setEndpoints((map) =>
          map[id]
            ? {
                ...map,
                [id]: {
                  ...map[id],
                  current_status: data.status,
                  consecutive_failures: data.consecutive_failures,
                  last_checked_at: result.checked_at,
                },
              }
            : map,
        );
        setRecent((map) => ({
          ...map,
          [id]: [...(map[id] || []), result].slice(-RECENT_PER_ENDPOINT),
        }));
        setFeed((list) => [{ ...event, id: `${id}-${result.id}` }, ...list].slice(0, FEED_SIZE));
      } else if (type === "status_changed") {
        setFeed((list) => [{ ...event, id: `s-${event.ts}-${data.endpoint_id}` }, ...list].slice(0, FEED_SIZE));
      } else if (type === "alert") {
        setFeed((list) => [{ ...event, id: `a-${data.id}` }, ...list].slice(0, FEED_SIZE));
        const kind = data.severity === "critical" ? "error" : data.severity === "warning" ? "warning" : "success";
        toast({ kind, title: data.kind.replace("_", " ").toUpperCase(), message: data.message });
        refreshAlerts();
        refreshSummary();
      } else if (type === "endpoint") {
        const { action, endpoint } = data;
        setEndpoints((map) => {
          if (action === "deleted") {
            const next = { ...map };
            delete next[endpoint.id];
            return next;
          }
          return { ...map, [endpoint.id]: endpoint };
        });
        if (action !== "updated") refreshSummary();
      }
      for (const listener of listeners.current) listener(event);
    },
    [toast, refreshAlerts, refreshSummary],
  );

  // WebSocket with exponential-backoff reconnect; resync over REST after every reconnect.
  useEffect(() => {
    let socket = null;
    let retryTimer = null;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
      socket.onopen = () => {
        if (attempt > 0) refresh();
        attempt = 0;
        setConnection("live");
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data);
          if (event.type !== "hello" && event.type !== "ping") handleEvent(event);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setConnection("reconnecting");
        attempt += 1;
        retryTimer = setTimeout(connect, Math.min(15000, 1000 * 2 ** Math.min(attempt, 4)));
      };
      socket.onerror = () => socket.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, [handleEvent, refresh]);

  useEffect(() => {
    refresh();
    api("/api/v1/meta").then(setMeta).catch(() => setMeta(null));
    const summaryTimer = setInterval(refreshSummary, 60000);
    const rateTimer = setInterval(() => {
      const cutoff = Date.now() - 60000;
      checkTimes.current = checkTimes.current.filter((t) => t >= cutoff);
      setChecksPerMinute(checkTimes.current.length);
    }, 2000);
    return () => {
      clearInterval(summaryTimer);
      clearInterval(rateTimer);
    };
  }, [refresh, refreshSummary]);

  const subscribe = useCallback((listener) => {
    listeners.current.add(listener);
    return () => listeners.current.delete(listener);
  }, []);

  const upsertEndpoint = useCallback((endpoint) => {
    setEndpoints((map) => ({ ...map, [endpoint.id]: endpoint }));
  }, []);

  const value = useMemo(
    () => ({
      endpoints,
      summary,
      recent,
      feed,
      meta,
      connection,
      loaded,
      loadError,
      openAlerts,
      checksPerMinute,
      refresh,
      refreshSummary,
      subscribe,
      upsertEndpoint,
    }),
    [
      endpoints,
      summary,
      recent,
      feed,
      meta,
      connection,
      loaded,
      loadError,
      openAlerts,
      checksPerMinute,
      refresh,
      refreshSummary,
      subscribe,
      upsertEndpoint,
    ],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive() {
  return useContext(LiveContext);
}

/** Subscribe a component to raw live events. */
export function useLiveEvents(handler) {
  const { subscribe } = useLive();
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => subscribe((event) => ref.current(event)), [subscribe]);
}

/** Re-render every `ms` so "5s ago" labels tick. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}
