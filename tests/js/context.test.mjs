// Tests for the page context's pure half.
//
// The rule under test is the one the reference learned the hard way: the
// route decides *which* live object may be read, and the live object only
// supplies the details. A widget that reads `cur_frm` unconditionally
// describes the page the reader has just left — and looks perfectly
// correct while doing it.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_LIST_COLUMNS,
  MAX_LIST_FILTERS,
  MAX_SELECTION,
  classifyRoute,
  currentRoute,
  currentSelection,
  describeListColumns,
  describeListFilters,
  describeReportFilters,
  describeSort,
  pageIdentity,
  renderListColumns,
  renderListFilters,
  resolveContext,
} from "../../albanna_ai_chat/public/js/lib/context.mjs";

describe("classifyRoute", () => {
  it("names a form, a list and a report", () => {
    assert.equal(classifyRoute("Form/Sales Invoice/SINV-0001"), "form");
    assert.equal(classifyRoute("List/Sales Order/List"), "list");
    assert.equal(classifyRoute("List/Sales Order/Report"), "report");
    assert.equal(classifyRoute("Query-Report/Accounts Receivable"), "report");
  });

  it("refuses the shapes under List that are neither a list nor a report", () => {
    // A kanban, a calendar, a tree: their filters are not the list's
    // filters, and a widget that read them would describe nothing.
    assert.equal(classifyRoute("List/Sales Order/Calendar"), "other");
    assert.equal(classifyRoute("List/Sales Order/Kanban"), "other");
  });

  it("answers 'other' for workspaces and dashboards", () => {
    assert.equal(classifyRoute("app/sales-order"), "other");
    assert.equal(classifyRoute(""), "other");
  });
});

describe("currentRoute", () => {
  it("joins Frappe v16's array route with slashes, not commas", () => {
    const route = currentRoute({
      window: { frappe: { get_route: () => ["Form", "Sales Invoice", "SINV-0001"] } },
    });
    assert.equal(route, "Form/Sales Invoice/SINV-0001");
  });

  it("passes a string route through", () => {
    assert.equal(
      currentRoute({ window: { frappe: { get_route: () => "List/Issue/List" } } }),
      "List/Issue/List",
    );
  });

  it("answers '' when there is no frappe at all", () => {
    assert.equal(currentRoute({ window: {} }), "");
  });
});

describe("describeListFilters", () => {
  it("reads the quadruples the list view gives, without the doctype", () => {
    const rows = describeListFilters([
      ["Sales Order", "customer", "=", "Albanna"],
      ["Sales Order", "status", "like", "%Open%"],
    ]);
    assert.deepEqual(rows, [
      { field: "customer", op: "=", value: "Albanna" },
      { field: "status", op: "like", value: "%Open%" },
    ]);
  });

  it("drops a filter with no field, and defaults the operator to =", () => {
    const rows = describeListFilters([
      ["Sales Order", "", "=", "x"],
      ["Sales Order", "company", undefined, "Albanna"],
    ]);
    assert.deepEqual(rows, [{ field: "company", op: "=", value: "Albanna" }]);
  });

  it("stops at the cap — the prompt is a context, not a dump", () => {
    const many = Array.from({ length: MAX_LIST_FILTERS + 10 }, (_, i) => [
      "Doc",
      `f${i}`,
      "=",
      String(i),
    ]);
    assert.equal(describeListFilters(many).length, MAX_LIST_FILTERS);
  });

  it("answers [] for a list that cannot say", () => {
    assert.deepEqual(describeListFilters(undefined), []);
    assert.deepEqual(describeListFilters("no"), []);
  });
});

describe("describeReportFilters", () => {
  it("reads the value through the control's method when it has one", () => {
    const rows = describeReportFilters([
      { df: { fieldname: "company" }, get_value: () => "Albanna" },
    ]);
    assert.deepEqual(rows, [{ field: "company", op: "=", value: "Albanna" }]);
  });

  it("a control whose method throws still answers with its value", () => {
    const rows = describeReportFilters([
      { df: { fieldname: "company" }, value: "Albanna", get_value: () => {
        throw new Error("boom");
      } },
    ]);
    assert.deepEqual(rows, [{ field: "company", op: "=", value: "Albanna" }]);
  });

  it("drops a filter with no value — a report ships with most empty", () => {
    assert.deepEqual(
      describeReportFilters([{ df: { fieldname: "company" } }]),
      [],
    );
  });
});

describe("describeListColumns / renderListColumns", () => {
  it("reads the fieldname out of either shape of column", () => {
    assert.deepEqual(describeListColumns([
      { df: { fieldname: "customer" } },
      { fieldname: "status" },
    ]), ["customer", "status"]);
  });

  it("stops at the column cap", () => {
    const many = Array.from({ length: MAX_LIST_COLUMNS + 10 }, (_, i) => ({
      fieldname: `c${i}`,
    }));
    assert.equal(describeListColumns(many).length, MAX_LIST_COLUMNS);
  });

  it("renders on one line, clipped", () => {
    assert.equal(renderListColumns(["a", "b"]), "a, b");
    assert.equal(renderListColumns([]), "");
  });
});

