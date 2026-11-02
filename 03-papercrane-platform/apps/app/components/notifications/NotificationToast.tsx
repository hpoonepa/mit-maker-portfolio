"use client";

import { useCallback } from "react";
import { useToast } from "@/components/toasts/useToast";
import {
  useNotificationRealtime,
  type NotificationRow,
} from "@/hooks/useNotificationRealtime";

/**
 * Bridges Supabase realtime notifications into the toast system.
 *
 * Mounts under <NotificationBell/> and renders nothing: its only job is
 * to listen for INSERTs and pop a toast keyed off the notification kind.
 *
 *   job.completed   → success toast (green check via the toast variant)
 *   job.failed      → error toast
 *   billing.upgrade → info toast
 *   member.invited  → info toast
 *   system.alert    → warning toast
 *
 * Anything else falls back to an info toast so we never silently swallow
 * a new notification kind that ships before the UI is updated.
 */

type ToastVariant = "success" | "error" | "info" | "warning";

function variantForKind(kind: string): ToastVariant {
  switch (kind) {
    case "job.completed":
      return "success";
    case "job.failed":
      return "error";
    case "system.alert":
      return "warning";
    case "billing.upgrade":
    case "member.invited":
      return "info";
    default:
      // Coarse-grained fallbacks based on the category prefix.
      if (kind.startsWith("job.")) return "info";
      if (kind.startsWith("system.")) return "warning";
      return "info";
  }
}

export function NotificationToast() {
  const { toast } = useToast();

  const onNotification = useCallback(
    (n: NotificationRow) => {
      toast({
        title: n.title,
        description: n.body ?? undefined,
        variant: variantForKind(n.kind),
      });
    },
    [toast],
  );

  useNotificationRealtime({ onNotification });

  return null;
}
