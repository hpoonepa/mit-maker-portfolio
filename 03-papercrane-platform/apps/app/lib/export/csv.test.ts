import { describe, it, expect } from "vitest";
import { formatCsv, csvEscape, type CsvDesignInput } from "./csv.js";

/** Split a single CSV record into fields, honouring RFC-4180 quoting. */
function parseRow(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQuotes) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      out.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out;
}

function parseCsv(csv: string): { header: string[]; rows: string[][] } {
  const lines = csv.replace(/\n$/, "").split("\n");
  const [head, ...rest] = lines;
  return { header: parseRow(head ?? ""), rows: rest.map(parseRow) };
}

function cell(header: string[], row: string[], col: string): string | undefined {
  const i = header.indexOf(col);
  return i === -1 ? undefined : row[i];
}

describe("formatCsv", () => {
  it("exports lowercase worker metric keys under canonical columns (casing-bug regression)", () => {
    const design: CsvDesignInput = {
      id: "d1",
      seed: 7,
      sequence: "ACDEFG",
      length: 6,
      tool: "boltz2",
      metrics: { iptm: 0.8, ipsae: 0.7, plddt: 90, pae: 5 },
    };
    const { header, rows } = parseCsv(formatCsv([design]));
    const row = rows[0]!;

    expect(cell(header, row, "ipTM")).toBe("0.8");
    expect(cell(header, row, "ipSAE")).toBe("0.7");
    expect(cell(header, row, "pLDDT")).toBe("90");
    expect(cell(header, row, "pAE")).toBe("5");
  });

  it("resolves additional lowercase / suffixed aliases (boltz2 adapter shape)", () => {
    const design: CsvDesignInput = {
      id: "d2",
      seed: 1,
      metrics: { plddt_mean: 88.5, ipae_mean: 4.2, ptm: 0.6, dockq: 0.55, pdockq: 0.51 },
    };
    const { header, rows } = parseCsv(formatCsv([design]));
    const row = rows[0]!;

    expect(cell(header, row, "pLDDT")).toBe("88.5");
    expect(cell(header, row, "pAE")).toBe("4.2");
    expect(cell(header, row, "pTM")).toBe("0.6");
    expect(cell(header, row, "DockQ")).toBe("0.55");
    expect(cell(header, row, "pDockQ")).toBe("0.51");
  });

  it("includes ipSAE and pLDDT in the header", () => {
    const { header } = parseCsv(
      formatCsv([{ id: "d1", seed: 0, metrics: { ipsae: 0.7, plddt: 90 } }]),
    );
    expect(header).toContain("ipSAE");
    expect(header).toContain("pLDDT");
  });

  it("keeps id/seed/sequence/length/tool as fixed leading columns", () => {
    const { header } = parseCsv(
      formatCsv([{ id: "d1", seed: 0, metrics: { iptm: 0.8 } }]),
    );
    expect(header.slice(0, 5)).toEqual(["id", "seed", "sequence", "length", "tool"]);
  });

  it("preserves RFC-4180 quoting for fields containing commas and quotes", () => {
    const design: CsvDesignInput = {
      id: 'a,b',
      seed: 0,
      sequence: 'AC"DE,FG',
      metrics: { iptm: 0.8 },
    };
    const csv = formatCsv([design]);
    // id with comma must be quoted; sequence with quote+comma must be quoted
    // and the embedded quote doubled.
    expect(csv).toContain('"a,b"');
    expect(csv).toContain('"AC""DE,FG"');

    // Round-trips back to the original values.
    const { header, rows } = parseCsv(csv);
    const row = rows[0]!;
    expect(cell(header, row, "id")).toBe("a,b");
    expect(cell(header, row, "sequence")).toBe('AC"DE,FG');
  });

  it("unions metric keys across designs and leaves missing values blank", () => {
    const csv = formatCsv([
      { id: "d1", seed: 0, metrics: { iptm: 0.8 } },
      { id: "d2", seed: 1, metrics: { ipsae: 0.7 } },
    ]);
    const { header, rows } = parseCsv(csv);
    expect(header).toContain("ipTM");
    expect(header).toContain("ipSAE");
    expect(cell(header, rows[0]!, "ipSAE")).toBe("");
    expect(cell(header, rows[1]!, "ipTM")).toBe("");
  });

  it("csvEscape doubles embedded quotes and drops non-finite numbers", () => {
    expect(csvEscape('he said "hi"')).toBe('"he said ""hi"""');
    expect(csvEscape(NaN)).toBe("");
    expect(csvEscape(42)).toBe("42");
  });
});
