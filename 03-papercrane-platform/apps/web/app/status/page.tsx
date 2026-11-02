export const dynamic = "force-dynamic";
export const revalidate = 30;

type ComponentStatus = {
  name: string;
  state: "ok" | "down" | "unknown";
  detail: string;
  checkedAt: string;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production"
    ? "https://api.papercrane.bio"
    : "http://localhost:3001");

async function pingHealthz(url: string): Promise<ComponentStatus> {
  const checkedAt = new Date().toISOString();
  try {
    const res = await fetch(`${url}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    if (res.ok) {
      return {
        name: "api",
        state: "ok",
        detail: `${res.status} ${res.statusText}`.trim(),
        checkedAt,
      };
    }
    return {
      name: "api",
      state: "down",
      detail: `${res.status} ${res.statusText}`.trim(),
      checkedAt,
    };
  } catch (err) {
    const reason = err instanceof Error ? err.message : "unreachable";
    return { name: "api", state: "down", detail: reason, checkedAt };
  }
}

function selfStatus(): ComponentStatus {
  return {
    name: "web",
    state: "ok",
    detail: "rendered",
    checkedAt: new Date().toISOString(),
  };
}

function workerStatus(): ComponentStatus {
  // TODO: ping worker /healthz once the worker exposes one.
  return {
    name: "worker",
    state: "unknown",
    detail: "no live ping yet",
    checkedAt: new Date().toISOString(),
  };
}

function dotColor(state: ComponentStatus["state"]): string {
  if (state === "ok") return "#16a34a";
  if (state === "down") return "#dc2626";
  return "#a3a3a3";
}

function fmtTime(iso: string): string {
  return new Date(iso).toISOString().replace("T", " ").replace(/\..+$/, "Z");
}

export default async function StatusPage() {
  const [api] = await Promise.all([pingHealthz(API_URL)]);
  const components: ComponentStatus[] = [api, selfStatus(), workerStatus()];

  const allOk = components.every((c) => c.state === "ok");
  const anyDown = components.some((c) => c.state === "down");

  const headline = anyDown
    ? "Some signals are bent"
    : allOk
      ? "All systems folded properly"
      : "Mostly folded, partly uncertain";
  const headlineColor = anyDown ? "#dc2626" : allOk ? "#16a34a" : "#a3a3a3";

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#fafaf7",
        color: "#111",
        padding: "96px 24px",
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div style={{ width: "100%", maxWidth: 720 }}>
        <h1
          style={{
            fontFamily:
              "Fraunces, ui-serif, Georgia, 'Times New Roman', serif",
            fontWeight: 400,
            fontSize: "clamp(48px, 7vw, 88px)",
            letterSpacing: "-0.02em",
            margin: 0,
            lineHeight: 1.05,
          }}
        >
          Status
        </h1>

        <p
          style={{
            fontFamily:
              "Fraunces, ui-serif, Georgia, 'Times New Roman', serif",
            fontStyle: "italic",
            fontSize: "clamp(20px, 2.4vw, 28px)",
            marginTop: 16,
            color: headlineColor,
          }}
        >
          {headline}.
        </p>

        <div
          style={{
            marginTop: 56,
            borderTop: "1px solid #e5e5e0",
          }}
        >
          {components.map((c) => (
            <div
              key={c.name}
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr auto",
                alignItems: "center",
                gap: 16,
                padding: "20px 0",
                borderBottom: "1px solid #e5e5e0",
                fontFamily:
                  "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                fontSize: 14,
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: dotColor(c.state),
                  display: "inline-block",
                }}
              />
              <span style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
                <span style={{ color: "#111" }}>{c.name}</span>
                <span style={{ color: "#888" }}>{c.detail}</span>
              </span>
              <span style={{ color: "#888" }}>{fmtTime(c.checkedAt)}</span>
            </div>
          ))}
        </div>

        <p
          style={{
            marginTop: 40,
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
            fontSize: 12,
            color: "#888",
          }}
        >
          checked against {API_URL} · refreshes every 30s
        </p>
      </div>
    </main>
  );
}
