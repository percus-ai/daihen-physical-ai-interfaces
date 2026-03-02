<script lang="ts">
  import { onDestroy } from 'svelte';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { Button, Tooltip } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';
		  import {
		    api,
		    type ExperimentEpisodeLink,
		    type DatasetViewerEpisodeVideoWindowResponse
		  } from '$lib/api/client';
  import ViewerDialogShell from '$lib/viewer/ViewerDialogShell.svelte';
  import { createDatasetAvailabilityController } from '$lib/viewer/datasetAvailability';
  import SessionLayoutEditor from '$lib/components/recording/SessionLayoutEditor.svelte';
  import DatasetEpisodeSearchTab from '$lib/components/recording/DatasetEpisodeSearchTab.svelte';
  import DatasetEpisodeThumbnail from '$lib/components/recording/DatasetEpisodeThumbnail.svelte';
  import { qk } from '$lib/queryKeys';
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

  type Evaluation = {
    trial_index: number;
    value?: string;
    blueprint_id?: string | null;
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
    blueprint_id: string | null;
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
      queryKey: qk.storage.model(($experimentQuery.data as Experiment | undefined)?.model_id ?? ''),
      queryFn: () =>
        api.storage.model(($experimentQuery.data as Experiment | undefined)?.model_id ?? '') as Promise<ModelInfo>,
      enabled: Boolean(($experimentQuery.data as Experiment | undefined)?.model_id)
    }))
  );

  const datasetsQuery = createQuery<DatasetListResponse>(
    toStore(() => ({
      queryKey: qk.storage.datasetsAll(),
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
  let linkModalOpen = $state(false);
  let activeTrialIndex = $state(1);
  let modalDatasetId = $state('');
  let modalEpisodeIndex = $state(0);
  const queryClient = useQueryClient();
  let viewerLayoutEditMode = $state(false);
  let viewerInitialInspectorTab = $state<'blueprint' | 'selection' | 'search'>('blueprint');
  let viewerDatasetAutoplayNonce = $state(0);

  let viewerMetaByDatasetId = $state<Record<string, { cameraKey: string }>>({});
  let viewerMetaLoadingByDatasetId = $state<Record<string, boolean>>({});
  let episodeCarouselIndexByTrialIndex = $state<Record<number, number>>({});

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

  $effect(() => {
    if (!linkModalOpen) return;
    if (modalDatasetId) return;
    const fallbackDatasetId = allDatasets[0]?.id ?? '';
    const nextDatasetId = recommendedDatasetId || fallbackDatasetId;
    if (!nextDatasetId) return;
    modalDatasetId = nextDatasetId;
    modalEpisodeIndex = 0;
  });

  const viewerDatasetId = $derived(modalDatasetId);
  const viewerEpisodeRaw = $derived(modalEpisodeIndex);

  const viewerAvailability = createDatasetAvailabilityController({
    datasetId: toStore(() => viewerDatasetId),
    enabled: toStore(() => Boolean(linkModalOpen) && Boolean(viewerDatasetId)),
    queryClient,
    notify: (message, level = 'info') => {
      if (level === 'success') toast.success(message);
      else if (level === 'error') toast.error(message);
      else toast(message);
    }
  });
  onDestroy(viewerAvailability.destroy);

	  const viewerDatasetQuery = viewerAvailability.datasetQuery;
	  const viewerIsLocal = viewerAvailability.isLocal;
	  const viewerIsLocalValue = $derived($viewerIsLocal);
	  const viewerTotalEpisodes = viewerAvailability.totalEpisodes;
  const viewerEpisodeIndex = $derived.by(() => {
    const next = Math.max(0, Math.floor(Number(viewerEpisodeRaw) || 0));
    if (!Number.isFinite(next)) return 0;
    const total = $viewerTotalEpisodes;
    if (total <= 0) return next;
    if (next >= total) return Math.max(0, total - 1);
    return next;
  });

	  const viewerDatasetSignalKeys = viewerAvailability.signalKeys;
  const viewerSyncJobQuery = viewerAvailability.syncJobQuery;
  const viewerSyncJobId = viewerAvailability.syncJobId;
  const viewerSyncStarting = viewerAvailability.syncStarting;
  const refetchViewerDataset = viewerAvailability.refetch;
	  const startViewerSyncJob = viewerAvailability.startSync;

	  const viewerVideoWindowEnabled = $derived(
	    Boolean(linkModalOpen) && Boolean(viewerDatasetId) && viewerIsLocalValue
	  );
	  const viewerVideoWindowQuery = createQuery<DatasetViewerEpisodeVideoWindowResponse>(
	    toStore(() => ({
	      queryKey: qk.storage.datasetViewerEpisodeVideoWindow(viewerDatasetId, viewerEpisodeIndex),
	      queryFn: () => api.storage.datasetViewerEpisodeVideoWindow(viewerDatasetId, viewerEpisodeIndex),
	      enabled: viewerVideoWindowEnabled
	    }))
	  );
	  const viewerVideoWindows = $derived.by(() => {
	    const videos = $viewerVideoWindowQuery.data?.videos ?? [];
	    const out: Record<string, { from_s: number; to_s: number }> = {};
	    for (const video of videos) {
	      out[video.key] = {
	        from_s: Number(video.from_s) || 0,
	        to_s: Number(video.to_s) || 0
	      };
	    }
	    return out;
	  });

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
        blueprint_id: row?.blueprint_id ?? null,
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

  const clampIndex = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

  const getEpisodeCarouselIndex = (trialIndex: number, total: number) => {
    const raw = Number(episodeCarouselIndexByTrialIndex[trialIndex] ?? 0);
    const next = Number.isFinite(raw) ? Math.floor(raw) : 0;
    return total > 0 ? clampIndex(next, 0, Math.max(0, total - 1)) : 0;
  };

  const setEpisodeCarouselIndex = (trialIndex: number, next: number, total: number) => {
    const bounded = total > 0 ? clampIndex(Math.floor(next), 0, Math.max(0, total - 1)) : 0;
    episodeCarouselIndexByTrialIndex = { ...episodeCarouselIndexByTrialIndex, [trialIndex]: bounded };
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
        blueprint_id: item.blueprint_id || null,
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

  let episodeLinksAutoSaving = $state(false);
  let episodeLinksAutoSavePending = $state(false);
  let episodeLinksAutoSaveTimer: number | null = $state(null);
  const EPISODE_LINKS_AUTOSAVE_TOAST_ID = 'episode-links-autosave';

  const snapshotEvaluationReplaceItems = () =>
    evaluationItems.map((item) => ({
      value: item.value ?? '',
      blueprint_id: item.blueprint_id || null,
      notes: item.notes || null,
      image_files: item.image_files,
      episode_links: item.episode_links
    }));

  const flushEpisodeLinksAutoSave = async () => {
    if (!experiment) return;
    if (submitting) return; // avoid fighting the explicit save flow
    if (episodeLinksAutoSaving) {
      episodeLinksAutoSavePending = true;
      return;
    }
    episodeLinksAutoSaving = true;
    episodeLinksAutoSavePending = false;
    const items = snapshotEvaluationReplaceItems();
    try {
      toast.loading('紐付けを自動保存中...', { id: EPISODE_LINKS_AUTOSAVE_TOAST_ID });
      await api.experiments.replaceEvaluations(experiment.id, { items });
    } catch {
      toast.error('紐付けエピソードの自動保存に失敗しました。', { id: EPISODE_LINKS_AUTOSAVE_TOAST_ID });
      return;
    } finally {
      episodeLinksAutoSaving = false;
    }
    toast.dismiss(EPISODE_LINKS_AUTOSAVE_TOAST_ID);
    if (episodeLinksAutoSavePending) scheduleEpisodeLinksAutoSave();
  };

  const scheduleEpisodeLinksAutoSave = () => {
    episodeLinksAutoSavePending = true;
    if (episodeLinksAutoSaveTimer != null && typeof window !== 'undefined') {
      window.clearTimeout(episodeLinksAutoSaveTimer);
    }
    if (typeof window === 'undefined') return;
    episodeLinksAutoSaveTimer = window.setTimeout(() => {
      episodeLinksAutoSaveTimer = null;
      void flushEpisodeLinksAutoSave();
    }, 650);
  };

  function normalizeEpisodeLinks(links: ExperimentEpisodeLink[]) {
    return links
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order)
      .map((link, idx) => ({
        dataset_id: link.dataset_id,
        episode_index: link.episode_index,
        sort_order: idx
      }));
  }

  const openViewerModal = (
    trialIndex: number,
    options: { editMode?: boolean; inspectorTab?: 'blueprint' | 'selection' | 'search' } = {}
  ) => {
    activeTrialIndex = trialIndex;
    viewerLayoutEditMode = Boolean(options.editMode);
    viewerInitialInspectorTab = options.inspectorTab ?? 'blueprint';
    viewerDatasetAutoplayNonce = 0;

    const row = evaluationItems.find((item) => item.trial_index === trialIndex);
    const links = normalizeEpisodeLinks(row?.episode_links ?? []);
    const first = links[0];

    const fallbackDatasetId = allDatasets[0]?.id ?? '';
    modalDatasetId = first?.dataset_id || recommendedDatasetId || fallbackDatasetId;
    modalEpisodeIndex = first?.episode_index ?? 0;

    linkModalOpen = true;
  };

  const openViewerModalAt = (
    trialIndex: number,
    datasetId: string,
    episodeIndex: number,
    options: { editMode?: boolean; inspectorTab?: 'blueprint' | 'selection' | 'search'; autoplay?: boolean } = {}
  ) => {
    activeTrialIndex = trialIndex;
    viewerLayoutEditMode = Boolean(options.editMode);
    viewerInitialInspectorTab = options.inspectorTab ?? 'blueprint';
    if (options.autoplay) viewerDatasetAutoplayNonce += 1;
    modalDatasetId = datasetId;
    modalEpisodeIndex = Math.max(0, Math.floor(Number(episodeIndex) || 0));
    linkModalOpen = true;
  };

  const activeEpisodeLinks = $derived.by(() => {
    const row = evaluationItems.find((item) => item.trial_index === activeTrialIndex);
    return normalizeEpisodeLinks(row?.episode_links ?? []);
  });

  const updateActiveEpisodeLinks = (nextLinks: ExperimentEpisodeLink[]) => {
    const idx = evaluationItems.findIndex((item) => item.trial_index === activeTrialIndex);
    if (idx < 0) return;
    updateItem(idx, { episode_links: normalizeEpisodeLinks(nextLinks) });
  };

  const handlePreviewEpisode = (datasetId: string, episodeIndex: number) => {
    if (!datasetId) return;
    const nextEpisode = Math.max(0, Math.floor(Number(episodeIndex) || 0));
    if (!Number.isFinite(nextEpisode)) return;
    modalDatasetId = datasetId;
    modalEpisodeIndex = nextEpisode;
  };

  const handlePreviewEpisodeAutoplay = (datasetId: string, episodeIndex: number) => {
    handlePreviewEpisode(datasetId, episodeIndex);
    viewerDatasetAutoplayNonce += 1;
  };

  const activeEpisodeIndexInLinks = $derived.by(() => {
    if (!viewerDatasetId) return -1;
    const key = `${viewerDatasetId}:${viewerEpisodeIndex}`;
    return activeEpisodeLinks.findIndex((link) => `${link.dataset_id}:${link.episode_index}` === key);
  });

  const prevLinkedEpisode = $derived.by(() => {
    if (!activeEpisodeLinks.length) return null;
    if (activeEpisodeIndexInLinks > 0) return activeEpisodeLinks[activeEpisodeIndexInLinks - 1] ?? null;
    return null;
  });

  const nextLinkedEpisode = $derived.by(() => {
    if (!activeEpisodeLinks.length) return null;
    if (activeEpisodeIndexInLinks >= 0) return activeEpisodeLinks[activeEpisodeIndexInLinks + 1] ?? null;
    return activeEpisodeLinks[0] ?? null;
  });

  const onPrevEpisode = $derived.by(() =>
    prevLinkedEpisode ? () => handlePreviewEpisodeAutoplay(prevLinkedEpisode.dataset_id, prevLinkedEpisode.episode_index) : undefined
  );

  const onNextEpisode = $derived.by(() =>
    nextLinkedEpisode ? () => handlePreviewEpisodeAutoplay(nextLinkedEpisode.dataset_id, nextLinkedEpisode.episode_index) : undefined
  );

  const handleAddEpisodeLink = (datasetId: string, episodeIndex: number) => {
    if (!datasetId) return;
    const nextEpisode = Math.max(0, Math.floor(Number(episodeIndex) || 0));
    if (!Number.isFinite(nextEpisode)) return;
    if (activeEpisodeLinks.some((link) => link.dataset_id === datasetId && link.episode_index === nextEpisode)) {
      return;
    }
    updateActiveEpisodeLinks([
      ...activeEpisodeLinks,
      {
        dataset_id: datasetId,
        episode_index: nextEpisode,
        sort_order: activeEpisodeLinks.length
      }
    ]);
    scheduleEpisodeLinksAutoSave();
  };

  const handleRemoveEpisodeLink = (datasetId: string, episodeIndex: number) => {
    if (!datasetId) return;
    const nextEpisode = Math.max(0, Math.floor(Number(episodeIndex) || 0));
    if (!Number.isFinite(nextEpisode)) return;
    updateActiveEpisodeLinks(
      activeEpisodeLinks.filter((link) => !(link.dataset_id === datasetId && link.episode_index === nextEpisode))
    );
    scheduleEpisodeLinksAutoSave();
  };

  const openLinkEditor = (trialIndex: number) => {
    openViewerModal(trialIndex, { editMode: true, inspectorTab: 'search' });
  };

  const openLinkViewer = (trialIndex: number) => {
    openViewerModal(trialIndex, { editMode: false, inspectorTab: 'blueprint' });
  };

  const closeLinkModal = () => {
    linkModalOpen = false;
    viewerLayoutEditMode = false;
    viewerInitialInspectorTab = 'blueprint';
    viewerDatasetAutoplayNonce = 0;
    modalDatasetId = '';
    modalEpisodeIndex = 0;
  };

  const thumbDatasetIds = $derived.by(() => {
    const ids = new Set<string>();
    for (const item of evaluationItems) {
      const links = normalizeEpisodeLinks(item.episode_links ?? []);
      const idx = getEpisodeCarouselIndex(item.trial_index, links.length);
      const primary = links[idx];
      const secondary = links[idx + 1];
      if (primary?.dataset_id) ids.add(primary.dataset_id);
      if (secondary?.dataset_id) ids.add(secondary.dataset_id);
    }
    return Array.from(ids);
  });

  $effect(() => {
    // Cache dataset viewer meta for thumbnails (first camera key).
    for (const datasetId of thumbDatasetIds) {
      if (!datasetId) continue;
      if (viewerMetaByDatasetId[datasetId]) continue;
      if (viewerMetaLoadingByDatasetId[datasetId]) continue;
      viewerMetaLoadingByDatasetId = { ...viewerMetaLoadingByDatasetId, [datasetId]: true };
      void api.storage
        .datasetViewer(datasetId)
        .then((payload) => {
          const cameraKey = String(payload.cameras?.[0]?.key ?? '');
          if (!cameraKey) return;
          viewerMetaByDatasetId = { ...viewerMetaByDatasetId, [datasetId]: { cameraKey } };
        })
        .catch(() => {
          // ignore; thumbnails are best-effort
        })
        .finally(() => {
          const next = { ...viewerMetaLoadingByDatasetId };
          delete next[datasetId];
          viewerMetaLoadingByDatasetId = next;
        });
    }
  });

  const getThumbUrl = (datasetId: string, episodeIndex: number) => {
    const meta = viewerMetaByDatasetId[datasetId];
    if (!meta?.cameraKey) return '';
    return api.storage.datasetViewerVideoUrl(datasetId, meta.cameraKey, episodeIndex);
  };
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

<ViewerDialogShell bind:open={linkModalOpen} zIndexBase={60} inset="0.75rem">
  {#snippet children()}
      <div class="grid h-full grid-rows-[auto_minmax(0,1fr)] gap-4">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
          <div class="flex flex-wrap items-start justify-between gap-3">
	            <div>
	              <p class="text-sm font-semibold text-slate-900">セッションビューア</p>
	              <p class="text-xs text-slate-500">
	                試行 {activeTrialIndex}
	                {#if viewerDatasetId}
	                  / {viewerDatasetId} / episode {viewerEpisodeIndex}
	                {/if}
	              </p>
	              {#if viewerDatasetId && $viewerDatasetQuery.isLoading}
	                <p class="mt-1 text-[11px] text-slate-500">データセット情報を取得中...</p>
	              {:else if viewerDatasetId && !$viewerIsLocal}
	                <p class="mt-1 text-[11px] text-slate-500">ローカル未配置: 同期を開始しました。</p>
	              {/if}
            </div>
            <div class="flex flex-wrap gap-2">
              <Button.Root
                class="btn-ghost"
                type="button"
                onclick={() => {
                  viewerLayoutEditMode = !viewerLayoutEditMode;
                }}
              >
                {viewerLayoutEditMode ? '閲覧モード' : '編集モード'}
              </Button.Root>
              <Button.Root class="btn-ghost" type="button" onclick={closeLinkModal}>閉じる</Button.Root>
            </div>
          </div>
        </div>

        {#if viewerDatasetId}
          <div class="min-h-0">
            {#snippet searchInspectorPanel()}
              <DatasetEpisodeSearchTab
                datasets={allDatasets}
                recommendedDatasetId={recommendedDatasetId}
                previewDatasetId={viewerDatasetId}
                previewEpisodeIndex={viewerEpisodeIndex}
                episodeLinks={activeEpisodeLinks}
                onPreview={handlePreviewEpisode}
                onAdd={handleAddEpisodeLink}
                onRemove={handleRemoveEpisodeLink}
              />
            {/snippet}
		            <SessionLayoutEditor
		              blueprintSessionId={viewerDatasetId}
		              blueprintSessionKind="recording"
		              layoutSessionId={viewerDatasetId}
		              layoutSessionKind="recording"
		              layoutMode="recording"
		              viewSource="dataset"
		              editMode={viewerLayoutEditMode}
	                initialInspectorTab={viewerInitialInspectorTab}
                inspectorExtraTabs={viewerLayoutEditMode ? [{ id: 'search', label: 'Search', panel: searchInspectorPanel }] : []}
		              embedded={true}
		              datasetId={viewerDatasetId}
			              datasetEpisodeIndex={viewerEpisodeIndex}
			              datasetCameraKeys={($viewerDatasetQuery.data?.cameras ?? []).map((camera) => camera.key)}
			              datasetSignalKeys={$viewerDatasetSignalKeys}
			              datasetVideoWindows={viewerVideoWindows}
			              datasetAutoplayNonce={viewerDatasetAutoplayNonce}
	                {onPrevEpisode}
	                {onNextEpisode}
		            />
          </div>
        {:else}
          <div class="card p-4 min-h-0 h-full">
            <div class="flex h-full flex-col items-center justify-center gap-3 rounded-xl border border-slate-200/70 bg-white/80 px-6 text-center">
              {#if $datasetsQuery.isLoading}
                <p class="text-sm text-slate-500">データセット一覧を読み込み中...</p>
                <p class="text-xs text-slate-500">少し待つと自動で表示が切り替わります。</p>
              {:else if recommendedDatasetId || allDatasets.length}
                <p class="text-sm text-slate-500">表示準備中...</p>
                <p class="text-xs text-slate-500">データセット選択を反映しています。</p>
              {:else}
                <p class="text-sm text-slate-500">表示するデータセットがありません。</p>
                <p class="text-xs text-slate-500">データセットを作成/同期してから開いてください。</p>
              {/if}
            </div>
          </div>
        {/if}
      </div>
  {/snippet}
</ViewerDialogShell>

<section class="space-y-6">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">集計</h2>
    <div class="mt-4 grid gap-4 text-sm text-slate-600 sm:grid-cols-3">
      <div class="rounded-xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">入力済み</p>
        <p class="text-base font-semibold text-slate-800">{filledCount} / {evaluationCount}</p>
        <p class="text-xs text-slate-500">未入力: {remainingCount}</p>
      </div>
      <div class="rounded-xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">保存済み評価件数</p>
        <p class="text-base font-semibold text-slate-800">{$summaryQuery.data?.total ?? 0}</p>
      </div>
      <div class="rounded-xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">カテゴリ比率</p>
        <p class="text-sm font-semibold text-slate-800">{formatRates($summaryQuery.data?.rates)}</p>
      </div>
    </div>
  </div>

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
	          {@const links = normalizeEpisodeLinks(item.episode_links ?? [])}
	          {@const totalLinks = links.length}
	          {@const carouselIndex = getEpisodeCarouselIndex(item.trial_index, totalLinks)}
	          {@const primary = links[carouselIndex]}
	          {@const secondary = links[carouselIndex + 1]}
	          {@const primaryDatasetId = String(primary?.dataset_id ?? '')}
	          {@const primaryEpisodeIndex = Math.max(0, Math.floor(Number(primary?.episode_index) || 0))}
	          {@const secondaryDatasetId = String(secondary?.dataset_id ?? '')}
	          {@const secondaryEpisodeIndex = Math.max(0, Math.floor(Number(secondary?.episode_index) || 0))}
	          {@const canPrev = carouselIndex > 0}
	          {@const canNext = carouselIndex + 1 < totalLinks}
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
                <div class="flex flex-wrap gap-2">
                  <Button.Root class="btn-ghost" type="button" onclick={() => openLinkEditor(item.trial_index)}>
                    新規紐付け
                  </Button.Root>
	              {#if item.episode_links.length > 0}
	                    <Button.Root class="btn-ghost" type="button" onclick={() => openLinkViewer(item.trial_index)}>
	                      閲覧
	                    </Button.Root>
	                  {/if}
	                </div>
	              </div>

	              {#if totalLinks > 0}
	                <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div class="overflow-hidden rounded-xl border border-slate-200/60 bg-white">
                    <div class="aspect-video bg-slate-950/5">
                      <DatasetEpisodeThumbnail
                        src={primaryDatasetId ? getThumbUrl(primaryDatasetId, primaryEpisodeIndex) : ''}
                        label={
                          viewerMetaLoadingByDatasetId[primaryDatasetId]
                            ? 'loading...'
                            : primaryDatasetId
                              ? `ep ${primaryEpisodeIndex + 1}`
                              : ''
                        }
                      />
                    </div>
	                    <div class="min-w-0 p-2">
	                      <p class="truncate text-xs font-semibold text-slate-900">{primaryDatasetId}</p>
	                      <p class="truncate text-[10px] text-slate-500">
	                        ep {primaryEpisodeIndex + 1} / {totalLinks}
	                      </p>
	                    </div>
	                  </div>

                  {#if secondary}
                    <div class="hidden overflow-hidden rounded-xl border border-slate-200/60 bg-white sm:block">
                      <div class="aspect-video bg-slate-950/5">
                        <DatasetEpisodeThumbnail
                          src={secondaryDatasetId ? getThumbUrl(secondaryDatasetId, secondaryEpisodeIndex) : ''}
                          label={
                            viewerMetaLoadingByDatasetId[secondaryDatasetId]
                              ? 'loading...'
                              : secondaryDatasetId
                                ? `ep ${secondaryEpisodeIndex + 1}`
                                : ''
                          }
                        />
                      </div>
                      <div class="min-w-0 p-2">
                        <p class="truncate text-xs font-semibold text-slate-900">{secondaryDatasetId}</p>
                        <p class="truncate text-[10px] text-slate-500">
                          ep {secondaryEpisodeIndex + 1} / {totalLinks}
                        </p>
                      </div>
                    </div>
                  {/if}

                  <div class="flex items-center gap-2 rounded-xl border border-slate-200/70 bg-white/80 p-2 sm:col-start-1 sm:row-start-2">
                    <button
                      class="btn-ghost px-3 py-2"
                      type="button"
                      disabled={!canPrev}
                      onclick={() => setEpisodeCarouselIndex(item.trial_index, carouselIndex - 1, totalLinks)}
	                    >
	                      ←
	                    </button>
                    <button
                      class="btn-primary px-4 py-2"
                      type="button"
                      disabled={!primaryDatasetId}
	                      onclick={() => {
	                        if (!primaryDatasetId) return;
	                        openViewerModalAt(item.trial_index, primaryDatasetId, primaryEpisodeIndex, {
	                          editMode: false,
                          inspectorTab: 'blueprint',
                          autoplay: true
                        });
                      }}
                    >
                      再生
                    </button>
                    <button
                      class="btn-ghost px-3 py-2"
	                      type="button"
	                      disabled={!canNext}
	                      onclick={() => setEpisodeCarouselIndex(item.trial_index, carouselIndex + 1, totalLinks)}
	                    >
	                      →
	                    </button>
                    <div class="flex-1"></div>
                    <span class="text-[10px] font-semibold text-slate-500 tabular-nums">{carouselIndex + 1} / {totalLinks}</span>
                  </div>
                </div>
              {/if}
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
</section>
