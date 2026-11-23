import { useEffect, useMemo, useRef, useState } from "react";

import { displayStatus, hostOf } from "../format.js";
import { StatusGlyph } from "./ui.jsx";

/** Tiny fuzzy matcher: all query characters must appear in order; earlier/denser matches score higher. */
function fuzzyScore(text, query) {
  if (!query) return 1;
  const t = text.toLowerCase();
  const q = query.toLowerCase();
  if (t.includes(q)) return 100 - t.indexOf(q);
  let ti = 0;
  let score = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, ti);
    if (found === -1) return 0;
    score += found === ti ? 3 : 1;
    ti = found + 1;
  }
  return score;
}

export function CommandPalette({ open, onClose, endpoints, actions, onOpenEndpoint }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const items = useMemo(() => {
    const endpointItems = endpoints
      .map((e) => ({
        id: `e-${e.id}`,
        group: "Endpoints",
        label: e.name,
        hint: hostOf(e.url),
        icon: <StatusGlyph status={displayStatus(e)} />,
        score: Math.max(fuzzyScore(e.name, query), fuzzyScore(e.url, query) * 0.6),
        run: () => onOpenEndpoint(e.id),
      }))
      .filter((i) => i.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, query ? 8 : 5);
    const actionItems = actions
      .map((a) => ({ ...a, group: a.group || "Actions", score: fuzzyScore(`${a.label} ${a.keywords || ""}`, query) }))
      .filter((a) => a.score > 0)
      .sort((a, b) => (query ? b.score - a.score : 0));
    return query ? [...endpointItems, ...actionItems] : [...actionItems, ...endpointItems];
  }, [endpoints, actions, query, onOpenEndpoint]);

  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const run = (item) => {
    onClose();
    item.run();
  };

  const onKeyDown = (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(items.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter" && items[active]) {
      event.preventDefault();
      run(items[active]);
    } else if (event.key === "Escape") {
      onClose();
    }
  };

  let lastGroup = null;
  return (
    <div className="overlay overlay-top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-label="Command palette">
        <div className="palette-input">
          <span className="palette-search">⌕</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search endpoints or type a command…"
            aria-label="Command"
          />
          <kbd className="kbd">esc</kbd>
        </div>
        <div className="palette-list" ref={listRef}>
          {items.length === 0 && <div className="palette-empty">No results for “{query}”</div>}
          {items.map((item, index) => {
            const header = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            return (
              <div key={item.id}>
                {header && <div className="palette-group">{header}</div>}
                <button
                  type="button"
                  data-index={index}
                  className={`palette-item${index === active ? " active" : ""}`}
                  onMouseMove={() => setActive(index)}
                  onClick={() => run(item)}
                >
                  <span className="palette-icon">{item.icon}</span>
                  <span className="palette-label">{item.label}</span>
                  {item.hint && <span className="palette-hint">{item.hint}</span>}
                  {item.shortcut && <kbd className="kbd">{item.shortcut}</kbd>}
                </button>
              </div>
            );
          })}
        </div>
        <div className="palette-footer">
          <span>
            <kbd className="kbd">↑</kbd>
            <kbd className="kbd">↓</kbd> navigate
          </span>
          <span>
            <kbd className="kbd">↵</kbd> select
          </span>
          <span>
            <kbd className="kbd">esc</kbd> close
          </span>
        </div>
      </div>
    </div>
  );
}
