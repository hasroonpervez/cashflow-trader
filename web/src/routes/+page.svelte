<script>
  let symbol = $state("AAPL");
  let bars = $state([]);
  let meta = $state(null);
  let error = $state("");
  let loading = $state(false);

  async function loadBars() {
    const sym = String(symbol || "").trim().toUpperCase();
    if (!sym) {
      error = "Enter a symbol";
      bars = [];
      meta = null;
      return;
    }
    loading = true;
    error = "";
    bars = [];
    meta = null;
    try {
      const res = await fetch("/api/bars/" + encodeURIComponent(sym));
      const data = await res.json();
      if (!res.ok) {
        const detail = data && data.detail ? String(data.detail) : "HTTP " + res.status;
        error = detail;
        return;
      }
      bars = data.bars || [];
      meta = { symbol: data.symbol, source: data.source, count: data.count };
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }
</script>

<main>
  <h1>CashFlow desk</h1>
  <p class="lede">
    Snapshot bars from the local API. This page does not fetch market data itself.
  </p>
  <form onsubmit={(e) => { e.preventDefault(); loadBars(); }}>
    <label>
      Symbol
      <input bind:value={symbol} name="symbol" autocomplete="off" />
    </label>
    <button type="submit" disabled={loading}>{loading ? "Loading" : "Load bars"}</button>
  </form>
  {#if error}
    <p class="err" role="alert">{error}</p>
  {/if}
  {#if meta}
    <p class="meta">{meta.symbol} · {meta.source} · {meta.count} bars</p>
  {/if}
  {#if bars.length}
    <table>
      <thead>
        <tr>
          <th>ts</th>
          <th>open</th>
          <th>high</th>
          <th>low</th>
          <th>close</th>
          <th>volume</th>
        </tr>
      </thead>
      <tbody>
        {#each bars as row}
          <tr>
            <td>{row.ts}</td>
            <td>{row.open}</td>
            <td>{row.high}</td>
            <td>{row.low}</td>
            <td>{row.close}</td>
            <td>{row.volume}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: ui-sans-serif, system-ui, sans-serif;
    background: #0f1419;
    color: #e7ecf1;
  }
  main { max-width: 52rem; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.4rem; font-weight: 600; }
  .lede { color: #9aa7b4; }
  form { display: flex; gap: 0.75rem; align-items: end; margin: 1rem 0; }
  label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.85rem; }
  input, button { font: inherit; padding: 0.4rem 0.6rem; border-radius: 6px; }
  input { background: #1b232c; color: inherit; border: 1px solid #334155; }
  button { background: #2563eb; color: white; border: 0; cursor: pointer; }
  button:disabled { opacity: 0.6; cursor: default; }
  .err { color: #f87171; }
  .meta { color: #9aa7b4; font-size: 0.9rem; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: right; padding: 0.35rem 0.5rem; border-bottom: 1px solid #1f2a36; }
  th:first-child, td:first-child { text-align: left; }
</style>
