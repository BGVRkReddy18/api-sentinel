/* Dependency-free SVG charts: sparkline, interactive line chart, uptime bars. */
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { formatMs, formatPct, parseTime } from "../format.js";

function useWidth(fallback = 600) {
  const ref = useRef(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!ref.current) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(120, entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function niceMax(value) {
  if (!value || value <= 0) return 100;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const steps = [1, 2, 2.5, 5, 10];
  for (const step of steps) if (value <= step * magnitude) return step * magnitude;
  return 10 * magnitude;
}

// ------------------------------------------------------------------ sparkline

export function Sparkline({ checks = [], height = 40 }) {
  const [ref, width] = useWidth(160);
  const points = checks.slice(-40);
  const latencies = points.filter((c) => c.is_success && c.response_time_ms != null).map((c) => c.response_time_ms);
  const max = Math.max(1, ...latencies) * 1.15;
  const step = points.length > 1 ? width / (points.length - 1) : width;
  const y = (ms) => height - 3 - (ms / max) * (height - 8);

  let path = "";
  points.forEach((c, i) => {
    if (!c.is_success || c.response_time_ms == null) return;
    path += `${path ? "L" : "M"}${(i * step).toFixed(1)},${y(c.response_time_ms).toFixed(1)}`;
  });

  return (
    <div ref={ref} className="sparkline">
      {points.length === 0 ? (
        <div className="sparkline-empty">waiting for first check…</div>
      ) : (
        <svg width={width} height={height} role="img" aria-label="recent response times">
          <path d={path} fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round" />
          {points.map((c, i) =>
            c.is_success ? null : (
              <rect key={i} x={i * step - 1.5} y={height - 10} width="3" height="8" rx="1" fill="var(--red)" />
            ),
          )}
        </svg>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ line chart

/**
 * data:   [{ t: ISO string, [key]: number|null, failed?: boolean }]
 * series: [{ key, label, color }]
 */
export function LineChart({ data, series, height = 240, emptyText = "No data yet", markFailures = false, area = true }) {
  const [ref, width] = useWidth(700);
  const gradientId = useId().replace(/:/g, "");
  const [hover, setHover] = useState(null);
  const pad = { top: 14, right: 16, bottom: 26, left: 56 };
  const innerW = Math.max(10, width - pad.left - pad.right);
  const innerH = height - pad.top - pad.bottom;

  const prepared = useMemo(
    () => data.map((d) => ({ ...d, time: parseTime(d.t)?.getTime() ?? 0 })).sort((a, b) => a.time - b.time),
    [data],
  );
  const values = prepared.flatMap((d) => series.map((s) => d[s.key]).filter((v) => v != null));
  const yMax = niceMax(Math.max(0, ...values) * 1.1);
  const t0 = prepared[0]?.time ?? 0;
  const t1 = prepared[prepared.length - 1]?.time ?? 1;
  const span = Math.max(1, t1 - t0);
  const x = (time) => pad.left + ((time - t0) / span) * innerW;
  const y = (v) => pad.top + innerH - (v / yMax) * innerH;

  const lines = series.map((s) => {
    let d = "";
    let fill = "";
    let pen = false;
    let segmentStart = null;
    let last = null;
    const closeSegment = () => {
      if (segmentStart !== null && last !== null) {
        fill += `L${last.toFixed(1)},${(pad.top + innerH).toFixed(1)}L${segmentStart.toFixed(1)},${(pad.top + innerH).toFixed(1)}Z`;
      }
      segmentStart = null;
    };
    for (const point of prepared) {
      const v = point[s.key];
      if (v == null) {
        pen = false;
        closeSegment();
        continue;
      }
      const px = x(point.time);
      const cmd = `${pen ? "L" : "M"}${px.toFixed(1)},${y(v).toFixed(1)}`;
      d += cmd;
      fill += cmd;
      if (!pen) segmentStart = px;
      last = px;
      pen = true;
    }
    closeSegment();
    return { ...s, d, fill };
  });

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);
  const xTicks = prepared.length > 1 ? [0, 0.2, 0.4, 0.6, 0.8, 1].map((f) => t0 + f * span) : [];
  const fmtX = (time) => {
    const date = new Date(time);
    return span > 2 * 86400000
      ? date.toLocaleDateString([], { month: "short", day: "numeric" })
      : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const onMove = (event) => {
    if (!prepared.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const time = t0 + ((px - pad.left) / innerW) * span;
    let best = 0;
    for (let i = 1; i < prepared.length; i += 1) {
      if (Math.abs(prepared[i].time - time) < Math.abs(prepared[best].time - time)) best = i;
    }
    setHover(best);
  };

  const hovered = hover != null ? prepared[hover] : null;

  return (
    <div ref={ref} className="chart">
      {prepared.length === 0 ? (
        <div className="chart-empty" style={{ height }}>
          {emptyText}
        </div>
      ) : (
        <>
          <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
            <defs>
              {series.map((s, i) => (
                <linearGradient key={s.key} id={`${gradientId}-${i}`} x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity="0.28" />
                  <stop offset="100%" stopColor={s.color} stopOpacity="0" />
                </linearGradient>
              ))}
            </defs>
            {yTicks.map((v) => (
              <g key={v}>
                <line x1={pad.left} x2={pad.left + innerW} y1={y(v)} y2={y(v)} className="grid" />
                <text x={pad.left - 8} y={y(v) + 4} textAnchor="end" className="axis">
                  {formatMs(v)}
                </text>
              </g>
            ))}
            {xTicks.map((t) => (
              <text key={t} x={x(t)} y={height - 6} textAnchor="middle" className="axis">
                {fmtX(t)}
              </text>
            ))}
            {area &&
              lines.map((s, i) => <path key={`a-${s.key}`} d={s.fill} fill={`url(#${gradientId}-${i})`} stroke="none" />)}
            {lines.map((s) => (
              <path key={s.key} d={s.d} fill="none" stroke={s.color} strokeWidth="1.75" strokeLinejoin="round" />
            ))}
            {prepared.length <= 150 &&
              series.map((s) =>
                prepared.map((p) =>
                  p[s.key] == null ? null : (
                    <circle key={`${s.key}-${p.time}`} cx={x(p.time)} cy={y(p[s.key])} r="2.2" fill={s.color} />
                  ),
                ),
              )}
            {markFailures &&
              prepared.map((p) =>
                p.failed ? (
                  <line
                    key={`f-${p.time}`}
                    x1={x(p.time)}
                    x2={x(p.time)}
                    y1={pad.top}
                    y2={pad.top + innerH}
                    className="fail-line"
                  />
                ) : null,
              )}
            {hovered && (
              <g>
                <line
                  x1={x(hovered.time)}
                  x2={x(hovered.time)}
                  y1={pad.top}
                  y2={pad.top + innerH}
                  className="hover-line"
                />
                {series.map((s) =>
                  hovered[s.key] != null ? (
                    <circle key={s.key} cx={x(hovered.time)} cy={y(hovered[s.key])} r="4" fill={s.color} />
                  ) : null,
                )}
              </g>
            )}
          </svg>
          {hovered && (
            <div
              className="tooltip"
              style={{
                left: Math.min(width - 190, Math.max(0, x(hovered.time) + 12)),
                top: pad.top,
              }}
            >
              <div className="tooltip-title">{new Date(hovered.time).toLocaleString()}</div>
              {series.map((s) => (
                <div key={s.key} className="tooltip-row">
                  <span className="swatch" style={{ background: s.color }} />
                  {s.label}
                  <strong>{formatMs(hovered[s.key])}</strong>
                </div>
              ))}
              {hovered.failed && <div className="tooltip-row tone-down">✕ {hovered.failLabel || "failed"}</div>}
            </div>
          )}
          <div className="legend">
            {series.map((s) => (
              <span key={s.key}>
                <span className="swatch" style={{ background: s.color }} />
                {s.label}
              </span>
            ))}
            {markFailures && (
              <span>
                <span className="swatch" style={{ background: "var(--red)" }} />
                failed check
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ uptime bars

function uptimeTone(pct) {
  if (pct == null) return "none";
  if (pct >= 99.9) return "great";
  if (pct >= 99) return "good";
  if (pct >= 95) return "warn";
  return "bad";
}

export function UptimeBars({ days = [], height = 32 }) {
  const [hover, setHover] = useState(null);
  return (
    <div className="uptime">
      <div className="uptime-bars" style={{ height }} onMouseLeave={() => setHover(null)}>
        {days.map((day, i) => (
          <div
            key={day.day}
            className={`uptime-bar tone-${uptimeTone(day.uptime_pct)}`}
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </div>
      <div className="uptime-caption">
        {hover != null && days[hover] ? (
          <span>
            <strong>
              {new Date(`${days[hover].day}T00:00:00Z`).toLocaleDateString([], {
                month: "short",
                day: "numeric",
                timeZone: "UTC",
              })}
            </strong>{" "}
            · {days[hover].uptime_pct == null ? "no data" : `${formatPct(days[hover].uptime_pct)} uptime`} ·{" "}
            {days[hover].total_checks} checks
          </span>
        ) : (
          <>
            <span>{days.length} days ago</span>
            <span>today</span>
          </>
        )}
      </div>
    </div>
  );
}


// ------------------------------------------------------------------ check strip

/** Better-Stack-style strip: one bar per recent check, height = latency, colour = result. */
export function CheckStrip({ checks = [], slots = 40, height = 26 }) {
  const recent = checks.slice(-slots);
  const padCount = Math.max(0, slots - recent.length);
  const latencies = recent.filter((c) => c.is_success && c.response_time_ms != null).map((c) => c.response_time_ms);
  const max = Math.max(1, ...latencies);
  return (
    <div className="strip" style={{ height }}>
      {Array.from({ length: padCount }, (_, i) => (
        <span key={`p${i}`} className="strip-bar strip-empty" />
      ))}
      {recent.map((c, i) => {
        const tone = !c.is_success ? "down" : c.error_type === "slow" ? "degraded" : "up";
        const h = c.is_success && c.response_time_ms != null ? 28 + (72 * c.response_time_ms) / max : 100;
        return (
          <span
            key={c.id ?? `${c.checked_at}-${i}`}
            className={`strip-bar strip-${tone}`}
            style={{ height: `${Math.round(h)}%` }}
            title={`${c.is_success ? "OK" : "Failed"} · ${formatMs(c.response_time_ms)}${c.status_code ? ` · HTTP ${c.status_code}` : ""}`}
          />
        );
      })}
    </div>
  );
}
