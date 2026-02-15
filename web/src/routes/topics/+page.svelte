<script lang="ts">
  import { Button } from 'bits-ui';
  import { getRosbridgeClient, type RosTopicInfo } from '$lib/recording/rosbridge';

  type RosbridgeStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

  let rosbridgeStatus = $state<RosbridgeStatus>('idle');
  let topics = $state<RosTopicInfo[]>([]);
  let loadingTopics = $state(false);
  let topicsError = $state('');
  let selectedTopic = $state('');
  let selectedTopicType = $state('');
  let previewPayload = $state<Record<string, unknown> | null>(null);
  let previewRaw = $state('');
  let previewUpdatedAt = $state('');
  let unsubscribePreview: (() => void) | null = null;

  const topicCount = $derived(topics.length);

  const toErrorMessage = (error: unknown) => {
    if (error instanceof Error && error.message) {
      return error.message;
    }
    return 'トピック一覧の取得に失敗しました。';
  };

  const parsePreviewPayload = (message: Record<string, unknown>) => {
    if (typeof message.data === 'string') {
      previewRaw = message.data;
      try {
        const parsed = JSON.parse(message.data);
        if (parsed && typeof parsed === 'object') {
          previewPayload = parsed as Record<string, unknown>;
          return;
        }
      } catch {
        // plain text payload
      }
    }
    previewRaw = '';
    previewPayload = message;
  };

  const clearPreview = () => {
    previewPayload = null;
    previewRaw = '';
    previewUpdatedAt = '';
  };

  const subscribeTopicPreview = (topicName: string) => {
    unsubscribePreview?.();
    unsubscribePreview = null;
    clearPreview();
    if (!topicName) return;

    const client = getRosbridgeClient();
    unsubscribePreview = client.subscribe(
      topicName,
      (message) => {
        parsePreviewPayload(message);
        previewUpdatedAt = new Date().toLocaleTimeString();
      },
      { throttle_rate: 120, queue_length: 1 }
    );
  };

  const selectTopic = (topic: RosTopicInfo) => {
    if (selectedTopic === topic.name) return;
    selectedTopic = topic.name;
    selectedTopicType = topic.type;
    subscribeTopicPreview(topic.name);
  };

  const refreshTopics = async () => {
    loadingTopics = true;
    topicsError = '';
    try {
      const client = getRosbridgeClient();
      const loaded = await client.listTopics();
      topics = [...loaded].sort((left, right) => left.name.localeCompare(right.name));

      if (selectedTopic && !topics.some((topic) => topic.name === selectedTopic)) {
        selectedTopic = '';
        selectedTopicType = '';
        clearPreview();
      }
      if (!selectedTopic && topics.length > 0) {
        selectTopic(topics[0]);
      }
    } catch (error) {
      topicsError = toErrorMessage(error);
    } finally {
      loadingTopics = false;
    }
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    const client = getRosbridgeClient();
    rosbridgeStatus = client.getStatus();
    const offStatus = client.onStatusChange((next) => {
      rosbridgeStatus = next;
      if (next === 'connected' && topics.length === 0 && !loadingTopics) {
        void refreshTopics();
      }
    });
    void refreshTopics();
    return () => {
      offStatus();
      unsubscribePreview?.();
      unsubscribePreview = null;
    };
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">ROSBridge</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">ROSトピック一覧</h1>
      <p class="mt-2 text-sm text-slate-600">
        rosbridge 経由で公開されている topic を確認し、カーソルを当てた topic の最新メッセージを表示します。
      </p>
    </div>
    <div class="flex items-center gap-3">
      <span class="chip">status: {rosbridgeStatus}</span>
      <span class="chip">topics: {topicCount}</span>
      <Button.Root class="btn-ghost" type="button" onclick={() => void refreshTopics()}>
        更新
      </Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
  <div class="card p-6">
    <div class="mb-4 flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">Topic List</h2>
      {#if loadingTopics}
        <span class="text-xs text-slate-500">読み込み中...</span>
      {/if}
    </div>

    {#if topicsError}
      <div class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        {topicsError}
      </div>
    {:else if !topics.length && !loadingTopics}
      <p class="text-sm text-slate-500">topic が見つかりませんでした。</p>
    {:else}
      <div class="max-h-[560px] overflow-y-auto rounded-2xl border border-slate-200/60 bg-white/70">
        <ul class="divide-y divide-slate-200/70">
          {#each topics as topic}
            <li>
              <button
                type="button"
                class={`flex w-full items-start justify-between gap-3 px-4 py-3 text-left transition hover:bg-slate-100/80 ${
                  selectedTopic === topic.name ? 'bg-slate-100/80' : ''
                }`}
                onmouseenter={() => selectTopic(topic)}
                onfocus={() => selectTopic(topic)}
                onclick={() => selectTopic(topic)}
              >
                <span class="font-mono text-xs text-slate-800">{topic.name}</span>
                <span class="shrink-0 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-500">
                  {topic.type || '-'}
                </span>
              </button>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">Topic Preview</h2>
    {#if selectedTopic}
      <div class="mt-4 flex flex-wrap gap-2">
        <span class="chip font-mono text-[11px]">{selectedTopic}</span>
        <span class="chip">{selectedTopicType || 'unknown type'}</span>
        <span class="chip">更新: {previewUpdatedAt || '-'}</span>
      </div>
      <div class="mt-4 rounded-2xl border border-slate-200/60 bg-white/80 p-4">
        {#if previewPayload}
          <pre class="max-h-[460px] overflow-auto whitespace-pre-wrap text-xs text-slate-700">{JSON.stringify(previewPayload, null, 2)}</pre>
        {:else if previewRaw}
          <pre class="max-h-[460px] overflow-auto whitespace-pre-wrap text-xs text-slate-700">{previewRaw}</pre>
        {:else}
          <p class="text-sm text-slate-500">この topic のメッセージを待機中です。</p>
        {/if}
      </div>
    {:else}
      <p class="mt-4 text-sm text-slate-500">一覧の topic にカーソルを当てると内容を表示します。</p>
    {/if}
  </div>
</section>
