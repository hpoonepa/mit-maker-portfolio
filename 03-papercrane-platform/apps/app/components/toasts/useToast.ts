"use client";

import { useContext } from "react";
import { ToastApiContext, type ToastApi } from "./ToastProvider";

/**
 * Access the toast API from any Client Component below <ToastProvider>.
 *
 *   const { toast } = useToast();
 *   toast({ title: "Saved", variant: "success" });
 *
 * Throws if called without a provider: this is a programmer error, not
 * a runtime failure mode, so we fail loudly to catch the mistake at dev
 * time rather than silently dropping the call.
 */
export function useToast(): ToastApi {
  const api = useContext(ToastApiContext);
  if (!api) {
    throw new Error(
      "useToast must be used inside a <ToastProvider>. Wrap your app at the dashboard layout level.",
    );
  }
  return api;
}
