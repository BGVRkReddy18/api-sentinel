import { useEffect, useState } from "react";

import { api, getApiKey, setApiKey } from "../api.js";
import { Badge, Button, Card, Kbd, Segmented } from "../components/ui.jsx";
import { useLive, useToasts } from "../store.jsx";

const CHAOS = [
  { mode: "healthy", label: "Healthy", hint: "Normal ~60 ms responses", tone: "up" },
  { mode: "slow", label: "Make it slow", hint: "~800 ms → anomaly + degraded", tone: "degraded" },
  { mode: "down", label: "Take it down", hint: "HTTP 503 → DOWN alert in ~40 s", tone: "down" },
];

const SHORTCUTS = [
  { keys: ["⌘", "K"], label: "Command palette" },
  { keys: ["N"], label: "New endpoint" },
  { keys: ["/"], label: "Filter endpoints" },
  { keys: ["G", "O"], label: "Go to Overview", sequence: true },
  { keys: ["G", "A"], label: "Go to Alerts", sequence: true },
  { keys: ["G", "S"], label: "Go to Status page", sequence: true },
  { keys: ["T"], label: "Toggle theme" },
  { keys: ["Esc"], label: "Close panel or dialog" },
];

export function Settings({ theme, setTheme }) {
  const { meta, connection } = useLive();
  const { push } = useToasts();
  const [key, setKey] = useState(getApiKey());
  const [verifying, setVerifying] = useState(false);
  const [mode, setMode] = useState(null);

  useEffect(() => {
    if (meta?.demo_enabled) {
      api("/demo/chaos")
        .then((r) => setMode(r.mode))
        .catch(() => setMode(null));
    }
  }, [meta]);

  const save = async () => {
    setApiKey(key.trim());
    if (!key.trim()) {
      push({ kind: "info", title: "Admin key cleared", message: "This browser is now read-only." });
      return;
    }
    setVerifying(true);
    try {
      await api("/api/v1/auth/verify");
      push({ kind: "success", title: "Admin key verified", message: "You can make changes from this browser." });
    } catch (e) {
      push({ kind: "error", title: "Key rejected", message: e.message });
    } finally {
      setVerifying(false);
    }
  };

  const chaos = async (next) => {
    try {
      const result = await api(`/demo/chaos/${next}`, { method: "POST" });
      setMode(result.mode);
      push({ kind: "info", title: `Demo API → ${result.mode}`, message: "Watch demo-orders on the overview." });
    } catch (e) {
      push({ kind: "error", title: "Chaos failed", message: e.message });
    }
  };

  return (
    <div className="page page-narrow">
      <header className="page-header">
        <div>
          <h1>Settings</h1>
          <p className="muted">Appearance, access, alerts and demo controls</p>
        </div>
      </header>

      <Card title="Appearance" actions={
        <Segmented
          size="sm"
          value={theme}
          onChange={setTheme}
          options={[
            { value: "dark", label: "Dark" },
            { value: "light", label: "Light" },
          ]}
        />
      }>
        <div className="shortcuts">
          {SHORTCUTS.map(({ keys, label, sequence }) => (
            <div key={label} className="shortcut">
              <span>{label}</span>
              <span className="shortcut-keys">
                {keys.map((k, i) => (
                  <span key={k}>
                    {sequence && i > 0 && <span className="muted small"> then </span>}
                    <Kbd>{k}</Kbd>
                  </span>
                ))}
              </span>
            </div>
          ))}
        </div>
      </Card>

      <Card
        title="Admin key"
        subtitle={
          meta?.auth_required
            ? "This deployment is protected: changes need SENTINEL_API_KEY. Anyone can view."
            : "No admin key is set on the server, so anyone can make changes. Set SENTINEL_API_KEY before going public."
        }
      >
        <div className="inline-form">
          <input
            type="password"
            placeholder="Paste the SENTINEL_API_KEY value"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <Button variant="primary" onClick={save} loading={verifying}>
            Save & verify
          </Button>
        </div>
        <p className="muted small">Stored only in this browser and sent as the X-API-Key header.</p>
      </Card>

      <Card
        title="Email alerts"
        actions={
          <Badge tone={meta?.email_enabled ? "up" : "degraded"}>
            {meta?.email_enabled ? `active · ${meta.email_provider}` : "not configured"}
          </Badge>
        }
      >
        <p className="muted small">
          Each endpoint has its own alert contacts (open an endpoint → Settings). When it goes down, recovers, slows
          down abnormally or its TLS certificate nears expiry, those people get an email.
        </p>
        {!meta?.email_enabled && (
          <p className="small">
            To turn it on, set <code>SENTINEL_EMAIL_PROVIDER=brevo</code>, <code>SENTINEL_BREVO_API_KEY</code> and{" "}
            <code>SENTINEL_EMAIL_FROM</code> on the server (free Brevo account, 300 emails/day). See DEPLOY.md.
          </p>
        )}
      </Card>

      {meta?.demo_enabled && (
        <Card
          title="Chaos controls"
          subtitle="Break the built-in demo API and watch Sentinel detect it in real time."
          actions={mode && <Badge tone={mode === "healthy" ? "up" : "down"}>demo: {mode}</Badge>}
        >
          <div className="chaos">
            {CHAOS.map((c) => (
              <button
                type="button"
                key={c.mode}
                className={`chaos-btn tone-border-${c.tone}${mode === c.mode ? " active" : ""}`}
                onClick={() => chaos(c.mode)}
              >
                <strong className={`tone-${c.tone}`}>{c.label}</strong>
                <span>{c.hint}</span>
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card title="Deployment">
        <dl className="config">
          <dt>Version</dt>
          <dd>{meta?.version ?? "–"}</dd>
          <dt>Environment</dt>
          <dd>{meta?.environment ?? "–"}</dd>
          <dt>Live stream</dt>
          <dd>
            {connection} · {meta?.live_clients ?? 0} connected clients
          </dd>
          <dt>Public URL</dt>
          <dd>{meta?.public_base_url || window.location.origin}</dd>
        </dl>
        <div className="link-row">
          <a href="/docs" target="_blank" rel="noreferrer">
            API docs ↗
          </a>
          <a href="/metrics" target="_blank" rel="noreferrer">
            Prometheus metrics ↗
          </a>
          <a href="/status">Public status page →</a>
        </div>
      </Card>
    </div>
  );
}
