<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button, Tabs } from 'bits-ui';
  import { buildUrlWithQueryState } from '$lib/pagination';
  import DatasetManagementPage from './datasets/+page.svelte';
  import ModelManagementPage from './models/+page.svelte';

  type StorageTab = 'datasets' | 'models';

  const parseStorageTab = (value: string | null): StorageTab => (value === 'models' ? 'models' : 'datasets');
  const activeTab = $derived(parseStorageTab(page.url.searchParams.get('tab')));

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

  {#if activeTab === 'datasets'}
    <DatasetManagementPage embedded={true} />
  {:else}
    <ModelManagementPage embedded={true} />
  {/if}
</section>
