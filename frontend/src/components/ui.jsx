import { useEffect, useRef, useState } from "react";

export const STATUS_LABEL = {
  up: "Operational",
  degraded: "Degraded",
  down: "Down",
  unknown: "Pending",
  paused: "Paused",
  maintenance: "Maintenance",
};

/** Linear-style status glyph: filled dot, half ring, empty ring. */
export function StatusGlyph({ status, size = 10 }) {
  return <span className={`glyph glyph-${status}`} style={{ width: size, height: size }} aria-label={status} />;
}

export function StatusDot({ status, pulse = false }) {
  return <span className={`dot dot-${status}${pulse ? " dot-pulse" : ""}`} aria-hidden="true" />;
}

export function StatusPill({ status }) {
  return (
    <span className={`pill pill-${status}`}>
      <StatusDot status={status} pulse={status === "down"} />
      {STATUS_LABEL[status] || status}
    </span>
  );
}

export function Badge({ tone = "neutral", children, title }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Kbd({ children }) {
  return <kbd className="kbd">{children}</kbd>;
}

export function Button({ variant = "secondary", size, loading = false, icon, children, ...rest }) {
  return (
    <button
      type="button"
      className={`btn btn-${variant}${size ? ` btn-${size}` : ""}`}
      disabled={loading || rest.disabled}
      {...rest}
    >
      {loading ? <span className="spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  );
}

export function Card({ title, subtitle, actions, children, className = "", padded = true }) {
  return (
    <section className={`card ${padded ? "card-padded" : ""} ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <p className="muted small">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ icon = "∅", title, children }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      {title && <div className="empty-title">{title}</div>}
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}

export function Modal({ title, onClose, children, footer, width = 560 }) {
  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: width }} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-header">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );
}

export function Segmented({ options, value, onChange, size }) {
  return (
    <div className={`segmented${size ? ` segmented-${size}` : ""}`} role="tablist">
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          role="tab"
          aria-selected={option.value === value}
          className={option.value === value ? "active" : ""}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.count !== undefined && <span className="seg-count">{option.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          type="button"
          key={tab.value}
          role="tab"
          aria-selected={tab.value === value}
          className={tab.value === value ? "active" : ""}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
          {tab.count ? <span className="tab-count">{tab.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label, hint }) {
  return (
    <label className="switch-row">
      <span className="switch-text">
        <span>{label}</span>
        {hint && <span className="muted small">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        className={`switch${checked ? " on" : ""}`}
        onClick={() => onChange(!checked)}
      >
        <span className="switch-thumb" />
      </button>
    </label>
  );
}

export function Skeleton({ height = 16, width = "100%" }) {
  return <div className="skeleton" style={{ height, width }} />;
}

/** Popover menu anchored to a trigger button; closes on outside click / Escape. */
export function Menu({ trigger, items, align = "right" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (event.type === "keydown" && event.key !== "Escape") return;
      if (event.type === "mousedown" && ref.current?.contains(event.target)) return;
      setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <div className="menu" ref={ref}>
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div className={`menu-pop menu-${align}`} role="menu">
          {items.map((item, i) =>
            item === "divider" ? (
              <div key={`d-${i}`} className="menu-divider" />
            ) : (
              <button
                type="button"
                role="menuitem"
                key={item.label}
                className={`menu-item${item.danger ? " danger" : ""}`}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
              >
                <span className="menu-icon">{item.icon}</span>
                {item.label}
                {item.hint && <span className="menu-hint">{item.hint}</span>}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/** Animate a number from its previous value to the new one. */
export function useCountUp(value, duration = 600) {
  const [display, setDisplay] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    if (typeof value !== "number" || Number.isNaN(value)) {
      setDisplay(value);
      return undefined;
    }
    const start = performance.now();
    const initial = typeof from.current === "number" ? from.current : 0;
    let frame;
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      setDisplay(initial + (value - initial) * eased);
      if (t < 1) frame = requestAnimationFrame(step);
      else from.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return display;
}

export function AnimatedNumber({ value, format = (v) => Math.round(v) }) {
  const display = useCountUp(value);
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return format(typeof display === "number" && !Number.isNaN(display) ? display : value);
}
