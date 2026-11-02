import Link from "next/link";

export default function NotFound() {
  return (
    <main
      style={{
        minHeight: "100vh",
        backgroundColor: "#F7F4ED",
        color: "#14110D",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 24px",
        textAlign: "center",
      }}
    >
      <div style={{ maxWidth: "640px", width: "100%" }}>
        <h1
          style={{
            fontFamily:
              '"Fraunces", Georgia, "Times New Roman", serif',
            fontWeight: 400,
            fontSize: "clamp(96px, 18vw, 168px)",
            lineHeight: 0.9,
            letterSpacing: "-0.04em",
            margin: 0,
            color: "#14110D",
          }}
        >
          404
        </h1>
        <p
          style={{
            fontFamily:
              '"Fraunces", Georgia, "Times New Roman", serif',
            fontSize: "clamp(20px, 2.4vw, 28px)",
            fontWeight: 400,
            lineHeight: 1.3,
            margin: "32px 0 12px",
            color: "#14110D",
          }}
        >
          This page has drifted out of the fold.
        </p>
        <p
          style={{
            fontFamily:
              '"Inter", system-ui, -apple-system, sans-serif',
            fontSize: "16px",
            lineHeight: 1.5,
            margin: "0 0 40px",
            color: "rgba(20, 17, 13, 0.65)",
          }}
        >
          The path you followed does not exist on Paper Crane.
        </p>
        <Link
          href="/"
          style={{
            display: "inline-block",
            fontFamily:
              '"Inter", system-ui, -apple-system, sans-serif',
            fontSize: "15px",
            fontWeight: 500,
            color: "#C1272D",
            textDecoration: "none",
            borderBottom: "1px solid #C1272D",
            paddingBottom: "2px",
          }}
        >
          Back to home →
        </Link>
        <div
          style={{
            marginTop: "64px",
            fontFamily:
              '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
            fontSize: "12px",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "rgba(20, 17, 13, 0.45)",
          }}
        >
          status 404 · not_found
        </div>
      </div>
    </main>
  );
}
