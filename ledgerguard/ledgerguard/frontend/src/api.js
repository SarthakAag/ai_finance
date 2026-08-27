const BASE_URL =
  import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const config = {
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  };

  // Let the browser create the multipart boundary for FormData.
  if (!(options.body instanceof FormData)) {
    config.headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${BASE_URL}${path}`, config);

  const text = await response.text();

  let data = {};

  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  if (!response.ok) {
    throw new Error(
      data?.detail ||
        data?.message ||
        `Request failed (${response.status})`
    );
  }

  return data;
}

// ============================================================
// NORMALIZE RECONCILIATION MATCH
// ============================================================

function normalizeMatch(match = {}) {
  const expected =
    match.expected_amount ??
    match.invoice_amount ??
    match.amount ??
    null;

  const actual =
    match.actual_amount ??
    match.bank_amount ??
    match.gateway_net_amount ??
    match.net_amount ??
    match.gateway_amount ??
    null;

  const variance =
    match.variance_amount ??
    (expected != null && actual != null
      ? Number(expected) - Number(actual)
      : null);

  return {
    ...match,

    // Financial values
    expected_amount: expected,
    actual_amount: actual,

    invoice_amount:
      match.invoice_amount ?? expected,

    gateway_net_amount:
      match.gateway_net_amount ??
      match.net_amount ??
      match.gateway_amount ??
      null,

    bank_amount:
      match.bank_amount ?? null,

    variance_amount: variance,
  };
}

// ============================================================
// NORMALIZE MATCH RESPONSE
// ============================================================

function normalizeMatchesResponse(data) {
  if (Array.isArray(data)) {
    return data.map(normalizeMatch);
  }

  if (Array.isArray(data?.matches)) {
    return data.matches.map(normalizeMatch);
  }

  return [];
}

// ============================================================
// API
// ============================================================

export const api = {
  // ==========================================================
  // HEALTH
  // ==========================================================

  health: () =>
    request("/health"),

  // ==========================================================
  // FILE UPLOADS
  // ==========================================================

  uploadFile: (file, source) => {
    const formData = new FormData();

    formData.append("file", file);

    if (source) {
      formData.append("source", source);
    }

    return request("/uploads", {
      method: "POST",
      body: formData,
    });
  },

  // ==========================================================
  // RECONCILIATION
  // ==========================================================

  runReconciliation: () =>
    request("/reconcile/run", {
      method: "POST",
    }),

  listMatches: async (status = null) => {
    const query = status
      ? `?status=${encodeURIComponent(status)}`
      : "";

    const data = await request(
      `/reconcile/matches${query}`
    );

    return normalizeMatchesResponse(data);
  },

  listExceptions: async () => {
    const data = await request(
      "/reconcile/exceptions"
    );

    return normalizeMatchesResponse(data);
  },

  // ==========================================================
  // DASHBOARD
  // ==========================================================

  dashboardStats: () =>
    request("/dashboard/stats"),

  dashboardRiskSignals: () =>
    request("/dashboard/risk-signals"),

  dashboardCostComparison: () =>
    request("/dashboard/cost-comparison"),

  // ==========================================================
  // REVIEW / HUMAN TICKETS
  // ==========================================================

  listTickets: async () => {
    return request("/review/tickets");
  },

  getTicket: (ticketId) => {
    if (!ticketId) {
      throw new Error("Missing ticket ID.");
    }

    return request(
      `/review/tickets/${encodeURIComponent(
        String(ticketId)
      )}`
    );
  },

  reviewSummary: () =>
    request("/review/summary"),

  // ==========================================================
  // AI AGENT
  // ==========================================================

  resolveExample: async (matchId) => {
    if (!matchId) {
      throw new Error(
        "Missing reconciliation match ID."
      );
    }

    const safeId = encodeURIComponent(
      String(matchId)
    );

    console.log(
      "[AI] POST /agent/resolve/",
      safeId
    );

    return request(
      `/agent/resolve/${safeId}`,
      {
        method: "POST",
      }
    );
  },

  resolveAll: () =>
    request("/agent/resolve-all", {
      method: "POST",
    }),

  getTrace: (matchId) => {
    if (!matchId) {
      throw new Error(
        "Missing reconciliation match ID."
      );
    }

    const safeId = encodeURIComponent(
      String(matchId)
    );

    return request(
      `/agent/trace/${safeId}`
    );
  },

  // ==========================================================
  // WORKSPACE
  // ==========================================================

  resetWorkspace: () =>
    request("/workspace/reset", {
      method: "POST",
    }),

  // ==========================================================
  // REFRESH DASHBOARD
  // ==========================================================

  refreshDashboard: async () => {
    const [
      stats,
      matches,
      exceptions,
      tickets,
    ] = await Promise.all([
      api.dashboardStats(),
      api.listMatches(),
      api.listExceptions(),
      api.listTickets(),
    ]);

    return {
      stats,
      matches,
      exceptions,
      tickets,
    };
  },
};

// ============================================================
// DEFAULT EXPORT
// ============================================================

export default api;