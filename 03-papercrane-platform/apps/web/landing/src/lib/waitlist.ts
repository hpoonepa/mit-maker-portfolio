type SignupResponse = {
  error?: string;
};

export function initWaitlistForm(): void {
  const form = document.querySelector<HTMLFormElement>(".waitlist-form");
  if (!form || form.dataset.initialized === "true") return;

  const button = form.querySelector<HTMLButtonElement>('button[type="submit"]');
  const status = form.querySelector<HTMLElement>(".waitlist-form__status");
  if (!button || !status) return;

  form.dataset.initialized = "true";

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;

    const data = new FormData(form);
    const originalLabel = button.textContent ?? "send  →";

    button.disabled = true;
    button.textContent = "sending…";
    status.textContent = "";
    delete status.dataset.state;

    try {
      const response = await fetch("/api/beta-signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: String(data.get("name") ?? ""),
          email: String(data.get("email") ?? ""),
          org: String(data.get("org") ?? ""),
          useCase: String(data.get("brief") ?? ""),
        }),
      });

      const payload = (await response.json().catch(() => ({}))) as SignupResponse;
      if (!response.ok) throw new Error(payload.error || "Request failed");

      form.reset();
      status.dataset.state = "success";
      status.textContent = "You're on the list. We'll respond within 48 hours.";
      button.textContent = "sent  ✓";
    } catch (error) {
      status.dataset.state = "error";
      status.textContent =
        error instanceof Error ? error.message : "Could not submit. Please try again.";
      button.disabled = false;
      button.textContent = originalLabel;
    }
  });
}