describe("describeSort", () => {
  it("renders the field and the direction, defaulting to desc", () => {
    assert.equal(describeSort("creation", "asc"), "creation asc");
    assert.equal(describeSort("modified"), "modified desc");
    assert.equal(describeSort(""), "");
  });
});

describe("pageIdentity", () => {
  it("a form is form|doctype|name", () => {
    assert.equal(
      pageIdentity({ view: "form", doctype: "Sales Invoice", name: "SINV-0001" }),
      "form|Sales Invoice|SINV-0001",
    );
  });

  it("everything else is its route — the identity does not grow", () => {
    // The description grows with the filters; the identity must not, or
    // the reader's thread would be re-scoped on every filter change.
    assert.equal(pageIdentity({ view: "List/Issue/List" }), "List/Issue/List");
  });

  it("reads the page itself when no context is given", () => {
    const env = {
      window: {
        frappe: { get_route: () => ["Form", "Issue", "ISS-0001"] },
        cur_frm: { doctype: "Issue", doc: { name: "ISS-0001", title: "Broken" } },
      },
    };
    assert.equal(pageIdentity(undefined, env), "form|Issue|ISS-0001");
  });
});

describe("resolveContext", () => {
  it("a form: the route decides, the open document supplies the title", () => {
    const env = {
      window: {
        frappe: { get_route: () => ["Form", "Sales Invoice", "SINV-0001"] },
        cur_frm: {
          doctype: "Sales Invoice",
          doc: { name: "SINV-0001", customer: "Albanna Ltd" },
        },
      },
    };
    const page = resolveContext(env);
    assert.equal(page.view, "form");
    assert.equal(page.doctype, "Sales Invoice");
    assert.equal(page.name, "SINV-0001");
    assert.equal(page.title, "Albanna Ltd");
  });

  it("a stale cur_frm is ignored — the route names a different document", () => {
    // The Desk never clears cur_frm on the way out of a form, so the
    // list the reader walked to still holds the form they left. The
    // route decides: the view is the route, and the stale form's fields
    // do not leak in. The doctype is the live list's to say — with no
    // live list, it is unknown, not borrowed from the stale form.
    const env = {
      window: {
        frappe: { get_route: () => ["List", "Issue", "List"] },
        cur_frm: { doctype: "Sales Invoice", doc: { name: "SINV-0001" } },
      },
    };
    const page = resolveContext(env);
    assert.equal(page.view, "List/Issue/List");
    assert.equal(page.doctype, "");
    assert.equal(page.title, "");
  });

  it("a list: the live list supplies filters, rows and columns", () => {
    const env = {
      window: {
        frappe: { get_route: () => ["List", "Issue", "List"] },
        cur_list: {
          doctype: "Issue",
          total_count: 7,
          sort_by: "modified",
          sort_order: "desc",
          columns: [{ df: { fieldname: "subject" } }],
          get_filters_for_args: () => [["Issue", "status", "=", "Open"]],
        },
      },
    };
    const page = resolveContext(env);
    assert.equal(page.doctype, "Issue");
    assert.equal(page.rows, 7);
    assert.equal(page.filters, "status = Open");
    assert.equal(page.columns, "subject");
    assert.equal(page.sort, "modified desc");
  });

  it("a report: the route decides, the live report supplies its filters", () => {
    const env = {
      window: {
        frappe: {
          get_route: () => ["List", "Sales Order", "Report"],
          query_report: {
            report_name: "Accounts Receivable",
            filters: [{ df: { fieldname: "company" }, value: "Albanna" }],
          },
        },
      },
    };
    const page = resolveContext(env);
    assert.equal(page.report, "Accounts Receivable");
    assert.equal(page.filters, "company = Albanna");
  });

  it("the selection travels with the description", () => {
    const env = {
      window: {
        frappe: { get_route: () => ["List", "Issue", "List"] },
        getSelection: () => "overdue invoices for Albanna",
      },
    };
    assert.equal(resolveContext(env).selection, "overdue invoices for Albanna");
  });
});

describe("currentSelection", () => {
  it("clips to the cap", () => {
    const text = "x".repeat(MAX_SELECTION + 50);
    assert.equal(currentSelection({ window: { getSelection: () => text } }).length, MAX_SELECTION);
  });

  it("a selection shorter than three characters is nothing", () => {
    assert.equal(currentSelection({ window: { getSelection: () => "hi" } }), "");
  });

  it("answers '' when the page cannot say", () => {
    assert.equal(currentSelection({ window: {} }), "");
    assert.equal(currentSelection({ window: { getSelection: () => null } }), "");
  });
});

describe("renderListFilters", () => {
  it("renders the rows as one clipped line", () => {
    const line = renderListFilters([
      { field: "status", op: "=", value: "Open" },
      { field: "company", op: "!=", value: "X" },
    ]);
    assert.equal(line, "status = Open; company != X");
  });
});
