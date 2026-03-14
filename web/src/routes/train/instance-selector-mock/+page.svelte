<script lang="ts">
  import InstanceSelectorMock from '$lib/components/training/InstanceSelectorMock.svelte';
</script>

<section class="mx-auto max-w-5xl">
  <div class="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
    <div class="space-y-6">
      <section class="card p-6">
        <h2 class="text-xl font-semibold text-slate-900">ポリシー</h2>
        <div class="mt-4 grid gap-4 sm:grid-cols-2">
          <div class="nested-block p-4">
            <p class="label">ポリシータイプ</p>
            <div class="mt-3 h-11 rounded-xl bg-slate-100/80"></div>
          </div>
          <div class="nested-block p-4">
            <p class="label">事前学習済みモデル</p>
            <div class="mt-3 h-11 rounded-xl bg-slate-100/80"></div>
          </div>
        </div>
      </section>

      <section class="card p-6">
        <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
        <div class="mt-4 nested-block p-4">
          <p class="label">選択中のデータセット</p>
          <div class="mt-3 h-16 rounded-xl bg-slate-100/80"></div>
        </div>
      </section>

      <section class="card p-6">
        <h2 class="text-xl font-semibold text-slate-900">学習パラメータ</h2>
        <div class="mt-4 grid gap-4 sm:grid-cols-3">
          <div class="nested-block p-4">
            <p class="label">ステップ数</p>
            <div class="mt-3 h-11 rounded-xl bg-slate-100/80"></div>
          </div>
          <div class="nested-block p-4">
            <p class="label">バッチサイズ</p>
            <div class="mt-3 h-11 rounded-xl bg-slate-100/80"></div>
          </div>
          <div class="nested-block p-4">
            <p class="label">保存頻度</p>
            <div class="mt-3 h-11 rounded-xl bg-slate-100/80"></div>
          </div>
        </div>
      </section>
    </div>

    <div class="space-y-6">
      <InstanceSelectorMock />
    </div>
  </div>
</section>
