import assert from "node:assert/strict";
import test from "node:test";

import {
  businessWeekLabel,
  businessWeekNumber,
  businessWeekRangeLabel,
} from "./format.js";

test("business week labels use the 30 March 2026 calendar start", () => {
  assert.equal(businessWeekNumber("2026-05-18"), 8);
  assert.equal(businessWeekLabel("2026-05-18"), "Week 8");
  assert.equal(businessWeekNumber("2026-05-11"), 7);
  assert.equal(businessWeekLabel("2026-05-11"), "Week 7");
});

test("top summary label renders Week 8 for 18 May 2026", () => {
  assert.equal(
    businessWeekRangeLabel("2026-05-18", "2026-05-18"),
    "Week 8 18 May 2026 - 24 May 2026",
  );
});
