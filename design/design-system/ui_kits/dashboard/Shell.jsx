(function () {
  const { Sidebar: DsSidebar, ModeSelector, SourceChip, SimulationBanner } = window.DesignSystem_1776e0;
  const NAV = [['dashboard', 'layout-dashboard', 'Plancia'], ['requests', 'building-2', 'Richieste e dipartimenti'], ['log', 'scroll-text', 'Registro decisioni']];
  function Sidebar({ screen, onScreen }) {
    return <DsSidebar items={NAV.map((n) => ({ id: n[0], icon: n[1], label: n[2] }))} active={screen} onSelect={onScreen} />;
  }
  function TopBar({ mode, onMode, sources }) {
    return <header style={{ position: 'relative', height: 64, flex: 'none', display: 'flex', alignItems: 'center', gap: 16, padding: '0 16px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface-1)' }}>
      <div style={{ font: '700 20px/28px var(--font-ui)', letterSpacing: '-.01em' }}>Sentrix</div>
      <div style={{ flex: 1 }} />
      {mode === 'scenario' && <SimulationBanner absolute />}
      <SourceChip sources={sources} />
      <ModeSelector value={mode} onChange={onMode} />
    </header>;
  }
  Object.assign(window, { Sidebar, TopBar });
})();
