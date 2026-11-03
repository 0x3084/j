import { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

// ----------------------------------------------------------------------------------- helpers
type Any = Record<string, any>;
const api = async (p: string, init?: RequestInit) => {
  const r = await fetch(p, init);
  if (!r.ok) throw new Error(`${r.status} ${p}`);
  return r.json();
};
function useApi<T = Any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let live = true;
    setErr(null);
    api(path).then((d) => live && setData(d)).catch((e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [path, ...deps]);
  return { data, err };
}
const pct = (x: any, d = 1) => (x === null || x === undefined || Number.isNaN(x) ? "–" : `${(x * 100).toFixed(d)}%`);
const num = (x: any, d = 2) => (x === null || x === undefined || Number.isNaN(x) ? "–" : Number(x).toFixed(d));
const money = (x: any) => (x === null || x === undefined ? "–" : Math.round(x).toLocaleString("en-US"));

// Series colors (validated reference palette: slot 1 blue, slot 2 orange) per theme.
function useColors() {
  const q = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const [dark, setDark] = useState(q?.matches ?? false);
  useEffect(() => {
    if (!q) return;
    const f = (e: MediaQueryListEvent) => setDark(e.matches);
    q.addEventListener("change", f);
    return () => q.removeEventListener("change", f);
  }, []);
  return dark
    ? { s1: "#3987e5", s2: "#d95926", grid: "#383835", axis: "#8e8d86", band: "#2a2a28", crit: "#d03b3b" }
    : { s1: "#2a78d6", s2: "#eb6834", grid: "#e6e5e0", axis: "#7a7974", band: "#f0efec", crit: "#d03b3b" };
}

function Gate({ v }: { v: string }) {
  return v === "PASS"
    ? <span className="badge pass" title="passed all pre-registered criteria">✓ PASS</span>
    : <span className="badge fail" title="failed at least one criterion">✕ FAIL</span>;
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

function TT({ active, payload, label, fmt }: Any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tt">
      <div className="k">{label}</div>
      {payload.map((p: Any) => (
        <div key={p.dataKey}><span className="k">{p.name}: </span>{fmt ? fmt(p.value) : num(p.value)}</div>
      ))}
    </div>
  );
}

// ----------------------------------------------------------------------------------- charts
function EquityChart({ series, holdout }: { series: Any; holdout?: string | null }) {
  const c = useColors();
  const rows = useMemo(() => {
    const m = new Map<string, Any>();
    (series.equity || []).forEach((p: Any) => m.set(p.t, { t: p.t, strategy: p.v }));
    const bk = Object.keys(series.benchmarks || {})[0];
    if (bk) {
      const b = series.benchmarks[bk];
      const first = b.length ? b[0].v : 1;
      b.forEach((p: Any) => { const r = m.get(p.t); if (r) r.bench = p.v / first; });
    }
    return Array.from(m.values());
  }, [series]);
  const bk = Object.keys(series.benchmarks || {})[0];
  const end = rows.length ? rows[rows.length - 1].t : undefined;
  return (
    <>
      <div className="legend">
        <span style={{ ["--c" as any]: c.s1 }}>Strategy (net of costs)</span>
        {bk && <span style={{ ["--c" as any]: c.s2 }}>{bk.replace(/_/g, " ")}</span>}
        {holdout && <span className="muted">shaded = untouched holdout period</span>}
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={rows} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={c.grid} vertical={false} />
          {holdout && end && <ReferenceArea x1={holdout} x2={end} fill={c.band} fillOpacity={0.9} />}
          <XAxis dataKey="t" tick={{ fill: c.axis, fontSize: 11 }} minTickGap={60} tickLine={false} axisLine={false} />
          <YAxis scale="log" domain={["auto", "auto"]} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={false}
                 tickFormatter={(v) => `${v.toFixed(1)}x`} width={44} />
          <Tooltip content={<TT fmt={(v: number) => `${v.toFixed(2)}x`} />} />
          <Line type="monotone" dataKey="strategy" name="Strategy" stroke={c.s1} strokeWidth={2} dot={false} isAnimationActive={false} />
          {bk && <Line type="monotone" dataKey="bench" name={bk} stroke={c.s2} strokeWidth={2} dot={false} isAnimationActive={false} />}
        </LineChart>
      </ResponsiveContainer>
    </>
  );
}

function AreaSeries({ data, name, fmt, height = 160, negative = false }: Any) {
  const c = useColors();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={(data || []).map((p: Any) => ({ t: p.t, v: p.v }))} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey="t" tick={{ fill: c.axis, fontSize: 11 }} minTickGap={60} tickLine={false} axisLine={false} />
        <YAxis tick={{ fill: c.axis, fontSize: 11 }} tickFormatter={fmt} tickLine={false} axisLine={false} width={48} />
        <Tooltip content={<TT fmt={fmt} />} />
        <Area type="monotone" dataKey="v" name={name} stroke={negative ? c.crit : c.s1} fill={negative ? c.crit : c.s1}
              fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ----------------------------------------------------------------------------------- tabs
function Overview({ go }: { go: (n: string) => void }) {
  const st = useApi("/api/status");
  const lb = useApi("/api/leaderboard");
  const pf = useApi("/api/portfolio");
  if (!lb.data || !st.data) return <div className="card">Loading… {lb.err || st.err}</div>;
  const rows: Any[] = lb.data.rows;
  const passed = rows.filter((r) => r.gate === "PASS");
  const meta = lb.data.meta;
  const inv = pf.data?.portfolios?.inv_vol;
  return (
    <>
      <div className="grid g4">
        <Tile label="Strategy families × markets tested" value={String(rows.length)}
              note={`${(meta.effective_trials.etf?.n_raw || 0) + (meta.effective_trials.crypto?.n_raw || 0)} parameter trials, all counted`} />
        <Tile label="Passed pre-registered gate" value={`${passed.length} / ${rows.length}`}
              note={passed.map((p) => p.experiment).join(", ") || "none → portfolio in cash"} />
        <Tile label="Combined portfolio holdout Sharpe (excess)" value={num(inv?.holdout?.sharpe)}
              note={`holdout CAGR ${pct(inv?.holdout?.cagr)} vs WF-OOS ${pct(inv?.wf_oos?.cagr)}`} />
        <Tile label="Real-money trading" value={st.data.live_trading_enabled ? "ENABLED" : "DISABLED"}
              note="simulation only; no broker credentials" />
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <div className="card">
          <h2>Verdict</h2>
          <p className="desc">What the out-of-sample evidence supports, after costs and multiple-testing corrections.</p>
          <ul className="fails" style={{ color: "var(--text-primary)", fontSize: 13, lineHeight: 1.6 }}>
            <li>Only regime-timing rotations in US-listed ETFs cleared the gate; both lost most of their edge in the 2022–2026 holdout.</li>
            <li>Versus cash the best ETF strategy is significant (reality check p={num(meta.reality_check?.etf?.vs_cash?.p_rc, 3)}); versus SPY buy-and-hold it is not (p={num(meta.reality_check?.etf?.vs_benchmark?.p_rc, 3)}).</li>
            <li>No crypto strategy passed: drawdowns of 45–84% or confidence intervals spanning zero.</li>
            <li>Trend following, pairs trading, short-term reversal and ML ranking failed after realistic costs.</li>
          </ul>
          <div className="prov">All figures are SIMULATED backtests on historical data, net of modelled costs — not earnings.</div>
        </div>
        <div className="card">
          <h2>Gate-passing strategies</h2>
          <p className="desc">Click to open details. The holdout was evaluated once, after the strategy set was frozen.</p>
          <div className="tablewrap"><table>
            <thead><tr><th>Strategy</th><th>WF-OOS Sharpe</th><th>Holdout Sharpe</th><th>Holdout CAGR</th><th>Holdout max DD</th></tr></thead>
            <tbody>{passed.map((r) => (
              <tr key={r.experiment} className="click" onClick={() => go(r.experiment)}>
                <td>{r.experiment}</td><td>{num(r.wf_sharpe)}</td><td>{num(r.ho_sharpe)}</td><td>{pct(r.ho_cagr)}</td><td>{pct(r.ho_maxdd)}</td>
              </tr>))}</tbody>
          </table></div>
        </div>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <h2>Data freshness &amp; provenance</h2>
        <div className="tablewrap"><table>
          <thead><tr><th>Source</th><th className="l">Description</th><th>Series</th><th>Earliest</th><th>Latest bar</th></tr></thead>
          <tbody>{Object.entries(st.data.data_sources || {}).map(([k, v]: any) => (
            <tr key={k}><td>{k}</td><td className="l">{v.description}</td><td>{v.series}</td><td>{v.earliest || "–"}</td><td>{v.latest || "–"}</td></tr>))}
          </tbody></table></div>
        <div className="prov">Server time {st.data.server_time_utc} UTC · {st.data.network_note}</div>
      </div>
    </>
  );
}

const COLS: [string, string, (x: any) => string][] = [
  ["experiment", "Strategy", (x) => x], ["market", "Market", (x) => x], ["family", "Family", (x) => x],
  ["wf_sharpe", "WF Sharpe", num], ["wf_sharpe_lo", "CI low", num], ["wf_cagr", "WF CAGR", (x) => pct(x)],
  ["wf_maxdd", "WF max DD", (x) => pct(x, 0)], ["dsr", "Defl. SR", num], ["sharpe_2x_cost", "SR 2×cost", num],
  ["cost_pct_gross", "Cost/gross", (x) => pct(x, 0)], ["trades", "Trades", (x) => (x ?? "–").toString()],
  ["ho_sharpe", "Holdout SR", num], ["ho_cagr", "Holdout CAGR", (x) => pct(x)],
];

function Leaderboard({ go }: { go: (n: string) => void }) {
  const { data, err } = useApi("/api/leaderboard");
  const [sort, setSort] = useState<[string, number]>(["robust_score", -1]);
  if (!data) return <div className="card">Loading… {err}</div>;
  const rows = [...data.rows].sort((a: Any, b: Any) => {
    const x = a[sort[0]], y = b[sort[0]];
    if (x === y) return 0;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return (x > y ? 1 : -1) * sort[1];
  });
  return (
    <div className="card">
      <h2>Strategy leaderboard</h2>
      <p className="desc">Default rank = robust score (lower 95% CI of walk-forward Sharpe, worst of half-periods / 2× costs, deflated Sharpe).
        Raw historical profit is not used for ranking. Click a column to sort, a row for details.</p>
      <div className="tablewrap"><table>
        <thead><tr>{COLS.map(([k, l]) => (
          <th key={k} onClick={() => setSort([k, sort[0] === k ? -sort[1] : -1])}>{l}{sort[0] === k ? (sort[1] > 0 ? " ▲" : " ▼") : ""}</th>))}
          <th>Gate</th></tr></thead>
        <tbody>{rows.map((r: Any) => (
          <tr key={r.experiment} className="click" onClick={() => go(r.experiment)} title={r.fail_reasons || "all criteria met"}>
            {COLS.map(([k, , f]) => <td key={k}>{f(r[k])}</td>)}<td><Gate v={r.gate} /></td>
          </tr>))}</tbody>
      </table></div>
      <div className="prov">{data.data_class}. ETF WF-OOS 2008–2021, holdout 2022–2026-10; crypto WF-OOS 2019-07/2021–2023, holdout 2024–2026-10.</div>
    </div>
  );
}

function Detail({ name, setName, names }: { name: string; setName: (n: string) => void; names: string[] }) {
  const s = useApi(`/api/experiments/${name}`, [name]);
  const ser = useApi(`/api/experiments/${name}/series`, [name]);
  const d = s.data;
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <select value={name} onChange={(e) => setName(e.target.value)}>{names.map((n) => <option key={n}>{n}</option>)}</select>
        {d && <Gate v={d.gate_pass ? "PASS" : "FAIL"} />}
        {d && <span className="sub">{d.family} · {d.market} · {d.universe} · {d.n_trials} trials</span>}
      </div>
      {!d || !ser.data ? <div className="card">Loading… {s.err || ser.err}</div> : (
        <>
          <div className="grid g4">
            <Tile label="WF-OOS Sharpe (excess, 95% CI)" value={num(d.wf_oos.sharpe)} note={`[${num(d.wf_oos.sharpe_lo)}, ${num(d.wf_oos.sharpe_hi)}] · p=${num(d.wf_oos.p_sharpe, 3)}`} />
            <Tile label="WF-OOS CAGR / max DD" value={pct(d.wf_oos.cagr)} note={`max DD ${pct(d.wf_oos.max_dd)} · vol ${pct(d.wf_oos.ann_vol)}`} />
            <Tile label="Holdout Sharpe / CAGR" value={num(d.holdout?.sharpe)} note={d.holdout ? `CAGR ${pct(d.holdout.cagr)} · max DD ${pct(d.holdout.max_dd)}` : "holdout locked"} />
            <Tile label="Deflated Sharpe (prob.)" value={num(d.dsr)} note={`vs best of ${d.n_trials_market_effective} effective trials`} />
          </div>
          <div className="grid g2" style={{ marginTop: 12 }}>
            <div className="card"><h2>Equity curve vs benchmark</h2><p className="desc">Growth of 1, log scale, walk-forward out-of-sample only.</p>
              <EquityChart series={ser.data} holdout={d.holdout ? (d.market === "etf" ? "2022-01-07" : "2024-01-05") : null} /></div>
            <div className="card"><h2>Drawdown</h2><p className="desc">Peak-to-trough decline of the net equity curve.</p>
              <AreaSeries data={ser.data.drawdown} name="Drawdown" fmt={(v: number) => pct(v, 0)} height={280} negative /></div>
          </div>
          <div className="grid g2" style={{ marginTop: 12 }}>
            <div className="card"><h2>Cumulative transaction costs</h2><p className="desc">Sum of per-bar costs (fraction of equity).</p>
              <AreaSeries data={ser.data.cum_costs} name="Costs" fmt={(v: number) => pct(v, 0)} /></div>
            <div className="card"><h2>Gross exposure</h2><p className="desc">Σ|w|; 0 = NO-TRADE state.</p>
              <AreaSeries data={ser.data.exposure} name="Exposure" fmt={(v: number) => num(v, 1)} /></div>
          </div>
          <div className="grid g2" style={{ marginTop: 12 }}>
            <div className="card"><h2>Stress tests (WF-OOS)</h2>
              <table><thead><tr><th>Scenario</th><th>Sharpe</th><th>CAGR</th></tr></thead><tbody>
                <tr><td>Base</td><td>{num(d.wf_oos.sharpe)}</td><td>{pct(d.wf_oos.cagr)}</td></tr>
                {Object.entries(d.stress).map(([k, v]: any) => <tr key={k}><td>{k}</td><td>{num(v.sharpe)}</td><td>{pct(v.cagr)}</td></tr>)}
              </tbody></table>
              <h3>Gate result</h3>
              {d.gate_failures?.length ? <ul className="fails">{d.gate_failures.map((f: string) => <li key={f}>{f}</li>)}</ul> : <div className="sub">All criteria met.</div>}
            </div>
            <div className="card"><h2>Trade statistics &amp; regimes</h2>
              <table><tbody>
                <tr><td>Trades</td><td>{d.wf_oos.n_trades}</td></tr><tr><td>Win rate</td><td>{pct(d.wf_oos.win_rate)}</td></tr>
                <tr><td>Avg win / loss</td><td>{pct(d.wf_oos.avg_win, 2)} / {pct(d.wf_oos.avg_loss, 2)}</td></tr>
                <tr><td>Expectancy / trade</td><td>{pct(d.wf_oos.expectancy, 3)}</td></tr><tr><td>Profit factor</td><td>{num(d.wf_oos.profit_factor)}</td></tr>
                <tr><td>Turnover / yr</td><td>{num(d.wf_oos.turnover_ann, 1)}×</td></tr><tr><td>Costs / gross profit</td><td>{pct(d.wf_oos.cost_pct_gross)}</td></tr>
                <tr><td>VaR95 / ES95 (daily)</td><td>{pct(d.wf_oos.var95, 2)} / {pct(d.wf_oos.es95, 2)}</td></tr>
                <tr><td>Sortino / Calmar</td><td>{num(d.wf_oos.sortino)} / {num(d.wf_oos.calmar)}</td></tr>
              </tbody></table>
              <h3>By regime (excess Sharpe)</h3>
              <table><tbody>{(d.regimes || []).map((r: Any) => <tr key={r.regime}><td>{r.regime}</td><td>{num(r.sharpe)}</td><td className="muted">{r.n} days</td></tr>)}</tbody></table>
            </div>
          </div>
          <div className="card" style={{ marginTop: 12 }}><h2>Walk-forward parameter selections</h2>
            <p className="desc">Chosen each January using only prior data; “None” = NO-TRADE for that year (no parameter set had a positive training Sharpe).</p>
            <div className="tablewrap"><table><thead><tr><th>Year from</th><th className="l">Selected parameters</th><th>Calendar return</th></tr></thead><tbody>
              {Object.entries(d.selections).map(([k, v]: any) => <tr key={k}><td>{k}</td><td className="l">{v ?? "None (NO TRADE)"}</td><td>{pct(d.yearly?.[k.slice(0, 4)])}</td></tr>)}
            </tbody></table></div></div>
        </>
      )}
    </>
  );
}

function Signals() {
  const { data, err } = useApi("/api/signals");
  if (!data) return <div className="card">Loading… {err}</div>;
  return (
    <div className="card">
      <h2>Current research signals</h2>
      <p className="desc">{data.data_class}. Only gate-passing strategies may be paper traded.</p>
      <div className="tablewrap"><table>
        <thead><tr><th>Strategy</th><th>Market</th><th>Gate</th><th>As of</th><th>State</th><th className="l">Target weights</th></tr></thead>
        <tbody>{data.signals.map((s: Any) => (
          <tr key={s.strategy}><td>{s.strategy}</td><td>{s.market}</td><td><Gate v={s.gate} /></td><td>{s.as_of}</td>
            <td>{s.state === "NO_TRADE" ? <span className="badge neutral">○ NO TRADE</span> : <span className="badge neutral">{s.state}</span>}</td>
            <td className="l">{Object.entries(s.weights).map(([k, v]: any) => `${k} ${(v * 100).toFixed(0)}%`).join(" · ") || "—"}</td></tr>))}
        </tbody></table></div>
    </div>
  );
}

function Markets() {
  const m = useApi("/api/markets");
  const q = useApi("/api/data-quality");
  if (!m.data) return <div className="card">Loading… {m.err}</div>;
  return (
    <>
      <div className="card">
        <h2>Performance by market and strategy family</h2>
        <p className="desc">Walk-forward out-of-sample excess Sharpe, after costs.</p>
        <table><thead><tr><th>Market</th><th>Family</th><th>Experiments</th><th>Best WF Sharpe</th><th>Median WF Sharpe</th><th>Passed</th></tr></thead>
          <tbody>{m.data.rows.map((r: Any) => <tr key={r.market + r.family}><td>{r.market}</td><td>{r.family}</td><td>{r.n}</td><td>{num(r.best_wf_sharpe)}</td><td>{num(r.median_wf_sharpe)}</td><td>{r.passed}</td></tr>)}</tbody></table>
      </div>
      {q.data && <div className="card" style={{ marginTop: 12 }}>
        <h2>Cross-source data checks</h2>
        <table><thead><tr><th>Check</th><th>n</th><th>Correlation</th><th>Mean abs diff (bps)</th></tr></thead>
          <tbody>{Object.entries(q.data.cross_checks).map(([k, v]: any) => <tr key={k}><td>{k}</td><td>{v.n}</td><td>{num(v.corr, 3)}</td><td>{num(v.mean_abs_diff_bps, 1)}</td></tr>)}</tbody></table>
      </div>}
    </>
  );
}

function Capital() {
  const c = useApi("/api/capital");
  const p = useApi("/api/portfolio");
  if (!c.data || !p.data) return <div className="card">Loading… {c.err || p.err}</div>;
  const lv = c.data.levels;
  const w100 = lv["100000"]?.withdrawals_20y_eur || [];
  return (
    <>
      <div className="card">
        <h2>Multi-strategy portfolio (gate-passing strategies only)</h2>
        <p className="desc">Walk-forward inverse-volatility allocation, monthly. Strategies: {p.data.passed.join(", ") || "none (cash)"}; pairwise correlation {num(p.data.passed_pair_corr)}.</p>
        <table><thead><tr><th>Method</th><th>Window</th><th>CAGR</th><th>Vol</th><th>Sharpe (excess)</th><th>Max DD</th></tr></thead><tbody>
          {Object.entries(p.data.portfolios).flatMap(([meth, v]: any) => ["wf_oos", "holdout", "full_oos"].map((w) => (
            <tr key={meth + w}><td>{meth}</td><td>{w}</td><td>{pct(v[w].cagr)}</td><td>{pct(v[w].ann_vol)}</td><td>{num(v[w].sharpe)}</td><td>{pct(v[w].max_dd)}</td></tr>)))}
        </tbody></table>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <h2>Capital levels (integer shares, minimum fees, EUR account)</h2>
        <p className="desc">Realised simulated path 2008–2026 for the combined portfolio. Taxes not modelled. Not a forecast.</p>
        <div className="tablewrap"><table><thead><tr><th>Capital (€)</th><th>CAGR (EUR, unhedged)</th><th>Max DD (EUR)</th><th>Fees+slippage % avg equity / yr</th><th>Drag vs fractional</th><th>Median 10y outcome (€)</th><th>5th pct 10y (€)</th></tr></thead><tbody>
          {Object.entries(lv).map(([k, v]: any) => (
            <tr key={k}><td>{money(+k)}</td><td>{pct(v.eur_unhedged?.cagr)}</td><td>{pct(v.eur_unhedged?.max_dd)}</td><td>{pct(v.fees_pct_of_capital_per_year, 2)}</td>
              <td>{pct(v.small_account_drag_cagr)}</td><td>{money(v.outcomes_10y_eur?.terminal_median)}</td><td>{money(v.outcomes_10y_eur?.terminal_p5)}</td></tr>))}
        </tbody></table></div>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <h2>Withdrawals from €100,000 over 20 years (bootstrap, inflation-indexed)</h2>
        <p className="desc">Depletion = real equity below 50% of start at any time. Monthly income shown is the starting amount before tax.</p>
        <table><thead><tr><th>Withdrawal rate</th><th>Monthly income (start)</th><th>P(depletion)</th><th>Median real terminal (€)</th><th>5th pct real terminal (€)</th></tr></thead><tbody>
          {w100.map((w: Any) => <tr key={w.withdrawal_rate}><td>{pct(w.withdrawal_rate, 0)}</td><td>€{money(w.monthly_income_start)}</td><td>{pct(w.p_depletion)}</td><td>{money(w.real_terminal_median)}</td><td>{money(w.real_terminal_p5)}</td></tr>)}
        </tbody></table>
        <div className="prov">Bootstrap of realised out-of-sample daily returns (2008–2026), which include the strong pre-2022 period; the 2022–2026 holdout was much weaker, so these ranges are likely optimistic.</div>
      </div>
    </>
  );
}

function Paper() {
  const st = useApi("/api/status");
  const runs: string[] = (st.data?.paper_runs || []).map((r: Any) => r.run);
  const [run, setRun] = useState<string | null>(null);
  const cur = run || runs[0] || null;
  const d = useApi(cur ? `/api/paper/${cur}` : null, [cur]);
  const c = useColors();
  if (!st.data) return <div className="card">Loading…</div>;
  if (!runs.length) return <div className="card">No paper runs yet. Start one with <code>python -m scripts.paper replay --strategy …</code></div>;
  const eq = (d.data?.equity || []).map((r: Any) => ({ t: r.ts.slice(0, 10), v: r.equity }));
  const last = d.data?.equity?.[d.data.equity.length - 1];
  const vb = d.data?.vs_backtest;
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <select value={cur || ""} onChange={(e) => setRun(e.target.value)}>{runs.map((r) => <option key={r}>{r}</option>)}</select>
        <span className="badge warn">⚠ {d.data?.data_class || "SIMULATED"}</span>
        {(d.data?.feeds || []).map((f: Any) => <span key={f.source} className="sub">feed {f.source} · {f.data_class} · last bar {f.last_bar?.slice(0, 10)}</span>)}
      </div>
      {!d.data ? <div className="card">Loading… {d.err}</div> : <>
        <div className="grid g4">
          <Tile label="Simulated equity" value={money(last?.equity)} note={`start ${money(d.data.equity[0]?.equity)} · not real money`} />
          <Tile label="Realized / unrealized P&L (sim.)" value={money(last?.realized)} note={`unrealized ${money(last?.unrealized)}`} />
          <Tile label="Costs paid (sim.)" value={money(last?.costs)} note="spread + slippage + commission" />
          <Tile label="Paper vs backtest" value={vb ? `ρ ${num(vb.daily_corr, 3)}` : "–"} note={vb ? `tracking error ${pct(vb.tracking_error_ann)} · gap ${pct(vb.return_gap_ann)}/yr` : ""} />
        </div>
        <div className="grid g2" style={{ marginTop: 12 }}>
          <div className="card"><h2>Paper equity</h2>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={eq} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="t" tick={{ fill: c.axis, fontSize: 11 }} minTickGap={50} tickLine={false} axisLine={false} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
                <Tooltip content={<TT fmt={money} />} />
                <Line dataKey="v" name="Equity" stroke={c.s1} strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer></div>
          <div className="card"><h2>Open positions</h2>
            <table><thead><tr><th>Symbol</th><th>Qty</th><th>Avg price</th><th>Mark</th><th>Unrealized</th></tr></thead><tbody>
              {d.data.positions.map((p: Any) => <tr key={p.symbol}><td>{p.symbol}</td><td>{num(p.qty, 0)}</td><td>{num(p.avg_price)}</td><td>{num(p.mark)}</td><td>{money(p.qty * (p.mark - p.avg_price))}</td></tr>)}
            </tbody></table>
            {!d.data.positions.length && <div className="sub">Flat (NO TRADE).</div>}
          </div>
        </div>
        <div className="grid g2" style={{ marginTop: 12 }}>
          <div className="card"><h2>Recent signals (after risk approval)</h2><div className="tablewrap" style={{ maxHeight: 320 }}><table>
            <thead><tr><th>Bar</th><th>Symbol</th><th>Proposed</th><th>Approved</th><th>Action</th></tr></thead><tbody>
              {d.data.signals.map((s: Any, i: number) => <tr key={i}><td>{s.ts.slice(0, 10)}</td><td>{s.symbol}</td><td>{pct(s.proposed, 0)}</td><td>{pct(s.approved, 0)}</td><td>{s.action}</td></tr>)}
            </tbody></table></div></div>
          <div className="card"><h2>Fills &amp; risk events</h2><div className="tablewrap" style={{ maxHeight: 320 }}><table>
            <thead><tr><th>Time</th><th>Symbol</th><th>Qty</th><th>Price</th><th>Cost</th></tr></thead><tbody>
              {d.data.fills.slice(0, 30).map((f: Any, i: number) => <tr key={i}><td>{f.ts.slice(0, 10)}</td><td>{f.symbol}</td><td>{num(f.qty, 0)}</td><td>{num(f.price)}</td><td>{num(f.cost)}</td></tr>)}
            </tbody></table>
            <h3>Events</h3>
            <table><tbody>{d.data.events.slice(0, 20).map((e: Any, i: number) => <tr key={i}><td>{e.utc}</td><td>{e.level}</td><td className="l">{e.code}: {String(e.message).slice(0, 80)}</td></tr>)}</tbody></table>
            {!d.data.events.length && <div className="sub">No risk events.</div>}
          </div></div>
        </div>
      </>}
    </>
  );
}

