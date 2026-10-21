import { useState, useContext } from "react";
import {
  Box,
  Button,
  FormField,
  Input,
  Modal,
  SpaceBetween,
  CopyToClipboard,
} from "@cloudscape-design/components";
import { apiClient, User } from "../api/client";
import { participantLink } from "../config";
import { useAuth } from "../auth/CognitoProvider";
import { FlashContext } from "../App";

interface ProvisionModalProps {
  visible: boolean;
  onDismiss: () => void;
  onSuccess: () => void;
}

export function ProvisionModal({
  visible,
  onDismiss,
  onSuccess,
}: ProvisionModalProps) {
  const { idToken } = useAuth();
  const { addFlash } = useContext(FlashContext);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<User | null>(null);

  const handleSubmit = async () => {
    if (!idToken || !name.trim() || !email.trim()) return;

    setIsSubmitting(true);
    try {
      const user = await apiClient.createUser(idToken, {
        name: name.trim(),
        email: email.trim(),
      });
      setResult(user);
      addFlash({
        type: "success",
        content: `User ${user.name} provisioned successfully.`,
      });
      onSuccess();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({
        type: "error",
        content: `Failed to provision user: ${message}`,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setName("");
    setEmail("");
    setResult(null);
    onDismiss();
  };

  return (
    <Modal
      visible={visible}
      onDismiss={handleClose}
      header="Add User"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={handleClose}>
              {result ? "Close" : "Cancel"}
            </Button>
            {!result && (
              <Button
                variant="primary"
                onClick={handleSubmit}
                loading={isSubmitting}
                disabled={!name.trim() || !email.trim()}
              >
                Provision
              </Button>
            )}
          </SpaceBetween>
        </Box>
      }
    >
      {result ? (
        <SpaceBetween size="m">
          <Box variant="p">
            User <strong>{result.name}</strong> has been provisioned.
          </Box>
          {result.participantToken ? (
            <FormField
              label="Participant Dashboard Link"
              description="Share this with the participant. It does not expire — they open it to launch their workspace and change instances on demand."
            >
              <SpaceBetween direction="horizontal" size="xs">
                <Input
                  value={participantLink(result.userId, result.participantToken)}
                  readOnly
                />
                <CopyToClipboard
                  copyButtonText="Copy"
                  copySuccessText="Copied!"
                  copyErrorText="Failed to copy"
                  textToCopy={participantLink(
                    result.userId,
                    result.participantToken
                  )}
                  variant="icon"
                />
              </SpaceBetween>
            </FormField>
          ) : null}
          <FormField
            label="Direct workspace URL"
            description="Expires in ~5 minutes — for admin testing only, not for handing out."
          >
            <SpaceBetween direction="horizontal" size="xs">
              <Input value={result.workspaceUrl} readOnly />
              <CopyToClipboard
                copyButtonText="Copy"
                copySuccessText="Copied!"
                copyErrorText="Failed to copy"
                textToCopy={result.workspaceUrl}
                variant="icon"
              />
            </SpaceBetween>
          </FormField>
        </SpaceBetween>
      ) : (
        <SpaceBetween size="m">
          <FormField label="Full Name" constraintText="Required">
            <Input
              value={name}
              onChange={({ detail }) => setName(detail.value)}
              placeholder="Jane Doe"
              disabled={isSubmitting}
            />
          </FormField>
          <FormField label="Email" constraintText="Required">
            <Input
              value={email}
              onChange={({ detail }) => setEmail(detail.value)}
              placeholder="jane@example.com"
              inputMode="email"
              disabled={isSubmitting}
            />
          </FormField>
        </SpaceBetween>
      )}
    </Modal>
  );
}
