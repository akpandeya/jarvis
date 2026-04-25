import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { keys, queryClient } from "../lib/queryClient";
import { SourceBadge } from "../components/SourceBadge";
import type { ClaudeSession, ClaudeSessionPatch } from "../lib/types";

const card = {
  border: "1px solid var(--color-border)",
  borderRadius: 6,
  padding: "0.65rem 1rem",
  marginBottom: "0.6rem",
};

const chip = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.25rem",
  fontSize: "0.72em",
  padding: "0.1rem 0.45rem",
  borderRadius: 999,
  border: "1px solid var(--color-border)",
  background: "var(--color-surface, transparent)",
  marginRight: "0.25rem",
  marginTop: "0.2rem",
};

const btnSm = {
  fontSize: "0.72rem",
  padding: "0.18rem 0.5rem",
  borderRadius: 4,
  border: "1px solid var(--color-border)",
  background: "transparent",
  cursor: "pointer",
} as const;

function TagChip({
  label,
  onRemove,
  tone,
}: {
  label: string;
  onRemove?: () => void;
  tone?: "auto" | "pr" | "jarvis" | "manual";
}) {
  const bg =
    tone === "pr"
      ? "rgba(88,166,255,0.12)"
      : tone === "jarvis"
      ? "rgba(246,185,59,0.14)"
      : tone === "auto"
      ? "rgba(120,120,120,0.10)"
      : "rgba(46,160,67,0.12)";
  return (
    <span style={{ ...chip, background: bg }}>
      {label}
      {onRemove && (
        <button
          aria-label={`Remove ${label}`}
          onClick={onRemove}
          style={{
            border: "none",
            background: "transparent",
            cursor: "pointer",
            color: "var(--color-muted)",
            padding: 0,
            marginLeft: 2,
            fontSize: "0.9em",
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </span>
  );
}

function tagTone(tag: string): "auto" | "pr" | "jarvis" | "manual" {
  if (tag.startsWith("pr:")) return "pr";
  if (tag === "jarvis-involved") return "jarvis";
  if (tag.startsWith("repo:") || tag.startsWith("branch:")) return "auto";
  return "manual";
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  if (diff < 86400 * 14) return `${Math.round(diff / 86400)}d ago`;
  return iso.slice(0, 10);
}

function SessionCard({ s }: { s: ClaudeSession }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(s.display_title ?? s.title ?? "");
  const [addingTag, setAddingTag] = useState(false);
  const [tagDraft, setTagDraft] = useState("");

  const patch = useMutation({
    mutationFn: (body: ClaudeSessionPatch) => api.claudeSessionPatch(s.session_id!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  const title = s.display_title || s.title || "(untitled)";

  return (
    <article style={{ ...card, opacity: s.archived ? 0.6 : 1 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "0.5rem",
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          {editing ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                patch.mutate({ display_title: draft });
                setEditing(false);
              }}
              style={{ display: "flex", gap: "0.3rem" }}
            >
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => {
                  if (draft !== (s.display_title ?? s.title ?? "")) {
                    patch.mutate({ display_title: draft });
                  }
                  setEditing(false);
                }}
                style={{
                  flex: 1,
                  fontSize: "0.9em",
                  padding: "0.2rem 0.4rem",
                  border: "1px solid var(--color-primary)",
                  borderRadius: 4,
                }}
              />
            </form>
          ) : (
            <div
              style={{ fontSize: "0.9em", cursor: "text" }}
              onClick={() => {
                setDraft(s.display_title ?? s.title ?? "");
                setEditing(true);
              }}
              title="Click to rename"
            >
              {title.slice(0, 160)}
            </div>
          )}
          <div
            style={{
              fontSize: "0.76em",
              color: "var(--color-muted)",
              marginTop: "0.2rem",
              display: "flex",
              gap: "0.6rem",
              flexWrap: "wrap",
            }}
          >
            <span>{relTime(s.last_active)}</span>
            {s.project && (
              <span>
                <SourceBadge source="github" /> {s.project}
              </span>
            )}
            {s.branch && <code>{s.branch}</code>}
            {s.turns != null && <span>{s.turns} turns</span>}
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.35rem", flexShrink: 0 }}>
          <button
            style={btnSm}
            onClick={() => patch.mutate({ archived: !s.archived })}
            title={s.archived ? "Unarchive" : "Archive"}
          >
            {s.archived ? "Unarchive" : "Archive"}
          </button>
          {s.session_id && (
            <a
              href={`/chat?session=${encodeURIComponent(s.session_id)}`}
              role="button"
              style={{ ...btnSm, borderColor: "var(--color-primary)" }}
            >
              ▶ Resume
            </a>
          )}
        </div>
      </div>
      <div style={{ marginTop: "0.35rem", display: "flex", flexWrap: "wrap" }}>
        {s.tags.map((t) => (
          <TagChip
            key={t}
            label={t}
            tone={tagTone(t)}
            onRemove={() => patch.mutate({ remove_tags: [t] })}
          />
        ))}
        {s.pr_links.map((p) => (
          <a
            key={`${p.repo}#${p.number}`}
            href={`/prs?repo=${encodeURIComponent(p.repo)}`}
            style={{ ...chip, textDecoration: "none" }}
          >
            → {p.repo}#{p.number}
          </a>
        ))}
        {addingTag ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const t = tagDraft.trim();
              if (t) patch.mutate({ add_tags: [t] });
              setTagDraft("");
              setAddingTag(false);
            }}
            style={{ display: "inline-flex" }}
          >
            <input
              autoFocus
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              onBlur={() => {
                const t = tagDraft.trim();
                if (t) patch.mutate({ add_tags: [t] });
                setTagDraft("");
                setAddingTag(false);
              }}
              placeholder="new tag"
              style={{
                ...chip,
                border: "1px dashed var(--color-primary)",
                padding: "0.1rem 0.45rem",
                minWidth: 80,
              }}
            />
          </form>
        ) : (
          <button
            onClick={() => setAddingTag(true)}
            style={{ ...chip, cursor: "pointer", borderStyle: "dashed" }}
            title="Add tag"
          >
            + tag
          </button>
        )}
      </div>
    </article>
  );
}

export default function Sessions() {
  const [params, setParams] = useSearchParams();
  const repo = params.get("repo") ?? "";
  const tags = useMemo(() => params.getAll("tag"), [params]);
  const archived = (params.get("archived") ?? "0") as "0" | "1" | "all";
  const q = params.get("q") ?? "";

  const setFilter = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p);
  };
  const toggleTag = (t: string) => {
    const p = new URLSearchParams(params);
    const current = p.getAll("tag");
    p.delete("tag");
    const next = current.includes(t) ? current.filter((x) => x !== t) : [...current, t];
    for (const x of next) p.append("tag", x);
    setParams(p);
  };

  const { data, isLoading, error } = useQuery({
    queryKey: keys.sessionsFiltered(repo || null, tags, archived, q || null),
    queryFn: () =>
      api.sessions({
        repo: repo || undefined,
        tag: tags.length ? tags : undefined,
        archived,
        q: q || undefined,
      }),
  });

  if (isLoading) return <p>Loading…</p>;
  if (error) return <p style={{ color: "var(--color-danger)" }}>Failed to load sessions.</p>;

  const sessions = data?.sessions ?? [];
  const claude = (data?.claude_sessions ?? []).filter((s) => s.session_id);

  return (
    <>
      <h2>Sessions</h2>

      {sessions.length === 0 ? null : (
        <>
          <h3 style={{ marginTop: "1rem" }}>Jarvis Sessions</h3>
          {sessions.map((s) => (
            <article key={s.id} style={card}>
              <header style={{ marginBottom: "0.4rem" }}>
                <strong>{s.started_at.slice(0, 16)}</strong>
                {s.project && (
                  <span style={{ marginLeft: "0.5rem" }}>
                    <SourceBadge source="github" />
                    <span style={{ marginLeft: "0.3rem" }}>{s.project}</span>
                  </span>
                )}
              </header>
              <p>{s.context}</p>
            </article>
          ))}
        </>
      )}

      <h3 style={{ marginTop: "1.5rem" }}>Claude Code Sessions</h3>
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: "0.75rem",
        }}
      >
        <select
          value={repo}
          onChange={(e) => setFilter("repo", e.target.value || null)}
          style={{ fontSize: "0.85rem" }}
        >
          <option value="">All repos</option>
          {(data?.projects ?? []).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <input
          value={q}
          onChange={(e) => setFilter("q", e.target.value || null)}
          placeholder="Search title or tag…"
          style={{ fontSize: "0.85rem", padding: "0.2rem 0.4rem", minWidth: 200 }}
        />
        <select
          value={archived}
          onChange={(e) => setFilter("archived", e.target.value)}
          style={{ fontSize: "0.85rem" }}
        >
          <option value="0">Active</option>
          <option value="1">Archived</option>
          <option value="all">All</option>
        </select>
        {(repo || tags.length > 0 || q || archived !== "0") && (
          <button style={btnSm} onClick={() => setParams(new URLSearchParams())}>
            Clear
          </button>
        )}
      </div>

      {(data?.all_tags ?? []).length > 0 && (
        <div style={{ marginBottom: "0.75rem", display: "flex", flexWrap: "wrap" }}>
          {(data?.all_tags ?? []).map((t) => (
            <span
              key={t}
              onClick={() => toggleTag(t)}
              style={{
                ...chip,
                cursor: "pointer",
                borderColor: tags.includes(t) ? "var(--color-primary)" : "var(--color-border)",
                background: tags.includes(t)
                  ? "rgba(88,166,255,0.14)"
                  : (chip as any).background,
              }}
            >
              {t}
            </span>
          ))}
        </div>
      )}

      {claude.length === 0 ? (
        <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
          No sessions match these filters.
        </p>
      ) : (
        claude.map((s) => <SessionCard key={s.session_id!} s={s} />)
      )}
    </>
  );
}
