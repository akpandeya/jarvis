import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { keys } from "../lib/queryClient";
import { useDebounced } from "../hooks/useDebounced";
import { EventList } from "./Timeline";

export default function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const debounced = useDebounced(q, 300);

  const { data, isFetching } = useQuery({
    queryKey: keys.search(debounced),
    queryFn: () => api.search(debounced),
    enabled: debounced.length > 0,
  });

  return (
    <>
      <h2>Search</h2>
      <form onSubmit={(e) => e.preventDefault()}>
        <input
          type="search"
          autoFocus
          placeholder="Search events…"
          value={q}
          style={{ width: "100%", maxWidth: 640 }}
          onChange={(e) => {
            const v = e.target.value;
            if (v) setParams({ q: v });
            else setParams({});
          }}
        />
      </form>
      <div style={{ marginTop: "1rem" }}>
        {!debounced && (
          <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
            Type to search across all events.
          </p>
        )}
        {debounced && isFetching && <p>Searching…</p>}
        {debounced && data && data.events.length === 0 && (
          <p>No results for "{debounced}"</p>
        )}
        {debounced && data && data.events.length > 0 && (
          <>
            <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
              {data.events.length} result(s) for "{debounced}"
            </p>
            <EventList events={data.events} />
          </>
        )}
      </div>
    </>
  );
}
