import { useMemo } from "react";
import { CircleMarker, GeoJSON, MapContainer, Polyline, Tooltip } from "react-leaflet";
import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";
import { feature } from "topojson-client";
import land110 from "world-atlas/land-110m.json";
import "leaflet/dist/leaflet.css";
import { FAMILY_LABEL, familyColor, useTheme } from "../lib/theme";
import type { Meta, NetworkInfo, RoutePlan } from "../lib/types";
import { fmt } from "../lib/format";
import ErrorBoundary from "./ErrorBoundary";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LAND = feature(land110 as any, (land110 as any).objects.land) as any;

interface Props {
  network: NetworkInfo | null;
  plan?: { routes: RoutePlan[] } | null;
  meta: Meta | null;
  height?: number;
}

/** Offline-capable map in nautical-chart colours: vector land (world-atlas), sea routes as dashed tracks, coloured by fuel once a plan is chosen. */
export default function FleetMap({ network, plan, meta, height = 420 }: Props) {
  const t = useTheme();
  const byRoute = useMemo(() => Object.fromEntries((plan?.routes ?? []).map((r) => [r.route_id, r])), [plan]);
  const ports = useMemo(() => {
    const used = new Set((network?.routes ?? []).flatMap((r) => r.ports));
    return (meta?.ports ?? []).filter((p) => used.has(p.id));
  }, [network, meta]);
  const bounds = useMemo<LatLngBoundsExpression | undefined>(() => {
    const pts = (network?.routes ?? []).flatMap((r) => r.geometry.map(([lon, lat]) => [lat, lon] as [number, number]));
    if (!pts.length) return undefined;
    const lats = pts.map((p) => p[0]), lons = pts.map((p) => p[1]);
    return [[Math.min(...lats) - 3, Math.min(...lons) - 3], [Math.max(...lats) + 3, Math.max(...lons) + 3]];
  }, [network]);
  const families = Array.from(new Set((plan?.routes ?? []).map((r) => r.fuel_family)));

  if (!network || !bounds) return <div className="map empty" style={{ height }}>Loading network…</div>;
  return (
    <div>
      <div className="map" style={{ height }}>
        <ErrorBoundary variant="inline" resetKey={network.name}>
        <MapContainer key={network.name + network.routes.length + t.land} bounds={bounds} scrollWheelZoom={false}
          style={{ height: "100%", width: "100%" }} attributionControl={false} worldCopyJump>
          <GeoJSON data={LAND} style={{ color: t.coast, weight: 0.7, fillColor: t.land, fillOpacity: 1 }} />
          {network.routes.map((r) => {
            const p = byRoute[r.id];
            const color = p ? familyColor(t, p.fuel_family) : t.ink;
            const line: LatLngExpression[] = r.geometry.map(([lon, lat]) => [lat, lon]);
            return (
              <Polyline key={r.id} positions={line} pathOptions={p ? { color, weight: 3 + Math.min(p.ships, 6) * 0.35, opacity: 0.9, lineCap: "round" }
                : { color, weight: 1.6, opacity: 0.85, dashArray: "6 5", lineCap: "butt" }}>
                <Tooltip sticky>
                  <b>{r.id} · {r.name}</b><br />
                  {fmt(r.distance_nm)} nm · {r.service} · demand {fmt(r.demand)} {r.cargo === "container" ? "TEU" : r.cargo === "pax" ? "pax" : "t"} {r.demand_unit}
                  {p && (<><br />{p.ships} × {p.vessel_label} @ {p.speed_kn.toFixed(1)} kn · {p.fuel_label}{p.shore_power ? " · shore power" : ""}
                    <br />{fmt(p.wtw_co2e_t)} t CO₂e/yr · CII {p.cii.rating}</>)}
                </Tooltip>
              </Polyline>
            );
          })}
          {ports.map((p) => (
            <CircleMarker key={p.id} center={[p.lat, p.lon]} radius={4}
              pathOptions={{ color: t["surface-1"], weight: 2, fillColor: t["text-primary"], fillOpacity: 1 }}>
              <Tooltip>{p.name}{p.ops_from <= (network.year ?? 2030) ? " · shore power" : ""}</Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
        </ErrorBoundary>
      </div>
      {plan && (
        <div className="legend" style={{ marginTop: 8 }}>
          {families.map((f) => (<span key={f}><i className="swatch" style={{ background: familyColor(t, f) }} />{FAMILY_LABEL[f] ?? f}</span>))}
          <span className="muted">line width ∝ ships deployed</span>
        </div>
      )}
    </div>
  );
}
