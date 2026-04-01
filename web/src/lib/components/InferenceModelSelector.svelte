<script lang="ts">
  import { Button, Dialog } from 'bits-ui';

  import FilterCandidateCombobox from '$lib/components/FilterCandidateCombobox.svelte';
  import { formatBytes } from '$lib/format';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';
  import type {
    InferenceModel,
    InferenceNumericOption,
    InferenceOwnerOption,
    InferenceValueOption
  } from '$lib/types/inference';

  type SyncFilter = 'all' | 'local' | 'remote';
  type TaskFilter = 'all' | 'with-task' | 'without-task';
  type NormalizedModel = InferenceModel & {
    id: string;
    displayName: string;
    ownerLabel: string;
    profileLabel: string;
    policyLabel: string;
    syncLabel: string;
    sourceLabel: string;
    trainingStepsLabel: string;
    batchSizeLabel: string;
    trainingMetaLabel: string;
    taskCandidates: string[];
    sizeLabel: string;
    searchIndex: string;
  };
  type Props = {
    models: InferenceModel[];
    ownerOptions?: InferenceOwnerOption[];
    profileOptions?: InferenceValueOption[];
    trainingStepsOptions?: InferenceNumericOption[];
    batchSizeOptions?: InferenceNumericOption[];
    selectedModelId: string;
    loading?: boolean;
    disabled?: boolean;
    onSelect: (modelId: string) => void;
  };

  let {
    models,
    ownerOptions = [],
    profileOptions = [],
    trainingStepsOptions = [],
    batchSizeOptions = [],
    selectedModelId,
    loading = false,
    disabled = false,
    onSelect
  }: Props = $props();

  let modalOpen = $state(false);
  let searchQuery = $state('');
  let policyFilter = $state('all');
  let ownerFilter = $state('all');
  let ownerInput = $state('');
  let profileFilter = $state('all');
  let profileInput = $state('');
  let syncFilter = $state<SyncFilter>('all');
  let taskFilter = $state<TaskFilter>('all');
  let trainingStepsMin = $state('');
  let trainingStepsMax = $state('');
  let batchSizeMin = $state('');
  let batchSizeMax = $state('');
  let pendingModelId = $state('');

  const chipClass = (active: boolean) =>
    active
      ? 'border-sky-300 bg-sky-50 text-sky-700 shadow-[0_0_0_2px_rgba(14,165,233,0.08)]'
      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50';
  const chipButtonClass =
    'whitespace-nowrap rounded-full border px-3 py-1.5 text-[12px] font-semibold transition';
  const roomyChipButtonClass =
    'whitespace-nowrap rounded-full border px-3.5 py-1.5 text-[12px] font-semibold transition';
  const lowerSpecPillClass =
    'inline-flex max-w-full items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold leading-none text-slate-700';

  const resolveModelId = (model: InferenceModel) => String(model.model_id ?? model.name ?? '').trim();
  const formatPolicyLabel = (value?: string) => String(value || 'unknown').trim() || 'unknown';
  const formatOwnerLabel = (model: InferenceModel) =>
    String(model.owner_name ?? model.owner_user_id ?? '作成者未取得').trim() || '作成者未取得';
  const formatProfileLabel = (model: InferenceModel) =>
    String(model.profile_name ?? 'プロファイル未設定').trim() || 'プロファイル未設定';
  const formatSourceLabel = (value?: string) => {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized) return 'local';
    if (normalized === 'r2') return 'R2';
    return normalized;
  };
  const formatNumericLabel = (value?: number | null) =>
    typeof value === 'number' && Number.isFinite(value) ? String(value) : '-';
  const formatSizeLabel = (sizeMb?: number) => {
    if (typeof sizeMb !== 'number' || Number.isNaN(sizeMb) || sizeMb <= 0) return 'サイズ未取得';
    return formatBytes(sizeMb * 1024 * 1024);
  };
  const normalizeCreatedAt = (value?: string | null) => String(value ?? '').trim();
  const includesNormalized = (target: string, query: string) =>
    target.toLocaleLowerCase('ja-JP').includes(query.toLocaleLowerCase('ja-JP'));

  const normalizedModels = $derived.by<NormalizedModel[]>(() =>
    [...models]
      .map((model) => {
        const id = resolveModelId(model);
        const displayName = String(model.name ?? id).trim() || id;
        const taskCandidates = (model.task_candidates ?? []).map((task) => String(task).trim()).filter(Boolean);
        const ownerLabel = formatOwnerLabel(model);
        const profileLabel = formatProfileLabel(model);
        const policyLabel = formatPolicyLabel(model.policy_type);
        const sourceLabel = formatSourceLabel(model.source);
        const trainingStepsLabel = formatNumericLabel(model.training_steps);
        const batchSizeLabel = formatNumericLabel(model.batch_size);
        return {
          ...model,
          id,
          displayName,
          ownerLabel,
          profileLabel,
          policyLabel,
          syncLabel: model.is_local ? '同期済み' : '未同期',
          sourceLabel,
          trainingStepsLabel,
          batchSizeLabel,
          trainingMetaLabel: `steps ${trainingStepsLabel} / batch ${batchSizeLabel}`,
          taskCandidates,
          sizeLabel: formatSizeLabel(model.size_mb),
          searchIndex: [
            id,
            displayName,
            ownerLabel,
            profileLabel,
            policyLabel,
            trainingStepsLabel,
            batchSizeLabel,
            sourceLabel,
            model.is_local ? '同期済み local' : '未同期 remote',
            ...taskCandidates
          ]
            .join(' ')
            .toLocaleLowerCase('ja-JP')
        };
      })
      .filter((model) => model.id)
      .sort((left, right) => {
        const leftCreatedAt = normalizeCreatedAt(left.created_at);
        const rightCreatedAt = normalizeCreatedAt(right.created_at);
        if (leftCreatedAt !== rightCreatedAt) {
          return rightCreatedAt.localeCompare(leftCreatedAt, 'en');
        }
        return left.displayName.localeCompare(right.displayName, 'ja');
      })
  );

  const policyOptions = $derived(['all', ...new Set(normalizedModels.map((model) => model.policyLabel))]);
  const resolvedOwnerOptions = $derived(
    (ownerOptions.length > 0
      ? ownerOptions
      : Array.from(
          new Map(
            normalizedModels
              .filter((model) => String(model.owner_user_id || '').trim())
              .map((model) => [String(model.owner_user_id), { user_id: String(model.owner_user_id), label: model.ownerLabel }])
          ).values()
        )).map((option) => ({
          value: option.user_id,
          label: option.label
        }))
  );
  const resolvedProfileOptions = $derived(
    (profileOptions.length > 0
      ? profileOptions
      : Array.from(
          new Set(
            normalizedModels
              .map((model) => String(model.profile_name || '').trim())
              .filter(Boolean)
          )
        ).map((value) => ({ value, label: value }))
    ).map((option) => ({
      value: option.value,
      label: option.label
    }))
  );
  const resolvedTrainingStepsOptions = $derived(
    trainingStepsOptions.length > 0
      ? trainingStepsOptions
      : Array.from(
          new Set(
            normalizedModels
              .map((model) => (typeof model.training_steps === 'number' ? model.training_steps : null))
              .filter((value): value is number => value !== null)
          )
        )
          .sort((left, right) => left - right)
          .map((value) => ({ value, label: String(value) }))
  );
  const resolvedTrainingStepItems = $derived(
    resolvedTrainingStepsOptions.map((option) => ({
      value: String(option.value),
      label: option.label
    }))
  );
  const resolvedBatchSizeOptions = $derived(
    batchSizeOptions.length > 0
      ? batchSizeOptions
      : Array.from(
          new Set(
            normalizedModels
              .map((model) => (typeof model.batch_size === 'number' ? model.batch_size : null))
              .filter((value): value is number => value !== null)
          )
        )
          .sort((left, right) => left - right)
          .map((value) => ({ value, label: String(value) }))
  );
  const resolvedBatchSizeItems = $derived(
    resolvedBatchSizeOptions.map((option) => ({
      value: String(option.value),
      label: option.label
    }))
  );
  const selectedModel = $derived(normalizedModels.find((model) => model.id === selectedModelId) ?? null);
  const parseMinBound = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number.parseInt(trimmed, 10);
    return Number.isInteger(parsed) ? parsed : null;
  };
  const parseMaxBound = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number.parseInt(trimmed, 10);
    return Number.isInteger(parsed) ? parsed : null;
  };
  const filteredModels = $derived.by<NormalizedModel[]>(() => {
    const normalizedQuery = searchQuery.trim().toLocaleLowerCase('ja-JP');
    const stepsMin = parseMinBound(trainingStepsMin);
    const stepsMax = parseMaxBound(trainingStepsMax);
    const batchMin = parseMinBound(batchSizeMin);
    const batchMax = parseMaxBound(batchSizeMax);
    const normalizedOwnerQuery = ownerInput.trim().toLocaleLowerCase('ja-JP');
    const normalizedProfileQuery = profileInput.trim().toLocaleLowerCase('ja-JP');
    return normalizedModels.filter((model) => {
      if (policyFilter !== 'all' && model.policyLabel !== policyFilter) return false;
      if (ownerFilter !== 'all' && String(model.owner_user_id || '') !== ownerFilter) return false;
      if (ownerFilter === 'all' && normalizedOwnerQuery && !includesNormalized(model.ownerLabel, normalizedOwnerQuery)) return false;
      if (profileFilter !== 'all' && String(model.profile_name || '') !== profileFilter) return false;
      if (profileFilter === 'all' && normalizedProfileQuery && !includesNormalized(String(model.profile_name || ''), normalizedProfileQuery)) return false;
      if (syncFilter === 'local' && !model.is_local) return false;
      if (syncFilter === 'remote' && model.is_local) return false;
      if (taskFilter === 'with-task' && model.taskCandidates.length === 0) return false;
      if (taskFilter === 'without-task' && model.taskCandidates.length > 0) return false;
      if (stepsMin !== null && (typeof model.training_steps !== 'number' || model.training_steps < stepsMin)) return false;
      if (stepsMax !== null && (typeof model.training_steps !== 'number' || model.training_steps > stepsMax)) return false;
      if (batchMin !== null && (typeof model.batch_size !== 'number' || model.batch_size < batchMin)) return false;
      if (batchMax !== null && (typeof model.batch_size !== 'number' || model.batch_size > batchMax)) return false;
      if (!normalizedQuery) return true;
      return includesNormalized(model.searchIndex, normalizedQuery);
    });
  });
  const pendingModel = $derived(
    filteredModels.find((model) => model.id === pendingModelId) ??
      normalizedModels.find((model) => model.id === pendingModelId) ??
      selectedModel
  );

  $effect(() => {
    if (!modalOpen) return;
    if (filteredModels.length === 0) {
      pendingModelId = '';
      return;
    }
    if (filteredModels.some((model) => model.id === pendingModelId)) return;
    pendingModelId = filteredModels.find((model) => model.id === selectedModelId)?.id ?? filteredModels[0].id;
  });

  const openModal = () => {
    searchQuery = '';
    policyFilter = 'all';
    ownerFilter = 'all';
    ownerInput = '';
    profileFilter = 'all';
    profileInput = '';
    syncFilter = 'all';
    taskFilter = 'all';
    trainingStepsMin = '';
    trainingStepsMax = '';
    batchSizeMin = '';
    batchSizeMax = '';
    pendingModelId = selectedModelId;
    modalOpen = true;
  };

  const applySelection = () => {
    if (!pendingModelId) return;
    onSelect(pendingModelId);
    modalOpen = false;
  };

  const chooseModel = (modelId: string) => {
    pendingModelId = modelId;
  };

  const closeModal = () => {
    modalOpen = false;
  };
