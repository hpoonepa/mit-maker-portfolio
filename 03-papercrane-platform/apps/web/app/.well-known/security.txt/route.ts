// RFC 9116: https://www.rfc-editor.org/rfc/rfc9116
//
// Next 16 App Router is picky about segments that start with `.`. Keep this
// handler static so the dev server does not trip its dynamic-route heuristics.
export const dynamic = "force-static";

export function GET() {
  const body =
    [
      "Contact: mailto:security@papercrane.bio",
      "Expires: 2027-04-23T00:00:00.000Z",
    ].join("\n") + "\n";

  return new Response(body, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=3600",
    },
  });
}