function Risk() {
  const [n, setN] = useState(0);
  const st = useApi("/api/status", [n]);
  const toggle = async (on: boolean) => { await api("/api/kill", { method: on ? "POST" : "DELETE" }); setN(n + 1); };
  if (!st.data) return <div className="card">Loading…</div>;
  return (
    <div className="grid g2">
      <div className="card">
        <h2>System status</h2>
        <table><tbody>
          <tr><td>Real-money trading</td><td>{st.data.live_trading_enabled ? <span className="badge fail">ENABLED</span> : <span className="badge pass">✓ DISABLED</span>}</td></tr>
          <tr><td>Mode</td><td>{st.data.real_money}</td></tr>
          <tr><td>Kill switch</td><td>{st.data.kill_switch ? <span className="badge fail">✕ ENGAGED</span> : <span className="badge pass">✓ released</span>}</td></tr>
          <tr><td>Holdout unlocked</td><td>{String(st.data.holdout_unlocked)}</td></tr>
          <tr><td>Server time (UTC)</td><td>{st.data.server_time_utc}</td></tr>
        </tbody></table>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn danger" onClick={() => toggle(true)}>Engage kill switch</button>
          <button className="btn" onClick={() => toggle(false)}>Release kill switch</button>
        </div>
        <div className="prov">The kill switch halts every paper trader at its next bar; HALTED runs need a manual risk-manager reset.</div>
      </div>
      <div className="card">
        <h2>Mandatory risk controls</h2>
        <p className="desc">Enforced by the independent risk manager on every order set; the simulated broker rejects any order not signed by it.</p>
        <ul className="fails" style={{ lineHeight: 1.7 }}>
          <li>Max position weight, gross, net and leverage caps</li><li>Asset-class concentration cap</li>
          <li>Ex-ante portfolio volatility cap (trailing covariance)</li><li>Daily loss → reduce-only until next session</li>
          <li>Max drawdown → HALT (manual reset)</li><li>Stale data → instrument frozen; feed down → HALT</li>
          <li>3 consecutive critical errors → HALT</li><li>Kill switch file / API</li>
        </ul>
        <div className="prov">Limits: configs/risk.yaml</div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------------- shell
const TABS = ["Overview", "Leaderboard", "Strategy", "Signals", "Markets", "Portfolio & Capital", "Paper trading", "Risk & Status"];

export default function App() {
  const [tab, setTab] = useState("Overview");
  const [name, setName] = useState("rotation_filtered_etf");
  const lb = useApi("/api/leaderboard");
  const names: string[] = (lb.data?.rows || []).map((r: Any) => r.experiment);
  const go = (n: string) => { setName(n); setTab("Strategy"); };
  return (
    <div className="app">
      <header className="top">
        <h1>QRS Research Desk</h1>
        <span className="sub">Systematic research &amp; paper trading · historical and simulated data only</span>
      </header>
      <div className="banner">
        <strong>Simulation only.</strong> Every return shown is a backtest or paper-trading simulation on historical data,
        net of modelled costs. None of it is realised profit. Real-money trading is disabled.
      </div>
      <nav className="tabs">{TABS.map((t) => <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}</nav>
      {tab === "Overview" && <Overview go={go} />}
      {tab === "Leaderboard" && <Leaderboard go={go} />}
      {tab === "Strategy" && <Detail name={name} setName={setName} names={names.length ? names : [name]} />}
      {tab === "Signals" && <Signals />}
      {tab === "Markets" && <Markets />}
      {tab === "Portfolio & Capital" && <Capital />}
      {tab === "Paper trading" && <Paper />}
      {tab === "Risk & Status" && <Risk />}
    </div>
  );
}
