<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { Button, Dialog } from 'bits-ui';
  import toast from 'svelte-french-toast';

  import { api } from '$lib/api/client';
  import { GPU_MODELS, getGpuModelLabel } from '$lib/policies';
  import type {
    TrainingInstanceCandidate,
    TrainingInstanceCandidatesResponse
  } from '$lib/types/training';

  type Provider = 'verda' | 'vast';
  type GpuCountFilter = 'any' | 1 | 2 | 4 | 8;
  type VerdaModeFilter = 'any' | 'spot' | 'ondemand';
  type VastModeFilter = 'any' | 'spot' | 'ondemand';
  type SelectionPayload = {
    cloudProvider: Provider;
    gpuModel: string;
    gpuCount: number;
    storageSize: number;
    selectedMode: 'spot' | 'ondemand';
    selectedInstanceType: string | null;
    selectedOfferId: number | null;
    selectedLocation: string;
    vastMaxPrice: number | null;
    candidateTitle: string;
    candidateDetail: string;
    candidateRoute: string;
    candidatePricePerHour: number | null;
  };
  type Candidate = TrainingInstanceCandidate & {
    priceLabel: string;
    gpuLabel: string;
    statusText: string;
  };
  type Props = {
    cloudProvider: Provider;
    gpuModel: string;
    gpuCount: number;
    storageSize: number;
    selectedMode: 'spot' | 'ondemand';
    selectedInstanceType: string | null;
    selectedOfferId: number | null;
    selectedLocation: string;
    selectedCandidateTitle: string;
    selectedCandidateDetail: string;
    selectedCandidateRoute: string;
    selectedCandidatePricePerHour: number | null;
    vastMaxPrice: number | null;
    isVerdaProviderEnabled?: boolean;
    isVastProviderEnabled?: boolean;
    onApplySelection: (selection: SelectionPayload) => void;
  };

  let {
    cloudProvider,
    gpuModel,
    gpuCount,
    storageSize,
    selectedMode,
    selectedInstanceType,
    selectedOfferId,
    selectedLocation,
    selectedCandidateTitle,
    selectedCandidateDetail,
    selectedCandidateRoute,
    selectedCandidatePricePerHour,
    vastMaxPrice,
    isVerdaProviderEnabled = true,
    isVastProviderEnabled = false,
    onApplySelection
  }: Props = $props();

  const gpuModelOptions = ['any', ...GPU_MODELS.map((gpu) => gpu.value)];
  const storagePresetOptions = ['200', '300', '400', '500'];
  const vastPricePresetOptions = ['', '2.5', '3.5', '5.0'];

  let draftProvider = $state<Provider>('verda');
  let draftGpuModel = $state<'any' | string>('any');
  let draftGpuCount = $state<GpuCountFilter>('any');
  let draftStorageSize = $state('200');
  let draftVerdaMode = $state<VerdaModeFilter>('any');
  let draftVastMode = $state<VastModeFilter>('any');
  let draftVastMaxPrice = $state('');
  let modalOpen = $state(false);
  let pendingCandidateId = $state<string | null>(null);

  const chipClass = (active: boolean) =>
    active
      ? 'border-sky-300 bg-sky-50 text-sky-700 shadow-[0_0_0_2px_rgba(14,165,233,0.08)]'
      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50';
  const disabledChipClass =
    'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400 opacity-60 shadow-none hover:border-slate-200 hover:bg-slate-100';
  const chipButtonClass = 'whitespace-nowrap rounded-full border px-2.5 py-1.5 text-[12px] font-semibold transition';
  const roomyChipButtonClass = 'whitespace-nowrap rounded-full border px-3.5 py-1.5 text-[12px] font-semibold transition';
  const compactChipButtonClass = 'whitespace-nowrap rounded-full border px-4 py-1.5 text-[12px] font-semibold transition';
  const storageInputClass = (active: boolean, invalid: boolean) =>
    invalid
      ? 'border-rose-200 bg-rose-50/70 text-slate-900 placeholder:text-rose-300 focus:border-rose-300'
      : active
        ? 'border-sky-300 bg-sky-50/40 text-slate-900'
        : 'border-slate-200 bg-slate-50/70 text-slate-900';

  const providerEnabled = (provider: Provider) =>
    provider === 'verda' ? isVerdaProviderEnabled : isVastProviderEnabled;
  const providerChipClass = (provider: Provider, active: boolean) =>
    providerEnabled(provider) ? chipClass(active) : disabledChipClass;

  const selectedCandidateKey = $derived.by(() => {
    if (cloudProvider === 'verda') {
      const instanceKey = String(selectedInstanceType || '').trim();
      const locationKey = String(selectedLocation || '').trim();
      if (!instanceKey || !locationKey) return null;
      return `verda:${instanceKey}:${selectedMode}:${locationKey}`;
    }
    if (selectedOfferId == null) return null;
    return `vast:${selectedOfferId}`;
  });

  const formatPrice = (value?: number | null) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '価格未取得';
    return `$${value.toFixed(3)}/h`;
  };

  const formatResourceNumber = (value?: number | null) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return null;
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  };

  const candidateDisplayTitle = (candidate: {
    provider: Provider;
    title: string;
    gpuLabel?: string;
    gpu_model?: string;
    gpu_count?: number;
  }) => {
    if (candidate.gpu_model && candidate.gpu_count) {
      return `${getGpuModelLabel(candidate.gpu_model)} x${candidate.gpu_count}`;
    }
    if (candidate.gpuLabel) return candidate.gpuLabel;
    return candidate.title;
  };

  const candidateResourceLines = (candidate: {
    detail?: string;
    route?: string | null;
    gpu_memory_gb?: number | null;
    gpu_count?: number;
    cpu_cores?: number | null;
    system_memory_gb?: number | null;
  }) => {
    const detailParts = String(candidate.detail || '')
      .split(' / ')
      .map((part) => part.trim())
      .filter(Boolean);

    let line1 = '';
    const gpuMemory = formatResourceNumber(candidate.gpu_memory_gb);
    const gpuCountValue = candidate.gpu_count ?? 0;
    if (gpuMemory) {
      line1 = `${gpuMemory}GB VRAM`;
      if (gpuCountValue > 1 && typeof candidate.gpu_memory_gb === 'number') {
        const total = formatResourceNumber(candidate.gpu_memory_gb * gpuCountValue);
        if (total) line1 += ` / 合計 ${total}GB`;
      }
    } else if (detailParts.length > 0) {
      line1 = detailParts[0];
    }

    const cpuText = formatResourceNumber(candidate.cpu_cores);
    const memoryText = formatResourceNumber(candidate.system_memory_gb);
    const systemParts = [
      cpuText ? `${cpuText} vCPU` : '',
      memoryText ? `${memoryText}GB RAM` : ''
    ].filter(Boolean);
    let line2 = systemParts.join(' / ');
    if (!line2 && detailParts.length > 1) {
      line2 = detailParts.slice(1).join(' / ');
    }
    if (!line1) {
      line1 = String(candidate.route || '').trim() || '構成未取得';
    }
    return { line1, line2 };
  };

  const candidateIdentifierLabel = (candidate: {
    provider: Provider;
    instance_type?: string | null;
    offer_id?: number | null;
  }) => {
    if (candidate.provider === 'verda') {
      return String(candidate.instance_type || '').trim() || 'instance_type 未取得';
    }
    if (candidate.offer_id != null) {
      return `offer_id ${candidate.offer_id}`;
    }
    return 'offer_id 未取得';
  };

  const lowerSpecPillClass =
    'inline-flex max-w-full items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold leading-none text-slate-700';

  const selectedModeForDraft = () => {
    if (draftProvider === 'verda') {
      return draftVerdaMode === 'any' ? null : draftVerdaMode;
    }
    if (draftVastMode === 'spot') return 'spot';
    if (draftVastMode === 'ondemand') return 'ondemand';
    return null;
  };

  const storageSettingValue = $derived(String(draftStorageSize ?? '').trim());
  const parsedStorageSize = $derived.by(() => {
    const parsed = Number(storageSettingValue);
    if (!Number.isFinite(parsed)) return null;
    return Math.floor(parsed);
  });
  const hasValidStorageSetting = $derived(Boolean(storageSettingValue.match(/^\d+$/)) && Number(storageSettingValue) >= 100);
  const currentRequestedMode = $derived(selectedModeForDraft());

  const verdaCandidatesQuery = createQuery<TrainingInstanceCandidatesResponse>(
    toStore(() => ({
      queryKey: [
        'training',
        'instance-candidates',
        'verda',
        draftGpuModel,
        draftGpuCount,
        currentRequestedMode
      ],
      queryFn: () =>
        api.training.instanceCandidates({
          provider: 'verda',
          gpu_model: draftGpuModel !== 'any' ? draftGpuModel : undefined,
          gpu_count: draftGpuCount !== 'any' ? draftGpuCount : undefined,
          mode: currentRequestedMode ?? undefined
        }),
      enabled: modalOpen && draftProvider === 'verda' && isVerdaProviderEnabled
    }))
  );

  const parsedMaxPrice = $derived.by(() => {
    const parsed = Number(draftVastMaxPrice);
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return parsed;
  });

  const vastCandidatesQuery = createQuery<TrainingInstanceCandidatesResponse>(
    toStore(() => ({
      queryKey: [
        'training',
        'instance-candidates',
        'vast',
        draftGpuModel,
        draftGpuCount,
        currentRequestedMode,
        parsedMaxPrice
      ],
      queryFn: () =>
        api.training.instanceCandidates({
          provider: 'vast',
          gpu_model: draftGpuModel !== 'any' ? draftGpuModel : undefined,
          gpu_count: draftGpuCount !== 'any' ? draftGpuCount : undefined,
          mode: currentRequestedMode ?? undefined,
          max_price: parsedMaxPrice
        }),
      enabled: modalOpen && draftProvider === 'vast' && isVastProviderEnabled
    }))
  );

  const currentLoading = $derived(
    draftProvider === 'verda'
      ? ($verdaCandidatesQuery.isPending || $verdaCandidatesQuery.isFetching)
      : ($vastCandidatesQuery.isPending || $vastCandidatesQuery.isFetching)
  );

  const normalizeCandidate = (candidate: TrainingInstanceCandidate): Candidate => ({
    ...candidate,
    detail: candidate.detail || candidate.route || candidate.location || '',
    route: candidate.route || candidate.location || 'auto',
    priceLabel: formatPrice(candidate.price_per_hour),
    gpuLabel: `${getGpuModelLabel(candidate.gpu_model)} x${candidate.gpu_count}`,
    statusText: '利用可能'
  });

  const draftCandidates = $derived.by(() => {
    const source = draftProvider === 'verda' ? $verdaCandidatesQuery.data?.candidates : $vastCandidatesQuery.data?.candidates;
    return (source ?? []).map(normalizeCandidate);
  });

  const resolvedSelectedCandidate = $derived.by(() => {
    const title = String(selectedCandidateTitle || '').trim();
    if (!title) return null;
    return {
      provider: cloudProvider,
      title,
      instance_type: cloudProvider === 'verda' ? selectedInstanceType : null,
      offer_id: cloudProvider === 'vast' ? selectedOfferId : null,
      detail: String(selectedCandidateDetail || '').trim(),
      route: String(selectedCandidateRoute || selectedLocation || 'auto').trim() || 'auto',
      priceLabel: formatPrice(selectedCandidatePricePerHour),
      gpuLabel: `${getGpuModelLabel(gpuModel)} x${gpuCount}`,
      gpu_count: gpuCount,
      statusText: '利用可能',
      price_per_hour: selectedCandidatePricePerHour
    };
  });

  const pendingCandidate = $derived(
    draftCandidates.find((candidate) => candidate.candidate_id === pendingCandidateId) ?? null
  );

  const statusTone = () => 'border-emerald-200/80 bg-emerald-50 text-emerald-700';

  const openModal = () => {
    draftProvider = cloudProvider;
    const hasSelectedTarget =
      (cloudProvider === 'verda' && Boolean(String(selectedInstanceType || '').trim())) ||
      (cloudProvider === 'vast' && selectedOfferId != null);
    draftGpuModel = hasSelectedTarget && gpuModel ? gpuModel : 'any';
    draftGpuCount = hasSelectedTarget ? ((gpuCount || 'any') as GpuCountFilter) : 'any';
    draftStorageSize = String(storageSize || 200);
    draftVerdaMode = cloudProvider === 'verda' && hasSelectedTarget ? selectedMode : 'any';
    draftVastMode = cloudProvider === 'vast'
      ? (hasSelectedTarget ? selectedMode : 'any')
      : 'any';
    draftVastMaxPrice = vastMaxPrice == null ? '' : String(vastMaxPrice);
    pendingCandidateId = hasSelectedTarget ? selectedCandidateKey : null;
    modalOpen = true;
  };

  const closeModal = () => {
    modalOpen = false;
  };

  $effect(() => {
    if (!modalOpen) return;
    if (draftCandidates.length === 0) {
      pendingCandidateId = null;
      return;
    }
    if (!pendingCandidateId || !draftCandidates.some((candidate) => candidate.candidate_id === pendingCandidateId)) {
      pendingCandidateId = draftCandidates[0].candidate_id;
    }
  });

  $effect(() => {
    if (!modalOpen) return;

    const html = document.documentElement;
    const body = document.body;
    const scrollY = window.scrollY;

    const prevHtmlOverflow = html.style.overflow;
    const prevHtmlOverscroll = html.style.overscrollBehavior;
    const prevBodyOverflow = body.style.overflow;
    const prevBodyPosition = body.style.position;
    const prevBodyTop = body.style.top;
    const prevBodyWidth = body.style.width;

    html.style.overflow = 'hidden';
    html.style.overscrollBehavior = 'none';
    body.style.overflow = 'hidden';
    body.style.position = 'fixed';
    body.style.top = `-${scrollY}px`;
    body.style.width = '100%';

    return () => {
      html.style.overflow = prevHtmlOverflow;
      html.style.overscrollBehavior = prevHtmlOverscroll;
      body.style.overflow = prevBodyOverflow;
      body.style.position = prevBodyPosition;
      body.style.top = prevBodyTop;
      body.style.width = prevBodyWidth;
      window.scrollTo({ top: scrollY, left: 0, behavior: 'auto' });
    };
  });

  const chooseCandidate = (candidateId: string) => {
    pendingCandidateId = candidateId;
  };

  const applySelection = () => {
    if (!pendingCandidate || !hasValidStorageSetting) return;

    const nextProvider = draftProvider;
    const nextMode = pendingCandidate.mode;
    onApplySelection({
      cloudProvider: nextProvider,
      gpuModel: pendingCandidate.gpu_model,
      gpuCount: pendingCandidate.gpu_count,
      storageSize: Number(storageSettingValue),
      selectedMode: nextMode,
      selectedInstanceType: nextProvider === 'verda' ? (pendingCandidate.instance_type ?? null) : null,
      selectedOfferId: nextProvider === 'vast' ? (pendingCandidate.offer_id ?? null) : null,
      selectedLocation: nextProvider === 'verda' ? String(pendingCandidate.location || 'auto') : 'auto',
      vastMaxPrice: nextProvider === 'vast' ? parsedMaxPrice : null,
      candidateTitle: pendingCandidate.title,
      candidateDetail: pendingCandidate.detail || '',
      candidateRoute: pendingCandidate.route || pendingCandidate.location || 'auto',
      candidatePricePerHour: pendingCandidate.price_per_hour ?? null
    });
    toast.success('学習先を反映しました。');
    modalOpen = false;
  };
