import React, { useState } from "react";
import {
  Box,
  Button,
  ColumnLayout,
  Container,
  Header,
  Icon,
  KeyValuePairs,
  Link,
  SpaceBetween,
  StatusIndicator,
  Badge,
} from "@cloudscape-design/components";
import { type ModuleConfig, PHASE_COLORS } from "../data/pipeline-config";
import { InstanceOptionsPanel } from "./InstanceOptionsPanel";
import { getConfig } from "../config";

interface ModuleDetailPanelProps {
  module: ModuleConfig;
  onClose: () => void;
  onStartLab: (moduleId: string) => void;
  // Open the Instance Options modal as soon as this panel mounts. Set when the participant
  // clicks "Start Workspace" on the Pipeline Map header: their workspace is stopped, and
  // Apply & Restart inside that modal is what starts it.
  openInstanceOptionsOnMount?: boolean;
  // The space's real volume in GB (null when unknown). Passed straight through to
  // InstanceOptionsPanel, which must size against the volume rather than the module's
  // recommended capacity.
  liveStorageGB?: number | null;
}

export function ModuleDetailPanel({
  module,
  onClose,
  onStartLab,
  openInstanceOptionsOnMount = false,
  liveStorageGB = null,
}: ModuleDetailPanelProps): React.JSX.Element {
  const [showInstanceOptions, setShowInstanceOptions] = useState(
    openInstanceOptionsOnMount
  );

  const statusType = module.status === "completed"
    ? "success"
    : module.status === "in-progress"
      ? "in-progress"
      : "stopped";

  const statusLabel = module.status === "completed"
    ? "Completed"
    : module.status === "in-progress"
      ? "In Progress"
      : "Locked";

  return (
    <>
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          width: "440px",
          height: "100vh",
          backgroundColor: "#ffffff",
          boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
          zIndex: 1000,
          overflowY: "auto",
          animation: "slideIn 300ms ease-out",
        }}
      >
        <style>{`
          @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
          }
        `}</style>

        <div
          style={{
            position: "sticky",
            top: 0,
            backgroundColor: "#ffffff",
            borderBottom: "1px solid #e9ebed",
            padding: "16px 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            zIndex: 1,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "8px",
                height: "32px",
                borderRadius: "4px",
                backgroundColor: PHASE_COLORS[module.phase],
              }}
            />
            <div>
              <h2 style={{ margin: 0, fontSize: "18px", fontWeight: 700, color: "#16191f" }}>
                {module.title}
              </h2>
              <span style={{ fontSize: "12px", color: "#5f6b7a", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                {module.phase} phase
              </span>
            </div>
          </div>
          <Button variant="icon" iconName="close" onClick={onClose} ariaLabel="Close panel" />
        </div>

        <div style={{ padding: "24px" }}>
          <SpaceBetween size="l">
            {/* Status & Tool Info */}
            <Container header={<Header variant="h3">Tool Information</Header>}>
              <SpaceBetween size="s">
                <KeyValuePairs
                  columns={2}
                  items={[
                    { label: "Tool", value: module.tool },
                    { label: "Version", value: <Badge color="blue">{module.version}</Badge> },
                    { label: "License", value: module.license },
                    {
                      label: "Status",
                      value: <StatusIndicator type={statusType}>{statusLabel}</StatusIndicator>,
                    },
                  ]}
                />
                <Box>
                  <Link href={module.sourceUrl} external>
                    View source repository
                  </Link>
                </Box>
              </SpaceBetween>
            </Container>

            {/* Compute Section */}
            <Container header={<Header variant="h3">Compute Resources</Header>}>
              <KeyValuePairs
                columns={2}
                items={[
                  {
                    label: "Instance",
                    value: (
                      <span style={{ fontFamily: "monospace", fontWeight: 600 }}>
                        {module.recommendedInstance}
                      </span>
                    ),
                  },
                  {
                    label: "Storage (EBS)",
                    // Show the volume that exists, and the module's recommendation only as
                    // a hint. This row used to print module.storageGB alone, which read as
                    // a statement of fact about the volume and was wrong for every module.
                    value:
                      liveStorageGB != null
                        ? `${liveStorageGB} GB provisioned · ${module.storageGB} GB recommended`
                        : `${module.storageGB} GB recommended`,
                  },
                  { label: "Est. Duration", value: `${module.estimatedMinutes} minutes` },
                  {
                    label: "Alternatives",
                    value: `${module.alternatives.length} options`,
                  },
                ]}
              />
              <Box margin={{ top: "m" }}>
                <Button onClick={() => setShowInstanceOptions(true)} iconName="settings">
                  Instance Options
                </Button>
              </Box>
            </Container>

            {/* Data Flow */}
            <Container header={<Header variant="h3">Data Flow</Header>}>
              <SpaceBetween size="xs">
                <div>
                  <Box variant="awsui-key-label">Input</Box>
                  <code style={{ fontSize: "12px", color: "#037f0c", wordBreak: "break-all" }}>
                    {module.inputPath}
                  </code>
                </div>
                <div style={{ textAlign: "center", color: "#5f6b7a" }}>
                  <Icon name="angle-down" />
                </div>
                <div>
                  <Box variant="awsui-key-label">Output</Box>
                  <code style={{ fontSize: "12px", color: "#0972d3", wordBreak: "break-all" }}>
                    {module.outputPath}
                  </code>
                </div>
                {module.feedsModules.length > 0 && (
                  <div style={{ marginTop: "8px" }}>
                    <Box variant="awsui-key-label">Feeds into</Box>
                    <span style={{ fontSize: "13px", color: "#16191f" }}>
                      {module.feedsModules.join(", ")}
                    </span>
                  </div>
                )}
              </SpaceBetween>
            </Container>

            {/* AWS Advantage */}
            <Container
              header={<Header variant="h3"><Icon name="status-info" /> AWS Advantage</Header>}
            >
              <Box color="text-body-secondary" fontSize="body-s">
                {module.awsAdvantage}
              </Box>
            </Container>

            {/* External execution (e.g. M10 AlpaSim on a GPU EC2 host over SSM) */}
            {module.externalExecution && (
              <Container
                header={
                  <Header variant="h3">
                    <Icon name="status-warning" /> {module.externalExecution.label}
                  </Header>
                }
              >
                <SpaceBetween size="s">
                  <Box color="text-body-secondary" fontSize="body-s">
                    {module.externalExecution.summary}
                  </Box>
                  <ol style={{ margin: 0, paddingLeft: 18 }}>
                    {module.externalExecution.steps.map((step, i) => (
                      <li key={i} style={{ fontSize: "13px", marginBottom: 4 }}>
                        {/* Substitute the DEPLOYED region. The SSM command used to
                            hardcode us-west-2, so participants in any other region
                            were told to target a region their host is not in. */}
                        {step.replace(/\{region\}/g, getConfig().region)}
                      </li>
                    ))}
                  </ol>
                  <Box variant="strong" color="text-status-warning" fontSize="body-s">
                    {module.externalExecution.costWarning}
                  </Box>
                  <Link href={module.externalExecution.guideHref} external>
                    Participant SSM run guide
                  </Link>
                </SpaceBetween>
              </Container>
            )}

            {/* Action Buttons */}
            <ColumnLayout columns={1}>
              <Button
                variant="primary"
                fullWidth
                disabled={module.status === "locked"}
                onClick={() => onStartLab(module.id)}
                iconName="caret-right-filled"
              >
                {module.status === "completed" ? "Re-run Lab" : module.status === "in-progress" ? "Resume Lab" : "Start Lab"}
              </Button>
            </ColumnLayout>
          </SpaceBetween>
        </div>
      </div>

      {showInstanceOptions && (
        <InstanceOptionsPanel
          liveStorageGB={liveStorageGB}
          module={module}
          onClose={() => setShowInstanceOptions(false)}
        />
      )}
    </>
  );
}
