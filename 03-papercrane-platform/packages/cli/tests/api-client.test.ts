import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, requireAuth } from "../src/lib/api-client.js";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("ApiClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the standalone tRPC query endpoint with a superjson envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({ result: { data: { json: { items: [{ id: "p1" }] } } } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient({
      apiUrl: "https://api.example.test/",
      apiKey: "pc_test_key",
    });

    const result = await client.query<{ items: Array<{ id: string }> }>(
      "projects.list",
      { limit: 5 },
    );

    expect(result).toEqual({
      ok: true,
      status: 200,
      data: { items: [{ id: "p1" }] },
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/^https:\/\/api\.example\.test\/trpc\/projects\.list\?/);
    expect(JSON.parse(decodeURIComponent(url.split("input=")[1]!))).toEqual({
      json: { limit: 5 },
    });
    expect(init.headers).toMatchObject({ authorization: "Bearer pc_test_key" });
  });

  it("posts tRPC mutations with a superjson envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({ result: { data: { json: { id: "job-1" } } } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient({ apiUrl: "https://api.example.test" });

    const result = await client.mutate<{ id: string }>("jobs.cancel", {
      id: "job-1",
    });

    expect(result.data).toEqual({ id: "job-1" });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/trpc/jobs.cancel",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ json: { id: "job-1" } }),
      }),
    );
  });

  it("surfaces a tRPC error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({ error: { json: { message: "job not found" } } }, 404),
      ),
    );
    const result = await new ApiClient({ apiUrl: "https://api.example.test" }).query(
      "jobs.get",
      { id: "missing" },
    );

    expect(result).toEqual({ ok: false, status: 404, error: "job not found" });
  });

  it("returns network failures without throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));
    const result = await new ApiClient({ apiUrl: "https://api.example.test" }).query(
      "projects.list",
    );
    expect(result).toEqual({ ok: false, status: 0, error: "connection refused" });
  });
});

describe("requireAuth", () => {
  it("rejects an unauthenticated client", () => {
    expect(() =>
      requireAuth(new ApiClient({ apiUrl: "https://api.example.test", apiKey: "" })),
    ).toThrow("not logged in");
  });
});