</script>

<section class="card overflow-hidden p-6">
  <div>
    <h2 class="text-xl font-semibold text-slate-900">クラウド設定</h2>
    <p class="mt-1 text-sm leading-6 text-slate-500">選択中の構成だけを表示し、条件調整はモーダル内に集約します。</p>
  </div>

  <div class="mt-5 rounded-[22px] border border-slate-200/80 bg-slate-50/70 p-4 shadow-sm">
    <p class="label">インスタンス</p>
    {#if resolvedSelectedCandidate}
      {@const selectedResourceLines = candidateResourceLines(resolvedSelectedCandidate)}
      <div class="mt-3">
        <div class="flex h-[106px] w-full flex-col rounded-xl border border-slate-200/80 bg-white px-4 py-3 text-left shadow-sm">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate text-[15px] font-semibold leading-5 text-slate-900">
                {candidateDisplayTitle(resolvedSelectedCandidate)}
              </p>
              <p class="truncate text-[11px] leading-4 text-slate-500">{selectedResourceLines.line1}</p>
              {#if selectedResourceLines.line2}
                <p class="truncate text-[11px] leading-4 text-slate-500">{selectedResourceLines.line2}</p>
              {/if}
            </div>
            <span class={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold leading-none shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] ${statusTone()}`}>
              {resolvedSelectedCandidate.statusText}
            </span>
          </div>

          <div class="mt-auto flex items-end justify-between gap-3">
            <div class="min-w-0">
              <span class={lowerSpecPillClass}>
                <span class="truncate">{candidateIdentifierLabel(resolvedSelectedCandidate)}</span>
              </span>
            </div>
            <div class="shrink-0 text-right">
              <p class="text-[14px] font-semibold text-slate-900">
                {resolvedSelectedCandidate.priceLabel}
              </p>
            </div>
          </div>
        </div>

        <div class="mt-2 flex items-center justify-between gap-3 text-xs text-slate-500">
          <p class="min-w-0 truncate">
            <span>選択済み</span>
            <span class="ml-1 font-semibold text-emerald-600">{selectedMode === 'spot' ? 'スポット' : 'オンデマンド'}</span>
          </p>
          <p class="shrink-0 text-right">
            <span>設定 {storageSize}GB ストレージ</span>
          </p>
        </div>
      </div>
    {:else}
      <div class="mt-3 flex h-[106px] w-full items-center rounded-xl border border-dashed border-slate-200 bg-white px-4 text-sm text-slate-500">
        インスタンス未選択
      </div>
    {/if}

    <Button.Root
      class="mt-4 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-100"
      type="button"
      onclick={openModal}
    >
      インスタンスを選ぶ
    </Button.Root>
  </div>
</section>

<Dialog.Root bind:open={modalOpen}>
  <Dialog.Portal>
    <Dialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <Dialog.Content
      class="fixed inset-x-3 bottom-3 top-3 z-[41] outline-none modal:bottom-auto modal:left-1/2 modal:right-auto modal:top-[6.5rem] modal:-translate-x-1/2"
    >
      <div class="flex h-full w-full flex-col overflow-hidden rounded-[26px] border border-slate-200/90 bg-white shadow-[0_32px_72px_-40px_rgba(15,23,42,0.28)] modal:h-[788px] modal:w-[960px] modal:max-w-[calc(100vw-96px)]">
        <div class="flex items-center justify-between gap-6 border-b border-slate-200/80 px-4 pb-3 pt-4 modal:px-8 modal:pb-3 modal:pt-6">
          <div>
            <p class="label">インスタンス</p>
            <h2 class="mt-2 text-[22px] font-semibold tracking-tight text-slate-950 modal:text-[24px]">候補を選択</h2>
          </div>
          <Button.Root
            class="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
            type="button"
            onclick={closeModal}
          >
            閉じる
          </Button.Root>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto px-4 pt-4 modal:overflow-visible modal:px-8 modal:pb-6">
          <div class="modal-grid grid min-h-full grid-cols-1 gap-6 modal:h-full modal:grid-cols-[1fr_336px]">
            <div class="flex min-h-0 flex-col modal:grid modal:h-full modal:grid-rows-[auto_minmax(0,1fr)_auto]">
              <div class="flex items-center justify-between gap-4">
                <p class="text-sm font-semibold text-slate-900">候補プレビュー</p>
                <p class="text-xs text-slate-500">{draftCandidates.length}件</p>
              </div>

              <div class="preview-scroll modal:min-h-0 modal:overflow-y-auto modal:pr-1">
                {#if currentLoading}
                  <div class="mt-3 flex h-[106px] w-full items-center rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-4 text-sm text-slate-500 modal:w-[250px]">
                    候補を読み込み中...
                  </div>
                {:else if draftCandidates.length > 0}
                  <div class="preview-query mt-3 pb-1">
                  <div class="preview-grid">
                    {#each draftCandidates as candidate}
                      {@const resourceLines = candidateResourceLines(candidate)}
                      <button
                        type="button"
                        class={`instance-option-card flex h-[106px] w-[250px] flex-col rounded-xl border px-4 py-3 text-left transition ${
                          pendingCandidateId === candidate.candidate_id
                            ? 'border-sky-300 bg-sky-50/30 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_0_0_3px_rgba(14,165,233,0.08)]'
                            : 'border-slate-200/80 bg-white shadow-sm hover:border-slate-300 hover:bg-slate-50/80'
                        }`}
                        onclick={() => chooseCandidate(candidate.candidate_id)}
                        aria-pressed={pendingCandidateId === candidate.candidate_id}
                      >
                        <div class="flex items-start justify-between gap-2">
                          <div class="min-w-0">
                            <p class="truncate text-[15px] font-semibold leading-5 text-slate-900">{candidateDisplayTitle(candidate)}</p>
                            <p class="truncate text-[11px] leading-4 text-slate-500">{resourceLines.line1}</p>
                            {#if resourceLines.line2}
                              <p class="truncate text-[11px] leading-4 text-slate-500">{resourceLines.line2}</p>
                            {/if}
                          </div>
                          <span class={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold leading-none shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] ${statusTone()}`}>
                            {candidate.statusText}
                          </span>
                        </div>

                        <div class="mt-auto flex items-end justify-between gap-3">
                          <div class="min-w-0">
                            <span class={lowerSpecPillClass}>
                              <span class="truncate">{candidateIdentifierLabel(candidate)}</span>
                            </span>
                          </div>
                          <div class="shrink-0 text-right">
                            <p class="text-[14px] font-semibold text-slate-900">{candidate.priceLabel}</p>
                          </div>
                        </div>
                      </button>
                    {/each}
                  </div>
                  </div>
                {:else}
                  <div class="mt-3 flex h-[106px] w-full items-center rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-4 text-sm text-slate-500 modal:w-[250px]">
                    条件に合う候補がありません。
                  </div>
                {/if}
              </div>

              <div class="mt-auto hidden border-t border-slate-200/80 pt-4 modal:block">
                <div class="flex justify-end">
                  <Button.Root
                    class="btn-primary min-w-[184px] px-5 py-3"
                    type="button"
                    onclick={applySelection}
                    disabled={!pendingCandidate || !hasValidStorageSetting}
                  >
                    この候補を使う
                  </Button.Root>
                </div>
              </div>
            </div>

            <div class="flex min-h-0 flex-col border-t border-slate-200/80 pt-5 modal:border-l modal:border-t-0 modal:pl-5 modal:pt-0">
              <div class="flex items-center justify-between gap-3">
                <p class="text-sm font-semibold text-slate-900">条件</p>
              </div>

              <div class="condition-query mt-2 min-h-0 flex-1 modal:h-full">
                <div class="condition-layout modal:h-full modal:justify-between">
                  <div class="condition-layout__base min-w-0">
                    <p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">ベース条件</p>
                    <div class="mt-1.5 space-y-1.5">
                      <div>
                        <span class="label">Provider</span>
                        <div class="mt-1 flex flex-wrap gap-1">
                          <button
                            type="button"
                            class={`${roomyChipButtonClass} ${providerChipClass('verda', draftProvider === 'verda')}`}
                            onclick={() => providerEnabled('verda') && (draftProvider = 'verda')}
                            disabled={!isVerdaProviderEnabled}
                            aria-disabled={!isVerdaProviderEnabled}
                            title={!isVerdaProviderEnabled ? 'Verda は現在選択できません' : 'Verda'}
                          >
                            Verda
                          </button>
                          <button
                            type="button"
                            class={`${roomyChipButtonClass} ${providerChipClass('vast', draftProvider === 'vast')}`}
                            onclick={() => providerEnabled('vast') && (draftProvider = 'vast')}
                            disabled={!isVastProviderEnabled}
                            aria-disabled={!isVastProviderEnabled}
                            title={!isVastProviderEnabled ? 'Vast.ai は現在選択できません' : 'Vast.ai'}
                          >
                            Vast.ai
                          </button>
                        </div>
                      </div>

                      <div>
                        <span class="label">GPUモデル</span>
                        <div class="mt-1 flex flex-wrap gap-1">
                          {#each gpuModelOptions as option}
                            <button
                              type="button"
                              class={`${roomyChipButtonClass} ${chipClass(draftGpuModel === option)}`}
                              onclick={() => (draftGpuModel = option)}
                            >
                              {option === 'any' ? '任意' : getGpuModelLabel(option)}
                            </button>
                          {/each}
                        </div>
                      </div>

                      <div>
                        <span class="label">GPU数</span>
                        <div class="mt-1 grid grid-cols-5 gap-1">
                          {#each ['any', 1, 2, 4, 8] as option}
                            <button
                              type="button"
                              class={`${chipButtonClass} ${chipClass(draftGpuCount === option)}`}
                              onclick={() => (draftGpuCount = option as GpuCountFilter)}
                            >
                              {option === 'any' ? '任意' : `${option} GPU`}
                            </button>
                          {/each}
                        </div>
                      </div>

                      {#if draftProvider === 'verda'}
                        <div>
                          <span class="label">インスタンス種別</span>
                          <div class="mt-1 flex flex-wrap gap-1">
                            {#each ['any', 'spot', 'ondemand'] as option}
                              <button
                                type="button"
                                class={`max-w-[130px] overflow-hidden text-ellipsis ${compactChipButtonClass} ${chipClass(draftVerdaMode === option)}`}
                                onclick={() => (draftVerdaMode = option as VerdaModeFilter)}
                              >
                                {option === 'any' ? '任意' : option === 'spot' ? 'スポット' : 'オンデマンド'}
                              </button>
                            {/each}
                          </div>
                        </div>
                      {:else}
                        <div>
                          <span class="label">インスタンス種別</span>
                          <div class="mt-1 grid grid-cols-3 gap-1">
                            {#each ['any', 'spot', 'ondemand'] as option}
                              <button
                                type="button"
                                class={`max-w-[130px] overflow-hidden text-ellipsis ${compactChipButtonClass} ${chipClass(draftVastMode === option)}`}
                                onclick={() => (draftVastMode = option as VastModeFilter)}
                              >
                                {option === 'any' ? '任意' : option === 'spot' ? 'スポット' : 'オンデマンド'}
                              </button>
                            {/each}
                          </div>
                        </div>

                        <div>
                          <span class="label">Max price ($/h)</span>
                          <div class="mt-1 grid grid-cols-2 gap-1">
                            {#each vastPricePresetOptions as option}
                              <button
                                type="button"
                                class={`${chipButtonClass} ${chipClass(draftVastMaxPrice === option)}`}
                                onclick={() => (draftVastMaxPrice = option)}
                              >
                                {option === '' ? '上限なし' : `$${option}`}
                              </button>
                            {/each}
                          </div>
                        </div>
                      {/if}
                    </div>
                  </div>

                  <div class="condition-layout__settings min-w-0">
                    <p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">設定</p>
                    <div class="mt-1.5 mb-2.5 space-y-1.5">
                      <div>
                        <div class="flex items-center justify-between gap-2">
                          <span class="label">ストレージ (GB)</span>
                          <span class="text-[10px] font-semibold text-rose-500">必須</span>
                        </div>
                        <div class="storage-preset-grid mt-1 grid gap-1">
                          {#each storagePresetOptions as option}
                            <button
                              type="button"
                              class={`${chipButtonClass} ${chipClass(draftStorageSize === option)}`}
                              onclick={() => (draftStorageSize = option)}
                            >
                              {option}GB
                            </button>
                          {/each}
                        </div>
                        <input
                          class={`storage-input input mt-1.5 h-9 ${storageInputClass(storagePresetOptions.includes(draftStorageSize), !hasValidStorageSetting)}`}
                          type="number"
                          min="100"
                          step="10"
                          bind:value={draftStorageSize}
                          placeholder="100以上を入力"
                        />
                        {#if !hasValidStorageSetting}
                          <p class="mt-1 text-[11px] text-rose-500">100GB以上の値を設定してください。</p>
                        {/if}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="border-t border-slate-200/80 px-4 pb-4 pt-4 modal:hidden">
          <Button.Root
            class="btn-primary w-full px-5 py-3"
            type="button"
            onclick={applySelection}
            disabled={!pendingCandidate || !hasValidStorageSetting}
          >
            この候補を使う
          </Button.Root>
        </div>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .condition-query {
    container-type: inline-size;
  }

  .preview-query {
    container-type: inline-size;
    width: 100%;
  }

  .preview-grid {
    display: grid;
    width: 100%;
    grid-template-columns: repeat(1, minmax(0, 1fr));
    justify-content: stretch;
    column-gap: 0.75rem;
    row-gap: 0.75rem;
  }

  .preview-grid .instance-option-card {
    width: 100%;
  }

  .condition-layout {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .condition-layout__settings {
    min-width: 0;
    border-top: 1px solid rgba(226, 232, 240, 0.8);
    padding-top: 0.625rem;
  }

  .storage-preset-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .storage-input {
    width: 100%;
  }

  @container (min-width: 500px) {
    .preview-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .condition-layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 176px;
      gap: 0.5rem;
    }

    .condition-layout__settings {
      border-top: 0;
      border-left: 1px solid rgba(226, 232, 240, 0.8);
      padding-top: 0;
      padding-left: 0.5rem;
    }

    .storage-preset-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .storage-input {
      width: 167px;
    }
  }

  @container (min-width: 646px) {
    .condition-layout {
      grid-template-columns: minmax(315px, 1fr) 315px;
      gap: 0.75rem;
    }

    .condition-layout__settings {
      padding-left: 0.75rem;
    }

    .storage-preset-grid {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }

    .storage-input {
      width: 100%;
    }
  }

  @container (min-width: 820px) {
    .preview-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      column-gap: 1rem;
    }
  }

  @container (min-width: 980px) {
    .preview-grid {
      grid-template-columns: repeat(4, minmax(0, 1fr));
      column-gap: 1rem;
    }
  }

  @media (min-width: 1056px) {
    .preview-grid {
      grid-template-columns: repeat(2, 250px);
      justify-content: start;
      column-gap: 0.75rem;
    }

    .preview-grid .instance-option-card {
      width: 250px;
    }
  }
</style>
