"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { ErrorText, PageHeader } from "@/components/ui";
import { TrendSourcesPanel } from "@/dashboard/TrendSourcesPanel";
import { ChannelsTable } from "@/dashboard/ChannelsTable";
import { ControlsPanel } from "@/dashboard/ControlsPanel";
import { OperationsForm } from "@/dashboard/OperationsForm";
import { UsersPanel } from "@/dashboard/UsersPanel";
import { api } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import type { SettingsResponse } from "@/lib/types";

export function SettingsView() {
  const { user } = useAuth();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.settings().then(setSettings).catch((e: Error) => setError(e.message));
  }, []);

  if (!user) return null;
  const isAdmin = hasRole(user.role, "admin");

  return (
    <>
      <PageHeader
        title="Einstellungen"
        description="Not-Aus, automatische Veröffentlichung, Budget, Kanäle und Benutzer."
      />
      <ErrorText error={error} />
      {settings && (
        <>
          <ControlsPanel
            controls={settings.controls}
            role={user.role}
            onChange={(controls) => setSettings({ ...settings, controls })}
          />
          <OperationsForm initial={settings.operations} editable={isAdmin} />
        </>
      )}
      <TrendSourcesPanel canTest={isAdmin} />
      <ChannelsTable role={user.role} />
      {isAdmin && <UsersPanel currentUserId={user.id} />}
    </>
  );
}
