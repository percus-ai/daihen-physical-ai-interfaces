<script lang="ts">
  import { Button, Dialog } from 'bits-ui';
  import toast from 'svelte-french-toast';
  import { GPU_MODELS, getGpuModelLabel } from '$lib/policies';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';

  type Provider = 'verda' | 'vast';
  type Availability = 'available' | 'checking' | 'blocked';
  type GpuCountFilter = 'any' | 1 | 2 | 4 | 8;
  type VerdaModeFilter = 'any' | 'spot' | 'ondemand';
  type VastInterruptibleFilter = 'any' | 'enabled' | 'disabled';
  type Candidate = {
    kind: Provider;
    id: string;
    title: string;
    price: string;
    gpuLabel: string;
    detail: string;
    route: string;
    mode: string;
    storage: string;
    boot: string;
    availability: Availability;
  };

  const baseVerdaCandidates: Candidate[] = [
    {
      kind: 'verda',
      id: '1H100.80S.22V',
      title: '1H100.80S.22V',
      price: '$2.43/h',
      gpuLabel: 'H100 x1',
      detail: '80GB HBM3',
      route: 'FIN-01',
      mode: 'スポット',
      storage: '200GB NVMe',
      boot: '約2分',
      availability: 'available'
    },
    {
      kind: 'verda',
      id: '2H100.80S.60V',
      title: '2H100.80S.60V',
      price: '$5.88/h',
      gpuLabel: 'H100 x2',
      detail: '160GB total',
      route: 'FIN-02',
      mode: 'オンデマンド',
      storage: '300GB NVMe',
      boot: '約4分',
      availability: 'checking'
    },
    {
      kind: 'verda',
      id: '1L40S.48.16V',
      title: '1L40S.48.16V',
      price: '$1.12/h',
      gpuLabel: 'L40S x1',
      detail: '48GB GDDR6',
      route: 'ICE-01',
      mode: 'スポット',
      storage: '150GB NVMe',
      boot: '約6分',
      availability: 'blocked'
    }
  ];

  const baseVastCandidates: Candidate[] = [
    {
      kind: 'vast',
      id: 'offer-31980517',
      title: 'Offer #31980517',
      price: '$2.91/h',
      gpuLabel: 'H200 x1',
      detail: '141GB HBM3e',
      route: 'US-West / ssh8.vast.ai',
      mode: 'Interruptible',
      storage: '140GB disk',
      boot: '約90秒',
      availability: 'available'
    },
    {
      kind: 'vast',
      id: 'offer-30018970',
      title: 'Offer #30018970',
      price: '$3.76/h',
      gpuLabel: 'H100 x1',
      detail: '80GB HBM3',
      route: 'EU-Central / 154.57.34.75',
      mode: 'オンデマンド',
      storage: '200GB disk',
      boot: '約3分',
      availability: 'checking'
    },
    {
      kind: 'vast',
      id: 'offer-29522443',
      title: 'Offer #29522443',
      price: '$0.88/h',
      gpuLabel: 'L40S x1',
      detail: '48GB GDDR6',
      route: 'Asia / ssh12.vast.ai',
      mode: 'Interruptible',
      storage: '100GB disk',
      boot: '約5分',
      availability: 'blocked'
    }
  ];

  const expandMockCandidates = (baseCandidates: Candidate[], totalCount: number): Candidate[] =>
    Array.from({ length: totalCount }, (_, index) => {
      const seed = baseCandidates[index % baseCandidates.length];
      if (index < baseCandidates.length) return seed;

      const ordinal = index + 1;
      const availabilityCycle: Availability[] = ['available', 'available', 'checking', 'blocked'];
      const availability = availabilityCycle[index % availabilityCycle.length];
      const gpuCountValue = ((index % 4) + 1) as 1 | 2 | 3 | 4;
      const priceValue = (seed.kind === 'verda' ? 1.95 : 1.65) + index * 0.24;

      if (seed.kind === 'verda') {
        const useL40S = index % 5 === 4;
        const gpuLabel = useL40S ? 'L40S x1' : `H100 x${gpuCountValue}`;
        return {
          kind: 'verda',
          id: `${ordinal}H100.80S.${20 + ordinal}V`,
          title: `${ordinal}H100.80S.${20 + ordinal}V`,
          price: `$${priceValue.toFixed(2)}/h`,
          gpuLabel,
          detail: useL40S ? '48GB GDDR6' : `${80 * gpuCountValue}GB HBM3`,
          route: `FIN-0${(index % 3) + 1}`,
          mode: index % 2 === 0 ? 'スポット' : 'オンデマンド',
          storage: `${200 + index * 20}GB NVMe`,
          boot: `約${2 + (index % 5)}分`,
          availability
        };
      }

      const useL40S = index % 4 === 3;
      const useH200 = index % 4 === 2;
      const gpuLabel = useL40S ? 'L40S x1' : useH200 ? 'H200 x1' : `H100 x${gpuCountValue}`;
      return {
        kind: 'vast',
        id: `offer-${31980517 + index * 117}`,
        title: `Offer #${31980517 + index * 117}`,
        price: `$${priceValue.toFixed(2)}/h`,
        gpuLabel,
        detail: useL40S ? '48GB GDDR6' : useH200 ? '141GB HBM3e' : `${80 * gpuCountValue}GB HBM3`,
        route: `${['US-West', 'EU-Central', 'Asia'][index % 3]} / host-${index + 1}.vast.ai`,
        mode: index % 2 === 0 ? 'Interruptible' : 'オンデマンド',
        storage: `${140 + index * 10}GB disk`,
        boot: `約${2 + (index % 4)}分`,
        availability
      };
    });

  const verdaCandidates = expandMockCandidates(baseVerdaCandidates, 20);
  const vastCandidates = expandMockCandidates(baseVastCandidates, 20);
  const initialBlockedCandidateIds = [...verdaCandidates, ...vastCandidates]
    .filter((candidate) => candidate.availability === 'blocked')
    .map((candidate) => candidate.id);

  let provider = $state<Provider>('verda');
  let gpuModel = $state('H100');
  let gpuCount = $state(1);
  let storageSize = $state(200);
  let verdaMode = $state<'spot' | 'ondemand'>('spot');
  let vastInterruptible = $state(true);
  let vastMaxPrice = $state('3.5');
  let draftProvider = $state<Provider>('verda');
  let draftGpuModel = $state<'any' | string>('any');
  let draftGpuCount = $state<GpuCountFilter>('any');
  let draftStorageSize = $state('');
  let draftVerdaMode = $state<VerdaModeFilter>('any');
  let draftVastInterruptible = $state<VastInterruptibleFilter>('any');
  let draftVastMaxPrice = $state('');
  let modalOpen = $state(false);
  let selectedCandidateId = $state<string>('1H100.80S.22V');
  let pendingCandidateId = $state<string | null>('1H100.80S.22V');
  let blockedCandidateIds = $state<string[]>(initialBlockedCandidateIds);
  let verifyingCandidateId = $state<string | null>(null);

  const candidatesForProvider = (targetProvider: Provider) => (targetProvider === 'verda' ? verdaCandidates : vastCandidates);

  const parseGpuCount = (label: string) => {
    const match = label.match(/x(\d+)/);
    return match ? Number(match[1]) : 0;
  };

  const parseStorageSize = (storage: string) => {
    const match = storage.match(/(\d+)/);
    return match ? Number(match[1]) : 0;
  };

  const parseHourlyPrice = (price: string) => {
    const normalized = price.replace(/[^0-9.]/g, '');
    return Number(normalized || '0');
  };

  const candidatePreviewLine = (candidate: Candidate) => `${candidate.detail} / ${candidate.route}`;
  const gpuModelOptions = ['any', ...GPU_MODELS.map((gpu) => gpu.value)];
  const storagePresetOptions = ['200', '300', '400', '500'];
  const vastPricePresetOptions = ['', '2.5', '3.5', '5.0'];
  const chipClass = (active: boolean) =>
    active
      ? 'border-sky-300 bg-sky-50 text-sky-700 shadow-[0_0_0_2px_rgba(14,165,233,0.08)]'
      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50';
  const chipButtonClass = 'whitespace-nowrap rounded-full border px-2.5 py-1.5 text-[12px] font-semibold transition';
  const roomyChipButtonClass = 'whitespace-nowrap rounded-full border px-3.5 py-1.5 text-[12px] font-semibold transition';
  const compactChipButtonClass = 'whitespace-nowrap rounded-full border px-4 py-1.5 text-[12px] font-semibold transition';
  const storageInputClass = (active: boolean, invalid: boolean) =>
    invalid
      ? 'border-rose-200 bg-rose-50/70 text-slate-900 placeholder:text-rose-300 focus:border-rose-300'
      : active
        ? 'border-sky-300 bg-sky-50/40 text-slate-900'
        : 'border-slate-200 bg-slate-50/70 text-slate-900';

  const confirmedCandidates = $derived(candidatesForProvider(provider));
  const draftCandidates = $derived(candidatesForProvider(draftProvider));

  const filteredCandidates = $derived(
    draftCandidates.filter((candidate) => {
      if (draftGpuModel !== 'any' && !candidate.gpuLabel.startsWith(draftGpuModel)) return false;
      if (draftGpuCount !== 'any' && parseGpuCount(candidate.gpuLabel) !== draftGpuCount) return false;

      if (draftProvider === 'verda') {
        if (draftVerdaMode !== 'any') {
          const expectedMode = draftVerdaMode === 'spot' ? 'スポット' : 'オンデマンド';
          if (candidate.mode !== expectedMode) return false;
        }
      } else {
        if (draftVastInterruptible === 'enabled' && candidate.mode !== 'Interruptible') return false;
        if (draftVastInterruptible === 'disabled' && candidate.mode === 'Interruptible') return false;

        const maxPrice = Number(draftVastMaxPrice);
        if (draftVastMaxPrice.trim() && Number.isFinite(maxPrice) && parseHourlyPrice(candidate.price) > maxPrice) {
          return false;
        }
      }

      return true;
    })
  );

  const selectedCandidate = $derived(
    confirmedCandidates.find((candidate) => candidate.id === selectedCandidateId) ?? null
  );
  const pendingCandidate = $derived(
    filteredCandidates.find((candidate) => candidate.id === pendingCandidateId) ?? null
  );
  const storageSettingValue = $derived(String(draftStorageSize ?? '').trim());
  const hasStorageSetting = $derived(storageSettingValue.length > 0);
  const hasValidStorageSetting = $derived(Boolean(storageSettingValue.match(/^\d+$/)) && Number(storageSettingValue) >= 200);

  const isBlocked = (candidateId: string) => blockedCandidateIds.includes(candidateId);
  const isSelected = (candidateId: string) => pendingCandidateId === candidateId;

  const statusTone = (candidate: Candidate | null) => {
    if (!candidate) return 'border-slate-200/80 bg-slate-100 text-slate-600';
    if (isBlocked(candidate.id)) return 'border-rose-200/80 bg-rose-50 text-rose-700';
    if (candidate.availability === 'checking') return 'border-amber-200/80 bg-amber-50 text-amber-700';
    return 'border-emerald-200/80 bg-emerald-50 text-emerald-700';
  };

  const statusText = (candidate: Candidate | null) => {
    if (!candidate) return '未選択';
    if (isBlocked(candidate.id)) return '選択不可';
    if (candidate.availability === 'checking') return '確認中';
    return '利用可能';
  };
  const statusTextColor = (candidate: Candidate | null) => {
    if (!candidate) return 'text-slate-500';
    if (isBlocked(candidate.id)) return 'text-rose-600';
    if (candidate.availability === 'checking') return 'text-amber-600';
    return 'text-emerald-600';
  };

  const chooseCandidate = (candidateId: string) => {
    pendingCandidateId = candidateId;
  };

  const openModal = () => {
    draftProvider = provider;
    draftGpuModel = 'any';
    draftGpuCount = 'any';
    draftStorageSize = String(storageSize);
    draftVerdaMode = 'any';
    draftVastInterruptible = 'any';
    draftVastMaxPrice = '';
    pendingCandidateId = selectedCandidateId;
    modalOpen = true;
  };

  const closeModal = () => {
    verifyingCandidateId = null;
    modalOpen = false;
  };

  $effect(() => {
    if (!modalOpen) return;
    if (filteredCandidates.length === 0) {
      pendingCandidateId = null;
      return;
    }
    if (!pendingCandidateId || !filteredCandidates.some((candidate) => candidate.id === pendingCandidateId)) {
      pendingCandidateId = filteredCandidates[0].id;
    }
  });

  const confirmSelection = async () => {
    if (!pendingCandidateId || isBlocked(pendingCandidateId)) return;
    const confirmedPending = pendingCandidate;
    if (!confirmedPending) return;

    verifyingCandidateId = pendingCandidateId;
    await new Promise((resolve) => setTimeout(resolve, 550));

    if (
      (provider === 'verda' && pendingCandidateId === '2H100.80S.60V') ||
      (provider === 'vast' && pendingCandidateId === 'offer-30018970')
    ) {
      blockedCandidateIds = [...blockedCandidateIds, pendingCandidateId];
      verifyingCandidateId = null;
      toast.error('利用可能性の最終確認で失敗しました。別の候補を選んでください。');
      return;
    }

    provider = draftProvider;
    gpuModel = draftGpuModel === 'any' ? confirmedPending.gpuLabel.split(' ')[0] : draftGpuModel;
    gpuCount = parseGpuCount(confirmedPending.gpuLabel) || gpuCount;
    storageSize = Number(storageSettingValue);
    verdaMode = draftVerdaMode === 'any' ? (confirmedPending.mode === 'オンデマンド' ? 'ondemand' : 'spot') : draftVerdaMode;
    vastInterruptible =
      draftVastInterruptible === 'any' ? confirmedPending.mode === 'Interruptible' : draftVastInterruptible === 'enabled';
    vastMaxPrice = draftVastMaxPrice;
    selectedCandidateId = pendingCandidateId;
    verifyingCandidateId = null;
    modalOpen = false;
    toast.success('学習先を固定しました。');
  };