</script>

<div class="nested-block p-4">
  <p class="label">推論モデル</p>
  {#if loading}
    <div class="mt-3 flex h-[106px] w-full items-center rounded-xl border border-dashed border-slate-200 bg-white px-4 text-sm text-slate-500">
      モデル一覧を読み込み中...
    </div>
  {:else if selectedModel}
    <div class="mt-3">
      <div class="flex h-[106px] w-full flex-col rounded-xl border border-slate-200/80 bg-white px-4 py-3 text-left shadow-sm">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate text-[15px] font-semibold leading-5 text-slate-900" title={selectedModel.displayName}>
              {selectedModel.displayName}
            </p>
            <p class="truncate text-[11px] leading-4 text-slate-500">{selectedModel.profileLabel}</p>
            <p class="truncate text-[11px] leading-4 text-slate-500">{selectedModel.trainingMetaLabel}</p>
          </div>
          <span
            class={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold leading-none shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] ${
              selectedModel.is_local ? 'border-emerald-200/80 bg-emerald-50 text-emerald-700' : 'border-amber-200/80 bg-amber-50 text-amber-700'
            }`}
          >
            {selectedModel.syncLabel}
          </span>
        </div>

        <div class="mt-auto flex items-end justify-between gap-3">
          <div class="min-w-0">
            <span class={lowerSpecPillClass}>
              <span class="truncate">{selectedModel.policyLabel}</span>
            </span>
          </div>
          <div class="shrink-0 text-right">
            <p class="max-w-[112px] truncate text-[14px] font-semibold text-slate-900">{selectedModel.ownerLabel}</p>
          </div>
        </div>
      </div>

      <div class="mt-2 flex items-center justify-between gap-3 text-xs text-slate-500">
        <p class="min-w-0 truncate font-mono">{selectedModel.id}</p>
        <p class="shrink-0 text-right">
          <span>{selectedModel.sizeLabel}</span>
        </p>
      </div>
      <div class="mt-1 flex items-center justify-between gap-3 text-xs text-slate-500">
        <p class="min-w-0 truncate">
          <span>選択済み</span>
          {#if selectedModel.is_loaded}
            <span class="ml-1 font-semibold text-sky-600">現在のワーカーで使用中</span>
          {/if}
        </p>
        <p class="shrink-0 text-right">task {selectedModel.taskCandidates.length}件</p>
      </div>
    </div>
  {:else if normalizedModels.length > 0}
    <div class="mt-3 flex h-[106px] w-full items-center rounded-xl border border-dashed border-slate-200 bg-white px-4 text-sm text-slate-500">
      モデル未選択
    </div>
  {:else}
    <div class="mt-3 flex h-[106px] w-full items-center rounded-xl border border-dashed border-slate-200 bg-white px-4 text-sm text-slate-500">
      利用可能な推論モデルがありません
    </div>
  {/if}

  <Button.Root
    class="mt-4 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-100"
    type="button"
    onclick={openModal}
    disabled={disabled || normalizedModels.length === 0}
  >
    モデルを選ぶ
  </Button.Root>
</div>

<Dialog.Root bind:open={modalOpen}>
  <Dialog.Portal>
    <Dialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <Dialog.Content
      class="fixed inset-x-3 bottom-3 top-3 z-[41] outline-none modal:bottom-auto modal:left-1/2 modal:right-auto modal:top-[6.5rem] modal:-translate-x-1/2"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <div class="flex h-full w-full flex-col overflow-hidden rounded-[26px] border border-slate-200/90 bg-white shadow-[0_32px_72px_-40px_rgba(15,23,42,0.28)] modal:h-[788px] modal:w-[775px] modal:max-w-[calc(100vw-96px)]">
        <div class="flex items-center justify-between gap-6 border-b border-slate-200/80 px-4 pb-3 pt-4 modal:px-8 modal:pb-3 modal:pt-6">
          <div>
            <p class="label">推論モデル</p>
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
                <p class="text-xs text-slate-500">{filteredModels.length}件</p>
              </div>

              <div class="preview-scroll modal:min-h-0 modal:overflow-y-auto modal:pr-1">
                {#if filteredModels.length > 0}
                  <div class="preview-query mt-3 pb-1">
                    <div class="preview-grid">
                    {#each filteredModels as model}
                      <button
                        type="button"
                        class={`model-option-card flex h-[106px] w-[250px] flex-col rounded-xl border px-4 py-3 text-left transition ${
                          pendingModelId === model.id
                            ? 'border-sky-300 bg-sky-50/30 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_0_0_3px_rgba(14,165,233,0.08)]'
                            : 'border-slate-200/80 bg-white shadow-sm hover:border-slate-300 hover:bg-slate-50/80'
                        }`}
                        onclick={() => chooseModel(model.id)}
                        aria-pressed={pendingModelId === model.id}
                      >
                        <div class="flex items-start justify-between gap-2">
                          <div class="min-w-0">
                            <p class="truncate text-[15px] font-semibold leading-5 text-slate-900" title={model.displayName}>
                              {model.displayName}
                            </p>
                            <p class="truncate text-[11px] leading-4 text-slate-500">{model.profileLabel}</p>
                            <p class="truncate text-[11px] leading-4 text-slate-500">{model.trainingMetaLabel}</p>
                          </div>
                          <span
                            class={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold leading-none shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] ${
                              model.is_local ? 'border-emerald-200/80 bg-emerald-50 text-emerald-700' : 'border-amber-200/80 bg-amber-50 text-amber-700'
                            }`}
                          >
                            {model.syncLabel}
                          </span>
                        </div>

                        <div class="mt-auto flex items-end justify-between gap-3">
                          <div class="min-w-0">
                            <span class={lowerSpecPillClass}>
                              <span class="truncate">{model.policyLabel}</span>
                            </span>
                          </div>
                          <div class="shrink-0 text-right">
                            <p class="max-w-[112px] truncate text-[14px] font-semibold text-slate-900">{model.ownerLabel}</p>
                          </div>
                        </div>
                      </button>
                    {/each}
                    </div>
                  </div>
                {:else}
                  <div class="mt-3 flex h-[106px] w-full items-center rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-4 text-sm text-slate-500">
                    条件に合う候補がありません。
                  </div>
                {/if}
              </div>

              <div class="mt-auto hidden border-t border-slate-200/80 pt-4 modal:block">
                <div class="flex justify-end">
                  <Button.Root class="btn-primary min-w-[184px] px-5 py-3" type="button" onclick={applySelection} disabled={!pendingModelId}>
                    このモデルを使う
                  </Button.Root>
                </div>
              </div>
            </div>

            <div class="flex min-h-0 flex-col border-t border-slate-200/80 pt-5 modal:border-l modal:border-t-0 modal:pl-5 modal:pt-0">
              <div class="flex items-center justify-between gap-3">
                <p class="text-sm font-semibold text-slate-900">条件</p>
                <button
                  type="button"
                  class="text-xs font-semibold text-slate-500 transition hover:text-slate-800"
                  onclick={() => {
                    searchQuery = '';
                    policyFilter = 'all';
                    ownerFilter = 'all';
                    ownerInput = '';
                    profileFilter = 'all';
                    profileInput = '';
                    syncFilter = 'all';
                    taskFilter = 'all';
                    trainingStepsMin = '';
                    trainingStepsMax = '';
                    batchSizeMin = '';
                    batchSizeMax = '';
                  }}
                >
                  リセット
                </button>
              </div>

              <div class="condition-query mt-2 min-h-0 flex-1 modal:h-full">
                <div class="condition-layout modal:h-full">
                  <div class="condition-layout__base min-w-0">
                    <p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">ベース条件</p>
                    <div class="mt-1.5 space-y-2">
                      <div>
                        <span class="label">Search</span>
                        <input
                          class="input mt-1.5 h-9"
                          type="search"
                          value={searchQuery}
                          placeholder="モデル名 / ID / task で検索"
                          oninput={(event) => (searchQuery = event.currentTarget.value)}
                        />
                      </div>

                      <div>
                        <span class="label">Policy</span>
                        <div class="mt-1 flex flex-wrap gap-1">
                          {#each policyOptions as option}
                            <button
                              type="button"
                              class={`${roomyChipButtonClass} ${chipClass(policyFilter === option)}`}
                              onclick={() => (policyFilter = option)}
                            >
                              {option === 'all' ? 'すべて' : option}
                            </button>
                          {/each}
                        </div>
                      </div>

                      <div>
                        <span class="label">作成者</span>
                        <div class="mt-1.5">
                          <FilterCandidateCombobox
                            items={resolvedOwnerOptions}
                            value={ownerFilter === 'all' ? '' : ownerFilter}
                            inputValue={ownerInput}
                            placeholder="作成者で絞り込む"
                            emptyMessage="一致する作成者がありません。"
                            onSelect={(value) => {
                              ownerFilter = value || 'all';
                              ownerInput = resolvedOwnerOptions.find((option) => option.value === value)?.label ?? '';
                            }}
                            onInput={(value) => {
                              ownerInput = value;
                              if (!value.trim()) ownerFilter = 'all';
                            }}
                          />
                        </div>
                      </div>

                      <div>
                        <span class="label">プロファイル</span>
                        <div class="mt-1.5">
                          <FilterCandidateCombobox
                            items={resolvedProfileOptions}
                            value={profileFilter === 'all' ? '' : profileFilter}
                            inputValue={profileInput}
                            placeholder="プロファイルで絞り込む"
                            emptyMessage="一致するプロファイルがありません。"
                            onSelect={(value) => {
                              profileFilter = value || 'all';
                              profileInput = resolvedProfileOptions.find((option) => option.value === value)?.label ?? '';
                            }}
                            onInput={(value) => {
                              profileInput = value;
                              if (!value.trim()) profileFilter = 'all';
                            }}
                          />
                        </div>
                      </div>

                      <div>
                        <span class="label">同期状態</span>
                        <div class="mt-1 grid grid-cols-3 gap-1">
                          {#each [
                            ['all', 'すべて'],
                            ['local', '同期済み'],
                            ['remote', '未同期']
                          ] as [value, label]}
                            <button
                              type="button"
                              class={`${chipButtonClass} ${chipClass(syncFilter === value)}`}
                              onclick={() => (syncFilter = value as SyncFilter)}
                            >
                              {label}
                            </button>
                          {/each}
                        </div>
                      </div>

                      <div>
                        <span class="label">Task候補</span>
                        <div class="mt-1 grid grid-cols-3 gap-1">
                          {#each [
                            ['all', 'すべて'],
                            ['with-task', '候補あり'],
                            ['without-task', '候補なし']
                          ] as [value, label]}
                            <button
                              type="button"
                              class={`${chipButtonClass} ${chipClass(taskFilter === value)}`}
                              onclick={() => (taskFilter = value as TaskFilter)}
                            >
                              {label}
                            </button>
                          {/each}
                        </div>
                      </div>

                      <div>
                        <span class="label">Steps</span>
                        <div class="mt-1.5 grid grid-cols-2 gap-2">
                          <FilterCandidateCombobox
                            items={resolvedTrainingStepItems}
                            value={trainingStepsMin}
                            inputValue={trainingStepsMin}
                            placeholder="min"
                            emptyMessage="一致する step 値がありません。"
                            onSelect={(value) => {
                              trainingStepsMin = value;
                            }}
                            onInput={(value) => {
                              trainingStepsMin = value;
                            }}
                          />
                          <FilterCandidateCombobox
                            items={resolvedTrainingStepItems}
                            value={trainingStepsMax}
                            inputValue={trainingStepsMax}
                            placeholder="max"
                            emptyMessage="一致する step 値がありません。"
                            onSelect={(value) => {
                              trainingStepsMax = value;
                            }}
                            onInput={(value) => {
                              trainingStepsMax = value;
                            }}
                          />
                        </div>
                      </div>

                      <div>
                        <span class="label">Batch Size</span>
                        <div class="mt-1.5 grid grid-cols-2 gap-2">
                          <FilterCandidateCombobox
                            items={resolvedBatchSizeItems}
                            value={batchSizeMin}
                            inputValue={batchSizeMin}
                            placeholder="min"
                            emptyMessage="一致する batch size がありません。"
                            onSelect={(value) => {
                              batchSizeMin = value;
                            }}
                            onInput={(value) => {
                              batchSizeMin = value;
                            }}
                          />
                          <FilterCandidateCombobox
                            items={resolvedBatchSizeItems}
                            value={batchSizeMax}
                            inputValue={batchSizeMax}
                            placeholder="max"
                            emptyMessage="一致する batch size がありません。"
                            onSelect={(value) => {
                              batchSizeMax = value;
                            }}
                            onInput={(value) => {
                              batchSizeMax = value;
                            }}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="border-t border-slate-200/80 px-4 pb-4 pt-4 modal:hidden">
          <Button.Root class="btn-primary w-full px-5 py-3" type="button" onclick={applySelection} disabled={!pendingModelId}>
            このモデルを使う
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

  .preview-grid .model-option-card {
    width: 100%;
  }

  .condition-layout {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

</style>
