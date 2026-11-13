import { useState, useEffect, useCallback, useContext } from "react";
import {
  Box,
  Container,
  Header,
  SpaceBetween,
  StatusIndicator,
} from "@cloudscape-design/components";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { apiClient, DailyCost } from "../api/client";
import { useAuth } from "../auth/CognitoProvider";
import { FlashContext } from "../App";

const BUDGET_LIMIT = 200;
const DAYS = 14;

export function CostsPage() {
  const { idToken } = useAuth();
  const { addFlash } = useContext(FlashContext);
  const [costs, setCosts] = useState<DailyCost[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchCosts = useCallback(async () => {
    if (!idToken) return;
    try {
      const data = await apiClient.getDailyCosts(idToken, DAYS);
      setCosts(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({ type: "error", content: `Failed to load costs: ${message}` });
    } finally {
      setIsLoading(false);
    }
  }, [idToken, addFlash]);

  useEffect(() => {
    fetchCosts();
  }, [fetchCosts]);

  const todayCost = costs.length > 0 ? costs[costs.length - 1].cost : 0;
  const todayPercent = Math.round((todayCost / BUDGET_LIMIT) * 100);
  const totalPeriod = costs.reduce((sum, d) => sum + d.cost, 0);

  const chartData = costs.map((d) => ({
    date: new Date(d.date).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    cost: d.cost,
    isToday: d.date === costs[costs.length - 1]?.date,
  }));

  const budgetStatus = todayPercent >= 90 ? "error" : todayPercent >= 70 ? "warning" : "success";
  const budgetLabel =
    todayPercent >= 90
      ? "Over budget threshold"
      : todayPercent >= 70
        ? "Approaching budget"
        : "Within budget";

  return (
    <SpaceBetween size="l">
      {/* Summary cards */}
      <SpaceBetween direction="horizontal" size="l">
        <Box>
          <Box variant="awsui-key-label">Today's Spend</Box>
          <Box variant="awsui-value-large">${todayCost.toFixed(2)}</Box>
        </Box>
        <Box>
          <Box variant="awsui-key-label">Budget Used Today</Box>
          <Box variant="awsui-value-large">
            <StatusIndicator type={budgetStatus}>
              {todayPercent}% - {budgetLabel}
            </StatusIndicator>
          </Box>
        </Box>
        <Box>
          <Box variant="awsui-key-label">14-Day Total</Box>
          <Box variant="awsui-value-large">${totalPeriod.toFixed(2)}</Box>
        </Box>
        <Box>
          <Box variant="awsui-key-label">Daily Budget</Box>
          <Box variant="awsui-value-large">${BUDGET_LIMIT}</Box>
        </Box>
      </SpaceBetween>

      {/* Chart */}
      <Container
        header={<Header variant="h2">Daily Cost (Last 14 Days)</Header>}
      >
        {isLoading ? (
          <Box textAlign="center" padding="l">
            Loading cost data...
          </Box>
        ) : costs.length === 0 ? (
          <Box textAlign="center" padding="l">
            No cost data available.
          </Box>
        ) : (
          <div style={{ width: "100%", height: 400 }}>
            <ResponsiveContainer>
              <BarChart
                data={chartData}
                margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis
                  tickFormatter={(v: number) => `$${v}`}
                  domain={[0, Math.max(BUDGET_LIMIT * 1.2, ...costs.map((c) => c.cost * 1.1))]}
                />
                <Tooltip
                  formatter={(value: number) => [`$${value.toFixed(2)}`, "Cost"]}
                  labelStyle={{ fontWeight: "bold" }}
                />
                <ReferenceLine
                  y={BUDGET_LIMIT}
                  stroke="#d91515"
                  strokeDasharray="5 5"
                  label={{
                    value: `Budget: $${BUDGET_LIMIT}`,
                    position: "right",
                    fill: "#d91515",
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                  {chartData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={
                        entry.isToday
                          ? "#0972d3"
                          : entry.cost > BUDGET_LIMIT
                            ? "#d91515"
                            : "#89bceb"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        <Box variant="small" textAlign="center" padding={{ top: "s" }}>
          Blue bar = today | Red = over budget | Dashed line = $200 daily budget
        </Box>
      </Container>
    </SpaceBetween>
  );
}
