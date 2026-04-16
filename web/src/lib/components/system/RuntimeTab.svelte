<script lang="ts">
  import type { BuildJobSummary, BuildSettingSummary } from '$lib/api/client';
  import BuildManagementPanel from '$lib/components/builds/BuildManagementPanel.svelte';

  let {
    buildLoading = false,
    buildLoadError = '',
    envBuildItems = [],
    sharedBuildItems = [],
    runningBuildJobs = [],
    selectedBuildConfigId = '',
    buildActionPending = {},
    buildLogLinesByJobId = {},
    onBuildRun,
    onBuildCancelByJobId,
    onBuildDelete,
  }: {
    buildLoading?: boolean;
    buildLoadError?: string;
    envBuildItems?: BuildSettingSummary[];
    sharedBuildItems?: BuildSettingSummary[];
    runningBuildJobs?: BuildJobSummary[];
    selectedBuildConfigId?: string;
    buildActionPending?: Record<string, boolean>;
    buildLogLinesByJobId?: Record<string, string[]>;
    onBuildRun: (item: BuildSettingSummary) => Promise<void>;
    onBuildCancelByJobId: (jobId: string, settingId?: string) => Promise<void>;
    onBuildDelete: (item: BuildSettingSummary) => Promise<void>;
  } = $props();
</script>

<BuildManagementPanel
  envItems={envBuildItems}
  sharedItems={sharedBuildItems}
  runningJobs={runningBuildJobs}
  selectedConfigId={selectedBuildConfigId}
  loading={buildLoading}
  loadError={buildLoadError}
  actionPending={buildActionPending}
  logLinesByJobId={buildLogLinesByJobId}
  onRun={onBuildRun}
  onCancelByJobId={onBuildCancelByJobId}
  onDelete={onBuildDelete}
/>
