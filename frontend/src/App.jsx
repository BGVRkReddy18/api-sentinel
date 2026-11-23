import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api.js";
import { CommandPalette } from "./components/CommandPalette.jsx";
import { EndpointForm } from "./components/EndpointForm.jsx";
import { Toasts } from "./components/Toasts.jsx";
import { Kbd } from "./components/ui.jsx";
import { Alerts } from "./pages/Alerts.jsx";
import { Dashboard } from "./pages/Dashboard.jsx";
import { EndpointPanel } from "./pages/EndpointDetail.jsx";
import { Settings } from "./pages/Settings.jsx";
import { StatusPage } from "./pages/StatusPage.jsx";
import { Link, matchPath, navigate, usePath } from "./router.jsx";
import { LiveProvider, ToastProvider, useLive, useToasts } from "./store.jsx";
import { useTheme } from "./theme.js";

const NAV = [
  { to: "/", label: "Overview" },
  { to: "/alerts", label: "Alerts" },
  { to: "/status", label: "Status page" },
  { to: "/settings", label: "Settings" },
];

function isTyping() {
  const el = document.activeElement;
  return el && (/input|textarea|select/i.test(el.tagName) || el.isContentEditable);
}

function Logo() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <defs>
        <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b93ff" />
          <stop offset="1" stopColor="#5e6ad2" />
        </linearGradient>
      </defs>
      <path d="M12 2 21 7v6c0 5-3.8 8.5-9 9-5.2-.5-9-4-9-9V7z" fill="url(#logo-g)" />
      <path d="m8 12.5 2.6 2.6L16.5 9" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Topbar({ path, theme, onToggleTheme, onOpenPalette, onNewEndpoint }) {
  const { connection, openAlerts } = useLive();
  const live = connection === "live";
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link to="/" className="brand">
          <Logo />
          <span>Sentinel</span>
        </Link>
        <nav className="nav">
          {NAV.map((item) => {
            const active = item.to === "/" ? path === "/" || path.startsWith("/endpoints") : path.startsWith(item.to);
            return (
              <Link key={item.to} to={item.to} className={`nav-link${active ? " active" : ""}`}>
                {item.label}
                {item.to === "/alerts" && openAlerts > 0 && <span className="nav-count">{openAlerts}</span>}
              </Link>
            );
          })}
        </nav>
        <div className="topbar-right">
          <button type="button" className="search-trigger" onClick={onOpenPalette}>
            <span className="search-icon">⌕</span>
            <span className="search-text">Search or jump to…</span>
            <Kbd>⌘K</Kbd>
          </button>
          <span className={`conn ${live ? "conn-live" : "conn-down"}`} title="Real-time WebSocket connection">
            <span className="live-dot" />
            {live ? "Live" : "Reconnecting"}
          </span>
          <button type="button" className="icon-btn theme-btn" onClick={onToggleTheme} aria-label="Toggle theme" title="Toggle theme (T)">
            {theme === "dark" ? "☾" : "☀"}
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={onNewEndpoint}>
            + New
          </button>
        </div>
      </div>
    </header>
  );
}

function Shell() {
  const path = usePath();
  const [theme, toggleTheme, setTheme] = useTheme();
  const { endpoints, meta } = useLive();
  const { push } = useToasts();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const pendingG = useRef(0);

  const detail = matchPath("/endpoints/:id", path);
  const openEndpoint = useCallback((id) => navigate(`/endpoints/${id}`), []);

  // Global keyboard shortcuts.
  useEffect(() => {
    const onKey = (event) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((v) => !v);
        return;
      }
      if (mod || event.altKey || isTyping() || paletteOpen || formOpen) return;
      const key = event.key.toLowerCase();
      if (Date.now() - pendingG.current < 1000) {
        pendingG.current = 0;
        const target = { o: "/", a: "/alerts", s: "/status", e: "/settings" }[key];
        if (target) {
          event.preventDefault();
          navigate(target);
        }
        return;
      }
      if (key === "g") pendingG.current = Date.now();
      else if (key === "n") {
        event.preventDefault();
        setFormOpen(true);
      } else if (key === "t") toggleTheme();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen, formOpen, toggleTheme]);

  const chaos = useCallback(
    async (mode) => {
      try {
        await api(`/demo/chaos/${mode}`, { method: "POST" });
        push({ kind: "info", title: `Demo API → ${mode}`, message: "Watch demo-orders react in real time." });
      } catch (e) {
        push({ kind: "error", title: "Chaos failed", message: e.message });
      }
    },
    [push],
  );

  const actions = useMemo(() => {
    const list = [
      { id: "new", label: "Create new endpoint", icon: "+", shortcut: "N", keywords: "add monitor", run: () => setFormOpen(true) },
      { id: "go-o", label: "Go to Overview", icon: "◧", group: "Navigate", run: () => navigate("/") },
      { id: "go-a", label: "Go to Alerts", icon: "▲", group: "Navigate", run: () => navigate("/alerts") },
      { id: "go-s", label: "Open public status page", icon: "◎", group: "Navigate", run: () => navigate("/status") },
      { id: "go-e", label: "Go to Settings", icon: "⚙", group: "Navigate", run: () => navigate("/settings") },
      { id: "docs", label: "Open API docs", icon: "{}", group: "Navigate", run: () => window.open("/docs", "_blank") },
      {
        id: "theme",
        label: `Switch to ${theme === "dark" ? "light" : "dark"} theme`,
        icon: theme === "dark" ? "☀" : "☾",
        shortcut: "T",
        keywords: "appearance mode",
        run: toggleTheme,
      },
      {
        id: "copy-status",
        label: "Copy status page link",
        icon: "⧉",
        keywords: "share",
        run: () => {
          navigator.clipboard?.writeText(`${window.location.origin}/status`);
          push({ kind: "success", title: "Copied", message: `${window.location.origin}/status` });
        },
      },
    ];
    if (meta?.demo_enabled) {
      list.push(
        { id: "c-down", label: "Demo: take the orders API down", icon: "↓", group: "Chaos", keywords: "break outage", run: () => chaos("down") },
        { id: "c-slow", label: "Demo: make the orders API slow", icon: "≈", group: "Chaos", keywords: "latency", run: () => chaos("slow") },
        { id: "c-ok", label: "Demo: restore the orders API", icon: "✓", group: "Chaos", keywords: "healthy fix", run: () => chaos("healthy") },
      );
    }
    return list;
  }, [theme, toggleTheme, meta, chaos, push]);

  if (path === "/status") {
    return (
      <>
        <StatusPage />
        <Toasts />
      </>
    );
  }

  let page;
  if (path === "/alerts") page = <Alerts />;
  else if (path === "/settings") page = <Settings theme={theme} setTheme={setTheme} />;
  else page = <Dashboard onNewEndpoint={() => setFormOpen(true)} />;

  return (
    <div className="app">
      <Topbar
        path={path}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenPalette={() => setPaletteOpen(true)}
        onNewEndpoint={() => setFormOpen(true)}
      />
      <main className="main">{page}</main>
      {detail && <EndpointPanel key={detail.id} id={detail.id} onClose={() => navigate("/")} />}
      {formOpen && <EndpointForm onClose={() => setFormOpen(false)} onSaved={(saved) => openEndpoint(saved.id)} />}
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        endpoints={Object.values(endpoints)}
        actions={actions}
        onOpenEndpoint={openEndpoint}
      />
      <Toasts />
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <LiveProvider>
        <Shell />
      </LiveProvider>
    </ToastProvider>
  );
}
