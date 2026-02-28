<script lang="ts">
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { Button, Tooltip } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api, type ExperimentEpisodeLink } from '$lib/api/client';
  import DatasetViewerPanel from '$lib/components/storage/DatasetViewerPanel.svelte';
  import { formatPercent } from '$lib/format';

  type Experiment = {
    id: string;
    model_id?: string;
    name?: string;
    evaluation_count?: number;
    metric_options?: string[] | null;
  };

  type ModelInfo = {
    id: string;
    dataset_id?: string | null;
  };

  type DatasetInfo = {
    id: string;
    name?: string;
    status?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetInfo[];
  };

  type EpisodeListResponse = {
    total?: number;
    episodes?: { episode_index: number }[];
  };

  type Evaluation = {
    trial_index: number;
    value?: string;
    notes?: string | null;
    image_files?: string[] | null;
    episode_links?: ExperimentEpisodeLink[] | null;
  };

  type EvaluationListResponse = {
    evaluations?: Evaluation[];
    total?: number;
  };

  type EvaluationSummary = {
    total?: number;
    counts?: Record<string, number>;
    rates?: Record<string, number>;
  };

  type MediaUrlResponse = {
    urls?: Record<string, string>;
  };

  type EvaluationDraft = {
    trial_index: number;
    value: string;
    selection: string;
    custom: string;
    notes: string;
    image_files: string[];
    episode_links: ExperimentEpisodeLink[];
  };

  const DEFAULT_METRIC_OPTIONS = ['成功', '失敗', '部分成功'];

  const experimentId = $derived(page.params.experiment_id ?? '');

  const experimentQuery = createQuery<Experiment>(
    toStore(() => ({
      queryKey: ['experiments', 'detail', experimentId],
      queryFn: () => api.experiments.get(experimentId),
      enabled: Boolean(experimentId)
    }))
  );

  const evaluationsQuery = createQuery<EvaluationListResponse>(
    toStore(() => ({
      queryKey: ['experiments', 'evaluations', experimentId],
      queryFn: () => api.experiments.evaluations(experimentId),
      enabled: Boolean(experimentId)
    }))
  );

  const summaryQuery = createQuery<EvaluationSummary>(
    toStore(() => ({
      queryKey: ['experiments', 'summary', experimentId],
      queryFn: () => api.experiments.evaluationSummary(experimentId),
      enabled: Boolean(experimentId)
    }))
  );

  const modelQuery = createQuery<ModelInfo>(
    toStore(() => ({
      queryKey: ['storage', 'model', ($experimentQuery.data as Experiment | undefined)?.model_id ?? ''],
      queryFn: () =>
        api.storage.model(($experimentQuery.data as Experiment | undefined)?.model_id ?? '') as Promise<ModelInfo>,
      enabled: Boolean(($experimentQuery.data as Experiment | undefined)?.model_id)
    }))
  );

  const datasetsQuery = createQuery<DatasetListResponse>(
    toStore(() => ({
      queryKey: ['storage', 'datasets', 'all'],
      queryFn: () => api.storage.datasets() as Promise<DatasetListResponse>
    }))
  );

  let evaluationItems: EvaluationDraft[] = $state([]);
  let initializedId = $state('');
  let submitting = $state(false);
  let error = $state('');
  let success = $state('');
  let uploadingIndex: number | null = $state(null);
  let uploadError = $state('');
  let imageUrlsError = $state('');
  let imageUrlMap: Record<string, string> = $state({});
  let imageKeySignature = $state('');
  let linkEditorOpen = $state(false);
  let linkViewerOpen = $state(false);
  let activeTrialIndex = $state(1);
  let viewerSelectedLinkKey = $state('');
  let editorLinksDraft: ExperimentEpisodeLink[] = $state([]);
  let editorDatasetSearch = $state('');
  let editorSelectedDatasetId = $state('');
  let editorEpisodeSelections: number[] = $state([]);

  const experiment = $derived($experimentQuery.data as Experiment | undefined);
  const evaluationCount = $derived(experiment?.evaluation_count ?? 0);
  const metricOptions = $derived(
    experiment?.metric_options && experiment.metric_options.length
      ? experiment.metric_options
      : DEFAULT_METRIC_OPTIONS
  );
  const recommendedDatasetId = $derived($modelQuery.data?.dataset_id ?? '');
  const allDatasets = $derived(
    (($datasetsQuery.data?.datasets ?? []).filter((item) => item.status === 'active') as DatasetInfo[])
  );
  const filteredDatasets = $derived(
    allDatasets.filter((item) => {
      if (!editorDatasetSearch.trim()) return true;
      const keyword = editorDatasetSearch.trim().toLowerCase();
      return item.id.toLowerCase().includes(keyword) || (item.name ?? '').toLowerCase().includes(keyword);
    })
  );
  const activeEvaluationDraft = $derived(
    evaluationItems.find((item) => item.trial_index === activeTrialIndex) as EvaluationDraft | undefined
  );
  const viewerLinks = $derived(
    [...(activeEvaluationDraft?.episode_links ?? [])].sort((a, b) => a.sort_order - b.sort_order)
  );
  const viewerSelectedLink = $derived(
    viewerLinks.find((link) => `${link.dataset_id}:${link.episode_index}` === viewerSelectedLinkKey) ??
      viewerLinks[0]
  );

  const editorDatasetViewerQuery = createQuery(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-editor', editorSelectedDatasetId],
      queryFn: () => api.storage.datasetViewer(editorSelectedDatasetId),
      enabled: Boolean(editorSelectedDatasetId)
    }))
  );

  const editorEpisodesQuery = createQuery<EpisodeListResponse>(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-editor', editorSelectedDatasetId, 'episodes'],
      queryFn: () => api.storage.datasetViewerEpisodes(editorSelectedDatasetId) as Promise<EpisodeListResponse>,
      enabled: Boolean(editorSelectedDatasetId) && Boolean($editorDatasetViewerQuery.data?.is_local)
    }))
  );

  const buildEvaluationDrafts = (exp: Experiment, existing: Evaluation[]) => {
    const map = new Map(existing.map((item) => [item.trial_index, item]));
    const drafts: EvaluationDraft[] = [];
    for (let index = 1; index <= (exp.evaluation_count ?? 0); index += 1) {
      const row = map.get(index);
      const currentValue = row?.value ?? '';
      const isCustom = currentValue ? !metricOptions.includes(currentValue) : true;
      drafts.push({
        trial_index: index,
        value: currentValue,
        selection: isCustom ? 'その他' : currentValue,
        custom: isCustom ? currentValue : '',
        notes: row?.notes ?? '',
        image_files: row?.image_files ?? [],
        episode_links: row?.episode_links ?? []
      });
    }
    return drafts;
  };

  const resetFromServer = () => {
    if (!experiment) return;
    const existing = $evaluationsQuery.data?.evaluations ?? [];
    evaluationItems = buildEvaluationDrafts(experiment, existing);
  };

  $effect(() => {
    if (experiment && $evaluationsQuery.data && experiment.id !== initializedId) {
      resetFromServer();
      initializedId = experiment.id;
    }
  });

  const filledCount = $derived(evaluationItems.filter((item) => item.value.trim()).length);
  const remainingCount = $derived(Math.max(0, (experiment?.evaluation_count ?? 0) - filledCount));
  const imageKeys = $derived(
    Array.from(new Set(evaluationItems.flatMap((item) => item.image_files ?? []).filter(Boolean)))
  );

  $effect(() => {
    const signature = imageKeys.join('|');
    if (signature !== imageKeySignature) {
      imageKeySignature = signature;
      void loadImageUrls();
    }
  });

  const updateItem = (index: number, updates: Partial<EvaluationDraft>) => {
    evaluationItems = evaluationItems.map((item, idx) =>
      idx === index ? { ...item, ...updates } : item
    );
  };

  const handleSelect = (index: number, value: string) => {
    if (value === 'その他') {
      const custom = evaluationItems[index]?.custom ?? '';
      updateItem(index, { selection: value, value: custom });
    } else {
      updateItem(index, { selection: value, value });
    }
  };

  const handleCustomInput = (index: number, value: string) => {
    if (evaluationItems[index]?.selection === 'その他') {
      updateItem(index, { custom: value, value });
    } else {
      updateItem(index, { custom: value });
    }
  };

  const handleNotesInput = (index: number, value: string) => {
    updateItem(index, { notes: value });
  };

  const handleRemoveImage = (index: number, key: string) => {
    const next = (evaluationItems[index]?.image_files ?? []).filter((item) => item !== key);
    updateItem(index, { image_files: next });
  };

  const handleUpload = async (index: number, event: Event) => {
    if (!experiment) return;
    const input = event.currentTarget as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    if (!files.length) return;

    uploadingIndex = index;
    uploadError = '';
    try {
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file));
      const response = await api.experiments.upload(experiment.id, formData, {
        scope: 'evaluation',
        trial_index: index + 1
      });
      if (response?.keys?.length) {
        const existing = evaluationItems[index]?.image_files ?? [];
        updateItem(index, { image_files: [...existing, ...response.keys] });
      }
      input.value = '';
    } catch {
      uploadError = '画像アップロードに失敗しました。';
    } finally {
      uploadingIndex = null;
    }
  };

  const formatRates = (rates?: Record<string, number>) => {
    if (!rates || Object.keys(rates).length === 0) return '-';
    return Object.entries(rates)
      .map(([key, value]) => `${key}: ${formatPercent(value)}`)
      .join(' / ');
  };

  const refetchSummary = async () => {
    const refetch = $summaryQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
  };

  const refetchEvaluations = async () => {
    const refetch = $evaluationsQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
  };

  const loadImageUrls = async () => {
    if (!imageKeys.length) {
      imageUrlMap = {};
      imageUrlsError = '';
      return;
    }
    try {
      const response = (await api.experiments.mediaUrls(imageKeys)) as MediaUrlResponse;
      imageUrlMap = response?.urls ?? {};
      imageUrlsError = '';
    } catch {
      imageUrlsError = '画像URLの取得に失敗しました。';
    }
  };

  const handleSave = async () => {
    if (!experiment) return;
    submitting = true;
    error = '';
    success = '';
    try {
      const items = evaluationItems.map((item) => ({
        value: item.value ?? '',
        notes: item.notes || null,
        image_files: item.image_files,
        episode_links: item.episode_links
      }));
      await api.experiments.replaceEvaluations(experiment.id, { items });
      await refetchSummary();
      await refetchEvaluations();
      resetFromServer();
      success = '評価を保存しました。';
    } catch {
      error = '評価の保存に失敗しました。';
    } finally {
      submitting = false;
    }
  };

  const handleClear = async () => {
    if (!experiment) return;
    if (!confirm('評価を全て削除しますか？')) return;
    submitting = true;
    error = '';
    success = '';
    try {
      await api.experiments.replaceEvaluations(experiment.id, { items: [] });
      await refetchSummary();
      await refetchEvaluations();
      resetFromServer();
      success = '評価を削除しました。';
    } catch {
      error = '評価の削除に失敗しました。';
    } finally {
      submitting = false;
    }
  };

  const normalizeEpisodeLinks = (links: ExperimentEpisodeLink[]) =>
    links
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order)
      .map((link, idx) => ({
        dataset_id: link.dataset_id,
        episode_index: link.episode_index,
        sort_order: idx
      }));

  const replaceTrialEpisodeLinks = (trialIndex: number, links: ExperimentEpisodeLink[]) => {
    const rowIndex = evaluationItems.findIndex((item) => item.trial_index === trialIndex);
    if (rowIndex < 0) return;
    updateItem(rowIndex, { episode_links: normalizeEpisodeLinks(links) });
  };

  const openLinkEditor = (trialIndex: number) => {
    activeTrialIndex = trialIndex;
    const row = evaluationItems.find((item) => item.trial_index === trialIndex);
    const existingLinks = normalizeEpisodeLinks(row?.episode_links ?? []);
    editorLinksDraft = existingLinks;
    editorDatasetSearch = '';
    const fallbackDatasetId = allDatasets[0]?.id ?? '';
    editorSelectedDatasetId =
      existingLinks[0]?.dataset_id || recommendedDatasetId || fallbackDatasetId;
    editorEpisodeSelections = existingLinks
      .filter((link) => link.dataset_id === editorSelectedDatasetId)
      .map((link) => link.episode_index);
    linkEditorOpen = true;
  };

  const openLinkViewer = (trialIndex: number) => {
    activeTrialIndex = trialIndex;
    const row = evaluationItems.find((item) => item.trial_index === trialIndex);
    const links = normalizeEpisodeLinks(row?.episode_links ?? []);
    viewerSelectedLinkKey = links.length ? `${links[0].dataset_id}:${links[0].episode_index}` : '';
    linkViewerOpen = true;
  };

  const closeLinkEditor = () => {
    linkEditorOpen = false;
  };

  const applyLinkEditor = () => {
    replaceTrialEpisodeLinks(activeTrialIndex, editorLinksDraft);
    linkEditorOpen = false;
  };

  const openEditorFromViewer = () => {
    linkViewerOpen = false;
    openLinkEditor(activeTrialIndex);
  };

  const removeEditorLink = (datasetId: string, episodeIndex: number) => {
    editorLinksDraft = normalizeEpisodeLinks(
      editorLinksDraft.filter(
        (link) => !(link.dataset_id === datasetId && link.episode_index === episodeIndex)
      )
    );
  };

  const addSelectedEpisodesToEditor = () => {
    if (!editorSelectedDatasetId || !editorEpisodeSelections.length) return;
    const existing = new Set(editorLinksDraft.map((link) => `${link.dataset_id}:${link.episode_index}`));
    const merged = [...editorLinksDraft];
    for (const episodeIndex of editorEpisodeSelections) {
      const key = `${editorSelectedDatasetId}:${episodeIndex}`;
      if (existing.has(key)) continue;
      merged.push({
        dataset_id: editorSelectedDatasetId,
        episode_index: episodeIndex,
        sort_order: merged.length
      });
    }
    editorLinksDraft = normalizeEpisodeLinks(merged);
  };

  const refreshEditorDataset = async () => {
    if (!editorSelectedDatasetId) return;
    const refetchViewer = $editorDatasetViewerQuery?.refetch;
    if (typeof refetchViewer === 'function') {
      await refetchViewer();
    }
    const refetchEpisodes = $editorEpisodesQuery?.refetch;
    if (typeof refetchEpisodes === 'function') {
      await refetchEpisodes();
    }
  };

  const editorPreviewEpisode = $derived.by(() => {
    if (editorEpisodeSelections.length > 0) {
      return editorEpisodeSelections[0];
    }
    const existing = editorLinksDraft.find((link) => link.dataset_id === editorSelectedDatasetId);
    return existing?.episode_index ?? 0;
  });

  $effect(() => {
    if (!linkEditorOpen) return;
    if (!editorSelectedDatasetId && recommendedDatasetId) {
      editorSelectedDatasetId = recommendedDatasetId;
    }
  });

  $effect(() => {
    if (!linkViewerOpen) return;
    if (!viewerLinks.length) {
      viewerSelectedLinkKey = '';
      return;
    }
    if (!viewerSelectedLinkKey) {
      viewerSelectedLinkKey = `${viewerLinks[0].dataset_id}:${viewerLinks[0].episode_index}`;
    }
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">評価入力</h1>
      <p class="mt-2 text-sm text-slate-600">{experiment?.name ?? experiment?.id ?? ''}</p>
    </div>
    <div class="flex flex-wrap gap-2">
      {#if experiment?.id}
        <Tooltip.Root>
          <Tooltip.Trigger class="btn-ghost" type={null}>
            {#snippet child({ props })}
              <Button.Root {...props} href={`/experiments/${experiment.id}`}>開く</Button.Root>
            {/snippet}
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content
              class="rounded-lg bg-slate-900/90 px-2 py-1 text-xs text-white shadow-lg"
              sideOffset={6}
            >
              {experiment?.name ?? experiment?.id}
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
        <Button.Root class="btn-ghost" href={`/experiments/${experiment.id}/analyses`}>考察入力へ</Button.Root>
      {/if}
    </div>
  </div>
</section>

{#if linkViewerOpen}
  <div class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]">
    <div class="mx-auto mt-8 w-[min(1200px,96vw)] rounded-2xl border border-slate-200/70 bg-white p-4 shadow-xl">
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-slate-900">紐付けエピソード閲覧</p>
          <p class="text-xs text-slate-500">試行 {activeTrialIndex}</p>
        </div>
        <div class="flex gap-2">
          <Button.Root class="btn-ghost" type="button" onclick={openEditorFromViewer}>編集へ</Button.Root>
          <Button.Root class="btn-ghost" type="button" onclick={() => (linkViewerOpen = false)}>閉じる</Button.Root>
        </div>
      </div>
      <div class="mt-4 grid h-[74vh] min-h-0 gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div class="min-h-0 overflow-y-auto rounded-xl border border-slate-200/70 bg-white/70 p-3">
          {#if viewerLinks.length}
            <div class="space-y-2">
              {#each viewerLinks as link}
                <button
                  class={`w-full rounded-xl border px-3 py-2 text-left text-sm transition ${
                    viewerSelectedLinkKey === `${link.dataset_id}:${link.episode_index}`
                      ? 'border-brand/40 bg-brand/10 text-slate-900'
                      : 'border-slate-200/70 bg-white/80 text-slate-700 hover:border-slate-300'
                  }`}
                  type="button"
                  onclick={() => (viewerSelectedLinkKey = `${link.dataset_id}:${link.episode_index}`)}
                >
                  <p class="font-semibold">{link.dataset_id}</p>
                  <p class="text-xs text-slate-500">episode {link.episode_index}</p>
                </button>
              {/each}
            </div>
          {:else}
            <p class="text-sm text-slate-500">紐付けがありません。</p>
          {/if}
        </div>
        <div class="min-h-0">
          {#if viewerSelectedLink}
            <DatasetViewerPanel
              datasetId={viewerSelectedLink.dataset_id}
              episodeIndex={viewerSelectedLink.episode_index}
            />
          {:else}
            <div class="flex h-full items-center justify-center rounded-xl border border-slate-200/70 bg-white/70 text-sm text-slate-500">
              表示するエピソードがありません。
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}

{#if linkEditorOpen}
  <div class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]">
    <div class="mx-auto mt-6 w-[min(1320px,98vw)] rounded-2xl border border-slate-200/70 bg-white p-4 shadow-xl">
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-slate-900">紐付けエピソード編集</p>
          <p class="text-xs text-slate-500">試行 {activeTrialIndex}</p>
        </div>
        <div class="flex gap-2">
          <Button.Root class="btn-ghost" type="button" onclick={closeLinkEditor}>キャンセル</Button.Root>
          <Button.Root class="btn-primary" type="button" onclick={applyLinkEditor}>反映</Button.Root>
        </div>
      </div>
      <div class="mt-4 grid h-[78vh] min-h-0 gap-4 lg:grid-cols-[minmax(0,1fr)_390px]">
        <div class="min-h-0">
          <DatasetViewerPanel
            datasetId={editorSelectedDatasetId}
            episodeIndex={editorPreviewEpisode}
            onEpisodeChange={(nextEpisode) => {
              editorEpisodeSelections = [nextEpisode];
            }}
          />
        </div>
        <div class="min-h-0 overflow-y-auto rounded-xl border border-slate-200/70 bg-white/70 p-3">
          <div class="space-y-4">
            <div>
              <p class="label">推奨データセット</p>
              {#if recommendedDatasetId}
                <Button.Root
                  class="btn-ghost mt-2 w-full justify-start"
                  type="button"
                  onclick={() => {
                    editorSelectedDatasetId = recommendedDatasetId;
                    editorEpisodeSelections = [];
                  }}
                >
                  {recommendedDatasetId}
                </Button.Root>
              {:else}
                <p class="mt-2 text-xs text-slate-500">推奨データセットはありません。</p>
              {/if}
            </div>

            <div>
              <p class="label">全データセット検索</p>
              <input
                class="input mt-2"
                type="text"
                placeholder="dataset id で検索"
                bind:value={editorDatasetSearch}
              />
              <div class="mt-2 max-h-40 space-y-1 overflow-y-auto rounded-lg border border-slate-200/70 p-2">
                {#if filteredDatasets.length}
                  {#each filteredDatasets as ds}
                    <button
                      class={`w-full rounded-lg px-2 py-1 text-left text-xs transition ${
                        editorSelectedDatasetId === ds.id
                          ? 'bg-brand/10 text-slate-900'
                          : 'text-slate-600 hover:bg-slate-100/70'
                      }`}
                      type="button"
                      onclick={() => {
                        editorSelectedDatasetId = ds.id;
                        editorEpisodeSelections = [];
                      }}
                    >
                      {ds.id}
                    </button>
                  {/each}
                {:else}
                  <p class="text-xs text-slate-500">該当データセットがありません。</p>
                {/if}
              </div>
            </div>

            <div>
              <p class="label">エピソード選択</p>
              {#if !editorSelectedDatasetId}
                <p class="mt-2 text-xs text-slate-500">データセットを選択してください。</p>
              {:else if $editorDatasetViewerQuery.isLoading}
                <p class="mt-2 text-xs text-slate-500">データセット情報を取得中...</p>
              {:else if $editorDatasetViewerQuery.error}
                <p class="mt-2 text-xs text-rose-600">
                  {$editorDatasetViewerQuery.error instanceof Error
                    ? $editorDatasetViewerQuery.error.message
                    : 'データセット情報の取得に失敗しました。'}
                </p>
              {:else if !$editorDatasetViewerQuery.data?.is_local}
                <p class="mt-2 text-xs text-slate-500">
                  ローカル未配置です。左ペインの同期完了後に再読み込みしてください。
                </p>
                <Button.Root class="btn-ghost mt-2" type="button" onclick={refreshEditorDataset}>
                  再読み込み
                </Button.Root>
              {:else if $editorEpisodesQuery.isLoading}
                <p class="mt-2 text-xs text-slate-500">エピソード一覧を取得中...</p>
              {:else}
                <div class="mt-2 max-h-40 space-y-1 overflow-y-auto rounded-lg border border-slate-200/70 p-2">
                  {#if ($editorEpisodesQuery.data?.episodes ?? []).length}
                    {#each $editorEpisodesQuery.data?.episodes ?? [] as episode}
                      <label class="flex items-center gap-2 text-xs text-slate-700">
                        <input
                          type="checkbox"
                          class="h-4 w-4 rounded border-slate-300"
                          bind:group={editorEpisodeSelections}
                          value={episode.episode_index}
                        />
                        episode {episode.episode_index}
                      </label>
                    {/each}
                  {:else}
                    <p class="text-xs text-slate-500">エピソードがありません。</p>
                  {/if}
                </div>
                <Button.Root class="btn-ghost mt-2 w-full" type="button" onclick={addSelectedEpisodesToEditor}>
                  選択エピソードを追加
                </Button.Root>
              {/if}
            </div>

            <div>
              <p class="label">現在の紐付け</p>
              <div class="mt-2 max-h-48 space-y-2 overflow-y-auto rounded-lg border border-slate-200/70 p-2">
                {#if editorLinksDraft.length}
                  {#each editorLinksDraft as link}
                    <div class="flex items-center justify-between gap-2 rounded-lg bg-slate-50/70 px-2 py-1 text-xs text-slate-700">
                      <div>
                        <p class="font-semibold">{link.dataset_id}</p>
                        <p class="text-slate-500">episode {link.episode_index}</p>
                      </div>
                      <Button.Root
                        class="btn-ghost px-2 py-1 text-[11px]"
                        type="button"
                        onclick={() => removeEditorLink(link.dataset_id, link.episode_index)}
                      >
                        削除
                      </Button.Root>
                    </div>
                  {/each}
                {:else}
                  <p class="text-xs text-slate-500">紐付けはありません。</p>
                {/if}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
{/if}

<section class="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="text-xl font-semibold text-slate-900">評価一覧</h2>
      <div class="flex flex-wrap gap-2">
        <Button.Root class="btn-ghost" type="button" onclick={resetFromServer}>最新を反映</Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleClear}>全削除</Button.Root>
      </div>
    </div>

    {#if uploadError}
      <p class="mt-3 text-sm text-rose-600">{uploadError}</p>
    {/if}
    {#if imageUrlsError}
      <p class="mt-3 text-sm text-rose-600">{imageUrlsError}</p>
    {/if}
    {#if error}
      <p class="mt-3 text-sm text-rose-600">{error}</p>
    {/if}
    {#if success}
      <p class="mt-3 text-sm text-emerald-600">{success}</p>
    {/if}

    <div class="mt-4 space-y-4">
      {#if $evaluationsQuery.isLoading}
        <p class="text-sm text-slate-500">読み込み中...</p>
      {:else if evaluationItems.length}
        {#each evaluationItems as item, index}
          <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4 shadow-sm">
            <div class="flex items-center justify-between">
              <p class="font-semibold text-slate-800">試行 {item.trial_index}</p>
              <span class="chip">#{item.trial_index}</span>
            </div>
            <div class="mt-3 grid gap-3 md:grid-cols-2">
              <label class="text-sm font-semibold text-slate-700">
                <span class="label">評価値</span>
                <select
                  class="input mt-2"
                  value={item.selection}
                  onchange={(event) => handleSelect(index, (event.currentTarget as HTMLSelectElement).value)}
                >
                  {#each metricOptions as option}
                    <option value={option}>{option}</option>
                  {/each}
                  <option value="その他">その他</option>
                </select>
                {#if item.selection === 'その他'}
                  <input
                    class="input mt-2"
                    type="text"
                    placeholder="自由入力"
                    value={item.custom}
                    oninput={(event) =>
                      handleCustomInput(index, (event.currentTarget as HTMLInputElement).value)
                    }
                  />
                {/if}
              </label>
              <label class="text-sm font-semibold text-slate-700">
                <span class="label">備考</span>
                <input
                  class="input mt-2"
                  type="text"
                  value={item.notes}
                  oninput={(event) =>
                    handleNotesInput(index, (event.currentTarget as HTMLInputElement).value)
                  }
                />
              </label>
            </div>
            <div class="mt-3 rounded-xl border border-slate-200/70 bg-slate-50/70 p-3">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p class="text-sm font-semibold text-slate-800">紐付けエピソード</p>
                  <p class="text-xs text-slate-500">{item.episode_links.length} 件</p>
                </div>
                {#if item.episode_links.length > 0}
                  <Button.Root class="btn-ghost" type="button" onclick={() => openLinkViewer(item.trial_index)}>
                    閲覧
                  </Button.Root>
                {:else}
                  <Button.Root class="btn-ghost" type="button" onclick={() => openLinkEditor(item.trial_index)}>
                    新規紐付け
                  </Button.Root>
                {/if}
              </div>
            </div>
            <div class="mt-3 text-sm text-slate-600">
              <p class="label">画像プレビュー</p>
              {#if item.image_files.length}
                <div class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {#each item.image_files as key}
                    <div class="group relative">
                      {#if imageUrlMap[key]}
                        <img
                          src={imageUrlMap[key]}
                          alt={`評価画像 ${item.trial_index}`}
                          class="h-20 w-full rounded-lg border border-slate-200/60 object-cover"
                          loading="lazy"
                        />
                      {:else}
                        <div class="flex h-20 items-center justify-center rounded-lg border border-dashed border-slate-200/70 bg-white/70 text-xs text-slate-400">
                          準備中
                        </div>
                      {/if}
                      <Button.Root
                        class="absolute right-1 top-1 rounded-full bg-slate-900/80 px-2 py-1 text-[10px] font-semibold text-white opacity-0 transition group-hover:opacity-100"
                        type="button"
                        onclick={() => handleRemoveImage(index, key)}
                        aria-label="画像を削除"
                        title="削除"
                      >
                        削除
                      </Button.Root>
                    </div>
                  {/each}
                </div>
              {:else}
                <p class="mt-2 text-xs text-slate-400">画像はありません。</p>
              {/if}
              <input
                class="input mt-2"
                type="file"
                accept="image/*"
                multiple
                disabled={uploadingIndex === index}
                onchange={(event) => handleUpload(index, event)}
              />
            </div>
          </div>
        {/each}
      {:else}
        <p class="text-sm text-slate-500">評価項目がありません。</p>
      {/if}
    </div>

    <div class="mt-6 flex flex-wrap gap-3">
      <Button.Root class="btn-primary" type="button" onclick={handleSave} disabled={submitting}>
        保存
      </Button.Root>
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">集計</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">入力済み</p>
        <p class="text-base font-semibold text-slate-800">{filledCount} / {evaluationCount}</p>
        <p class="text-xs text-slate-500">未入力: {remainingCount}</p>
      </div>
      <div>
        <p class="label">保存済み評価件数</p>
        <p class="text-base font-semibold text-slate-800">{$summaryQuery.data?.total ?? 0}</p>
      </div>
      <div>
        <p class="label">カテゴリ比率</p>
        <p class="text-sm font-semibold text-slate-800">{formatRates($summaryQuery.data?.rates)}</p>
      </div>
    </div>
  </div>
</section>
