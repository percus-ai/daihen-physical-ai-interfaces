<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button, Tabs } from 'bits-ui';
  import { buildUrlWithQueryState } from '$lib/pagination';
  import DatasetManagementPage from './datasets/+page.svelte';
  import ModelManagementPage from './models/+page.svelte';

  type StorageTab = 'datasets' | 'models';
  type StorageStatusTab = 'active' | 'archived';

  const parseStorageTab = (value: string | null): StorageTab => (value === 'models' ? 'models' : 'datasets');
  const parseStorageStatusTab = (value: string | null): StorageStatusTab => (value === 'archived' ? 'archived' : 'active');
  const activeTab = $derived(parseStorageTab(page.url.searchParams.get('tab')));
  const activeStatusTab = $derived(parseStorageStatusTab(page.url.searchParams.get('status')));

  const statusTabTriggerClass = (value: StorageStatusTab) => {
    const isActive = activeStatusTab === value;
    if (value === 'active') {
      return `rounded-full border px-4 py-2 text-sm font-semibold transition ${
        isActive
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700 shadow-sm'
          : 'border-transparent text-slate-600 hover:text-slate-900'
      }`;
    }
    return `rounded-full border px-4 py-2 text-sm font-semibold transition ${
      isActive
        ? 'border-rose-200 bg-rose-50 text-rose-700 shadow-sm'
        : 'border-transparent text-slate-600 hover:text-slate-900'
    }`;
  };

  const handleTabChange = async (nextValue: string) => {
    const nextTab = nextValue === 'models' ? 'models' : 'datasets';
    if (nextTab === activeTab) return;
    await goto(
      buildUrlWithQueryState(page.url, {
        tab: nextTab === 'datasets' ? null : nextTab
      }),
      {
        replaceState: true,
        noScroll: true,
        keepFocus: true,
        invalidateAll: false
      }
    );
  };

  const handleStatusChange = async (nextValue: string) => {
    const nextStatus: StorageStatusTab = nextValue === 'archived' ? 'archived' : 'active';
    if (nextStatus === activeStatusTab) return;
    await goto(
      buildUrlWithQueryState(page.url, {
        status: nextStatus === 'active' ? null : nextStatus,
        page: null
      }),
      {
        replaceState: true,
        noScroll: true,
        keepFocus: true,
        invalidateAll: false
      }
    );
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ管理</h1>
      <p class="mt-2 text-sm text-slate-600">データセットとモデルをタブで切り替えて管理します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/usage">ストレージ使用量</Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <Tabs.Root value={activeTab} onValueChange={handleTabChange}>
      <Tabs.List class="inline-grid grid-cols-2 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1">
        <Tabs.Trigger
          value="datasets"
          class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
        >
          データセット
        </Tabs.Trigger>
        <Tabs.Trigger
          value="models"
          class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
        >
          モデル
        </Tabs.Trigger>
      </Tabs.List>
    </Tabs.Root>

    <Tabs.Root value={activeStatusTab} onValueChange={handleStatusChange}>
      <Tabs.List class="inline-grid grid-cols-2 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1">
        <Tabs.Trigger value="active" class={statusTabTriggerClass('active')}>
          アクティブ
        </Tabs.Trigger>
        <Tabs.Trigger value="archived" class={statusTabTriggerClass('archived')}>
          アーカイブ
        </Tabs.Trigger>
      </Tabs.List>
    </Tabs.Root>
  </div>

  {#if activeTab === 'datasets'}
    <DatasetManagementPage embedded={true} />
  {:else}
    <ModelManagementPage embedded={true} />
  {/if}
</section>
