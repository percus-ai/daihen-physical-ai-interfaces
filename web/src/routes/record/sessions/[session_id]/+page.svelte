<script lang="ts">
  import { page } from '$app/state';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  import { Button } from 'bits-ui';
  import SessionLayoutEditor from '$lib/components/recording/SessionLayoutEditor.svelte';

  const sessionId = $derived(page.params.session_id ?? '');

  let editMode = $state(true);
  const toggleEditMode = () => {
    editMode = !editMode;
  };

  const handleReconnect = () => {
    const client = getRosbridgeClient();
    client.connect().catch(() => {
      // ignore; connection status handles UI fallback
    });
  };
</script>

<section class="card-strong p-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="section-title">Record Dataset</p>
      <h1 class="text-3xl font-semibold text-slate-900">データセット収録</h1>
    </div>
    <div class="flex flex-wrap gap-3">
      <Button.Root class="btn-ghost" type="button" onclick={toggleEditMode}>
        {editMode ? '閲覧モード' : '編集モード'}
      </Button.Root>
      <Button.Root class="btn-ghost" href="/record">録画一覧</Button.Root>
      <Button.Root class="btn-ghost" href="/record/new">新規データセット</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={handleReconnect}>再接続</Button.Root>
    </div>
  </div>
</section>

<SessionLayoutEditor
  blueprintSessionId={sessionId}
  blueprintSessionKind="recording"
  layoutSessionId={sessionId}
  layoutSessionKind="recording"
  layoutMode="recording"
  viewSource="ros"
  {editMode}
/>
