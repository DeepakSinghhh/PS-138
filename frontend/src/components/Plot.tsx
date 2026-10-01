import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import type { Data, Layout, Config } from "plotly.js";
import { useTheme } from "../lib/theme";

const PlotlyComponent = createPlotlyComponent(Plotly);
const SANS = '"Archivo Variable", "Archivo", system-ui, sans-serif';
const MONO = '"IBM Plex Mono", ui-monospace, monospace';

interface Props {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number;
  config?: Partial<Config>;
  onClick?: (e: any) => void;
  ariaLabel: string;
}

/** Theme-aware Plotly wrapper: recessive hairline grid, Archivo text with mono tick labels, ink hover labels. */
export default function Plot({ data, layout, height = 320, config, onClick, ariaLabel }: Props) {
  const t = useTheme();
  // numeric ticks in mono; category labels (service names, models) stay in the text face
  const categorical = (k: "x" | "y") => data.some((d) => {
    const v = (d as Record<string, unknown>)[k];
    return Array.isArray(v) && typeof v[0] === "string";
  });
  const tickFamily = (k: "x" | "y") => (categorical(k) ? SANS : MONO);
  const axis = {
    gridcolor: t.grid, linecolor: t.axis, zerolinecolor: t.axis, tickcolor: t.axis,
    tickfont: { color: t["text-muted"], size: 10.5 }, title: { font: { color: t["text-secondary"], size: 12 } },
    automargin: true,
  };
  const merged: Partial<Layout> = {
    height,
    margin: { l: 56, r: 16, t: 12, b: 44 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: SANS, color: t["text-secondary"], size: 12 },
    hoverlabel: { bgcolor: t.ink, bordercolor: t.ink, font: { color: t.page, family: SANS, size: 12 } },
    modebar: { bgcolor: "rgba(0,0,0,0)", color: t["text-muted"], activecolor: t.accent },
    legend: { orientation: "h", y: -0.22, font: { color: t["text-secondary"] } },
    bargap: 0.38,
    ...layout,
    xaxis: { ...axis, tickfont: { ...axis.tickfont, family: tickFamily("x") }, ...(layout?.xaxis ?? {}) },
    yaxis: { ...axis, tickfont: { ...axis.tickfont, family: tickFamily("y") }, ...(layout?.yaxis ?? {}) },
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
