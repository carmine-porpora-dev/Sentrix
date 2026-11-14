/* @ds-bundle: {"format":4,"namespace":"DesignSystem_1776e0","components":[{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Card","sourcePath":"components/core/Card.jsx"},{"name":"EmptyState","sourcePath":"components/core/EmptyState.jsx"},{"name":"DEPARTMENTS","sourcePath":"components/core/Icon.jsx"},{"name":"Icon","sourcePath":"components/core/Icon.jsx"},{"name":"Tooltip","sourcePath":"components/core/Tooltip.jsx"},{"name":"DepartmentCard","sourcePath":"components/data/DepartmentCard.jsx"},{"name":"IterationIndicator","sourcePath":"components/data/IterationIndicator.jsx"},{"name":"MetricCard","sourcePath":"components/data/MetricCard.jsx"},{"name":"ProvenanceTooltip","sourcePath":"components/data/ProvenanceTooltip.jsx"},{"name":"RunStatus","sourcePath":"components/data/RunStatus.jsx"},{"name":"EventFormRow","sourcePath":"components/forms/EventFormRow.jsx"},{"name":"FieldHeader","sourcePath":"components/forms/FieldHeader.jsx"},{"name":"ManualSwitch","sourcePath":"components/forms/ManualSwitch.jsx"},{"name":"TextField","sourcePath":"components/forms/TextField.jsx"},{"name":"LayerPanel","sourcePath":"components/map/LayerPanel.jsx"},{"name":"LayerToggleButton","sourcePath":"components/map/LayerToggleButton.jsx"},{"name":"MapAttribution","sourcePath":"components/map/MapAttribution.jsx"},{"name":"MapLegend","sourcePath":"components/map/MapLegend.jsx"},{"name":"MapMarker","sourcePath":"components/map/MapMarker.jsx"},{"name":"MapToggle","sourcePath":"components/map/MapToggle.jsx"},{"name":"EventManagerHeader","sourcePath":"components/navigation/EventManagerHeader.jsx"},{"name":"EventManagerRail","sourcePath":"components/navigation/EventManagerRail.jsx"},{"name":"ModeSelector","sourcePath":"components/navigation/ModeSelector.jsx"},{"name":"Sidebar","sourcePath":"components/navigation/Sidebar.jsx"},{"name":"SidebarButton","sourcePath":"components/navigation/SidebarButton.jsx"},{"name":"SimulationBanner","sourcePath":"components/navigation/SimulationBanner.jsx"},{"name":"SourceChip","sourcePath":"components/navigation/SourceChip.jsx"},{"name":"Tabs","sourcePath":"components/navigation/Tabs.jsx"},{"name":"AgentTimelineItem","sourcePath":"components/operations/AgentTimelineItem.jsx"},{"name":"DecisionCallout","sourcePath":"components/operations/DecisionCallout.jsx"},{"name":"DecisionLogRow","sourcePath":"components/operations/DecisionLogRow.jsx"},{"name":"ErrorCallout","sourcePath":"components/operations/ErrorCallout.jsx"},{"name":"EventManager","sourcePath":"components/operations/EventManager.jsx"},{"name":"IterationTable","sourcePath":"components/operations/IterationTable.jsx"},{"name":"PlanMeasureRow","sourcePath":"components/operations/PlanMeasureRow.jsx"},{"name":"RequestCard","sourcePath":"components/operations/RequestCard.jsx"},{"name":"RequestGroup","sourcePath":"components/operations/RequestGroup.jsx"}],"sourceHashes":{"components/core/Badge.jsx":"3ddcdc5ae47e","components/core/Button.jsx":"6e0f245a0fb9","components/core/Card.jsx":"39c61514b112","components/core/EmptyState.jsx":"d855e8794fe9","components/core/Icon.jsx":"94853e774aa3","components/core/Tooltip.jsx":"6c4ddc107fdd","components/data/DepartmentCard.jsx":"677a45cf603a","components/data/IterationIndicator.jsx":"ffb15d7d39ac","components/data/MetricCard.jsx":"5b93e9a1d991","components/data/ProvenanceTooltip.jsx":"5e5cc0c0ee7c","components/data/RunStatus.jsx":"9842355b2ee8","components/forms/EventFormRow.jsx":"9ad857b9915d","components/forms/FieldHeader.jsx":"7ac6d5aa0494","components/forms/ManualSwitch.jsx":"5795483f9693","components/forms/TextField.jsx":"18d5557784b5","components/map/LayerPanel.jsx":"c4e8277205a6","components/map/LayerToggleButton.jsx":"61bc65a19136","components/map/MapAttribution.jsx":"fc70312127c2","components/map/MapLegend.jsx":"3fad3856504a","components/map/MapMarker.jsx":"6580db8f388c","components/map/MapToggle.jsx":"b3b206a5c2db","components/navigation/EventManagerHeader.jsx":"3fc9c0a08507","components/navigation/EventManagerRail.jsx":"e841e8995813","components/navigation/ModeSelector.jsx":"1351bc09d3a4","components/navigation/Sidebar.jsx":"c656f5219684","components/navigation/SidebarButton.jsx":"b658cbe1024d","components/navigation/SimulationBanner.jsx":"2c91bc301401","components/navigation/SourceChip.jsx":"69eeac03cc9f","components/navigation/Tabs.jsx":"abfb609e63ca","components/operations/AgentTimelineItem.jsx":"bf6d9585178d","components/operations/DecisionCallout.jsx":"08b9f0f70f63","components/operations/DecisionLogRow.jsx":"728c67a9b3eb","components/operations/ErrorCallout.jsx":"e6956105fd8f","components/operations/EventManager.jsx":"b83e0763c6ab","components/operations/IterationTable.jsx":"70f2c29fa7ec","components/operations/PlanMeasureRow.jsx":"c8e51122c036","components/operations/RequestCard.jsx":"891b9f569962","components/operations/RequestGroup.jsx":"6882e92727f7","ui_kits/dashboard/MapPanel.jsx":"e2f5a5a2829d","ui_kits/dashboard/Panels.jsx":"8412d25aff83","ui_kits/dashboard/Shell.jsx":"ccbbfc04b3e9"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

  const __ds_ns = (window.DesignSystem_1776e0 = window.DesignSystem_1776e0 || {});

  const __ds_scope = {};

  (__ds_ns.__errors = __ds_ns.__errors || []);

  // components/core/Card.jsx
  try {
    (() => {
      function Card({
        variant = 'default',
        padding = 16,
        clickable = false,
        onClick,
        className = '',
        style,
        children
      }) {
        const cls = ['nuo-card', variant === 'nested' ? 'nuo-card--nested' : '', padding === 20 ? 'nuo-card--p20' : '', clickable ? 'nuo-card--clickable' : '', className].join(' ');
        return /*#__PURE__*/React.createElement("div", {
          className: cls,
          style: style,
          onClick: onClick,
          role: clickable ? 'button' : undefined,
          tabIndex: clickable ? 0 : undefined
        }, children);
      }
      Object.assign(__ds_scope, { Card });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/core/Card.jsx", error: String((e && e.message) || e) }); }

  // components/core/Icon.jsx
  try {
    (() => {
      const DEPARTMENTS = {
        traffic: {
          name: 'Traffic Control',
          icon: 'traffic-cone',
          unit: 'agenti disponibili'
        },
        police: {
          name: 'Municipal Police',
          icon: 'shield',
          unit: 'pattuglie disponibili'
        },
        transport: {
          name: 'Transport Control',
          icon: 'bus',
          unit: 'mezzi disponibili'
        },
        comms: {
          name: 'Public Communication',
          icon: 'megaphone',
          unit: 'canali disponibili'
        }
      };
      const ALIAS = {
        'loader-2': 'loader-circle',
        'alert-triangle': 'triangle-alert'
      };
      const pascal = s => s.split('-').map(p => p.charAt(0).toUpperCase() + p.slice(1)).join('');
      function Icon({
        name,
        size = 20,
        stroke = 1.5,
        spin = false,
        className = '',
        style
      }) {
        const L = typeof window !== 'undefined' ? window.lucide : null;
        const icons = L && L.icons || {};
        const raw = icons[pascal(name)] || icons[pascal(ALIAS[name] || name)];
        const node = raw && raw[0] === 'svg' ? raw[2] : raw;
        return /*#__PURE__*/React.createElement("svg", {
          className: 'nuo-icon ' + (spin ? 'nuo-spin ' : '') + className,
          style: style,
          width: size,
          height: size,
          viewBox: "0 0 24 24",
          fill: "none",
          stroke: "currentColor",
          strokeWidth: stroke,
          strokeLinecap: "round",
          strokeLinejoin: "round",
          "aria-hidden": "true"
        }, node ? node.map((n, i) => React.createElement(n[0], {
          key: i,
          ...Object.fromEntries(Object.entries(n[1]).map(([k, v]) => [k.replace(/-([a-z])/g, (m, c) => c.toUpperCase()), v]))
        })) : null);
      }
      Object.assign(__ds_scope, { DEPARTMENTS, Icon });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/core/Icon.jsx", error: String((e && e.message) || e) }); }

  // components/core/Badge.jsx
  try {
    (() => {
      const KINDS = {
        real: ['REALE', 'activity'],
        estimate: ['STIMA', 'waves'],
        simulated: ['SIMULATO', 'flask-conical'],
        unavailable: ['Non disponibile', 'minus'],
        pending: ['In attesa', 'clock']
      };
      function Badge({
        kind = 'real',
        children
      }) {
        const k = KINDS[kind] || KINDS.real;
        return /*#__PURE__*/React.createElement("span", {
          className: 'nuo-badge nuo-badge--' + kind
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: k[1],
          size: 14
        }), children || k[0]);
      }
      Object.assign(__ds_scope, { Badge });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

  // components/core/Button.jsx
  try {
    (() => {
      function Button({
        variant = 'solid',
        icon,
        loading = false,
        loadingLabel = 'Analisi in corso…',
        disabled = false,
        block = false,
        ariaLabel,
        type = 'button',
        onClick,
        children
      }) {
        const iconOnly = !children && !loading;
        const cls = ['nuo-btn', 'nuo-btn--' + variant, iconOnly ? 'nuo-btn--icon' : '', block ? 'nuo-btn--block' : '', loading ? 'is-loading' : ''].join(' ');
        return /*#__PURE__*/React.createElement("button", {
          type: type,
          className: cls,
          disabled: disabled,
          "aria-label": ariaLabel,
          "aria-busy": loading || undefined,
          onClick: loading ? undefined : onClick
        }, loading ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "loader-2",
          spin: true
        }) : icon ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: icon
        }) : null, loading ? loadingLabel : children);
      }
      Object.assign(__ds_scope, { Button });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

  // components/core/EmptyState.jsx
  try {
    (() => {
      function EmptyState({
        icon,
        title,
        tone = 'neutral',
        children,
        className = ''
      }) {
        const ic = icon || (tone === 'success' ? 'circle-check' : 'inbox');
        return /*#__PURE__*/React.createElement("div", {
          className: 'nuo-empty nuo-empty--' + tone + ' ' + className
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: ic,
          size: 48,
          stroke: 1.5
        }), /*#__PURE__*/React.createElement("div", {
          className: "nuo-empty__title"
        }, title), children && /*#__PURE__*/React.createElement("div", {
          className: "nuo-empty__text"
        }, children));
      }
      Object.assign(__ds_scope, { EmptyState });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/core/EmptyState.jsx", error: String((e && e.message) || e) }); }

  // components/core/Tooltip.jsx
  try {
    (() => {
      function Tooltip({
        content,
        placement = 'top',
        open = false,
        children
      }) {
        return /*#__PURE__*/React.createElement("span", {
          className: 'nuo-tip' + (placement === 'bottom' ? ' nuo-tip--bottom' : '') + (open ? ' nuo-tip--open' : '')
        }, children, /*#__PURE__*/React.createElement("span", {
          className: "nuo-tip__bubble",
          role: "tooltip"
        }, content));
      }
      Object.assign(__ds_scope, { Tooltip });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/core/Tooltip.jsx", error: String((e && e.message) || e) }); }

  // components/data/DepartmentCard.jsx
  try {
    (() => {
      function DepartmentCard({
        dept = 'traffic',
        remaining = 0,
        total = 0
      }) {
        const d = __ds_scope.DEPARTMENTS[dept];
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-dept"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-dept__head"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-dept__icon"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: d.icon
        })), /*#__PURE__*/React.createElement("span", {
          className: "nuo-dept__name"
        }, d.name)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
          className: 'nuo-dept__num' + (remaining === 0 ? ' is-zero' : '')
        }, remaining), /*#__PURE__*/React.createElement("span", {
          className: "nuo-dept__of"
        }, " / ", total)), /*#__PURE__*/React.createElement("div", {
          className: "nuo-dept__unit"
        }, d.unit)), /*#__PURE__*/React.createElement("div", {
          className: "nuo-bar"
        }, /*#__PURE__*/React.createElement("i", {
          style: {
            width: (total ? remaining / total * 100 : 0) + '%'
          }
        })));
      }
      Object.assign(__ds_scope, { DepartmentCard });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/data/DepartmentCard.jsx", error: String((e && e.message) || e) }); }

  // components/data/IterationIndicator.jsx
  try {
    (() => {
      function IterationIndicator({
        current = 1,
        total = 3
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-iter"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-iter__label"
        }, "Iterazione ", current, " di ", total), /*#__PURE__*/React.createElement("span", {
          className: "nuo-iter__ticks"
        }, Array.from({
          length: total
        }, (_, i) => /*#__PURE__*/React.createElement("i", {
          key: i,
          className: 'nuo-iter__tick' + (i < current ? ' is-on' : '')
        }))));
      }
      Object.assign(__ds_scope, { IterationIndicator });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/data/IterationIndicator.jsx", error: String((e && e.message) || e) }); }

  // components/data/ProvenanceTooltip.jsx
  try {
    (() => {
      function ProvenanceTooltip({
        title,
        badge = 'real',
        rows = [],
        floating = false
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: 'nuo-prov' + (floating ? ' nuo-prov--float' : ''),
          role: "tooltip"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-prov__head"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-prov__title"
        }, title), badge && /*#__PURE__*/React.createElement(__ds_scope.Badge, {
          kind: badge
        })), rows.map(r => /*#__PURE__*/React.createElement("div", {
          className: "nuo-prov__row",
          key: r[0]
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-prov__k"
        }, r[0]), /*#__PURE__*/React.createElement("span", {
          className: "nuo-prov__v"
        }, [].concat(r[1]).map((l, i) => /*#__PURE__*/React.createElement("span", {
          key: i
        }, l))))));
      }
      Object.assign(__ds_scope, { ProvenanceTooltip });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/data/ProvenanceTooltip.jsx", error: String((e && e.message) || e) }); }

  // components/data/MetricCard.jsx
  try {
    (() => {
      function MetricCard({
        label,
        value,
        before,
        unit,
        delta,
        badge,
        loading = false,
        compact = false,
        provenance,
        showProvenance = false
      }) {
        if (loading) return /*#__PURE__*/React.createElement("div", {
          className: "nuo-metric",
          "aria-busy": "true"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-loadbar"
        }), /*#__PURE__*/React.createElement("div", {
          className: "nuo-skel",
          style: {
            width: 130,
            height: 20
          }
        }), /*#__PURE__*/React.createElement("div", {
          className: "nuo-skel",
          style: {
            width: 160,
            height: 40
          }
        }), /*#__PURE__*/React.createElement("div", {
          className: "nuo-metric__foot"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-metric__label"
        }, "In caricamento\u2026"), /*#__PURE__*/React.createElement("div", {
          className: "nuo-skel",
          style: {
            width: 76,
            height: 28
          }
        })));
        const hasBefore = before != null;
        const b = badge === undefined ? hasBefore ? 'simulated' : 'real' : badge;
        const small = compact || hasBefore || String(value || '').length >= 7;
        const d = delta || {};
        const tone = d.tone || 'neutral';
        const dIcon = tone === 'neutral' ? 'minus' : d.direction === 'down' ? 'arrow-down' : 'arrow-up';
        const card = /*#__PURE__*/React.createElement("div", {
          className: 'nuo-metric' + (small ? ' is-sm' : ''),
          tabIndex: provenance ? 0 : undefined
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-metric__label"
        }, label), /*#__PURE__*/React.createElement("div", {
          className: "nuo-metric__value"
        }, hasBefore && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
          className: "nuo-metric__before"
        }, before), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "arrow-right",
          size: 24
        })), value, unit && /*#__PURE__*/React.createElement("span", {
          className: "nuo-metric__unit"
        }, unit)), /*#__PURE__*/React.createElement("div", {
          className: "nuo-metric__foot"
        }, delta ? /*#__PURE__*/React.createElement("span", {
          className: 'nuo-delta nuo-delta--' + tone
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: dIcon,
          size: 16
        }), d.text || '0,0%') : /*#__PURE__*/React.createElement("span", null), b && /*#__PURE__*/React.createElement(__ds_scope.Badge, {
          kind: b
        })));
        if (!provenance) return card;
        return /*#__PURE__*/React.createElement("div", {
          className: 'nuo-mc' + (showProvenance ? ' is-tip' : '')
        }, card, /*#__PURE__*/React.createElement(__ds_scope.ProvenanceTooltip, {
          floating: true,
          title: provenance.title || label,
          badge: provenance.badge === undefined ? b : provenance.badge,
          rows: provenance.rows
        }));
      }
      Object.assign(__ds_scope, { MetricCard });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/data/MetricCard.jsx", error: String((e && e.message) || e) }); }

  // components/data/RunStatus.jsx
  try {
    (() => {
      const STEPS = ['INTAKE', 'ANALYZE', 'RECONCILE', 'PLAN', 'DISPATCH', 'AWAIT', 'REPLAN', 'VERIFY', 'DONE'];
      const S = {
        INTAKE: ['Acquisizione'],
        ANALYZE: ['Analisi'],
        RECONCILE: ['Riconciliazione'],
        PLAN: ['Pianificazione'],
        DISPATCH: ['Invio richieste'],
        AWAIT: ['In attesa risposte', 'warn', 'clock'],
        REPLAN: ['Ripianificazione'],
        VERIFY: ['Verifica'],
        DONE: ['Completato', 'done', 'check'],
        ERRORE: ['Errore', 'error', 'triangle-alert'],
        DECISIONE: ['Decisione richiesta', 'warn', 'user']
      };
      const KIND = {
        run: ['var(--color-accent)', 'var(--color-state-fill-running)'],
        warn: ['var(--color-warning)', 'var(--color-state-fill-waiting)'],
        done: ['var(--color-data-real)', 'var(--color-state-fill-done)'],
        error: ['var(--color-danger)', 'var(--color-state-fill-error)']
      };
      function RunStatus({
        state = 'INTAKE',
        step = 0
      }) {
        const s = S[state] || S.INTAKE;
        const kind = s[1] || 'run';
        const [c, f] = KIND[kind];
        const cur = STEPS.indexOf(state) >= 0 ? STEPS.indexOf(state) : step;
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-run"
        }, /*#__PURE__*/React.createElement(__ds_scope.Tooltip, {
          content: /*#__PURE__*/React.createElement("span", {
            style: {
              fontFamily: 'var(--font-mono)'
            }
          }, state === 'DECISIONE' ? 'DECISIONE UMANA RICHIESTA' : state),
          placement: "bottom"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-chip",
          style: {
            '--c': c,
            '--f': f
          }
        }, s[2] ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: s[2],
          size: 16
        }) : /*#__PURE__*/React.createElement("span", {
          className: "nuo-dot nuo-dot--pulse"
        }), s[0])), /*#__PURE__*/React.createElement("div", {
          className: 'nuo-steps' + (state === 'DONE' ? ' nuo-steps--done' : '')
        }, STEPS.map((k, i) => /*#__PURE__*/React.createElement("i", {
          key: k,
          className: 'nuo-step' + (i < cur || state === 'DONE' ? ' is-done' : '') + (i === cur && state !== 'DONE' ? ' is-current' : '') + (i === cur && state === 'ERRORE' ? ' is-error' : '') + (i === cur && kind === 'warn' ? ' is-warn' : '')
        }))));
      }
      Object.assign(__ds_scope, { RunStatus });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/data/RunStatus.jsx", error: String((e && e.message) || e) }); }

  // components/forms/EventFormRow.jsx
  try {
    (() => {
      function EventFormRow({
        icon,
        label,
        value,
        live = false
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-efr"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: icon,
          size: 16
        }), /*#__PURE__*/React.createElement("span", {
          className: "nuo-efr__label"
        }, label), /*#__PURE__*/React.createElement("span", {
          className: "nuo-efr__value"
        }, live ? '—' : value));
      }
      Object.assign(__ds_scope, { EventFormRow });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/forms/EventFormRow.jsx", error: String((e && e.message) || e) }); }

  // components/forms/FieldHeader.jsx
  try {
    (() => {
      function FieldHeader({
        label,
        badge
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-fhead"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-field__label"
        }, label), badge && /*#__PURE__*/React.createElement(__ds_scope.Badge, {
          kind: badge
        }));
      }
      Object.assign(__ds_scope, { FieldHeader });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/forms/FieldHeader.jsx", error: String((e && e.message) || e) }); }

  // components/forms/ManualSwitch.jsx
  try {
    (() => {
      function ManualSwitch({
        checked = false,
        onChange
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-switchbox"
        }, /*#__PURE__*/React.createElement("button", {
          type: "button",
          role: "switch",
          "aria-checked": checked,
          className: 'nuo-switch' + (checked ? ' is-on' : ''),
          onClick: () => onChange && onChange(!checked)
        }, /*#__PURE__*/React.createElement("span", {
          className: 'nuo-track' + (checked ? ' is-on' : '')
        }), "Risposta manuale", /*#__PURE__*/React.createElement("span", {
          className: "nuo-switch__state"
        }, checked ? 'On' : 'Off')), /*#__PURE__*/React.createElement("div", {
          className: "nuo-field__hint"
        }, checked ? 'Accetti o rifiuti tu le richieste dei dipartimenti.' : 'I dipartimenti rispondono in automatico.'));
      }
      Object.assign(__ds_scope, { ManualSwitch });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/forms/ManualSwitch.jsx", error: String((e && e.message) || e) }); }

  // components/forms/TextField.jsx
  try {
    (() => {
      function TextField({
        label,
        value,
        onChange,
        placeholder,
        suffix,
        mono = false,
        error,
        disabled = false,
        hint,
        id,
        inputMode
      }) {
        const fid = id || 'f-' + (label || 'x').replace(/\W/g, '');
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-field"
        }, label && /*#__PURE__*/React.createElement("label", {
          className: "nuo-field__label",
          htmlFor: fid
        }, label), /*#__PURE__*/React.createElement("div", {
          className: 'nuo-input' + (mono ? ' nuo-input--mono' : '') + (error ? ' is-error' : '') + (disabled ? ' is-disabled' : '')
        }, /*#__PURE__*/React.createElement("input", {
          id: fid,
          value: value,
          placeholder: placeholder,
          disabled: disabled,
          inputMode: inputMode,
          "aria-invalid": !!error,
          onChange: e => onChange && onChange(e.target.value)
        }), suffix && /*#__PURE__*/React.createElement("span", {
          className: "nuo-input__suffix"
        }, suffix)), error ? /*#__PURE__*/React.createElement("div", {
          className: "nuo-field__msg"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "triangle-alert",
          size: 16
        }), error) : hint ? /*#__PURE__*/React.createElement("div", {
          className: "nuo-field__hint"
        }, hint) : null);
      }
      Object.assign(__ds_scope, { TextField });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/forms/TextField.jsx", error: String((e && e.message) || e) }); }

  // components/map/LayerPanel.jsx
  try {
    (() => {
      function LayerPanel({
        layers = [],
        onToggle
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-layers",
          role: "group",
          "aria-label": "Livelli"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-layers__title"
        }, "Livelli"), layers.map(l => /*#__PURE__*/React.createElement("button", {
          key: l.id,
          type: "button",
          role: "checkbox",
          "aria-checked": l.on,
          className: 'nuo-layer' + (l.on ? ' is-on' : ''),
          onClick: () => onToggle && onToggle(l.id)
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-layer__box"
        }, l.on && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "check",
          size: 12,
          stroke: 3
        })), /*#__PURE__*/React.createElement("span", {
          className: 'nuo-layer__sw' + (l.dashed ? ' nuo-layer__sw--dashed' : ''),
          style: {
            '--c': l.color
          }
        }), /*#__PURE__*/React.createElement("span", {
          className: "nuo-layer__name"
        }, l.name))));
      }
      Object.assign(__ds_scope, { LayerPanel });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/map/LayerPanel.jsx", error: String((e && e.message) || e) }); }

  // components/map/LayerToggleButton.jsx
  try {
    (() => {
      function LayerToggleButton({
        open = false,
        onToggle,
        className = ''
      }) {
        return /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: 'nuo-ltb' + (open ? ' is-open ' : ' ') + className,
          "aria-expanded": open,
          "aria-label": "Livelli mappa",
          onClick: onToggle
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "layers",
          size: 20
        }));
      }
      Object.assign(__ds_scope, { LayerToggleButton });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/map/LayerToggleButton.jsx", error: String((e && e.message) || e) }); }

  // components/map/MapAttribution.jsx
  try {
    (() => {
      function MapAttribution() {
        return /*#__PURE__*/React.createElement("span", {
          className: "nuo-attrib"
        }, /*#__PURE__*/React.createElement("a", {
          href: "https://www.openstreetmap.org/copyright",
          target: "_blank",
          rel: "noreferrer"
        }, "\xA9 OpenStreetMap contributors"), " \xB7 ", /*#__PURE__*/React.createElement("a", {
          href: "https://protomaps.com",
          target: "_blank",
          rel: "noreferrer"
        }, "Protomaps"));
      }
      Object.assign(__ds_scope, { MapAttribution });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/map/MapAttribution.jsx", error: String((e && e.message) || e) }); }

  // components/map/MapLegend.jsx
  try {
    (() => {
      const L = [['Scorrevole', 'var(--color-map-congestion-1)'], ['Rallentata', 'var(--color-map-congestion-2)'], ['Intensa', 'var(--color-map-congestion-3)'], ['Satura', 'var(--color-map-congestion-4)']];
      function MapLegend() {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-legend"
        }, L.map(l => /*#__PURE__*/React.createElement("span", {
          className: "nuo-legend__i",
          key: l[0]
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-legend__sw",
          style: {
            '--c': l[1]
          }
        }), l[0])));
      }
      Object.assign(__ds_scope, { MapLegend });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/map/MapLegend.jsx", error: String((e && e.message) || e) }); }

  // components/map/MapMarker.jsx
  try {
    (() => {
      function MapMarker({
        dept = 'traffic',
        state = 'normal'
      }) {
        const c = state === 'accepted' ? 'var(--color-status-accepted)' : state === 'rejected' ? 'var(--color-status-rejected)' : 'var(--color-accent)';
        return /*#__PURE__*/React.createElement("span", {
          className: "nuo-marker",
          style: {
            '--c': c
          }
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-marker__body"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: __ds_scope.DEPARTMENTS[dept].icon,
          size: 24
        })), /*#__PURE__*/React.createElement("span", {
          className: "nuo-marker__tail"
        }), state !== 'normal' && /*#__PURE__*/React.createElement("span", {
          className: "nuo-marker__badge"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: state === 'accepted' ? 'check' : 'x',
          size: 12,
          stroke: 3
        })));
      }
      Object.assign(__ds_scope, { MapMarker });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/map/MapMarker.jsx", error: String((e && e.message) || e) }); }

  // components/map/MapToggle.jsx
  try {
    (() => {
      function MapToggle({
        after = false,
        onAfterChange,
        iteration = 1,
        onIterationChange,
        iterations = 2
      }) {
        const step = d => onIterationChange && onIterationChange((iteration - 1 + d + iterations) % iterations + 1);
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-maptoggle"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-mt"
        }, /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: 'nuo-mt__lbl' + (!after ? ' is-on' : ''),
          onClick: () => onAfterChange && onAfterChange(false)
        }, "Prima"), /*#__PURE__*/React.createElement("button", {
          type: "button",
          role: "switch",
          "aria-checked": after,
          "aria-label": "Prima / Dopo",
          className: "nuo-mt__tr",
          onClick: () => onAfterChange && onAfterChange(!after)
        }, /*#__PURE__*/React.createElement("span", {
          className: 'nuo-track' + (after ? ' is-on' : '')
        })), /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: 'nuo-mt__lbl' + (after ? ' is-on' : ''),
          onClick: () => onAfterChange && onAfterChange(true)
        }, "Dopo")), /*#__PURE__*/React.createElement("div", {
          className: "nuo-mt",
          style: {
            padding: '0 5px'
          }
        }, /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: "nuo-mt__arrow",
          "aria-label": "Iterazione precedente",
          onClick: () => step(-1)
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "chevron-left"
        })), /*#__PURE__*/React.createElement("span", {
          className: "nuo-mt__it"
        }, "Iterazione ", iteration), /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: "nuo-mt__arrow",
          "aria-label": "Iterazione successiva",
          onClick: () => step(1)
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "chevron-right"
        }))));
      }
      Object.assign(__ds_scope, { MapToggle });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/map/MapToggle.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/EventManagerHeader.jsx
  try {
    (() => {
      function EventManagerHeader({
        running = false,
        fixed = false,
        onToggle
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-emh"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "calendar-clock",
          size: 20,
          style: {
            color: 'var(--color-accent)'
          }
        }), /*#__PURE__*/React.createElement("span", {
          className: "nuo-emh__title"
        }, "Analisi evento"), running && /*#__PURE__*/React.createElement("span", {
          className: "nuo-chip nuo-chip--sm",
          style: {
            '--c': 'var(--color-accent)',
            '--f': 'var(--color-state-fill-running)'
          }
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-dot nuo-dot--pulse"
        }), "In corso"), /*#__PURE__*/React.createElement("span", {
          style: {
            flex: 1
          }
        }), !fixed && /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: "nuo-emh__btn",
          "aria-expanded": "true",
          "aria-label": "Comprimi analisi evento",
          onClick: onToggle
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "chevron-up",
          size: 20
        })));
      }
      Object.assign(__ds_scope, { EventManagerHeader });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/EventManagerHeader.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/EventManagerRail.jsx
  try {
    (() => {
      function EventManagerRail({
        running = false,
        open = false,
        onToggle,
        className = ''
      }) {
        return /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: 'nuo-rail ' + className,
          "aria-expanded": open,
          "aria-label": "Analisi evento",
          onClick: onToggle
        }, running && /*#__PURE__*/React.createElement("span", {
          className: "nuo-loadbar"
        }), /*#__PURE__*/React.createElement("span", {
          className: "nuo-rail__row"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "calendar-clock",
          size: 20,
          style: {
            color: 'var(--color-accent)'
          }
        }), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: open ? 'chevron-up' : 'chevron-down',
          size: 20,
          style: {
            color: 'var(--color-text-secondary)'
          }
        })), running && /*#__PURE__*/React.createElement("span", {
          className: "nuo-chip nuo-chip--sm",
          style: {
            '--c': 'var(--color-accent)',
            '--f': 'var(--color-state-fill-running)'
          }
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-dot nuo-dot--pulse"
        }), "In corso"));
      }
      Object.assign(__ds_scope, { EventManagerRail });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/EventManagerRail.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/ModeSelector.jsx
  try {
    (() => {
      function ModeSelector({
        value = 'live',
        onChange
      }) {
        const M = [['live', 'LIVE', 'Dati reali'], ['scenario', 'SCENARIO', 'Simulazione']];
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-modes",
          role: "radiogroup",
          "aria-label": "Modalit\xE0"
        }, M.map(([k, n, s]) => /*#__PURE__*/React.createElement("button", {
          key: k,
          type: "button",
          role: "radio",
          "aria-checked": value === k,
          className: 'nuo-mode nuo-mode--' + k + (value === k ? ' is-active' : ''),
          onClick: () => onChange && onChange(k)
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-mode__name"
        }, n), /*#__PURE__*/React.createElement("span", {
          className: "nuo-mode__sub"
        }, s))));
      }
      Object.assign(__ds_scope, { ModeSelector });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/ModeSelector.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/SidebarButton.jsx
  try {
    (() => {
      function SidebarButton({
        icon,
        label,
        active = false,
        onClick
      }) {
        return /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: 'nuo-sbtn' + (active ? ' is-active' : ''),
          "aria-label": label,
          title: label,
          "aria-current": active ? 'page' : undefined,
          onClick: onClick
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: icon,
          size: 22
        }));
      }
      Object.assign(__ds_scope, { SidebarButton });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/SidebarButton.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/Sidebar.jsx
  try {
    (() => {
      function Sidebar({
        items = [],
        active,
        onSelect,
        brand = 'NUO',
        height
      }) {
        return /*#__PURE__*/React.createElement("nav", {
          className: "nuo-sidebar",
          style: height ? {
            height
          } : undefined,
          "aria-label": "Principale"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-sidebar__brand",
          title: "Sentrix"
        }, brand), /*#__PURE__*/React.createElement("div", {
          className: "nuo-sidebar__items"
        }, items.map(it => /*#__PURE__*/React.createElement(__ds_scope.SidebarButton, {
          key: it.id,
          icon: it.icon,
          label: it.label,
          active: active === it.id,
          onClick: () => onSelect && onSelect(it.id)
        }))));
      }
      Object.assign(__ds_scope, { Sidebar });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Sidebar.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/SimulationBanner.jsx
  try {
    (() => {
      function SimulationBanner({
        absolute = false
      }) {
        return /*#__PURE__*/React.createElement("span", {
          className: 'nuo-simbanner' + (absolute ? ' nuo-simbanner--abs' : '')
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "flask-conical",
          size: 20,
          stroke: 2
        }), "SIMULAZIONE");
      }
      Object.assign(__ds_scope, { SimulationBanner });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/SimulationBanner.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/SourceChip.jsx
  try {
    (() => {
      const {
        useState,
        useEffect,
        useRef
      } = React;
      function SourceChip({
        sources = [],
        defaultOpen = false
      }) {
        const [open, setOpen] = useState(defaultOpen);
        const ref = useRef(null);
        useEffect(() => {
          const h = e => {
            if (e.type === 'keydown' ? e.key === 'Escape' : ref.current && !ref.current.contains(e.target)) setOpen(false);
          };
          document.addEventListener('mousedown', h);
          document.addEventListener('keydown', h);
          return () => {
            document.removeEventListener('mousedown', h);
            document.removeEventListener('keydown', h);
          };
        }, []);
        if (!sources.length) return null;
        const text = sources.length === 1 ? 'Fonte non disponibile: ' + sources[0] : sources.length + ' fonti non disponibili';
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-src",
          ref: ref
        }, /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: "nuo-srcchip",
          "aria-expanded": open,
          onClick: () => setOpen(!open)
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "triangle-alert",
          size: 16
        }), text, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "chevron-down",
          size: 16
        })), open && /*#__PURE__*/React.createElement("div", {
          className: "nuo-pop",
          role: "dialog"
        }, sources.map(s => /*#__PURE__*/React.createElement("div", {
          key: s
        }, /*#__PURE__*/React.createElement("b", null, s), /*#__PURE__*/React.createElement("span", null, "Non disponibile. Si usano gli ultimi dati noti.")))));
      }
      Object.assign(__ds_scope, { SourceChip });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/SourceChip.jsx", error: String((e && e.message) || e) }); }

  // components/navigation/Tabs.jsx
  try {
    (() => {
      function Tabs({
        items = [],
        active,
        onChange
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-tabs",
          role: "tablist"
        }, items.map(t => /*#__PURE__*/React.createElement("button", {
          key: t.id,
          type: "button",
          role: "tab",
          "aria-selected": active === t.id,
          className: 'nuo-tab' + (active === t.id ? ' is-active' : ''),
          onClick: () => onChange && onChange(t.id)
        }, t.label)));
      }
      Object.assign(__ds_scope, { Tabs });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Tabs.jsx", error: String((e && e.message) || e) }); }

  // components/operations/AgentTimelineItem.jsx
  try {
    (() => {
      const T = {
        waiting: ['var(--color-text-muted)', 'clock', 'In attesa'],
        running: ['var(--color-accent)', 'loader-2', 'In esecuzione…'],
        done: ['var(--color-success)', 'check', 'Completato'],
        fallback: ['var(--color-warning)', 'check', 'Completato con testo di riserva'],
        error: ['var(--color-danger)', 'triangle-alert', 'Errore']
      };
      function AgentTimelineItem({
        name,
        status = 'waiting',
        duration,
        note,
        last = false
      }) {
        const t = T[status] || T.waiting;
        return /*#__PURE__*/React.createElement("div", {
          className: 'nuo-tl is-' + status + (last ? ' is-last' : '')
        }, !last && /*#__PURE__*/React.createElement("span", {
          className: "nuo-tl__line"
        }), /*#__PURE__*/React.createElement("span", {
          className: "nuo-tl__node",
          style: {
            '--c': t[0]
          }
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: t[1],
          size: 16,
          spin: status === 'running'
        })), /*#__PURE__*/React.createElement("div", {
          className: "nuo-tl__body"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-tl__row"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-tl__name"
        }, name), /*#__PURE__*/React.createElement("span", {
          className: "nuo-tl__dur"
        }, duration || '—')), /*#__PURE__*/React.createElement("div", {
          className: "nuo-tl__desc"
        }, note || t[2])));
      }
      Object.assign(__ds_scope, { AgentTimelineItem });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/AgentTimelineItem.jsx", error: String((e && e.message) || e) }); }

  // components/operations/DecisionCallout.jsx
  try {
    (() => {
      function DecisionCallout({
        title = 'Decisione umana richiesta',
        measure,
        children
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout nuo-callout--decision",
          role: "alert"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "triangle-alert",
          size: 28,
          style: {
            color: 'var(--color-warning)'
          }
        }), /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout__body"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout__title"
        }, title), /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout__msg"
        }, measure), children));
      }
      Object.assign(__ds_scope, { DecisionCallout });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/DecisionCallout.jsx", error: String((e && e.message) || e) }); }

  // components/operations/DecisionLogRow.jsx
  try {
    (() => {
      const A = {
        system: ['cpu', 'Sistema'],
        agent: ['bot', 'Agente'],
        user: ['user', 'Utente']
      };
      function DecisionLogRow({
        time,
        actor = 'system',
        actorLabel,
        decision,
        reason,
        head = false,
        variant = 'wide',
        hover = false
      }) {
        const vc = variant === 'log' ? ' nuo-logrow--log' : '';
        if (head) return /*#__PURE__*/React.createElement("div", {
          className: 'nuo-logrow is-head' + vc
        }, /*#__PURE__*/React.createElement("span", null, "Ora"), /*#__PURE__*/React.createElement("span", null, "Attore"), /*#__PURE__*/React.createElement("span", null, "Decisione e motivo"));
        const a = __ds_scope.DEPARTMENTS[actor] ? [__ds_scope.DEPARTMENTS[actor].icon, __ds_scope.DEPARTMENTS[actor].name] : A[actor] || A.system;
        return /*#__PURE__*/React.createElement("div", {
          className: 'nuo-logrow' + vc + (hover ? ' is-hover' : '')
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-logrow__time"
        }, time), /*#__PURE__*/React.createElement("span", {
          className: "nuo-logrow__actor"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: a[0],
          size: 16
        }), actorLabel || a[1]), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("div", {
          className: "nuo-logrow__dec"
        }, decision), reason && /*#__PURE__*/React.createElement("div", {
          className: "nuo-logrow__why"
        }, reason)));
      }
      Object.assign(__ds_scope, { DecisionLogRow });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/DecisionLogRow.jsx", error: String((e && e.message) || e) }); }

  // components/operations/ErrorCallout.jsx
  try {
    (() => {
      function ErrorCallout({
        message,
        instruction
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout nuo-callout--error",
          role: "alert"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "triangle-alert",
          size: 24,
          style: {
            color: 'var(--color-danger)'
          }
        }), /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout__body"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout__msg"
        }, message), instruction && /*#__PURE__*/React.createElement("div", {
          className: "nuo-callout__ins"
        }, instruction)));
      }
      Object.assign(__ds_scope, { ErrorCallout });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/ErrorCallout.jsx", error: String((e && e.message) || e) }); }

  // components/operations/EventManager.jsx
  try {
    (() => {
      const PRESETS = [50000, 150000, 300000];
      const fmt = n => new Intl.NumberFormat('it-IT', {
        useGrouping: 'always'
      }).format(n);
      function List({
        icon,
        items,
        onRemove,
        hint
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-em__list"
        }, items.map((s, i) => /*#__PURE__*/React.createElement("div", {
          className: "nuo-em__row",
          key: s + i
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: icon,
          size: 16
        }), /*#__PURE__*/React.createElement("span", null, s), /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: "nuo-em__rm",
          "aria-label": 'Rimuovi ' + s,
          onClick: () => onRemove && onRemove(i)
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "x",
          size: 16
        })))), /*#__PURE__*/React.createElement("div", {
          className: "nuo-field__hint"
        }, hint));
      }
      function EventManager({
        attendance = '',
        onAttendanceChange,
        closures = [],
        stops = [],
        onRemoveClosure,
        onRemoveStop,
        onAnalyze,
        analyzing = false
      }) {
        const n = parseInt(String(attendance).replace(/\D/g, ''), 10);
        const invalid = attendance !== '' && !/^[\d.]+$/.test(attendance);
        const disabled = attendance === '' || invalid || !n;
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-card nuo-em"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-field"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-field__label"
        }, "Affluenza ipotizzata"), /*#__PURE__*/React.createElement("div", {
          className: "nuo-em__presets"
        }, PRESETS.map(p => /*#__PURE__*/React.createElement("button", {
          key: p,
          type: "button",
          className: 'nuo-preset' + (n === p ? ' is-on' : ''),
          onClick: () => onAttendanceChange && onAttendanceChange(fmt(p))
        }, fmt(p)))), /*#__PURE__*/React.createElement(__ds_scope.TextField, {
          value: attendance,
          onChange: onAttendanceChange,
          placeholder: "es. 150.000",
          suffix: "persone",
          mono: true,
          inputMode: "numeric",
          error: invalid ? 'Inserisci un numero valido' : undefined,
          id: "em-attendance"
        })), /*#__PURE__*/React.createElement("div", {
          className: "nuo-field"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-field__label"
        }, "Chiusure strada"), /*#__PURE__*/React.createElement(List, {
          icon: "ban",
          items: closures,
          onRemove: onRemoveClosure,
          hint: "Clicca una strada sulla mappa per chiuderla"
        })), /*#__PURE__*/React.createElement("div", {
          className: "nuo-field"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-field__label"
        }, "Interruzioni fermata"), /*#__PURE__*/React.createElement(List, {
          icon: "bus",
          items: stops,
          onRemove: onRemoveStop,
          hint: "Clicca una fermata sulla mappa"
        })), /*#__PURE__*/React.createElement(__ds_scope.Button, {
          block: true,
          loading: analyzing,
          disabled: disabled,
          onClick: onAnalyze
        }, "Analizza"));
      }
      Object.assign(__ds_scope, { EventManager });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/EventManager.jsx", error: String((e && e.message) || e) }); }

  // components/operations/IterationTable.jsx
  try {
    (() => {
      function IterationTable({
        columns = ['Iter. 1', 'Iter. 2', 'Iter. 3'],
        rows = [],
        hoverRow = -1
      }) {
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-log"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-logrow nuo-logrow--compare is-head"
        }, /*#__PURE__*/React.createElement("span", null, "Metrica"), columns.map(c => /*#__PURE__*/React.createElement("span", {
          key: c
        }, c))), rows.map((r, i) => /*#__PURE__*/React.createElement("div", {
          key: r.metric,
          className: 'nuo-logrow nuo-logrow--compare' + (hoverRow === i ? ' is-hover' : '')
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-cmp__metric"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-cmp__name"
        }, r.metric), r.badge && /*#__PURE__*/React.createElement(__ds_scope.Badge, {
          kind: r.badge
        })), r.values.map((v, k) => /*#__PURE__*/React.createElement("span", {
          className: "nuo-cmp__val",
          key: k
        }, v)))));
      }
      Object.assign(__ds_scope, { IterationTable });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/IterationTable.jsx", error: String((e && e.message) || e) }); }

  // components/operations/PlanMeasureRow.jsx
  try {
    (() => {
      function PlanMeasureRow({
        n,
        text,
        dept = 'traffic'
      }) {
        const d = __ds_scope.DEPARTMENTS[dept];
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-meas"
        }, /*#__PURE__*/React.createElement("span", {
          className: "nuo-meas__n"
        }, n), /*#__PURE__*/React.createElement("div", {
          className: "nuo-meas__body"
        }, /*#__PURE__*/React.createElement("div", {
          className: "nuo-meas__text"
        }, text), /*#__PURE__*/React.createElement("div", {
          className: "nuo-meas__dept"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "arrow-right",
          size: 16
        }), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: d.icon,
          size: 16
        }), d.name)));
      }
      Object.assign(__ds_scope, { PlanMeasureRow });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/PlanMeasureRow.jsx", error: String((e && e.message) || e) }); }

  // components/operations/RequestCard.jsx
  try {
    (() => {
      const R = {
        CREATED: ['Creata', 'var(--color-status-pending)', 'plus'],
        SENT: ['Inviata', 'var(--color-status-pending)', 'send'],
        RECEIVED: ['Ricevuta', 'var(--color-status-pending)', 'mail'],
        ACCEPTED: ['Accettata', 'var(--color-status-accepted)', 'check'],
        REJECTED: ['Rifiutata', 'var(--color-status-rejected)', 'x'],
        IN_PROGRESS: ['In corso', 'var(--color-status-pending)', null],
        COMPLETED: ['Completata', 'var(--color-status-accepted)', 'check-check']
      };
      const FILL = {
        'var(--color-status-pending)': 'var(--color-state-fill-waiting)',
        'var(--color-status-accepted)': 'var(--color-state-fill-done)',
        'var(--color-status-rejected)': 'var(--color-state-fill-error)'
      };
      function RequestCard({
        dept = 'traffic',
        code,
        status = 'CREATED',
        measure,
        rejection,
        alternativeTo
      }) {
        const r = R[status] || R.CREATED;
        return /*#__PURE__*/React.createElement("div", {
          className: 'nuo-req' + (alternativeTo ? ' nuo-req--alt' : '')
        }, alternativeTo && /*#__PURE__*/React.createElement("div", {
          className: "nuo-req__alt"
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "corner-up-left",
          size: 16
        }), "Alternativa a ", alternativeTo), /*#__PURE__*/React.createElement("div", {
          className: "nuo-req__head"
        }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
          className: "nuo-req__dept"
        }, __ds_scope.DEPARTMENTS[dept].name), /*#__PURE__*/React.createElement("div", {
          className: "nuo-req__code"
        }, code)), /*#__PURE__*/React.createElement("span", {
          className: "nuo-chip nuo-chip--sm",
          style: {
            '--c': r[1],
            '--f': FILL[r[1]]
          }
        }, r[2] ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: r[2],
          size: 16
        }) : /*#__PURE__*/React.createElement("span", {
          className: "nuo-dot nuo-dot--pulse"
        }), r[0])), /*#__PURE__*/React.createElement("div", {
          className: "nuo-req__measure"
        }, measure), status === 'REJECTED' && rejection && /*#__PURE__*/React.createElement("div", {
          className: "nuo-req__rej"
        }, /*#__PURE__*/React.createElement("b", null, rejection.code), rejection.reason));
      }
      Object.assign(__ds_scope, { RequestCard });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/RequestCard.jsx", error: String((e && e.message) || e) }); }

  // components/operations/RequestGroup.jsx
  try {
    (() => {
      function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
      const {
        useState
      } = React;
      function RequestGroup({
        request,
        alternatives = [],
        open,
        defaultOpen = false,
        onToggle,
        unread = false
      }) {
        const [o, setO] = useState(defaultOpen);
        const isOpen = open !== undefined ? open : o;
        const n = alternatives.length;
        const toggle = () => {
          setO(!isOpen);
          onToggle && onToggle(!isOpen);
        };
        return /*#__PURE__*/React.createElement("div", {
          className: "nuo-rg"
        }, /*#__PURE__*/React.createElement(__ds_scope.RequestCard, request), n > 0 && /*#__PURE__*/React.createElement("button", {
          type: "button",
          className: "nuo-rg__toggle",
          "aria-expanded": isOpen,
          onClick: toggle
        }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: "corner-down-right",
          size: 16
        }), /*#__PURE__*/React.createElement("span", null, n === 1 ? '1 alternativa' : n + ' alternative'), !isOpen && unread && /*#__PURE__*/React.createElement("span", {
          className: "nuo-rg__new"
        }, /*#__PURE__*/React.createElement("i", null), "Nuova risposta"), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
          name: isOpen ? 'chevron-up' : 'chevron-down',
          size: 20,
          style: {
            marginLeft: 'auto'
          }
        })), n > 0 && isOpen && /*#__PURE__*/React.createElement("div", {
          className: "nuo-rg__alts"
        }, alternatives.map(a => /*#__PURE__*/React.createElement(__ds_scope.RequestCard, _extends({
          key: a.code
        }, a, {
          alternativeTo: a.alternativeTo || request.code
        })))));
      }
      Object.assign(__ds_scope, { RequestGroup });
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "components/operations/RequestGroup.jsx", error: String((e && e.message) || e) }); }

  // ui_kits/dashboard/MapPanel.jsx
  try {
    (() => {
      (function () {
        const {
          MapToggle,
          LayerToggleButton,
          LayerPanel,
          MapMarker,
          MapLegend,
          MapAttribution,
          Icon
        } = window.DesignSystem_1776e0;
        const CLS = ['', '--color-map-congestion-1', '--color-map-congestion-2', '--color-map-congestion-3', '--color-map-congestion-4'];
        const CNAME = ['', 'Scorrevole', 'Rallentata', 'Intensa', 'Satura'];
        const ROADS = [{
          id: 'Via Marina',
          d: 'M40 560L300 520L560 540L960 500',
          c: [4, 3, 3, 2],
          at: [300, 520]
        }, {
          id: 'Corso Umberto I',
          d: 'M120 120L330 260L520 330L760 420',
          c: [3, 2, 2, 1],
          at: [425, 295]
        }, {
          id: 'Via Toledo',
          d: 'M520 40L520 330L500 540',
          c: [2, 2, 1, 1],
          at: [520, 330]
        }, {
          id: 'Via Caracciolo',
          d: 'M60 400L360 380L700 250L940 180',
          c: [1, 1, 1, 1],
          at: [360, 380]
        }, {
          id: 'Circumvallazione',
          d: 'M780 60L800 300L760 420L780 640',
          c: [3, 2, 2, 2],
          at: [800, 300]
        }];
        const STOPS = [{
          id: 'Fermata Garibaldi',
          x: 300,
          y: 520,
          l: [0, 0]
        }, {
          id: 'Fermata Municipio',
          x: 520,
          y: 540,
          l: [1, 1]
        }, {
          id: 'Fermata Duomo',
          x: 780,
          y: 300,
          l: [2, 1]
        }, {
          id: 'Fermata Mergellina',
          x: 360,
          y: 380,
          l: [0, 0]
        }];
        const SR = [6, 9, 13],
          SC = ['--color-map-stop-low', '--color-map-stop-mid', '--color-map-stop-over'];
        const pc = (x, y) => ({
          left: x / 10 + '%',
          top: y / 7 + '%'
        });
        function MapPanel({
          after,
          onAfter,
          iteration,
          onIteration,
          layers,
          onLayer,
          closures,
          onCloseRoad,
          onStop,
          requests,
          hasRun
        }) {
          const [tip, setTip] = React.useState(null);
          const [lp, setLp] = React.useState(false);
          const on = id => layers.find(l => l.id === id).on;
          const sel = !after ? 0 : iteration === 1 ? 1 : 2;
          const stateOf = d => {
            const r = requests.filter(x => x.dept === d).slice(-1)[0];
            return r ? r.status === 'ACCEPTED' || r.status === 'COMPLETED' ? 'accepted' : r.status === 'REJECTED' ? 'rejected' : 'normal' : 'normal';
          };
          const mv = (e, text) => {
            const b = e.currentTarget.closest('[data-map]').getBoundingClientRect();
            setTip({
              x: e.clientX - b.left + 12,
              y: e.clientY - b.top + 12,
              text
            });
          };
          const closed = id => after && closures.includes(id);
          return /*#__PURE__*/React.createElement("div", {
            "data-map": "1",
            style: {
              position: 'relative',
              height: '100%',
              minHeight: 0,
              overflow: 'hidden',
              borderRadius: 10,
              background: '#0A0E17',
              border: '1px solid var(--color-border-card)'
            }
          }, /*#__PURE__*/React.createElement("svg", {
            viewBox: "0 0 1000 700",
            preserveAspectRatio: "none",
            style: {
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%'
            }
          }, on('e') && /*#__PURE__*/React.createElement("polygon", {
            points: "560,90 770,90 770,230 560,230",
            fill: "var(--color-map-event-area)",
            fillOpacity: ".12",
            stroke: "var(--color-map-event-area)",
            strokeWidth: "2",
            vectorEffect: "non-scaling-stroke",
            onMouseMove: e => mv(e, 'Area evento'),
            onMouseLeave: () => setTip(null)
          }), on('c') && ROADS.map(r => {
            const cls = r.c[sel];
            return /*#__PURE__*/React.createElement("path", {
              key: r.id,
              d: r.d,
              fill: "none",
              stroke: 'var(' + CLS[cls] + ')',
              strokeWidth: "6",
              strokeLinecap: "round",
              strokeLinejoin: "round",
              vectorEffect: "non-scaling-stroke",
              style: {
                opacity: .4,
                cursor: 'pointer',
                transition: 'opacity 150ms ease-out'
              },
              onMouseEnter: e => {
                e.currentTarget.style.opacity = 1;
              },
              onMouseMove: e => mv(e, r.id + ' · ' + CNAME[cls]),
              onMouseLeave: e => {
                e.currentTarget.style.opacity = .4;
                setTip(null);
              },
              onClick: () => onCloseRoad(r.id)
            });
          }), on('x') && ROADS.filter(r => closed(r.id)).map(r => /*#__PURE__*/React.createElement("path", {
            key: r.id,
            d: r.d,
            fill: "none",
            stroke: "var(--color-map-closure)",
            strokeWidth: "4",
            strokeDasharray: "10 8",
            vectorEffect: "non-scaling-stroke",
            pointerEvents: "none"
          })), on('d') && closed('Corso Umberto I') && /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("path", {
            d: "M330 262L300 330L430 420L580 380L520 332",
            fill: "none",
            stroke: "var(--color-map-detour)",
            strokeWidth: "4",
            strokeLinecap: "round",
            strokeLinejoin: "round",
            vectorEffect: "non-scaling-stroke"
          }), /*#__PURE__*/React.createElement("circle", {
            cx: "330",
            cy: "262",
            r: "5",
            fill: "var(--color-map-detour)"
          }), /*#__PURE__*/React.createElement("path", {
            d: "M510 320L535 334L508 344Z",
            fill: "var(--color-map-detour)"
          })), on('f') && STOPS.map(s => /*#__PURE__*/React.createElement("circle", {
            key: s.id,
            cx: s.x,
            cy: s.y,
            r: SR[s.l[after ? 1 : 0]],
            fill: 'var(' + SC[s.l[after ? 1 : 0]] + ')',
            stroke: "var(--color-bg)",
            strokeWidth: "2",
            vectorEffect: "non-scaling-stroke",
            style: {
              cursor: 'pointer'
            },
            onMouseMove: e => mv(e, s.id),
            onMouseLeave: () => setTip(null),
            onClick: () => onStop(s.id)
          }))), on('x') && ROADS.filter(r => closed(r.id)).map(r => /*#__PURE__*/React.createElement("span", {
            key: r.id,
            style: {
              position: 'absolute',
              ...pc(r.at[0], r.at[1]),
              transform: 'translate(-50%,-50%)',
              width: 24,
              height: 24,
              borderRadius: '50%',
              background: 'var(--color-bg)',
              border: '2px solid var(--color-map-closure)',
              color: 'var(--color-map-closure)',
              display: 'grid',
              placeItems: 'center',
              pointerEvents: 'none'
            }
          }, /*#__PURE__*/React.createElement(Icon, {
            name: "ban",
            size: 16,
            stroke: 2
          }))), on('r') && requests.length > 0 && [['traffic', 330, 260], ['police', 520, 330], ['transport', 780, 300], ['comms', 520, 170]].filter(m => requests.some(r => r.dept === m[0]) || m[0] === 'traffic' && hasRun).map(m => /*#__PURE__*/React.createElement("span", {
            key: m[0],
            style: {
              position: 'absolute',
              ...pc(m[1], m[2]),
              transform: 'translate(-22px,-52px)'
            }
          }, /*#__PURE__*/React.createElement(MapMarker, {
            dept: m[0],
            state: stateOf(m[0])
          }))), /*#__PURE__*/React.createElement("div", {
            style: {
              position: 'absolute',
              top: 16,
              left: 16
            }
          }, /*#__PURE__*/React.createElement(MapToggle, {
            after: after,
            onAfterChange: onAfter,
            iteration: iteration,
            onIterationChange: onIteration
          })), /*#__PURE__*/React.createElement("div", {
            style: {
              position: 'absolute',
              top: 16,
              right: 16,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              gap: 8
            }
          }, /*#__PURE__*/React.createElement(LayerToggleButton, {
            open: lp,
            onToggle: () => setLp(!lp)
          }), lp && /*#__PURE__*/React.createElement(LayerPanel, {
            layers: layers,
            onToggle: onLayer
          })), /*#__PURE__*/React.createElement("div", {
            style: {
              position: 'absolute',
              bottom: 16,
              left: 16
            }
          }, /*#__PURE__*/React.createElement(MapLegend, null)), /*#__PURE__*/React.createElement("div", {
            style: {
              position: 'absolute',
              bottom: 16,
              right: 16
            }
          }, /*#__PURE__*/React.createElement(MapAttribution, null)), /*#__PURE__*/React.createElement("div", {
            style: {
              position: 'absolute',
              left: '50%',
              bottom: 70,
              transform: 'translateX(-50%)',
              font: '500 14px/20px var(--font-ui)',
              color: 'var(--color-text-muted)',
              pointerEvents: 'none'
            }
          }), tip && /*#__PURE__*/React.createElement("div", {
            style: {
              position: 'absolute',
              left: tip.x,
              top: tip.y,
              padding: '8px 10px',
              background: 'var(--color-surface-2)',
              border: '1px solid var(--color-border-tooltip)',
              borderRadius: 4,
              font: '500 14px/20px var(--font-ui)',
              pointerEvents: 'none',
              whiteSpace: 'nowrap'
            }
          }, tip.text));
        }
        window.MapPanel = MapPanel;
        window.MAP_STOP_NAMES = STOPS.map(s => s.id);
      })();
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/MapPanel.jsx", error: String((e && e.message) || e) }); }

  // ui_kits/dashboard/Panels.jsx
  try {
    (() => {
      function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
      (function () {
        const {
          RunStatus,
          IterationIndicator,
          AgentTimelineItem,
          DepartmentCard,
          RequestCard,
          RequestGroup,
          DecisionCallout,
          EmptyState,
          Tabs,
          ManualSwitch,
          Button,
          Card,
          DecisionLogRow,
          MetricCard
        } = window.DesignSystem_1776e0;
        const AG = [['Traffic Agent', 1, 2, '3,2 s'], ['Transit Agent', 1, 2, '2,8 s'], ['Planner', 3, 4, '6,0 s'], ['Verifier', 7, 7, '1,6 s']];
        function agentStatus(a, stage) {
          if (stage < 0 || stage < a[1]) return 'waiting';
          if (stage <= a[2]) return 'running';
          return a[0] === 'Planner' ? 'fallback' : 'done';
        }
        const DEPT = [['traffic', 8, 12], ['police', 6, 10], ['transport', 5, 6], ['comms', 3, 4]];
        function Metrics({
          after,
          mode,
          loading
        }) {
          const b = after ? mode === 'scenario' ? 'simulated' : 'estimate' : 'real';
          const v = after ? ['9.340', '31', '6.120', '3', '11,2'] : ['12.480', '24', '9.870', '7', '15,6'];
          const d = after ? [{
            tone: 'better',
            direction: 'down',
            text: '−25,2%'
          }, {
            tone: 'better',
            direction: 'up',
            text: '+29,2%'
          }, {
            tone: 'better',
            direction: 'down',
            text: '−38,0%'
          }, {
            tone: 'better',
            direction: 'down',
            text: '−4'
          }, {
            tone: 'better',
            direction: 'down',
            text: '−28,2%'
          }] : Array(5).fill({
            tone: 'neutral',
            text: '0,0%'
          });
          const B = ['12.480', '24', '9.870', '7', '15,6'];
          const PR = [['Fonte', 'Modello di traffico'], ['Metodo', 'Ore × veicoli in ritardo'], ['Unità', 'h'], ['Ora del dato', '21:04']];
          const L = ['Ore-veicolo perse', 'Velocità media', 'Persone in area', 'Fermate sovraccariche', 'Attesa media'],
            U = ['h', 'km/h', '', '', 'min'];
          return /*#__PURE__*/React.createElement("div", {
            style: {
              display: 'grid',
              gridTemplateColumns: 'repeat(5,minmax(0,1fr))',
              gap: 16
            }
          }, L.map((l, i) => /*#__PURE__*/React.createElement(MetricCard, {
            key: l,
            label: l,
            value: v[i],
            before: after ? B[i] : undefined,
            unit: U[i] || undefined,
            delta: d[i],
            badge: b,
            loading: loading,
            compact: i !== 0,
            provenance: {
              rows: PR
            }
          })));
        }
        function RightPanel({
          stage,
          waiting,
          requests,
          manual,
          onManual,
          onResolve,
          after,
          iteration,
          log = []
        }) {
          const [tab, setTab] = React.useState('agents');
          React.useEffect(() => {
            if (waiting) setTab('ops');
          }, [waiting]);
          const state = waiting ? 'DECISIONE' : stage < 0 ? 'DONE' : ['INTAKE', 'ANALYZE', 'RECONCILE', 'PLAN', 'DISPATCH', 'AWAIT', 'REPLAN', 'VERIFY', 'DONE'][stage];
          const idle = stage < 0;
          const acc = requests.filter(r => r.status === 'ACCEPTED' || r.status === 'COMPLETED').map(r => r.dept);
          const rem = (d, n) => Math.max(0, n - (acc.includes(d) ? d === 'police' ? 2 : 1 : 0));
          const originals = requests.filter(r => !r.alternativeTo);
          return /*#__PURE__*/React.createElement("div", {
            style: {
              display: 'flex',
              flexDirection: 'column',
              gap: 16,
              minHeight: 0
            }
          }, /*#__PURE__*/React.createElement(Tabs, {
            active: tab,
            onChange: setTab,
            items: [{
              id: 'agents',
              label: 'Agenti'
            }, {
              id: 'ops',
              label: 'Operations'
            }, {
              id: 'log',
              label: 'Decisioni'
            }]
          }), tab === 'agents' && /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
            style: {
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              gap: 12,
              flexWrap: 'wrap'
            }
          }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
            className: "t-lg",
            style: {
              marginBottom: 10
            }
          }, "Stato del run"), idle ? /*#__PURE__*/React.createElement("div", {
            className: "t-xs",
            style: {
              color: 'var(--color-text-secondary)'
            }
          }, "Nessun run in corso. Imposta l'evento e premi Analizza.") : /*#__PURE__*/React.createElement(RunStatus, {
            state: state,
            step: 5
          })), /*#__PURE__*/React.createElement(IterationIndicator, {
            current: after ? iteration : Math.min(1, iteration),
            total: 3
          })), !idle && /*#__PURE__*/React.createElement("div", {
            style: {
              marginTop: 16
            }
          }, AG.map((a, i) => /*#__PURE__*/React.createElement(AgentTimelineItem, {
            key: a[0],
            name: a[0],
            status: agentStatus(a, stage),
            duration: agentStatus(a, stage) === 'waiting' ? undefined : agentStatus(a, stage) === 'running' ? '…' : a[3],
            note: agentStatus(a, stage) === 'fallback' ? 'Completato con testo di riserva: risposta non valida' : undefined,
            last: i === AG.length - 1
          })))), tab === 'ops' && /*#__PURE__*/React.createElement(React.Fragment, null, waiting && /*#__PURE__*/React.createElement(DecisionCallout, {
            measure: "Presidio incroci Corso Umberto I"
          }, /*#__PURE__*/React.createElement("div", {
            style: {
              display: 'flex',
              gap: 8,
              marginTop: 12
            }
          }, /*#__PURE__*/React.createElement(Button, {
            icon: "check",
            onClick: () => onResolve(true)
          }, "Accetta misura"), /*#__PURE__*/React.createElement(Button, {
            variant: "stroke",
            icon: "x",
            onClick: () => onResolve(false)
          }, "Rifiuta misura"))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
            className: "t-lg",
            style: {
              marginBottom: 12
            }
          }, "Dipartimenti"), /*#__PURE__*/React.createElement("div", {
            style: {
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 10
            }
          }, DEPT.map(d => /*#__PURE__*/React.createElement(DepartmentCard, {
            key: d[0],
            dept: d[0],
            remaining: rem(d[0], d[1]),
            total: d[2]
          })))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
            className: "t-lg",
            style: {
              marginBottom: 12
            }
          }, "Richieste operative"), /*#__PURE__*/React.createElement("div", {
            style: {
              marginBottom: 16
            }
          }, /*#__PURE__*/React.createElement(ManualSwitch, {
            checked: manual,
            onChange: onManual
          })), requests.length === 0 && /*#__PURE__*/React.createElement(EmptyState, {
            icon: "send",
            title: "Nessuna richiesta inviata"
          }), originals.map(r => {
            const alts = requests.filter(x => x.alternativeTo === r.code);
            return /*#__PURE__*/React.createElement(RequestGroup, {
              key: r.code,
              request: r,
              alternatives: alts,
              unread: alts.length > 0
            });
          }))), tab === 'log' && /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
            className: "t-lg",
            style: {
              marginBottom: 12
            }
          }, "Registro decisioni"), log.length === 0 ? /*#__PURE__*/React.createElement(EmptyState, {
            icon: "scroll-text",
            title: "Nessuna decisione registrata"
          }) : /*#__PURE__*/React.createElement("div", {
            className: "nuo-log"
          }, /*#__PURE__*/React.createElement(DecisionLogRow, {
            head: true,
            variant: "log"
          }), log.map((r, i) => /*#__PURE__*/React.createElement(DecisionLogRow, _extends({
            key: i,
            variant: "log"
          }, r))))));
        }
        function LogScreen({
          log
        }) {
          return /*#__PURE__*/React.createElement("div", {
            style: {
              padding: 16,
              overflow: 'auto',
              minHeight: 0
            }
          }, /*#__PURE__*/React.createElement("div", {
            className: "t-2xl",
            style: {
              marginBottom: 16
            }
          }, "Registro decisioni"), /*#__PURE__*/React.createElement("div", {
            className: "nuo-log",
            style: {
              maxWidth: 960
            }
          }, /*#__PURE__*/React.createElement(DecisionLogRow, {
            head: true
          }), log.map((r, i) => /*#__PURE__*/React.createElement(DecisionLogRow, _extends({
            key: i
          }, r)))));
        }
        function RequestsScreen({
          requests
        }) {
          return /*#__PURE__*/React.createElement("div", {
            style: {
              padding: 16,
              overflow: 'auto',
              minHeight: 0
            }
          }, /*#__PURE__*/React.createElement("div", {
            className: "t-2xl",
            style: {
              marginBottom: 16
            }
          }, "Richieste e dipartimenti"), /*#__PURE__*/React.createElement("div", {
            style: {
              display: 'grid',
              gridTemplateColumns: 'repeat(4,minmax(0,1fr))',
              gap: 16,
              marginBottom: 24
            }
          }, DEPT.map(d => /*#__PURE__*/React.createElement(DepartmentCard, {
            key: d[0],
            dept: d[0],
            remaining: d[1],
            total: d[2]
          }))), /*#__PURE__*/React.createElement("div", {
            style: {
              maxWidth: 640
            }
          }, requests.length ? requests.map(r => /*#__PURE__*/React.createElement(RequestCard, _extends({
            key: r.code
          }, r))) : /*#__PURE__*/React.createElement("div", {
            className: "t-sm",
            style: {
              color: 'var(--color-text-secondary)'
            }
          }, "Nessuna richiesta: avvia un'analisi dalla Plancia.")));
        }
        Object.assign(window, {
          Metrics,
          RightPanel,
          LogScreen,
          RequestsScreen
        });
      })();
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/Panels.jsx", error: String((e && e.message) || e) }); }

  // ui_kits/dashboard/Shell.jsx
  try {
    (() => {
      (function () {
        const {
          Sidebar: DsSidebar,
          ModeSelector,
          SourceChip,
          SimulationBanner
        } = window.DesignSystem_1776e0;
        const NAV = [['dashboard', 'layout-dashboard', 'Plancia'], ['requests', 'building-2', 'Richieste e dipartimenti'], ['log', 'scroll-text', 'Registro decisioni']];
        function Sidebar({
          screen,
          onScreen
        }) {
          return /*#__PURE__*/React.createElement(DsSidebar, {
            items: NAV.map(n => ({
              id: n[0],
              icon: n[1],
              label: n[2]
            })),
            active: screen,
            onSelect: onScreen
          });
        }
        function TopBar({
          mode,
          onMode,
          sources
        }) {
          return /*#__PURE__*/React.createElement("header", {
            style: {
              position: 'relative',
              height: 64,
              flex: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 16,
              padding: '0 16px',
              borderBottom: '1px solid var(--color-border)',
              background: 'var(--color-surface-1)'
            }
          }, /*#__PURE__*/React.createElement("div", {
            style: {
              font: '700 20px/28px var(--font-ui)',
              letterSpacing: '-.01em'
            }
          }, "Sentrix"), /*#__PURE__*/React.createElement("div", {
            style: {
              flex: 1
            }
          }), mode === 'scenario' && /*#__PURE__*/React.createElement(SimulationBanner, {
            absolute: true
          }), /*#__PURE__*/React.createElement(SourceChip, {
            sources: sources
          }), /*#__PURE__*/React.createElement(ModeSelector, {
            value: mode,
            onChange: onMode
          }));
        }
        Object.assign(window, {
          Sidebar,
          TopBar
        });
      })();
    })();
  } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/Shell.jsx", error: String((e && e.message) || e) }); }

  __ds_ns.Badge = __ds_scope.Badge;

  __ds_ns.Button = __ds_scope.Button;

  __ds_ns.Card = __ds_scope.Card;

  __ds_ns.EmptyState = __ds_scope.EmptyState;

  __ds_ns.DEPARTMENTS = __ds_scope.DEPARTMENTS;

  __ds_ns.Icon = __ds_scope.Icon;

  __ds_ns.Tooltip = __ds_scope.Tooltip;

  __ds_ns.DepartmentCard = __ds_scope.DepartmentCard;

  __ds_ns.IterationIndicator = __ds_scope.IterationIndicator;

  __ds_ns.MetricCard = __ds_scope.MetricCard;

  __ds_ns.ProvenanceTooltip = __ds_scope.ProvenanceTooltip;

  __ds_ns.RunStatus = __ds_scope.RunStatus;

  __ds_ns.EventFormRow = __ds_scope.EventFormRow;

  __ds_ns.FieldHeader = __ds_scope.FieldHeader;

  __ds_ns.ManualSwitch = __ds_scope.ManualSwitch;

  __ds_ns.TextField = __ds_scope.TextField;

  __ds_ns.LayerPanel = __ds_scope.LayerPanel;

  __ds_ns.LayerToggleButton = __ds_scope.LayerToggleButton;

  __ds_ns.MapAttribution = __ds_scope.MapAttribution;

  __ds_ns.MapLegend = __ds_scope.MapLegend;

  __ds_ns.MapMarker = __ds_scope.MapMarker;

  __ds_ns.MapToggle = __ds_scope.MapToggle;

  __ds_ns.EventManagerHeader = __ds_scope.EventManagerHeader;

  __ds_ns.EventManagerRail = __ds_scope.EventManagerRail;

  __ds_ns.ModeSelector = __ds_scope.ModeSelector;

  __ds_ns.Sidebar = __ds_scope.Sidebar;

  __ds_ns.SidebarButton = __ds_scope.SidebarButton;

  __ds_ns.SimulationBanner = __ds_scope.SimulationBanner;

  __ds_ns.SourceChip = __ds_scope.SourceChip;

  __ds_ns.Tabs = __ds_scope.Tabs;

  __ds_ns.AgentTimelineItem = __ds_scope.AgentTimelineItem;

  __ds_ns.DecisionCallout = __ds_scope.DecisionCallout;

  __ds_ns.DecisionLogRow = __ds_scope.DecisionLogRow;

  __ds_ns.ErrorCallout = __ds_scope.ErrorCallout;

  __ds_ns.EventManager = __ds_scope.EventManager;

  __ds_ns.IterationTable = __ds_scope.IterationTable;

  __ds_ns.PlanMeasureRow = __ds_scope.PlanMeasureRow;

  __ds_ns.RequestCard = __ds_scope.RequestCard;

  __ds_ns.RequestGroup = __ds_scope.RequestGroup;

})();
