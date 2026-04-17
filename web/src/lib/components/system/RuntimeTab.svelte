<script lang="ts">
  import type { BuildJobSummary, BuildSettingSummary } from '$lib/api/client';
  import BuildManagementPanel from '$lib/components/builds/BuildManagementPanel.svelte';

  let {
    buildLoading = false,
    buildLoadError = '',
    buildCurrentPlatform = '',
    buildCurrentSm = '',
    envBuildItems = [],
    sharedBuildItems = [],
    runningBuildJobs = [],
    buildActionPending = {},
    buildLogLinesByJobId = {},
    onBuildRun,
    onBuildCancelByJobId,
    onBuildDelete,
  }: {
    buildLoading?: boolean;
    buildLoadError?: string;
    buildCurrentPlatform?: string;
    buildCurrentSm?: string;
    envBuildItems?: BuildSettingSummary[];
    sharedBuildItems?: BuildSettingSummary[];
    runningBuildJobs?: BuildJobSummary[];
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
  loading={buildLoading}
  loadError={buildLoadError}
  currentSm={buildCurrentSm}
  currentPlatform={buildCurrentPlatform}
  actionPending={buildActionPending}
  logLinesByJobId={buildLogLinesByJobId}
  onRun={onBuildRun}
  onCancelByJobId={onBuildCancelByJobId}
  onDelete={onBuildDelete}
/>
