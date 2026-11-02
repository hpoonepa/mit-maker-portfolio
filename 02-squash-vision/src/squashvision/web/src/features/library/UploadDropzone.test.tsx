// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UploadDropzone } from "./UploadDropzone";

class FakeUploadRequest extends EventTarget {
  static created = 0;
  static current: FakeUploadRequest | null = null;
  static requests: FakeUploadRequest[] = [];
  readonly upload = new EventTarget();
  status = 0;
  responseText = "";
  sent: FormData | null = null;
  method = "";
  url = "";
  aborted = false;

  constructor() {
    FakeUploadRequest.created += 1;
    super();
    FakeUploadRequest.current = this;
    FakeUploadRequest.requests.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader() {}

  getResponseHeader() {
    return "upload-request";
  }

  send(body: FormData) {
    this.sent = body;
  }

  abort() {
    this.aborted = true;
    this.dispatchEvent(new Event("abort"));
  }

  respond(status: number, value: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(value);
    this.dispatchEvent(new Event("load"));
  }
}

const uploadedMatch = {
  id: "real-match-id",
  title: "League night",
  metadata: { playerOne: "Mina", playerTwo: "Inez", playedOn: null, score: null },
  assets: [],
  updatedAt: "2026-08-25T12:00:00Z",
  version: 1,
  preparationState: "prepared",
  quality: { availability: "unavailable", warnings: [] },
  latestJob: null,
  latestReport: null,
  calibrationRevision: null,
  modelQuality: [],
};

beforeEach(() => {
  vi.stubGlobal("XMLHttpRequest", FakeUploadRequest);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  FakeUploadRequest.created = 0;
  FakeUploadRequest.current = null;
  FakeUploadRequest.requests = [];
});

describe("local video ingest", () => {
  it("rejects unsupported files before upload and keeps selection keyboard accessible", () => {
    renderDropzone();
    const input = screen.getByLabelText("Choose one match video");
    fireEvent.change(input, { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });

    expect(screen.getByRole("alert")).toHaveTextContent("Choose an MP4, MOV, M4V, or WebM video");
    expect(FakeUploadRequest.current).toBeNull();
  });
  it("clears the native picker value so the exact same file can be chosen again", () => {
    renderDropzone();
    const input = screen.getByLabelText("Choose one match video") as HTMLInputElement;
    Object.defineProperty(input, "value", { configurable: true, writable: true, value: "C:\\fakepath\\match.mp4" });
    const file = new File(["video"], "match.mp4", { type: "video/mp4" });

    fireEvent.change(input, { target: { files: [file] } });

    expect(input.value).toBe("");
    expect(screen.getByText("match.mp4")).toBeInTheDocument();
  });
  it("rejects a multi-file drop and exposes a keyboard focus target", () => {
    renderDropzone();
    const input = screen.getByLabelText("Choose one match video");
    input.focus();
    fireEvent.focus(input);
    expect(input).toHaveFocus();
    const target = screen.getByText(/Choose a match video/).closest("label");
    expect(target).not.toBeNull();
    expect(target).toHaveAttribute("data-focused", "true");
    fireEvent.drop(target as HTMLLabelElement, {
      dataTransfer: {
        files: [
          new File(["one"], "one.mp4", { type: "video/mp4" }),
          new File(["two"], "two.mp4", { type: "video/mp4" }),
        ],
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose exactly one video");
    expect(screen.getByRole("button", { name: "Upload match" })).toBeDisabled();
  });


  it("rejects files above the local byte limit before creating XHR", () => {
    renderDropzone();
    const oversized = new File(["x"], "long-match.mp4", { type: "video/mp4" });
    Object.defineProperty(oversized, "size", { configurable: true, value: 20 * 1024 * 1024 * 1024 + 1 });
    fireEvent.change(screen.getByLabelText("Choose one match video"), {
      target: { files: [oversized] },
    });

    expect(screen.getByRole("alert")).toHaveTextContent("exceeds the 20 GB local upload limit");
    expect(FakeUploadRequest.current).toBeNull();
  });

  it("sends optional metadata, reports real byte progress, and resolves only with the server ID", async () => {
    const onUploaded = vi.fn();
    renderDropzone(onUploaded);
    const input = screen.getByLabelText("Choose one match video");
    fireEvent.change(input, { target: { files: [new File(["video"], "match.mp4", { type: "video/mp4" })] } });
    fireEvent.change(screen.getByLabelText("Match title"), { target: { value: "League night" } });
    fireEvent.change(screen.getByLabelText("Player A"), { target: { value: "Mina" } });
    fireEvent.change(screen.getByLabelText("Player B"), { target: { value: "Inez" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload match" }));

    const request = FakeUploadRequest.current;
    expect(request?.method).toBe("POST");
    expect(request?.url).toBe("/api/v1/matches");
    expect(request?.sent?.get("title")).toBe("League night");
    expect(request?.sent?.get("playerOne")).toBe("Mina");
    request?.upload.dispatchEvent(new ProgressEvent("progress", { loaded: 5, total: 10, lengthComputable: true }));
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50"));
    expect(screen.getByText("5 B of 10 B uploaded")).toBeInTheDocument();
    request?.upload.dispatchEvent(new ProgressEvent("progress", { loaded: 10, total: 10, lengthComputable: true }));
    await waitFor(() => expect(screen.getByText("Preparing your match")).toBeVisible());
    expect(onUploaded).not.toHaveBeenCalled();

    request?.respond(201, uploadedMatch);
    expect(await screen.findByText("Upload complete")).toBeInTheDocument();
    expect(onUploaded).toHaveBeenCalledWith(expect.objectContaining({ id: "real-match-id" }));
  });

  it("continues reporting upload progress and completion after StrictMode effect replay", async () => {
    const onUploaded = vi.fn();
    render(
      <StrictMode>
        <UploadDropzone onUploaded={onUploaded} />
      </StrictMode>,
    );
    chooseVideo();
    expect(screen.getByRole("button", { name: "Upload match" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Upload match" }));

    const request = FakeUploadRequest.current;
    request?.upload.dispatchEvent(new ProgressEvent("progress", { loaded: 3, total: 6, lengthComputable: true }));
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50"));

    request?.respond(201, uploadedMatch);
    expect(await screen.findByText("Upload complete")).toBeInTheDocument();
    expect(FakeUploadRequest.created).toBe(1);
    expect(onUploaded).toHaveBeenCalledWith(expect.objectContaining({ id: "real-match-id" }));
  });

  it("keeps the active upload intact when a replacement is dropped and resubmitted", async () => {
    renderDropzone();
    chooseVideo();
    fireEvent.click(screen.getByRole("button", { name: "Upload match" }));
    const request = FakeUploadRequest.current;
    request?.upload.dispatchEvent(new ProgressEvent("progress", { loaded: 2, total: 5, lengthComputable: true }));
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40"));
    const dropzone = screen.getByLabelText("Choose one match video").closest("label");

    fireEvent.drop(dropzone as HTMLLabelElement, {
      dataTransfer: {
        files: [new File(["replacement"], "second.mp4", { type: "video/mp4" })],
      },
    });
    fireEvent.submit(dropzone?.closest("form") as HTMLFormElement);

    expect(screen.getByText("match.mp4")).toBeInTheDocument();
    expect(screen.queryByText("second.mp4")).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByText("2 B of 5 B uploaded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel upload" })).toBeEnabled();
    expect(dropzone).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Cancel this upload before choosing another video.")).toBeInTheDocument();
    expect(FakeUploadRequest.requests).toEqual([request]);

    request?.respond(201, uploadedMatch);
    expect(await screen.findByText("Upload complete")).toBeInTheDocument();
  });

  it("aborts an active upload when the dropzone unmounts", () => {
    const view = renderDropzone();
    chooseVideo();
    fireEvent.click(screen.getByRole("button", { name: "Upload match" }));
    const request = FakeUploadRequest.current;
    view.unmount();
    expect(request?.aborted).toBe(true);
  });

  it("cancels the active XHR and maps insufficient disk to an actionable finite error", async () => {
    renderDropzone();
    chooseVideo();
    fireEvent.click(screen.getByRole("button", { name: "Upload match" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload cancelled");

    chooseVideo();
    fireEvent.click(screen.getByRole("button", { name: "Upload match" }));
    FakeUploadRequest.current?.respond(507, {
      code: "insufficient_disk",
      message: "insufficient disk space is available for this upload",
      details: null,
      requestId: "upload-request",
    });
    expect(await screen.findByRole("button", { name: "Retry upload" })).toBeEnabled();
  });
  it.each([
    ["duration_exceeded", "This video exceeds the 3-hour match limit"],
    ["invalid_duration", "The video duration could not be read"],
    ["no_video_stream", "No video track was found"],
    ["unsupported_container", "Choose an MP4, MOV, M4V, or WebM video"],
    ["invalid_media", "The video could not be decoded"],
    ["proxy_failed", "The video timestamps could not be mapped"],
    ["other_validation", "The upload was rejected. Review the file details"],
  ])("maps %s by stable code without a generic duration claim", async (code, expected) => {
    renderDropzone();
    chooseVideo();
    fireEvent.click(screen.getByRole("button", { name: "Upload match" }));
    FakeUploadRequest.current?.respond(422, {
      code,
      message: "unsafe tool stderr",
      details: null,
      requestId: "upload-request",
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(screen.getByRole("alert")).not.toHaveTextContent(
      "under 60 minutes",
    );
  });
});

function renderDropzone(onUploaded = vi.fn()) {
  return render(<UploadDropzone onUploaded={onUploaded} />);
}

function chooseVideo() {
  fireEvent.change(screen.getByLabelText("Choose one match video"), {
    target: { files: [new File(["video"], "match.mp4", { type: "video/mp4" })] },
  });
}
