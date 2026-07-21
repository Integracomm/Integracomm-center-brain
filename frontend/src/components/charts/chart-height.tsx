import { ResponsiveContainer } from "recharts";

// Wrapper que fixa uma altura previsível para gráficos Recharts.
// Recharts exige um container com altura definida — nunca usar % altura solto.
export function ChartHeight({
  children,
  height = 260,
}: {
  children: React.ReactElement;
  height?: number;
}) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}
