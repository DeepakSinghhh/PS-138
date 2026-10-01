import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import type { Data, Layout, Config } from "plotly.js";
import { useTheme } from "../lib/theme";

const PlotlyComponent = createPlotlyComponent(Plotly);

interface Props {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number;
  config?: Partial<Config>;
  onClick?: (e: any) => void;
  ariaLabel: string;
}

/** Theme-aware Plotly wrapper: recessive hairline grid, IBM Plex Sans, transparent surface, hover on. */
export default function Plot({ data, layout, height = 320, config, onClick, ariaLabel }: Props) {
  const t = useTheme();
  const axis = {
    gridcolor: t.grid, linecolor: t.axis, zerolinecolor: t.axis, tickcolor: t.axis,
    tickfont: { color: t["text-muted"], size: 11 }, title: { font: { color: t["text-secondary"], size: 12 } },
    automargin: true,
  };
  const merged: Partial<Layout> = {
    height,
    margin: { l: 56, r: 16, t: 12, b: 44 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: '"Plus Jakarta Sans Variable", "Plus Jakarta Sans", system-ui, sans-serif', color: t["text-secondary"], size: 12 },
    hoverlabel: { bgcolor: t["surface-1"], bordercolor: t.border, font: { color: t["text-primary"], family: '"Plus Jakarta Sans Variable", sans-serif' } },
    modebar: { bgcolor: "rgba(0,0,0,0)", color: t["text-muted"], activecolor: t.accent },
    legend: { orientation: "h", y: -0.22, font: { color: t["text-secondary"] } },
    ...layout,
    xaxis: { ...axis, ...(layout?.xaxis ?? {}) },
    yaxis: { ...axis, ...(layout?.yaxis ?? {}) },
  };
  if (layout?.scene) {
    const sceneAxis = { ...axis, backgroundcolor: "rgba(0,0,0,0)", showbackground: false };
    merged.scene = { ...layout.scene, xaxis: { ...sceneAxis, ...(layout.scene.xaxis ?? {}) },
      yaxis: { ...sceneAxis, ...(layout.scene.yaxis ?? {}) }, zaxis: { ...sceneAxis, ...(layout.scene.zaxis ?? {}) } };
  }
  return (
    <div role="img" aria-label={ariaLabel}>
      <PlotlyComponent
        data={data}
        layout={merged}
        config={{ displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"], ...config }}
        style={{ width: "100%" }}
        useResizeHandler
        onClick={onClick}
      />
    </div>
  );
}
