import type { TailwindTokens } from "./token-types.ts";

export const tokenTheme: TailwindTokens["extend"] = {
  "colors": {
    "bg": "var(--color-bg)",
    "surface-1": "var(--color-surface-1)",
    "surface-2": "var(--color-surface-2)",
    "surface-3": "var(--color-surface-3)",
    "border": "var(--color-border)",
    "border-strong": "var(--color-border-strong)",
    "border-card": "var(--color-border-card)",
    "border-tooltip": "var(--color-border-tooltip)",
    "text": "var(--color-text)",
    "text-secondary": "var(--color-text-secondary)",
    "text-muted": "var(--color-text-muted)",
    "overlay": "var(--color-overlay)",
    "accent": "var(--color-accent)",
    "accent-hover": "var(--color-accent-hover)",
    "accent-2": "var(--color-accent-2)",
    "success": "var(--color-success)",
    "warning": "var(--color-warning)",
    "danger": "var(--color-danger)",
    "data-real": "var(--color-data-real)",
    "data-estimate": "var(--color-data-estimate)",
    "data-simulated": "var(--color-data-simulated)",
    "data-unavailable": "var(--color-data-unavailable)",
    "scenario-frame": "var(--color-scenario-frame)",
    "status-accepted": "var(--color-status-accepted)",
    "status-rejected": "var(--color-status-rejected)",
    "status-pending": "var(--color-status-pending)",
    "delta-better": "var(--color-delta-better)",
    "delta-worse": "var(--color-delta-worse)",
    "badge-fill-real": "var(--color-badge-fill-real)",
    "badge-fill-estimate": "var(--color-badge-fill-estimate)",
    "badge-fill-simulated": "var(--color-badge-fill-simulated)",
    "badge-fill-unavailable": "var(--color-badge-fill-unavailable)",
    "badge-fill-pending": "var(--color-badge-fill-pending)",
    "state-fill-running": "var(--color-state-fill-running)",
    "state-fill-waiting": "var(--color-state-fill-waiting)",
    "state-fill-done": "var(--color-state-fill-done)",
    "state-fill-error": "var(--color-state-fill-error)",
    "mode-fill-live": "var(--color-mode-fill-live)",
    "mode-fill-scenario": "var(--color-mode-fill-scenario)",
    "row-hover": "var(--color-row-hover)",
    "chart-1": "var(--color-chart-1)",
    "chart-2": "var(--color-chart-2)",
    "chart-3": "var(--color-chart-3)",
    "chart-4": "var(--color-chart-4)",
    "map-congestion-1": "var(--color-map-congestion-1)",
    "map-congestion-2": "var(--color-map-congestion-2)",
    "map-congestion-3": "var(--color-map-congestion-3)",
    "map-congestion-4": "var(--color-map-congestion-4)",
    "map-closure": "var(--color-map-closure)",
    "map-detour": "var(--color-map-detour)",
    "map-event-area": "var(--color-map-event-area)",
    "map-stop-low": "var(--color-map-stop-low)",
    "map-stop-mid": "var(--color-map-stop-mid)",
    "map-stop-over": "var(--color-map-stop-over)",
    "surface-screen": "var(--surface-screen)",
    "surface-card": "var(--surface-card)",
    "surface-nested": "var(--surface-nested)",
    "surface-hover": "var(--surface-hover)",
    "text-primary": "var(--text-primary)",
    "text-support": "var(--text-support)",
    "action": "var(--action)",
    "action-hover": "var(--action-hover)",
    "focus-ring": "var(--focus-ring)"
  },
  "fontFamily": {
    "ui": "var(--font-ui)",
    "mono": "var(--font-mono)"
  },
  "fontSize": {
    "kpi": [
      "var(--fs-kpi)",
      {
        "lineHeight": "var(--lh-kpi)",
        "fontWeight": "var(--fw-kpi)",
        "letterSpacing": "var(--ls-kpi)"
      }
    ],
    "kpi-sm": [
      "var(--fs-kpi-sm)",
      {
        "lineHeight": "var(--lh-kpi-sm)",
        "fontWeight": "var(--fw-kpi-sm)",
        "letterSpacing": "var(--ls-kpi-sm)"
      }
    ],
    "2xl": [
      "var(--fs-2xl)",
      {
        "lineHeight": "var(--lh-2xl)",
        "fontWeight": "var(--fw-2xl)",
        "letterSpacing": "var(--ls-2xl)"
      }
    ],
    "xl": [
      "var(--fs-xl)",
      {
        "lineHeight": "var(--lh-xl)",
        "fontWeight": "var(--fw-xl)",
        "letterSpacing": "var(--ls-xl)"
      }
    ],
    "lg": [
      "var(--fs-lg)",
      {
        "lineHeight": "var(--lh-lg)",
        "fontWeight": "var(--fw-lg)",
        "letterSpacing": "var(--ls-lg)"
      }
    ],
    "md": [
      "var(--fs-md)",
      {
        "lineHeight": "var(--lh-md)",
        "fontWeight": "var(--fw-md)",
        "letterSpacing": "var(--ls-md)"
      }
    ],
    "sm": [
      "var(--fs-sm)",
      {
        "lineHeight": "var(--lh-sm)",
        "fontWeight": "var(--fw-sm)",
        "letterSpacing": "var(--ls-sm)"
      }
    ],
    "xs": [
      "var(--fs-xs)",
      {
        "lineHeight": "var(--lh-xs)",
        "fontWeight": "var(--fw-xs)",
        "letterSpacing": "var(--ls-xs)"
      }
    ],
    "badge": [
      "var(--fs-badge)",
      {
        "lineHeight": "var(--lh-badge)",
        "fontWeight": "var(--fw-badge)",
        "letterSpacing": "var(--ls-badge)"
      }
    ]
  },
  "spacing": {
    "space-4": "var(--space-4)",
    "space-8": "var(--space-8)",
    "space-12": "var(--space-12)",
    "space-16": "var(--space-16)",
    "space-24": "var(--space-24)",
    "space-32": "var(--space-32)",
    "space-48": "var(--space-48)",
    "layout-event-manager": "var(--layout-event-manager)",
    "layout-right-panel": "var(--layout-right-panel)",
    "layout-event-manager-compact": "var(--layout-event-manager-compact)",
    "layout-right-panel-compact": "var(--layout-right-panel-compact)",
    "layout-event-manager-rail": "var(--layout-event-manager-rail)",
    "layout-right-panel-wide": "var(--layout-right-panel-wide)",
    "layout-gap": "var(--layout-gap)",
    "layout-screen-padding": "var(--layout-screen-padding)",
    "size-control-height": "var(--size-control-height)",
    "size-badge-height": "var(--size-badge-height)",
    "size-sidebar-width": "var(--size-sidebar-width)",
    "size-sidebar-button": "var(--size-sidebar-button)",
    "size-topbar-height": "var(--size-topbar-height)",
    "size-metrics-height": "var(--size-metrics-height)",
    "size-icon": "var(--size-icon)",
    "size-icon-sidebar": "var(--size-icon-sidebar)",
    "size-icon-marker": "var(--size-icon-marker)",
    "size-focus-ring-offset": "var(--size-focus-ring-offset)",
    "size-road-line": "var(--size-road-line)",
    "size-chip-height": "var(--size-chip-height)",
    "size-mode-button-height": "var(--size-mode-button-height)",
    "size-node": "var(--size-node)",
    "size-status-chip-height": "var(--size-status-chip-height)",
    "size-dept-icon": "var(--size-dept-icon)",
    "size-progress-bar": "var(--size-progress-bar)",
    "size-marker": "var(--size-marker)",
    "size-marker-badge": "var(--size-marker-badge)",
    "size-layer-panel-width": "var(--size-layer-panel-width)",
    "size-layer-row-height": "var(--size-layer-row-height)",
    "size-popover-width": "var(--size-popover-width)"
  },
  "strokeWidth": {
    "size-icon-stroke": "var(--size-icon-stroke)"
  },
  "borderRadius": {
    "card": "var(--radius-card)",
    "card-inner": "var(--radius-card-inner)",
    "control": "var(--radius-control)",
    "tag": "var(--radius-tag)",
    "tooltip": "var(--radius-tooltip)"
  },
  "borderWidth": {
    "hairline": "var(--border-hairline)",
    "control": "var(--border-control)",
    "scenario-frame-width": "var(--border-scenario-frame)"
  },
  "opacity": {
    "badge-fill": "var(--opacity-badge-fill)",
    "card-border": "var(--opacity-card-border)",
    "tooltip-border": "var(--opacity-tooltip-border)",
    "congestion-rest": "var(--opacity-congestion-rest)",
    "congestion-hover": "var(--opacity-congestion-hover)",
    "event-area-fill": "var(--opacity-event-area-fill)"
  },
  "transitionDuration": {
    "motion": "var(--motion-duration)"
  },
  "transitionTimingFunction": {
    "motion": "var(--motion-easing)"
  },
  "screens": {
    "compact": "1440px"
  }
};

export const tokenUtilities: TailwindTokens["utilities"] = {
  ".transition-base": {
    "transition": "var(--transition-base)"
  }
};
