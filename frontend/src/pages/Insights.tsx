import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { keys } from "../lib/queryClient";
import { SourceBadge } from "../components/SourceBadge";

function Bar({ value, max, width = 200 }: { value: number; max: number; width?: number }) {
  const w = Math.max(1, Math.round((value / Math.max(max, 1)) * width));
  return (
    <span
      style={{
        display: "inline-block",
        background: "var(--color-primary)",
        height: "1.2em",
        borderRadius: 2,
        verticalAlign: "middle",
        width: w,
      }}
    />
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <article
      style={{
        border: "1px solid var(--color-border)",
        borderRadius: 6,
        padding: "0.75rem 1rem",
      }}
    >
      <header>
        <strong>{title}</strong>
      </header>
      <div style={{ marginTop: "0.5rem" }}>{children}</div>
    </article>
  );
}

function Empty() {
  return <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>No data</p>;
}

export default function Insights() {
  const [params, setParams] = useSearchParams();
  const days = +(params.get("days") ?? 30);
  const { data, isLoading } = useQuery({
    queryKey: keys.insights(days),
    queryFn: () => api.insights(days),
  });

  if (isLoading) return <p>Loading…</p>;
  if (!data) return <p>No data</p>;

  const maxTod = Math.max(...Object.values(data.time_of_day), 1);
  const maxDow = Math.max(...Object.values(data.day_of_week), 1);
  const maxSrc = Math.max(...Object.values(data.sources), 1);
  const maxProj = Math.max(...Object.values(data.projects), 1);

  return (
    <>
      <h2>Work Patterns</h2>
      <form onSubmit={(e) => e.preventDefault()} style={{ marginBottom: "1rem" }}>
        <select value={days} onChange={(e) => setParams({ days: e.target.value })}>
          {[7, 14, 30, 60, 90].map((d) => (
            <option key={d} value={d}>
              Last {d} days
            </option>
          ))}
        </select>
      </form>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "1.5rem",
        }}
      >
        <Card title="Activity by Hour">
          {Object.keys(data.time_of_day).length === 0 ? (
            <Empty />
          ) : (
            Object.entries(data.time_of_day)
              .filter(([, c]) => c > 0)
              .map(([hour, count]) => (
                <div key={hour} style={{ margin: "2px 0" }}>
                  <span
                    style={{
                      display: "inline-block",
                      width: "3em",
                      color: "var(--color-muted)",
                      fontSize: "0.85em",
                    }}
                  >
                    {hour}
                  </span>
                  <Bar value={count} max={maxTod} />
                  <span
                    style={{
                      marginLeft: "0.5rem",
                      color: "var(--color-muted)",
                      fontSize: "0.85em",
                    }}
                  >
                    {count}
                  </span>
                </div>
              ))
          )}
        </Card>

        <Card title="Activity by Day">
          {Object.keys(data.day_of_week).length === 0 ? (
            <Empty />
          ) : (
            Object.entries(data.day_of_week).map(([day, count]) => (
              <div key={day} style={{ margin: "2px 0" }}>
                <span
                  style={{
                    display: "inline-block",
                    width: "6em",
                    color: "var(--color-muted)",
                    fontSize: "0.85em",
                  }}
                >
                  {day}
                </span>
                <Bar value={count} max={maxDow} />
                <span
                  style={{
                    marginLeft: "0.5rem",
                    color: "var(--color-muted)",
                    fontSize: "0.85em",
                  }}
                >
                  {count}
                </span>
              </div>
            ))
          )}
        </Card>

        <Card title="Sources">
          {Object.keys(data.sources).length === 0 ? (
            <Empty />
          ) : (
            Object.entries(data.sources).map(([src, count]) => (
              <div key={src} style={{ margin: "2px 0" }}>
                <SourceBadge source={src} />
                <span style={{ marginLeft: "0.5rem" }}>
                  <Bar value={count} max={maxSrc} width={150} />
                </span>
                <span
                  style={{
                    marginLeft: "0.5rem",
                    color: "var(--color-muted)",
                    fontSize: "0.85em",
                  }}
                >
                  {count}
                </span>
              </div>
            ))
          )}
        </Card>

        <Card title="Projects">
          {Object.keys(data.projects).length === 0 ? (
            <Empty />
          ) : (
            Object.entries(data.projects).map(([proj, count]) => (
              <div key={proj} style={{ margin: "2px 0" }}>
                <span
                  style={{
                    display: "inline-block",
                    width: "10em",
                    color: "var(--color-muted)",
                    fontSize: "0.85em",
                  }}
                >
                  {proj.slice(0, 20)}
                </span>
                <Bar value={count} max={maxProj} width={150} />
                <span
                  style={{
                    marginLeft: "0.5rem",
                    color: "var(--color-muted)",
                    fontSize: "0.85em",
                  }}
                >
                  {count}
                </span>
              </div>
            ))
          )}
        </Card>

        <Card title="Top Collaborators">
          {data.collaborators.length === 0 ? (
            <Empty />
          ) : (
            data.collaborators.map((c) => (
              <div key={c.name} style={{ margin: "2px 0" }}>
                <span>{c.name}</span>
                <span
                  style={{
                    marginLeft: "0.5rem",
                    color: "var(--color-muted)",
                    fontSize: "0.85em",
                  }}
                >
                  ({c.events} events)
                </span>
              </div>
            ))
          )}
        </Card>

        <Card title="Context Switching">
          {!data.context_switches ? (
            <Empty />
          ) : (
            <>
              <p>
                Average <strong>{data.context_switches.avg_per_day}</strong> switches/day
              </p>
              {Object.entries(data.context_switches.daily).map(([date, count]) => (
                <div key={date} style={{ margin: "2px 0" }}>
                  <span
                    style={{
                      display: "inline-block",
                      width: "7em",
                      color: "var(--color-muted)",
                      fontSize: "0.85em",
                    }}
                  >
                    {date.slice(5)}
                  </span>
                  <Bar value={count} max={30} width={count * 15} />
                  <span
                    style={{
                      marginLeft: "0.5rem",
                      color: "var(--color-muted)",
                      fontSize: "0.85em",
                    }}
                  >
                    {count}
                  </span>
                </div>
              ))}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