</script>

<section class="card overflow-hidden p-6">
  <div>
    <h2 class="text-xl font-semibold text-slate-900">クラウド設定</h2>
    <p class="mt-1 text-sm leading-6 text-slate-500">選択中の構成だけを表示し、条件調整はモーダル内に集約します。</p>
  </div>

  <div class="mt-5 nested-block p-4">
    <p class="label">インスタンス</p>
    {#if selectedCandidate}
      <div class="mt-3">
        <div class="flex h-[106px] w-full flex-col rounded-xl border border-slate-200/80 bg-white px-4 py-3 text-left shadow-sm">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate text-[15px] font-semibold leading-5 text-slate-900">
                {selectedCandidate.title}
              </p>
              <p class="mt-1 truncate text-[11px] leading-4 text-slate-500">
                {candidatePreviewLine(selectedCandidate)}
              </p>
            </div>
            <span class={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold leading-none shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] ${statusTone(selectedCandidate)}`}>
              {statusText(selectedCandidate)}
            </span>
          </div>

          <div class="mt-auto flex items-end justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate text-[13px] font-semibold text-slate-800">
                {selectedCandidate.gpuLabel}
              </p>
            </div>
            <div class="shrink-0 text-right">
              <p class="text-[14px] font-semibold text-slate-900">
                {selectedCandidate.price}
              </p>
            </div>
          </div>
        </div>

        <div class="mt-2 flex items-center justify-between gap-3 text-xs text-slate-500">
          <p class="min-w-0 truncate">
            <span>継続監視</span>
            <span class={`ml-1 font-semibold ${statusTextColor(selectedCandidate)}`}>{statusText(selectedCandidate)}</span>
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
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
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
              <p class="text-xs text-slate-500">{filteredCandidates.length}件</p>
            </div>

            <div class="preview-scroll modal:min-h-0 modal:overflow-y-auto modal:pr-1">
              {#if filteredCandidates.length > 0}
                <div class="preview-query mt-3 pb-1">
                  <div class="preview-grid">
                  {#each filteredCandidates as candidate}
                    <button
                      type="button"
                      class={`instance-option-card flex h-[106px] w-[250px] flex-col rounded-xl border px-4 py-3 text-left transition ${
                        isSelected(candidate.id)
                          ? 'border-sky-300 bg-sky-50/30 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_0_0_3px_rgba(14,165,233,0.08)]'
                          : isBlocked(candidate.id)
                            ? 'cursor-not-allowed border-slate-200 bg-slate-100/80'
                            : 'border-slate-200/80 bg-white shadow-sm hover:border-slate-300 hover:bg-slate-50/80'
                      }`}
                      onclick={() => chooseCandidate(candidate.id)}
                      disabled={isBlocked(candidate.id)}
                      aria-pressed={isSelected(candidate.id)}
                      >
                        <div class="flex items-start justify-between gap-2">
                          <div class="min-w-0">
                          <p class={`truncate text-[15px] font-semibold leading-5 ${isBlocked(candidate.id) ? 'text-slate-500' : 'text-slate-900'}`}>
                            {candidate.title}
                          </p>
                          <p class={`mt-1 truncate text-[11px] leading-4 ${isBlocked(candidate.id) ? 'text-slate-400' : 'text-slate-500'}`}>
                            {candidatePreviewLine(candidate)}
                          </p>
                        </div>
                        <span class={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold leading-none shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] ${statusTone(candidate)}`}>
                          {statusText(candidate)}
                        </span>
                      </div>

                      <div class="mt-auto flex items-end justify-between gap-3">
                        <div class="min-w-0">
                          <p class={`truncate text-[13px] font-semibold ${isBlocked(candidate.id) ? 'text-slate-500' : 'text-slate-800'}`}>
                            {candidate.gpuLabel}
                          </p>
                        </div>
                        <div class="shrink-0 text-right">
                          <p class={`text-[14px] font-semibold ${isBlocked(candidate.id) ? 'text-slate-500' : 'text-slate-900'}`}>
                            {candidate.price}
                          </p>
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
                  onclick={confirmSelection}
                  disabled={!pendingCandidate || isBlocked(pendingCandidate.id) || verifyingCandidateId !== null || !hasValidStorageSetting}
                >
                  {verifyingCandidateId ? '確認中...' : 'この候補を使う'}
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
                        class={`${roomyChipButtonClass} ${chipClass(draftProvider === 'verda')}`}
                        onclick={() => (draftProvider = 'verda')}
                      >
                        Verda
                      </button>
                      <button
                        type="button"
                        class={`${roomyChipButtonClass} ${chipClass(draftProvider === 'vast')}`}
                        onclick={() => (draftProvider = 'vast')}
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
                      <span class="label">Interruptible</span>
                      <div class="mt-1 grid grid-cols-3 gap-1">
                        {#each ['any', 'enabled', 'disabled'] as option}
                          <button
                            type="button"
                            class={`${chipButtonClass} ${chipClass(draftVastInterruptible === option)}`}
                            onclick={() => (draftVastInterruptible = option as VastInterruptibleFilter)}
                          >
                            {option === 'any' ? '任意' : option === 'enabled' ? '有効' : '無効'}
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
                        min="200"
                        step="10"
                        bind:value={draftStorageSize}
                        placeholder="200以上を入力"
                      />
                      {#if !hasValidStorageSetting}
                        <p class="mt-1 text-[11px] text-rose-500">200GB以上の値を設定してください。</p>
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
            onclick={confirmSelection}
            disabled={!pendingCandidate || isBlocked(pendingCandidate.id) || verifyingCandidateId !== null || !hasValidStorageSetting}
          >
            {verifyingCandidateId ? '確認中...' : 'この候補を使う'}
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
