import { useEffect, useMemo, useState } from "react";
import { api } from "./api";

const SOURCES = [
  { key: "invoice", label: "Invoices", description: "Invoice / ERP transactions", icon: "📄" },
  { key: "razorpay", label: "Razorpay", description: "Gateway settlements", icon: "💳" },
  { key: "bank", label: "Bank", description: "Bank statement / credits", icon: "🏦" },
];

const NAV = [
  ["overview", "⌂", "Dashboard"],
  ["bills", "▤", "Bill Explorer"],
  ["matches", "✓", "Reconciliation"],
  ["exceptions", "⚠", "Exceptions"],
  ["tickets", "▣", "Review Queue"],
];

function getArray(data, keys = []) {
  if (Array.isArray(data)) return data;
  for (const key of keys) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
}

function getNumber(data, keys = [], fallback = 0) {
  for (const key of keys) {
    const value = data?.[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "") {
      const number = Number(value);
      if (Number.isFinite(number)) return number;
    }
  }
  return fallback;
}

function money(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(number);
}

function number(value) {
  const n = Number(value);
  return Number.isFinite(n) ? new Intl.NumberFormat("en-IN").format(n) : "0";
}

function dateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function status(value) {
  return String(value || "PENDING")
    .trim()
    .toUpperCase()
    .replaceAll(" ", "_");
}

function stage(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replaceAll(" ", "_");
}

function financials(record = {}) {
  const finite = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };

  const expected =
    finite(record.expected_amount) ??
    finite(record.invoice_amount) ??
    finite(record.amount) ??
    finite(record.gross_amount);

  const gateway =
    finite(record.gateway_net_amount) ??
    finite(record.net_amount) ??
    finite(record.gateway_amount) ??
    finite(record.settlement_amount);

  const bank =
    finite(record.bank_amount) ??
    finite(record.bank_credit_amount) ??
    finite(record.bank_credit);

  const actual = bank ?? gateway;

  const stored = finite(record.variance_amount);
  const calculated =
    expected !== null && actual !== null
      ? Number((expected - actual).toFixed(2))
      : null;

  return {
    expected,
    gateway,
    bank,
    actual,
    variance: calculated ?? stored,
  };
}

function varianceExplanation(record = {}) {
  const f = financials(record);

  if (f.expected === null || f.actual === null) {
    return "The evidence is incomplete. The agent needs an invoice amount and a gateway or bank amount before it can calculate a financial difference.";
  }

  if (Math.abs(f.variance ?? 0) < 0.01) {
    return `The invoice and settlement agree at ${money(f.expected)}. No financial variance was detected.`;
  }

  const difference = Math.abs(f.variance);
  const direction =
    f.variance > 0
      ? `the settlement is lower than the invoice by ${money(difference)}`
      : `the settlement is higher than the invoice by ${money(difference)}`;

  if (
    f.gateway !== null &&
    f.bank !== null &&
    Math.abs(f.gateway - f.bank) >= 0.01
  ) {
    return `The invoice is ${money(f.expected)}, the gateway net is ${money(
      f.gateway
    )}, and the bank credit is ${money(
      f.bank
    )}. Therefore ${direction}. The gateway-to-bank difference should be checked for settlement timing, fees, reversals, or a missing bank entry.`;
  }

  if (record.variance_reason) {
    return `The invoice is ${money(f.expected)} and the actual settlement is ${money(
      f.actual
    )}. Therefore ${direction}. Recorded reason: ${record.variance_reason}.`;
  }

  return `The invoice is ${money(f.expected)} and the actual settlement is ${money(
    f.actual
  )}. Therefore ${direction}. The next checks should cover fees, settlement timing, partial payments, FX differences, reversals, or missing records.`;
}

function badgeClass(value) {
  const s = status(value);
  if (["MATCHED", "RECONCILED", "RESOLVED"].includes(s)) {
    return "border-emerald-400/20 bg-emerald-500/10 text-emerald-300";
  }
  if (["ESCALATED", "EXCEPTION", "FAILED"].includes(s)) {
    return "border-rose-400/20 bg-rose-500/10 text-rose-300";
  }
  if (["AI_REVIEW", "ML_REVIEW"].includes(s)) {
    return "border-violet-400/20 bg-violet-500/10 text-violet-300";
  }
  return "border-amber-400/20 bg-amber-500/10 text-amber-300";
}

