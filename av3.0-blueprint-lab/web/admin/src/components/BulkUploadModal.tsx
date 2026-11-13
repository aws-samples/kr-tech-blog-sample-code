import { useState, useContext } from "react";
import {
  Box,
  Button,
  CopyToClipboard,
  FileUpload,
  Modal,
  SpaceBetween,
  Table,
  StatusIndicator,
} from "@cloudscape-design/components";
import { apiClient, BulkProvisionResult } from "../api/client";
import { useAuth } from "../auth/CognitoProvider";
import { FlashContext } from "../App";

interface ProvisionRow {
  name: string;
  email: string;
  module?: string;
}

interface BulkUploadModalProps {
  visible: boolean;
  onDismiss: () => void;
  onSuccess: () => void;
}

type ModalStep = "upload" | "preview" | "results";

function parseCsv(text: string): ProvisionRow[] {
  const lines = text.trim().split("\n");
  if (lines.length < 2) return [];

  const headers = lines[0].toLowerCase().split(",").map((h) => h.trim());
  const nameIdx = headers.indexOf("name");
  const emailIdx = headers.indexOf("email");
  const moduleIdx = headers.indexOf("module");

  if (nameIdx === -1 || emailIdx === -1) return [];

  return lines.slice(1).reduce<ProvisionRow[]>((acc, line) => {
    const cols = line.split(",").map((c) => c.trim());
    const name = cols[nameIdx] ?? "";
    const email = cols[emailIdx] ?? "";
    if (name && email) {
      acc.push({
        name,
        email,
        module: moduleIdx !== -1 ? cols[moduleIdx] : undefined,
      });
    }
    return acc;
  }, []);
}

export function BulkUploadModal({
  visible,
  onDismiss,
  onSuccess,
}: BulkUploadModalProps) {
  const { idToken } = useAuth();
  const { addFlash } = useContext(FlashContext);
  const [step, setStep] = useState<ModalStep>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [rows, setRows] = useState<ProvisionRow[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<BulkProvisionResult | null>(null);

  const handleFileChange = async (selectedFiles: File[]) => {
    setFiles(selectedFiles);
    if (selectedFiles.length > 0) {
      const text = await selectedFiles[0].text();
      const parsed = parseCsv(text);
      setRows(parsed);
      if (parsed.length > 0) {
        setStep("preview");
      } else {
        addFlash({
          type: "error",
          content:
            "CSV must have 'name' and 'email' columns with at least one data row.",
        });
      }
    }
  };

  const handleSubmit = async () => {
    if (!idToken || rows.length === 0) return;

    setIsSubmitting(true);
    try {
      const res = await apiClient.bulkProvision(idToken, rows);
      setResult(res);
      setStep("results");
      addFlash({
        type: "success",
        content: `Bulk provisioning complete: ${res.succeeded.length} succeeded, ${res.failed.length} failed.`,
      });
      onSuccess();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({
        type: "error",
        content: `Bulk provisioning failed: ${message}`,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setStep("upload");
    setFiles([]);
    setRows([]);
    setResult(null);
    onDismiss();
  };

  const allUrls =
    result?.succeeded.map((r) => `${r.name},${r.email},${r.workspaceUrl}`).join("\n") ?? "";

  return (
    <Modal
      visible={visible}
      onDismiss={handleClose}
      size="large"
      header="Bulk Upload Users"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={handleClose}>
              {step === "results" ? "Close" : "Cancel"}
            </Button>
            {step === "preview" && (
              <Button
                variant="primary"
                onClick={handleSubmit}
                loading={isSubmitting}
              >
                Provision {rows.length} Users
              </Button>
            )}
            {step === "results" && result && result.succeeded.length > 0 && (
              <CopyToClipboard
                copyButtonText="Copy All URLs"
                copySuccessText="Copied!"
                copyErrorText="Failed to copy"                textToCopy={allUrls}
                variant="button"
              />
            )}
          </SpaceBetween>
        </Box>
      }
    >
      {step === "upload" && (
        <SpaceBetween size="m">
          <Box variant="p">
            Upload a CSV file with columns: <code>name</code>, <code>email</code>
            , and optionally <code>module</code>.
          </Box>
          <FileUpload
            value={files}
            onChange={({ detail }) =>
              handleFileChange(detail.value as unknown as File[])
            }
            accept=".csv"
            i18nStrings={{
              uploadButtonText: () => "Choose CSV file",
              dropzoneText: () => "Drop CSV file here",
              removeFileAriaLabel: () => "Remove file",
              limitShowFewer: "Show fewer files",
              limitShowMore: "Show more files",
              errorIconAriaLabel: "Error",
            }}
            constraintText="CSV format only. Max 100 users per upload."
          />
        </SpaceBetween>
      )}

      {step === "preview" && (
        <SpaceBetween size="m">
          <Box variant="p">
            Preview: {rows.length} user(s) will be provisioned.
          </Box>
          <Table
            items={rows.slice(0, 20)}
            columnDefinitions={[
              { id: "name", header: "Name", cell: (r) => r.name },
              { id: "email", header: "Email", cell: (r) => r.email },
              {
                id: "module",
                header: "Module",
                cell: (r) => r.module ?? "-",
              },
            ]}
            variant="embedded"
          />
          {rows.length > 20 && (
            <Box variant="small">
              ...and {rows.length - 20} more rows not shown.
            </Box>
          )}
        </SpaceBetween>
      )}

      {step === "results" && result && (
        <SpaceBetween size="m">
          {result.succeeded.length > 0 && (
            <Table
              header={
                <Box variant="h4">
                  <StatusIndicator type="success">
                    Succeeded ({result.succeeded.length})
                  </StatusIndicator>
                </Box>
              }
              items={result.succeeded}
              columnDefinitions={[
                { id: "name", header: "Name", cell: (r) => r.name },
                { id: "email", header: "Email", cell: (r) => r.email },
                {
                  id: "url",
                  header: "Workspace URL",
                  cell: (r) => (
                    <SpaceBetween direction="horizontal" size="xs">
                      <Box variant="code">{r.workspaceUrl}</Box>
                      <CopyToClipboard
                        copyButtonText="Copy"
                        copySuccessText="Copied!"
                copyErrorText="Failed to copy"                        textToCopy={r.workspaceUrl}
                        variant="icon"
                      />
                    </SpaceBetween>
                  ),
                },
              ]}
              variant="embedded"
            />
          )}
          {result.failed.length > 0 && (
            <Table
              header={
                <Box variant="h4">
                  <StatusIndicator type="error">
                    Failed ({result.failed.length})
                  </StatusIndicator>
                </Box>
              }
              items={result.failed}
              columnDefinitions={[
                { id: "name", header: "Name", cell: (r) => r.name },
                { id: "email", header: "Email", cell: (r) => r.email },
                { id: "error", header: "Error", cell: (r) => r.error },
              ]}
              variant="embedded"
            />
          )}
        </SpaceBetween>
      )}
    </Modal>
  );
}
