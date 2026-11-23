import { useState } from "react";

import { api } from "../api.js";
import { useLive, useToasts } from "../store.jsx";
import { Button, Modal, Switch } from "./ui.jsx";

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];
const INTERVALS = [
  { value: 30, label: "30 sec" },
  { value: 60, label: "1 min" },
  { value: 120, label: "2 min" },
  { value: 300, label: "5 min" },
  { value: 900, label: "15 min" },
  { value: 3600, label: "1 hour" },
];
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const DEFAULTS = {
  name: "",
  url: "https://",
  method: "GET",
  interval_seconds: 60,
  timeout_seconds: 10,
  max_retries: 2,
  retry_backoff_seconds: 0.5,
  expected_status: 200,
  expected_body_contains: "",
  max_latency_ms: "",
  headers: "",
  body: "",
  is_active: true,
  is_public: true,
  alert_emails: [],
};

function headersToText(headers) {
  return Object.entries(headers || {})
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
}

function parseHeaders(text) {
  const headers = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const index = line.indexOf(":");
    if (index < 1) throw new Error(`Invalid header line "${line}" (use "Name: value")`);
    headers[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return headers;
}

/** Mirrors the backend rule: every attempt timing out + all backoff must fit in the interval. */
function worstCaseSeconds(f) {
  const retries = Number(f.max_retries);
  return Number(f.timeout_seconds) * (retries + 1) + Number(f.retry_backoff_seconds) * (2 ** retries - 1) * 1.1;
}

export function EmailChips({ value, onChange, placeholder = "friend@example.com" }) {
  const [draft, setDraft] = useState("");
  const [invalid, setInvalid] = useState(false);

  const commit = () => {
    const parts = draft
      .split(/[\s,;]+/)
      .map((p) => p.trim().toLowerCase())
      .filter(Boolean);
    if (!parts.length) return true;
    const bad = parts.find((p) => !EMAIL_RE.test(p));
    if (bad) {
      setInvalid(true);
      return false;
    }
    onChange([...new Set([...value, ...parts])].slice(0, 10));
    setDraft("");
    setInvalid(false);
    return true;
  };

  return (
    <div className={`chips${invalid ? " chips-invalid" : ""}`}>
      {value.map((email) => (
        <span key={email} className="chip">
          {email}
          <button type="button" aria-label={`Remove ${email}`} onClick={() => onChange(value.filter((e) => e !== email))}>
            ✕
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setInvalid(false);
        }}
        onKeyDown={(e) => {
          if (["Enter", ",", " ", "Tab"].includes(e.key) && draft.trim()) {
            if (e.key !== "Tab") e.preventDefault();
            commit();
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={commit}
        placeholder={value.length ? "" : placeholder}
      />
    </div>
  );
}

export function EndpointForm({ endpoint, onClose, onSaved }) {
  const editing = Boolean(endpoint);
  const { upsertEndpoint, meta } = useLive();
  const { push } = useToasts();
  const [form, setForm] = useState(() =>
    editing
      ? {
          ...DEFAULTS,
          ...endpoint,
          expected_body_contains: endpoint.expected_body_contains || "",
          max_latency_ms: endpoint.max_latency_ms ?? "",
          headers: headersToText(endpoint.headers),
          body: endpoint.body || "",
          alert_emails: endpoint.alert_emails || [],
        }
      : DEFAULTS,
  );
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));
  const setValue = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  const worst = worstCaseSeconds(form);
  const budgetOk = worst < Number(form.interval_seconds);
  const intervalOptions = INTERVALS.some((i) => i.value === Number(form.interval_seconds))
    ? INTERVALS
    : [...INTERVALS, { value: Number(form.interval_seconds), label: `${form.interval_seconds} sec` }];

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    let headers;
    try {
      headers = parseHeaders(form.headers);
    } catch (e) {
      setError(e.message);
      return;
    }
    const payload = {
      name: form.name.trim(),
      url: form.url.trim(),
      method: form.method,
      interval_seconds: Number(form.interval_seconds),
      timeout_seconds: Number(form.timeout_seconds),
      max_retries: Number(form.max_retries),
      retry_backoff_seconds: Number(form.retry_backoff_seconds),
      expected_status: Number(form.expected_status),
      expected_body_contains: form.expected_body_contains.trim() || null,
      max_latency_ms: form.max_latency_ms === "" ? null : Number(form.max_latency_ms),
      headers,
      body: ["GET", "HEAD"].includes(form.method) ? null : form.body || null,
      is_active: form.is_active,
      is_public: form.is_public,
      alert_emails: form.alert_emails,
    };
    setSaving(true);
    try {
      const saved = editing
        ? await api(`/api/v1/endpoints/${endpoint.id}`, { method: "PATCH", body: payload })
        : await api("/api/v1/endpoints", { method: "POST", body: payload });
      upsertEndpoint(saved);
      push({
        kind: "success",
        title: editing ? "Changes saved" : "Now monitoring",
        message: editing ? saved.name : `${saved.name} - first check in a few seconds.`,
      });
      onSaved?.(saved);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={editing ? `Edit ${endpoint.name}` : "New endpoint"}
      onClose={onClose}
      width={620}
      footer={
        <>
          <span className="muted small footer-hint">
            {budgetOk ? `Worst case ${worst.toFixed(1)}s per check` : "Timeout × attempts exceeds the interval"}
          </span>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="endpoint-form" loading={saving} disabled={!budgetOk}>
            {editing ? "Save changes" : "Create endpoint"}
          </Button>
        </>
      }
    >
      <form id="endpoint-form" className="form" onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        <div className="form-section">
          <div className="form-label">Request</div>
          <div className="url-row">
            <select value={form.method} onChange={set("method")} aria-label="Method">
              {METHODS.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
            <input
              required
              type="url"
              value={form.url}
              onChange={set("url")}
              placeholder="https://api.example.com/health"
              aria-label="URL"
              autoFocus={!editing}
            />
          </div>
          <input
            required
            maxLength={120}
            value={form.name}
            onChange={set("name")}
            placeholder="Display name, e.g. payments-api"
            aria-label="Name"
          />
        </div>

        <div className="form-section">
          <div className="form-label">Schedule & reliability</div>
          <div className="form-grid">
            <label className="field">
              <span>Check every</span>
              <select value={form.interval_seconds} onChange={set("interval_seconds")}>
                {intervalOptions.map((i) => (
                  <option key={i.value} value={i.value}>
                    {i.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Timeout (s)</span>
              <input type="number" min={0.5} max={60} step={0.5} required value={form.timeout_seconds} onChange={set("timeout_seconds")} />
            </label>
            <label className="field">
              <span>Retries</span>
              <input type="number" min={0} max={5} required value={form.max_retries} onChange={set("max_retries")} />
            </label>
          </div>
        </div>

        <div className="form-section">
          <div className="form-label">Assertions</div>
          <div className="form-grid">
            <label className="field">
              <span>Expected status</span>
              <input type="number" min={100} max={599} required value={form.expected_status} onChange={set("expected_status")} />
            </label>
            <label className="field span-2">
              <span>Body contains</span>
              <input value={form.expected_body_contains} onChange={set("expected_body_contains")} placeholder='"status":"ok"' />
            </label>
            <label className="field">
              <span>Latency SLO (ms)</span>
              <input type="number" min={1} value={form.max_latency_ms} onChange={set("max_latency_ms")} placeholder="800" />
            </label>
          </div>
        </div>

        <div className="form-section">
          <div className="form-label">
            Alert emails
            <span className="muted small">
              {meta?.email_enabled
                ? " · owners get an email when it goes down, recovers or slows down"
                : " · saved now; delivery starts once email is configured on the server"}
            </span>
          </div>
          <EmailChips value={form.alert_emails} onChange={setValue("alert_emails")} />
        </div>

        <div className="form-section switches">
          <Switch checked={form.is_active} onChange={setValue("is_active")} label="Active" hint="Run checks on schedule" />
          <Switch
            checked={form.is_public}
            onChange={setValue("is_public")}
            label="Public"
            hint="Show on the status page"
          />
        </div>

        <button type="button" className="link-btn" onClick={() => setAdvanced((v) => !v)}>
          {advanced ? "−" : "+"} Advanced: headers, body, backoff
        </button>
        {advanced && (
          <div className="form-section">
            <label className="field">
              <span>Headers (one per line, “Name: value”)</span>
              <textarea rows={3} value={form.headers} onChange={set("headers")} placeholder="Authorization: Bearer …" />
            </label>
            {!["GET", "HEAD"].includes(form.method) && (
              <label className="field">
                <span>Request body</span>
                <textarea rows={3} value={form.body} onChange={set("body")} placeholder='{"ping": true}' />
              </label>
            )}
            <label className="field" style={{ maxWidth: 200 }}>
              <span>Retry backoff (s)</span>
              <input type="number" min={0} max={30} step={0.1} value={form.retry_backoff_seconds} onChange={set("retry_backoff_seconds")} />
            </label>
          </div>
        )}
      </form>
    </Modal>
  );
}
