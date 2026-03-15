<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  import { Button } from 'bits-ui';
  import SessionLayoutEditor from '$lib/components/recording/SessionLayoutEditor.svelte';
  import { scrollIntoViewSoon, speakSessionMessage } from '$lib/session/sessionUx';

  const sessionId = $derived(page.params.session_id ?? '');
  const STATUS_TOPIC = '/lerobot_recorder/status';
  const STATUS_LABELS: Record<string, string> = {
    idle: '待機',
    warming: '準備中',
    recording: '録画中',
    paused: '一時停止',
    resetting: 'リセット中',
    inactive: '停止',
    completed: '完了',
    failed: '失敗'
  };

  type RecorderStatus = {
    state?: string;
    dataset_id?: string;
    episode_index?: number | null;
    num_episodes?: number | null;
    frame_count?: number | null;
    episode_frame_count?: number | null;
    last_frame_at?: string | null;
  };

  let editMode = $state(false);
  let rosbridgeStatus = $state<'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'>('idle');
  let recorderStatus = $state<RecorderStatus | null>(null);
  let editorAnchor = $state<HTMLElement | null>(null);
  let lastAnnouncedState = $state('');

  const parseRecorderPayload = (msg: Record<string, unknown>): RecorderStatus => {
    if (typeof msg.data === 'string') {
      try {
        return JSON.parse(msg.data) as RecorderStatus;
      } catch {
        return { state: 'unknown' };
      }
    }
    return msg as RecorderStatus;
  };

  const toggleEditMode = () => {
    editMode = !editMode;
  };

  const handleReconnect = () => {
    const client = getRosbridgeClient();
    client.connect().catch(() => {
      // ignore; connection status handles UI fallback
    });
  };

  const recorderState = $derived(recorderStatus?.state ?? rosbridgeStatus);

  onMount(() => {
    const stopAutoScroll = scrollIntoViewSoon(editorAnchor, 180);
    const client = getRosbridgeClient();
    const unsubscribe = client.subscribe(STATUS_TOPIC, (message) => {
      recorderStatus = parseRecorderPayload(message);
    });
    const offStatus = client.onStatusChange((next) => {
      rosbridgeStatus = next;
    });
    rosbridgeStatus = client.getStatus();
    return () => {
      stopAutoScroll();
      unsubscribe();
      offStatus();
    };
  });

  $effect(() => {
    const state = String(recorderStatus?.state ?? '').trim();
    if (!state) return;
    if (!lastAnnouncedState) {
      lastAnnouncedState = state;
      return;
    }
    if (lastAnnouncedState === state) return;
    lastAnnouncedState = state;
    if (state === 'resetting') {
      speakSessionMessage('環境をリセットしてください。');
      return;
    }
    if (state === 'recording') {
      speakSessionMessage('録画中です。');
      return;
    }
    if (state === 'completed') {
      speakSessionMessage('エピソードを保存しました。');
      return;
    }
    if (state === 'failed') {
      speakSessionMessage('録画でエラーが発生しました。');
      return;
    }
    if (state === 'paused') {
      speakSessionMessage('一時停止です。');
    }
  });
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

<div class="mt-6" bind:this={editorAnchor}>
<SessionLayoutEditor
  blueprintSessionId={sessionId}
  blueprintSessionKind="recording"
  layoutSessionId={sessionId}
  layoutSessionKind="recording"
  layoutMode="recording"
  viewSource="ros"
  {editMode}
/>
</div>
