import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../lib/api";
import { keys, queryClient } from "../lib/queryClient";

type Profile = { name: string; path: string };

function ProfileSelect({
  value,
  onChange,
  profiles,
  disabled,
}: {
  value: string;
  onChange: (profile: string) => void;
  profiles: Profile[];
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      style={{
        fontSize: "0.85em",
        padding: "0.2rem 0.4rem",
        background: "var(--color-bg-elev)",
        color: "var(--color-text)",
        border: "1px solid var(--color-border)",
        borderRadius: 4,
      }}
    >
      <option value="">— none —</option>
      {profiles.map((p) => (
        <option key={p.path} value={p.path}>
          {p.name}
        </option>
      ))}
    </select>
  );
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      style={{
        marginBottom: "1.5rem",
        padding: "1rem 1.25rem",
        border: "1px solid var(--color-border)",
        borderRadius: 6,
      }}
    >
      <header style={{ marginBottom: "0.75rem" }}>
        <div style={{ fontWeight: 600 }}>{title}</div>
        {subtitle && (
          <div style={{ fontSize: "0.8em", color: "var(--color-muted)", marginTop: "0.2rem" }}>
            {subtitle}
          </div>
        )}
      </header>
      {children}
    </section>
  );
}

function Row({
  label,
  right,
}: {
  label: React.ReactNode;
  right: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: "1rem",
        padding: "0.4rem 0",
        borderBottom: "1px solid var(--color-border-muted)",
      }}
    >
      <code style={{ fontSize: "0.85em" }}>{label}</code>
      {right}
    </div>
  );
}

function GitHubPanel() {
  const { data, isLoading } = useQuery({
    queryKey: keys.settingsBrowserProfiles,
    queryFn: api.settingsBrowserProfiles,
  });
  const save = useMutation({
    mutationFn: ({ account, profile }: { account: string; profile: string }) =>
      api.setBrowserProfile(account, profile),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.settingsBrowserProfiles });
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  if (isLoading || !data) return <p>Loading…</p>;
  if (!data.installed)
    return (
      <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
        Firefox not installed. URLs will open in the system default browser.
      </p>
    );

  const accounts = Object.keys(data.accounts);
  if (accounts.length === 0) {
    return (
      <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
        No GitHub accounts detected via <code>gh auth status</code>.
      </p>
    );
  }
  return (
    <>
      {accounts.map((a) => (
        <Row
          key={a}
          label={a}
          right={
            <ProfileSelect
              value={data.accounts[a] ?? ""}
              profiles={data.profiles}
              onChange={(profile) => save.mutate({ account: a, profile })}
            />
          }
        />
      ))}
    </>
  );
}

function JiraPanel() {
  const { data, isLoading } = useQuery({
    queryKey: keys.settingsJiraProfiles,
    queryFn: api.settingsJiraProfiles,
  });
  const save = useMutation({
    mutationFn: ({ host, profile }: { host: string; profile: string }) =>
      api.setJiraProfile(host, profile),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.settingsJiraProfiles });
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  if (isLoading || !data) return <p>Loading…</p>;
  if (!data.installed)
    return (
      <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
        Firefox not installed.
      </p>
    );
  if (data.hosts.length === 0) {
    return (
      <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
        No Jira hosts yet — add one with{" "}
        <code>jarvis jira watch-board &lt;url&gt;</code>.
      </p>
    );
  }

  return (
    <>
      {data.hosts.map((h) => (
        <Row
          key={h}
          label={h}
          right={
            <ProfileSelect
              value={data.mapping[h] ?? ""}
              profiles={data.profiles}
              onChange={(profile) => save.mutate({ host: h, profile })}
            />
          }
        />
      ))}
    </>
  );
}

function GcalPanel() {
  const { data, isLoading } = useQuery({
    queryKey: keys.settingsGcalAccountMap,
    queryFn: api.settingsGcalAccountMap,
  });
  const save = useMutation({
    mutationFn: ({ calAccount, gh }: { calAccount: string; gh: string }) =>
      api.setGcalAccount(calAccount, gh),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.settingsGcalAccountMap });
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  if (isLoading || !data) return <p>Loading…</p>;
  if (data.gcal_accounts.length === 0) {
    return (
      <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
        No Google Calendar accounts configured.
      </p>
    );
  }

  return (
    <>
      {data.gcal_accounts.map((cal) => (
        <Row
          key={cal}
          label={cal}
          right={
            <select
              value={data.mapping[cal] ?? ""}
              onChange={(e) => save.mutate({ calAccount: cal, gh: e.target.value })}
              style={{
                fontSize: "0.85em",
                padding: "0.2rem 0.4rem",
                background: "var(--color-bg-elev)",
                color: "var(--color-text)",
                border: "1px solid var(--color-border)",
                borderRadius: 4,
              }}
            >
              <option value="">— none —</option>
              {data.gh_accounts.map((gh) => (
                <option key={gh} value={gh}>
                  {gh}
                </option>
              ))}
            </select>
          }
        />
      ))}
    </>
  );
}

export default function Settings() {
  return (
    <>
      <h2>Settings</h2>
      <p style={{ fontSize: "0.88em", color: "var(--color-muted)", marginTop: 0 }}>
        Map each source (GitHub account, Jira host, calendar) to a Firefox profile.
        Links opened from Jarvis will launch in the mapped profile; others use the
        system default browser.
      </p>

      <SectionCard
        title="GitHub account → Firefox profile"
        subtitle="PR links open in the mapped profile. gh accounts come from `gh auth status`."
      >
        <GitHubPanel />
      </SectionCard>

      <SectionCard
        title="Jira host → Firefox profile"
        subtitle="Every ticket URL (Focus page, Timeline, /jarvis-suggest) opens in the mapped profile."
      >
        <JiraPanel />
      </SectionCard>

      <SectionCard
        title="Calendar account → GitHub account"
        subtitle="Meeting join links on Focus use the mapped gh account → its Firefox profile."
      >
        <GcalPanel />
      </SectionCard>
    </>
  );
}