function StatusBadge({ value }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${badgeClass(
        value
      )}`}
    >
      {status(value).replaceAll("_", " ")}
    </span>
  );
}

function Card({ children, className = "" }) {
  return (
    <div
      className={`rounded-2xl border border-white/10 bg-slate-900/70 shadow-xl shadow-black/10 backdrop-blur ${className}`}
    >
      {children}
    </div>
  );
}

function Kpi({ label, value, sub, icon, tone = "violet" }) {
  const tones = {
    violet: "from-violet-500/20 to-indigo-500/5 text-violet-300",
    emerald: "from-emerald-500/20 to-teal-500/5 text-emerald-300",
    amber: "from-amber-500/20 to-orange-500/5 text-amber-300",
    rose: "from-rose-500/20 to-red-500/5 text-rose-300",
  };

  return (
    <Card className="overflow-hidden">
      <div className={`bg-gradient-to-br p-5 ${tones[tone]}`}>
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              {label}
            </p>
            <p className="mt-2 text-3xl font-black text-white">{value}</p>
            <p className="mt-1 text-xs text-slate-400">{sub}</p>
          </div>
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/5 text-xl">
            {icon}
          </div>
        </div>
      </div>
    </Card>
  );
}

function UploadCard({ source, file, uploading, result, error, onFile, onUpload }) {
  return (
    <Card className="p-5">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/5 text-xl">
          {source.icon}
        </div>
        <div>
          <h3 className="font-bold text-white">{source.label}</h3>
          <p className="text-xs text-slate-500">{source.description}</p>
        </div>
        {result && <span className="ml-auto text-emerald-400">✓</span>}
      </div>

      <label className="mt-4 flex min-h-24 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-white/15 bg-white/[0.03] p-3 text-center hover:border-violet-400/50">
        <input
          type="file"
          accept=".xlsx,.xls,.csv,.pdf"
          className="hidden"
          onChange={(e) => {
            const selected = e.target.files?.[0];
            if (selected) onFile(source.key, selected);
          }}
        />
        <span className="text-xs font-semibold text-slate-300">
          {file ? file.name : "Choose Excel / CSV / PDF"}
        </span>
        <span className="mt-1 text-[11px] text-slate-500">Click to browse</span>
      </label>

      {file && !result && (
        <button
          onClick={() => onUpload(source.key)}
          disabled={uploading}
          className="mt-3 w-full rounded-xl bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2.5 text-xs font-bold text-white hover:brightness-110 disabled:opacity-50"
        >
          {uploading ? "Uploading..." : `Upload ${source.label}`}
        </button>
      )}

      {result && (
        <div className="mt-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs text-emerald-300">
          <div className="font-bold">Upload successful</div>
          <div className="mt-1">
            {number(
              result.rows_read ??
                result.rows ??
                result.total_rows ??
                result.transactions ??
                0
            )}{" "}
            rows processed
          </div>
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-xl border border-rose-500/20 bg-rose-500/5 p-3 text-xs text-rose-300">
          {error}
        </div>
      )}
    </Card>
  );
}

function Pipeline({ total, matched, ml, ai, escalated }) {
  const rows = [
    ["Matched", matched],
    ["ML Review", ml],
    ["AI Review", ai],
    ["Escalated", escalated],
  ];

  return (
    <Card className="p-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
          Reconciliation flow
        </p>
        <h3 className="mt-1 text-lg font-bold text-white">Transaction Pipeline</h3>
      </div>

      <div className="mt-6 space-y-5">
        <div>
          <div className="mb-2 flex justify-between text-xs">
            <span className="text-slate-400">Total transactions</span>
            <strong className="text-white">{number(total)}</strong>
          </div>
          <div className="h-2 rounded-full bg-white/5">
            <div className="h-full w-full rounded-full bg-violet-500" />
          </div>
        </div>

        {rows.map(([label, value]) => {
          const pct = total > 0 ? Math.min(100, (value / total) * 100) : 0;
          return (
            <div key={label}>
              <div className="mb-2 flex justify-between text-xs">
                <span className="text-slate-400">{label}</span>
                <strong className="text-white">{number(value)}</strong>
              </div>
              <div className="h-2 rounded-full bg-white/5">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function ThreeWay({ record }) {
  const f = financials(record);
  const items = [
    ["Invoice", f.expected, "📄"],
    ["Gateway", f.gateway, "💳"],
    ["Bank", f.bank, "🏦"],
  ];

  return (
    <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
      <p className="text-xs font-bold uppercase tracking-wider text-violet-300">
        Three-way financial evidence
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {items.map(([label, value, icon], index) => (
          <div key={label} className="relative">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <div className="text-lg">{icon}</div>
              <p className="mt-2 text-[11px] font-bold uppercase text-slate-500">
                {label}
              </p>
              <p className="mt-1 text-lg font-black text-white">
                {money(value)}
              </p>
            </div>
            {index < 2 && (
              <span className="absolute -right-2 top-1/2 z-10 hidden -translate-y-1/2 rounded-full bg-slate-800 px-1.5 text-slate-400 md:block">
                →
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function MatchTable({ matches, onSelect, onResolve, loading }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-white/10 bg-white/[0.02]">
          <tr>
            {["Order", "Expected", "Actual", "Variance", "Stage", "Status", "Action"].map(
              (head) => (
                <th
                  key={head}
                  className="px-5 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500"
                >
                  {head}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {matches.map((match, index) => {
            const f = financials(match);
            const id = match.id || match.match_id;
            const variance = f.variance;
            const review =
              stage(match.match_stage).includes("review") ||
              status(match.status) === "ESCALATED";

            return (
              <tr key={id || index} className="hover:bg-white/[0.02]">
                <td className="px-5 py-4">
                  <button
                    onClick={() => onSelect(match)}
                    className="font-bold text-white hover:text-violet-300"
                  >
                    {match.order_id || "Unknown"}
                  </button>
                </td>
                <td className="px-5 py-4 text-slate-400">{money(f.expected)}</td>
                <td className="px-5 py-4 text-slate-400">{money(f.actual)}</td>
                <td
                  className={`px-5 py-4 font-bold ${
                    variance === null
                      ? "text-slate-500"
                      : variance < 0
                      ? "text-rose-400"
                      : variance > 0
                      ? "text-amber-400"
                      : "text-emerald-400"
                  }`}
                >
                  {money(variance)}
                </td>
                <td className="px-5 py-4 text-xs uppercase tracking-wide text-slate-500">
                  {stage(match.match_stage).replaceAll("_", " ") || "—"}
                </td>
                <td className="px-5 py-4">
                  <StatusBadge value={match.status} />
                </td>
                <td className="px-5 py-4">
                  {review && id ? (
                    <button
                      onClick={() => onResolve(id)}
                      disabled={loading[id]}
                      className="rounded-lg bg-violet-600 px-3 py-2 text-xs font-bold text-white hover:bg-violet-500 disabled:opacity-50"
                    >
                      {loading[id] ? "Investigating..." : "AI Investigate"}
                    </button>
                  ) : (
                    <button
                      onClick={() => onSelect(match)}
                      className="rounded-lg border border-white/10 px-3 py-2 text-xs font-bold text-slate-300 hover:bg-white/5"
                    >
                      Details
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ExceptionCard({ item, onResolve, loading }) {
  const id = item.id || item.match_id;
  const f = financials(item);
  const risk =
    Number(item.risk_score ?? item.risk ?? item.confidence ?? 72) <= 1
      ? Number(item.risk_score ?? item.risk ?? item.confidence ?? 0) * 100
      : Number(item.risk_score ?? item.risk ?? 72);

  return (
    <Card className="overflow-hidden border-rose-500/20">
      <div className="flex flex-col gap-4 p-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-violet-400">
            Risk queue
          </p>
          <h3 className="mt-1 text-lg font-bold text-white">
            {item.order_id || "Unknown Order"}
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge value={item.status || "EXCEPTION"} />
            <span className="rounded-full bg-rose-500/10 px-2.5 py-1 text-[11px] font-bold text-rose-300">
              Risk {Math.round(Math.min(100, Math.max(0, risk)))}
            </span>
          </div>
        </div>

        {id && (
          <button
            onClick={() => onResolve(id)}
            disabled={loading}
            className="rounded-xl bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2.5 text-xs font-bold text-white hover:brightness-110 disabled:opacity-50"
          >
            {loading ? "Investigating..." : "Run AI Investigation"}
          </button>
        )}
      </div>

      <div className="mx-5 mb-5 rounded-xl bg-white/[0.03] p-4">
        <p className="text-xs leading-5 text-slate-400">
          {item.variance_reason ||
            item.reason ||
            item.message ||
            "This transaction could not be automatically reconciled."}
        </p>
      </div>

      <div className="grid gap-3 border-t border-white/5 p-5 sm:grid-cols-3">
        <Metric label="Expected" value={money(f.expected)} />
        <Metric label="Actual" value={money(f.actual)} />
        <Metric label="Variance" value={money(f.variance)} />
      </div>
    </Card>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
      <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
        {label}
      </p>
      <p className="mt-1 text-sm font-bold text-white">{value}</p>
    </div>
  );
}

function TicketTable({ tickets, onSelect }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-white/10">
          <tr>
            {["Order", "Subject", "Amount", "Status", "Created"].map((head) => (
              <th
                key={head}
                className="px-5 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500"
              >
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {tickets.map((ticket, index) => (
            <tr
              key={ticket.id || ticket.ticket_id || index}
              onClick={() => onSelect?.(ticket)}
              className="cursor-pointer hover:bg-white/[0.02]"
            >
              <td className="px-5 py-4 font-bold text-white">
                {ticket.order_id || "—"}
              </td>
              <td className="max-w-sm px-5 py-4 text-slate-400">
                {ticket.subject || "Reconciliation exception"}
              </td>
              <td className="px-5 py-4 text-slate-400">
                {money(ticket.expected_amount)}
              </td>
              <td className="px-5 py-4">
                <StatusBadge
                  value={ticket.status || (ticket.resolved ? "RESOLVED" : "ESCALATED")}
                />
              </td>
              <td className="px-5 py-4 text-xs text-slate-500">
                {dateTime(ticket.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MatchModal({ match, onClose, onResolve, loading, message }) {
  const id = match.id || match.match_id;
  const f = financials(match);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-3xl border border-white/10 bg-slate-950 shadow-2xl">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-white/10 bg-slate-950/95 p-6 backdrop-blur">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-violet-400">
              Bill investigation
            </p>
            <h2 className="mt-1 text-2xl font-black text-white">
              {match.order_id || "Transaction Details"}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-xl px-3 py-2 text-xl text-slate-500 hover:bg-white/5 hover:text-white"
          >
            ×
          </button>
        </div>

        <div className="space-y-5 p-6">
          <div className="flex items-center justify-between">
            <StatusBadge value={match.status} />
            <span className="text-xs text-slate-500">{dateTime(match.created_at)}</span>
          </div>

          <ThreeWay record={match} />

          <div className="grid gap-3 sm:grid-cols-3">
            <Metric label="Invoice / Expected" value={money(f.expected)} />
            <Metric label="Actual Settlement" value={money(f.actual)} />
            <Metric label="Variance" value={money(f.variance)} />
          </div>

          <div className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-5">
            <div className="flex gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-600 text-white">
                ✦
              </div>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-violet-300">
                  AI Agent Explanation
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-300">
                  {varianceExplanation(match)}
                </p>
              </div>
            </div>
          </div>

          {match.variance_reason && (
            <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wider text-amber-300">
                Recorded reason
              </p>
              <p className="mt-2 text-sm text-amber-100">{match.variance_reason}</p>
            </div>
          )}

          {message && (
            <div
              className={`rounded-xl p-3 text-sm ${
                message.type === "success"
                  ? "bg-emerald-500/10 text-emerald-300"
                  : "bg-rose-500/10 text-rose-300"
              }`}
            >
              {message.text}
            </div>
          )}

          {id && (
            <button
              onClick={() => onResolve(id)}
              disabled={loading}
              className="w-full rounded-xl bg-gradient-to-r from-indigo-500 to-violet-600 px-5 py-3 text-sm font-bold text-white hover:brightness-110 disabled:opacity-50"
            >
              {loading ? "AI Agent Investigating..." : "Run AI Investigation"}
            </button>
          )}

          <details className="rounded-2xl border border-white/10 bg-black/10">
            <summary className="cursor-pointer px-4 py-3 text-sm font-bold text-slate-300">
              Raw reconciliation data
            </summary>
            <pre className="max-h-72 overflow-auto p-4 text-xs leading-5 text-slate-500">
              {JSON.stringify(match, null, 2)}
            </pre>
          </details>
        </div>
      </div>
    </div>
  );
}

function Empty({ text }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] p-10 text-center">
      <div className="text-3xl">◌</div>
      <p className="mt-3 text-sm text-slate-500">{text}</p>
    </div>
  );
}

export default function App() {
  const [dark, setDark] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  const [files, setFiles] = useState({
    invoice: null,
    razorpay: null,
    bank: null,
  });
  const [uploadResults, setUploadResults] = useState({});
  const [uploadErrors, setUploadErrors] = useState({});
  const [uploading, setUploading] = useState({});

  const [stats, setStats] = useState({});
  const [matches, setMatches] = useState([]);
  const [exceptions, setExceptions] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [riskSignals, setRiskSignals] = useState([]);
  const [costComparison, setCostComparison] = useState({});

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState(null);

  const [agentLoading, setAgentLoading] = useState({});
  const [agentMessages, setAgentMessages] = useState({});
  const [selectedMatch, setSelectedMatch] = useState(null);

  useEffect(() => {
    const saved = localStorage.getItem("ledgerguard-theme");
    if (saved === "light") setDark(false);
  }, []);

  useEffect(() => {
    localStorage.setItem("ledgerguard-theme", dark ? "dark" : "light");
  }, [dark]);

  const loadDashboard = async () => {
    setError("");
    setLoading(true);

    try {
      const results = await Promise.allSettled([
        api.dashboardStats(),
        api.listMatches(),
        api.listExceptions(),
        api.listTickets(),
        api.dashboardRiskSignals?.(),
        api.dashboardCostComparison?.(),
      ]);

      const [statsResult, matchesResult, exceptionsResult, ticketsResult, riskResult, costResult] =
        results;

      if (statsResult.status === "fulfilled") {
        setStats(statsResult.value?.stats || statsResult.value?.data || statsResult.value || {});
      }

      if (matchesResult.status === "fulfilled") {
        setMatches(
          getArray(matchesResult.value, ["matches", "data", "results"])
        );
      }

      if (exceptionsResult.status === "fulfilled") {
        setExceptions(
          getArray(exceptionsResult.value, [
            "exceptions",
            "matches",
            "data",
            "results",
          ])
        );
      }

      if (ticketsResult.status === "fulfilled") {
        setTickets(getArray(ticketsResult.value, ["tickets", "data", "results"]));
      }

      if (riskResult?.status === "fulfilled") {
        setRiskSignals(getArray(riskResult.value, ["signals", "risk_signals", "data"]));
      }

      if (costResult?.status === "fulfilled") {
        setCostComparison(costResult.value?.data || costResult.value || {});
      }

      const failed = results.find((item) => item.status === "rejected");
      if (failed && statsResult.status === "rejected" && matchesResult.status === "rejected") {
        throw failed.reason;
      }
    } catch (e) {
      setError(e?.message || "Unable to load dashboard.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, []);

  const handleFile = (source, file) => {
    setFiles((prev) => ({ ...prev, [source]: file }));
    setUploadResults((prev) => ({ ...prev, [source]: null }));
    setUploadErrors((prev) => ({ ...prev, [source]: null }));
  };

  const handleUpload = async (source) => {
    const file = files[source];
    if (!file) return;

    setUploading((prev) => ({ ...prev, [source]: true }));
    setUploadErrors((prev) => ({ ...prev, [source]: null }));

    try {
      const result = await api.uploadFile(file, source);
      setUploadResults((prev) => ({ ...prev, [source]: result }));
      await loadDashboard();
    } catch (e) {
      setUploadErrors((prev) => ({
        ...prev,
        [source]: e?.message || "Upload failed.",
      }));
    } finally {
      setUploading((prev) => ({ ...prev, [source]: false }));
    }
  };

  const runReconciliation = async () => {
    if (running) return;

    setRunning(true);
    setMessage(null);

    try {
      const result = await api.runReconciliation();
      const count =
        result?.matches_created ??
        result?.matches ??
        result?.total_matches ??
        result?.count;

      setMessage({
        type: "success",
        text:
          count != null
            ? `Reconciliation completed. ${count} match records processed.`
            : "Reconciliation completed successfully.",
      });

      await loadDashboard();
      setActiveTab("overview");
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.message || "Reconciliation failed.",
      });
    } finally {
      setRunning(false);
    }
  };

  const resolveMatch = async (matchId) => {
    if (!matchId || agentLoading[matchId]) return;

    const current = matches.find(
      (item) => String(item.id || item.match_id) === String(matchId)
    );

    if (!current) {
      await loadDashboard();
      return;
    }

    setAgentLoading((prev) => ({ ...prev, [matchId]: true }));
    setAgentMessages((prev) => ({ ...prev, [matchId]: null }));

    try {
      const result = await api.resolveExample(matchId);
      setAgentMessages((prev) => ({
        ...prev,
        [matchId]: {
          type: "success",
          text: result?.final_status
            ? `AI agent completed: ${result.final_status}`
            : "AI agent completed successfully.",
        },
      }));
      await loadDashboard();
    } catch (e) {
      setAgentMessages((prev) => ({
        ...prev,
        [matchId]: {
          type: "error",
          text: e?.message || "AI investigation failed.",
        },
      }));
    } finally {
      setAgentLoading((prev) => {
        const next = { ...prev };
        delete next[matchId];
        return next;
      });
    }
  };

  const calculated = useMemo(() => {
    const matched = matches.filter((m) =>
      ["MATCHED", "RECONCILED"].includes(status(m.status))
    ).length;

    const escalated = matches.filter(
      (m) => status(m.status) === "ESCALATED"
    ).length;

    const ml = matches.filter((m) =>
      ["ml_ai_review", "ml_review"].includes(stage(m.match_stage))
    ).length;

    const ai = matches.filter(
      (m) =>
        stage(m.match_stage) === "ai_review" ||
        status(m.status) === "AI_REVIEW"
    ).length;

    const total =
      getNumber(stats, [
        "total",
        "total_transactions",
        "transactions",
        "total_matches",
        "count",
      ]) || matches.length;

    const exceptionCount =
      getNumber(stats, [
        "exceptions",
        "exception_count",
        "unmatched",
        "unmatched_count",
      ]) || exceptions.length;

    const varianceTotal = matches.reduce((sum, item) => {
      const v = financials(item).variance;
      return sum + (v == null ? 0 : Math.abs(v));
    }, 0);

    return {
      total,
      matched:
        getNumber(stats, ["matched", "reconciled", "matched_count", "reconciled_count"]) ||
        matched,
      escalated:
        getNumber(stats, ["escalated", "escalated_count"]) || escalated,
      ml,
      ai,
      exceptionCount,
      humanReview:
        getNumber(stats, ["human_review", "human_review_count", "review_count"]) ||
        tickets.length,
      varianceTotal,
    };
  }, [stats, matches, exceptions, tickets]);

  const uploadCount = SOURCES.filter((source) => uploadResults[source.key]).length;
  const allUploaded = uploadCount === SOURCES.length;

  const shell = dark
    ? "min-h-screen bg-[#070b14] text-white"
    : "min-h-screen bg-slate-100 text-slate-900";

  const sidebar = dark
    ? "border-white/10 bg-[#0a101d]"
    : "border-slate-200 bg-white";

  return (
    <div className={shell}>
      <header
        className={`sticky top-0 z-40 border-b backdrop-blur-xl ${
          dark
            ? "border-white/10 bg-[#070b14]/90"
            : "border-slate-200 bg-white/90"
        }`}
      >
        <div className="flex h-16 items-center justify-between px-5 lg:px-7">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 font-black text-white shadow-lg">
              LG
            </div>
            <div>
              <h1 className="font-black tracking-tight">LedgerGuard</h1>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">
                Reconciliation OS
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-bold text-emerald-300 sm:block">
              ● Backend Connected
            </span>
            <button
              onClick={() => setDark((prev) => !prev)}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-bold text-slate-300 hover:bg-white/10"
            >
              {dark ? "☀ Light" : "◐ Dark"}
            </button>
            <button
              onClick={loadDashboard}
              disabled={loading}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-bold text-slate-300 hover:bg-white/10 disabled:opacity-50"
            >
              {loading ? "Refreshing..." : "↻ Refresh"}
            </button>
          </div>
        </div>
      </header>

      <div className="flex">
        <aside
          className={`sticky top-16 hidden h-[calc(100vh-4rem)] w-64 shrink-0 border-r p-4 lg:block ${sidebar}`}
        >
          <div className="rounded-2xl border border-violet-500/20 bg-gradient-to-br from-violet-500/15 to-indigo-500/5 p-4">
            <p className="text-[10px] font-bold uppercase tracking-wider text-violet-300">
              Workspace
            </p>
            <p className="mt-1 font-bold">Finance Operations</p>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              Reconcile invoices, gateway settlements and bank credits in one control center.
            </p>
          </div>

          <nav className="mt-5 space-y-1">
            {NAV.map(([key, icon, label]) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-bold transition ${
                  activeTab === key
                    ? "bg-gradient-to-r from-indigo-500/20 to-violet-500/10 text-violet-200 ring-1 ring-violet-500/20"
                    : "text-slate-500 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span className="w-5 text-center">{icon}</span>
                {label}
              </button>
            ))}
          </nav>

          <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.02] p-4">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
              System status
            </p>
            <div className="mt-3 flex items-center gap-2 text-xs text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,.8)]" />
              Backend healthy
            </div>
            <p className="mt-2 text-xs text-slate-500">{uploadCount}/3 sources uploaded</p>
          </div>
        </aside>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mb-5 flex gap-2 overflow-x-auto lg:hidden">
            {NAV.map(([key, , label]) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`whitespace-nowrap rounded-xl px-4 py-2 text-xs font-bold ${
                  activeTab === key
                    ? "bg-violet-600 text-white"
                    : "border border-white/10 bg-white/5 text-slate-400"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <section className="mb-6 overflow-hidden rounded-3xl border border-violet-500/20 bg-gradient-to-br from-slate-950 via-indigo-950/70 to-violet-950/60 p-6 shadow-2xl shadow-violet-950/20 lg:p-8">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.2em] text-violet-300">
                  Finance control center
                </p>
                <h2 className="mt-2 text-3xl font-black tracking-tight sm:text-4xl">
                  See where every rupee went.
                </h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                  Upload invoice, Razorpay and bank data. LedgerGuard reconciles the
                  three sources, calculates financial variance, scores exceptions and
                  gives reviewers an evidence-first AI investigation.
                </p>
              </div>

              <button
                onClick={runReconciliation}
                disabled={running || !allUploaded}
                className="shrink-0 rounded-2xl bg-white px-6 py-4 text-sm font-black text-slate-950 shadow-xl hover:bg-violet-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {running ? "⟳ Running..." : "▶ Run Reconciliation"}
              </button>
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              {SOURCES.map((source) => (
                <span
                  key={source.key}
                  className={`rounded-full border px-3 py-1.5 text-[11px] font-bold ${
                    uploadResults[source.key]
                      ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-300"
                      : "border-white/10 bg-white/5 text-slate-500"
                  }`}
                >
                  {uploadResults[source.key] ? "✓" : "○"} {source.label}
                </span>
              ))}
            </div>
          </section>

          {error && (
            <div className="mb-5 rounded-2xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm text-rose-300">
              <strong>Dashboard error:</strong> {error}
            </div>
          )}

          {message && (
            <div
              className={`mb-5 rounded-2xl border p-4 text-sm ${
                message.type === "success"
                  ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-300"
                  : "border-rose-500/20 bg-rose-500/5 text-rose-300"
              }`}
            >
              {message.type === "success" ? "✓ " : "⚠ "}
              {message.text}
            </div>
          )}

          {activeTab === "overview" && (
            <>
              <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <Kpi
                  label="Transactions"
                  value={number(calculated.total)}
                  sub="Records processed"
                  icon="◈"
                />
                <Kpi
                  label="Reconciled"
                  value={number(calculated.matched)}
                  sub="Successful matches"
                  icon="✓"
                  tone="emerald"
                />
                <Kpi
                  label="Exceptions"
                  value={number(calculated.exceptionCount)}
                  sub="Need attention"
                  icon="⚠"
                  tone="amber"
                />
                <Kpi
                  label="Variance Exposure"
                  value={money(calculated.varianceTotal)}
                  sub="Absolute financial difference"
                  icon="₹"
                  tone="rose"
                />
              </section>

              <section className="mt-6 grid gap-6 xl:grid-cols-2">
                <Pipeline
                  total={calculated.total}
                  matched={calculated.matched}
                  ml={calculated.ml}
                  ai={calculated.ai}
                  escalated={calculated.escalated}
                />

                <Card className="p-6">
                  <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                    AI investigation
                  </p>
                  <h3 className="mt-1 text-lg font-bold text-white">
                    How the agent explains a bill
                  </h3>
                  <p className="mt-3 text-sm leading-6 text-slate-400">
                    The agent does not simply say “failed”. It starts from the
                    invoice amount, compares gateway settlement and bank credit,
                    calculates the actual variance, checks the recorded reason and
                    explains what evidence the reviewer should inspect next.
                  </p>

                  <div className="mt-5 grid gap-3 sm:grid-cols-3">
                    {[
                      ["01", "Compare", "Invoice vs gateway vs bank"],
                      ["02", "Explain", "Amount and root-cause evidence"],
                      ["03", "Resolve", "Close or escalate with context"],
                    ].map(([n, title, desc]) => (
                      <div
                        key={n}
                        className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
                      >
                        <p className="text-[10px] font-black text-violet-400">{n}</p>
                        <p className="mt-1 text-sm font-bold text-white">{title}</p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">{desc}</p>
                      </div>
                    ))}
                  </div>
                </Card>
              </section>

              <section className="mt-6">
                <Card>
                  <div className="flex items-center justify-between border-b border-white/10 p-5">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                        Live reconciliation
                      </p>
                      <h3 className="mt-1 text-lg font-bold text-white">
                        Latest transactions
                      </h3>
                    </div>
                    <button
                      onClick={() => setActiveTab("matches")}
                      className="text-xs font-bold text-violet-300 hover:text-violet-200"
                    >
                      View all →
                    </button>
                  </div>
                  {matches.length ? (
                    <MatchTable
                      matches={matches.slice(0, 8)}
                      onSelect={setSelectedMatch}
                      onResolve={resolveMatch}
                      loading={agentLoading}
                    />
                  ) : (
                    <div className="p-5">
                      <Empty text="Upload the three source files and run reconciliation." />
                    </div>
                  )}
                </Card>
              </section>
            </>
          )}

          {activeTab === "bills" && (
            <section>
              <div className="mb-5">
                <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                  Bill explorer
                </p>
                <h2 className="mt-1 text-2xl font-black">Full financial evidence</h2>
                <p className="mt-2 text-sm text-slate-500">
                  Click any bill to inspect the invoice, gateway settlement, bank credit,
                  variance and AI explanation.
                </p>
              </div>

              <div className="grid gap-4">
                {matches.length ? (
                  matches.map((match, index) => {
                    const f = financials(match);
                    return (
                      <Card key={match.id || match.match_id || index} className="p-5">
                        <div className="flex flex-col gap-5 xl:flex-row xl:items-center">
                          <div className="min-w-48">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-violet-400">
                              Order
                            </p>
                            <p className="mt-1 font-black text-white">
                              {match.order_id || "Unknown"}
                            </p>
                            <div className="mt-2">
                              <StatusBadge value={match.status} />
                            </div>
                          </div>

                          <div className="grid flex-1 gap-3 sm:grid-cols-3">
                            <Metric label="Invoice" value={money(f.expected)} />
                            <Metric label="Gateway" value={money(f.gateway)} />
                            <Metric label="Bank" value={money(f.bank)} />
                          </div>

                          <div className="xl:w-52">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                              Variance
                            </p>
                            <p
                              className={`mt-1 text-xl font-black ${
                                f.variance === null
                                  ? "text-slate-500"
                                  : f.variance === 0
                                  ? "text-emerald-400"
                                  : "text-rose-400"
                              }`}
                            >
                              {money(f.variance)}
                            </p>
                            <button
                              onClick={() => setSelectedMatch(match)}
                              className="mt-2 text-xs font-bold text-violet-300"
                            >
                              Open investigation →
                            </button>
                          </div>
                        </div>
                      </Card>
                    );
                  })
                ) : (
                  <Empty text="No bills available yet." />
                )}
              </div>
            </section>
          )}

          {activeTab === "matches" && (
            <section>
              <div className="mb-5">
                <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                  Reconciliation
                </p>
                <h2 className="mt-1 text-2xl font-black">Match ledger</h2>
              </div>
              <Card>
                {matches.length ? (
                  <MatchTable
                    matches={matches}
                    onSelect={setSelectedMatch}
                    onResolve={resolveMatch}
                    loading={agentLoading}
                  />
                ) : (
                  <div className="p-5">
                    <Empty text="No reconciliation records found." />
                  </div>
                )}
              </Card>
            </section>
          )}

          {activeTab === "exceptions" && (
            <section>
              <div className="mb-5">
                <p className="text-xs font-bold uppercase tracking-wider text-rose-400">
                  Risk queue
                </p>
                <h2 className="mt-1 text-2xl font-black">Exceptions that need attention</h2>
                <p className="mt-2 text-sm text-slate-500">
                  Prioritize high-risk financial discrepancies before close.
                </p>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                {exceptions.length ? (
                  exceptions.map((item, index) => (
                    <ExceptionCard
                      key={item.id || item.match_id || item.order_id || index}
                      item={item}
                      onResolve={resolveMatch}
                      loading={agentLoading[item.id || item.match_id]}
                    />
                  ))
                ) : (
                  <div className="xl:col-span-2">
                    <Empty text="No reconciliation exceptions." />
                  </div>
                )}
              </div>

              {riskSignals.length > 0 && (
                <Card className="mt-6 p-5">
                  <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                    Risk signals
                  </p>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    {riskSignals.slice(0, 6).map((signal, index) => (
                      <div
                        key={signal.id || index}
                        className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
                      >
                        <p className="font-bold text-white">
                          {signal.title || signal.name || "Risk signal"}
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">
                          {signal.description || signal.reason || JSON.stringify(signal)}
                        </p>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </section>
          )}

          {activeTab === "tickets" && (
            <section>
              <div className="mb-5">
                <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                  Human review
                </p>
                <h2 className="mt-1 text-2xl font-black">Review queue</h2>
                <p className="mt-2 text-sm text-slate-500">
                  Escalated cases that require a human decision.
                </p>
              </div>
              <Card>
                {tickets.length ? (
                  <TicketTable tickets={tickets} onSelect={setSelectedMatch} />
                ) : (
                  <div className="p-5">
                    <Empty text="No human-review tickets." />
                  </div>
                )}
              </Card>
            </section>
          )}

          <section className="mt-8">
            <div className="mb-4">
              <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                Data ingestion
              </p>
              <h2 className="mt-1 text-xl font-black">Source files</h2>
              <p className="mt-1 text-xs text-slate-500">
                Upload all three sources before running reconciliation.
              </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              {SOURCES.map((source) => (
                <UploadCard
                  key={source.key}
                  source={source}
                  file={files[source.key]}
                  uploading={uploading[source.key]}
                  result={uploadResults[source.key]}
                  error={uploadErrors[source.key]}
                  onFile={handleFile}
                  onUpload={handleUpload}
                />
              ))}
            </div>
          </section>

          {Object.keys(costComparison).length > 0 && (
            <section className="mt-6">
              <Card className="p-5">
                <p className="text-xs font-bold uppercase tracking-wider text-violet-400">
                  Cost comparison
                </p>
                <pre className="mt-3 overflow-auto text-xs text-slate-500">
                  {JSON.stringify(costComparison, null, 2)}
                </pre>
              </Card>
            </section>
          )}
        </main>
      </div>

      {selectedMatch && (
        <MatchModal
          match={selectedMatch}
          onClose={() => setSelectedMatch(null)}
          onResolve={resolveMatch}
          loading={agentLoading[selectedMatch.id || selectedMatch.match_id]}
          message={agentMessages[selectedMatch.id || selectedMatch.match_id]}
        />
      )}
    </div>
  );
}
