"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";

const TERMINAL = new Set([
  "succeeded",
  "partial",
  "failed",
  "cancelled",
  "purged",
]);
type WatchedJob = { id: string; name: string };
type AlertContext = {
  jobs: WatchedJob[];
  ready: boolean;
  setWatched: (job: WatchedJob, enabled: boolean) => void;
};
const Context = createContext<AlertContext | null>(null);

/** Tab-scoped alerts survive navigation and reload, and never cross accounts. */
export function JobCompletionAlerts({
  scope,
  children,
}: {
  scope: string;
  children: ReactNode;
}) {
  const storageKey = `papercrane:job-alerts:${scope}`;
  const [jobs, setJobs] = useState<WatchedJob[]>([]);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    try {
      const saved: unknown = JSON.parse(
        sessionStorage.getItem(storageKey) ?? "[]",
      );
      if (Array.isArray(saved))
        setJobs(
          saved.filter(
            (job): job is WatchedJob =>
              !!job &&
              typeof job.id === "string" &&
              typeof job.name === "string",
          ),
        );
    } catch {
      /* Storage can be disabled; alerts still work for this visit. */
    }
    setReady(true);
  }, [storageKey]);
  const setWatched = useCallback(
    (job: WatchedJob, enabled: boolean) => {
      setJobs((current) => {
        const next = [
          ...current.filter((item) => item.id !== job.id),
          ...(enabled ? [job] : []),
        ];
        try {
          sessionStorage.setItem(storageKey, JSON.stringify(next));
        } catch {
          /* In-memory fallback. */
        }
        return next;
      });
    },
    [storageKey],
  );

  return (
    <Context.Provider value={{ jobs, ready, setWatched }}>
      {children}
      {ready &&
        jobs.map((job) => (
          <WatchJob key={job.id} job={job} onDone={setWatched} />
        ))}
    </Context.Provider>
  );
}

function WatchJob({
  job,
  onDone,
}: {
  job: WatchedJob;
  onDone: AlertContext["setWatched"];
}) {
  const query = trpc.jobs.get.useQuery(
    { id: job.id },
    { refetchInterval: 5_000, refetchIntervalInBackground: true },
  );
  const { toast } = useToast();
  const delivered = useRef(false);
  const status = query.data?.status;
  useEffect(() => {
    if (!status || !TERMINAL.has(status) || delivered.current) return;
    delivered.current = true;
    const outcome =
      status === "succeeded"
        ? "finished"
        : status === "partial"
          ? "has partial results"
          : status === "failed"
            ? "failed"
            : "stopped";
    const title = `${job.name} ${outcome}`;
    toast({
      title,
      description: `Job ${job.id.slice(0, 8)}`,
      variant: status === "failed" ? "error" : "info",
    });
    if ("Notification" in window && Notification.permission === "granted") {
      try {
        const notification = new Notification("Papercrane", {
          body: title,
          tag: `papercrane-job-${job.id}`,
        });
        notification.onclick = () => {
          window.focus();
          window.location.assign(`/app/jobs/${job.id}`);
          notification.close();
        };
      } catch {
        /* Browsers without system notification support still get the in-app alert. */
      }
    }
    onDone(job, false);
  }, [status, job, toast, onDone]);
  return null;
}

export function JobAlertToggle({
  jobId,
  toolName,
}: {
  jobId: string;
  toolName: string;
}) {
  const context = useContext(Context);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checked = context?.jobs.some((job) => job.id === jobId) ?? false;
  const toggle = async () => {
    if (!context) return;
    setError(null);
    if (checked) {
      context.setWatched({ id: jobId, name: toolName }, false);
      return;
    }
    if (!("Notification" in window)) {
      setError("Browser alerts aren’t supported here.");
      return;
    }
    setBusy(true);
    try {
      const permission =
        Notification.permission === "default"
          ? await Notification.requestPermission()
          : Notification.permission;
      if (permission !== "granted") {
        setError("Allow notifications in your browser to enable this alert.");
        return;
      }
      context.setWatched({ id: jobId, name: toolName }, true);
    } catch {
      setError("Couldn’t enable the alert. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <label className="inline-flex cursor-pointer items-center gap-3 text-sm text-ink">
        <input
          type="checkbox"
          role="switch"
          checked={checked}
          disabled={!context?.ready || busy}
          onChange={() => void toggle()}
          className="h-4 w-4 accent-crane"
        />
        Notify when finished
      </label>
      <p className="text-xs text-graphite">
        Browser alert while this tab stays open.
      </p>
      {error && (
        <p role="alert" className="text-xs text-graphite">
          {error}
        </p>
      )}
    </div>
  );
}
