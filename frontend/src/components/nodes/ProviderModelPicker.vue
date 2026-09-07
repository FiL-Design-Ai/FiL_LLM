<script setup lang="ts">
/**
 * The model picker for FiLProviderLoader, on the shared `FilBrowser` frame.
 *
 * What changed from the fixed-width dialog it replaces, and why:
 *
 *   - The provider tabs and the three rows of segmented filters moved into the
 *     left column, each row carrying a COUNT. Before, narrowing OpenRouter's
 *     367 models to free vision ones meant reading three separate controls and
 *     finding out how many were left only afterwards.
 *
 *   - Search ranks instead of filtering. `gpt-4o` used to sit below every
 *     longer name containing it, because a substring filter keeps the
 *     provider's own order.
 *
 *   - Recently used is a filter of its own. Favourites answer "the four I
 *     always use"; nothing answered "the one I tried twenty minutes ago".
 *
 * The picker still owns everything about providers, tiers and vision flags —
 * the browser knows none of it. It is handed `BrowserItem[]` and reports the
 * id that was picked.
 */
import { computed, ref, watch } from "vue";
import FilBrowser from "@/components/widgets/FilBrowser.vue";
import FilBrowserSidebar from "@/components/widgets/FilBrowserSidebar.vue";
import FilButton from "@/components/widgets/FilButton.vue";
import { useProviderStore, PROVIDER_LIST } from "@/stores/providerStore";
import { isFavourite, toggleFavourite } from "@/stores/modelFavourites";
import { noteRecent, recentsFor } from "@/stores/browserRecents";
import { PROVIDER_LABEL, PROVIDER_ICON } from "@/composables/providerMeta";
import { rankItems, type SearchField } from "@/lib/browserSearch";
import type { BrowserItem, BrowserSidebarSection, BrowserTag } from "@/lib/browserTypes";
import { useI18n } from "@/composables/useI18n";
import { toast } from "@/stores/toastStore";

const props = withDefaults(
  defineProps<{
    open: boolean;
    provider: string;
    model: string;
  }>(),
  { open: false, provider: "ollama", model: "" },
);

const emit = defineEmits<{
  "update:open": [value: boolean];
  select: [payload: { provider: string; model: string }];
}>();

const store = useProviderStore();
const { t, tPlural } = useI18n();

const selectedProvider = ref<string>(props.provider);
const selectedModel = ref<string>(props.model);
const searchQuery = ref<string>("");

/**
 * Reads go through this, not bare `localStorage`. These run at module scope,
 * and `localStorage` is not guaranteed to exist — a blocked-storage profile, a
 * `file://` origin or an opaque one leaves it undefined or makes the getter
 * throw, and an unguarded read there takes the whole picker down on import.
 */
function recall(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // quota, or a profile that forbids writes
  }
}

const STORAGE_KEY_VIEW = "fil_model_picker_view_mode";
const STORAGE_KEY_STATUS = "fil_model_picker_status_filter";
const STORAGE_KEY_TYPE = "fil_model_picker_type_filter";
const STORAGE_KEY_TIER = "fil_model_picker_tier_filter";
const STORAGE_KEY_ONLY = "fil_model_picker_only_filter";
const STORAGE_KEY_CONTENT = "fil_model_picker_content_filter";
const STORAGE_KEY_SORT = "fil_model_picker_sort_mode";

type StatusFilter = "all" | "verified";
type TypeFilter = "all" | "vision" | "text";
type TierFilter = "all" | "free" | "paid" | "local";
type OnlyFilter = "all" | "fav" | "recent";
type ContentFilter = "all" | "nsfw" | "sfw";
export type SortMode = "smart" | "name-asc" | "name-desc" | "verified" | "fav";

// The filters survive closing the picker, the way the view mode already did:
// somebody who narrowed 367 models to free vision ones should not redo it on
// every visit.
const statusFilter = ref<StatusFilter>((recall(STORAGE_KEY_STATUS) as StatusFilter) || "all");
const typeFilter = ref<TypeFilter>((recall(STORAGE_KEY_TYPE) as TypeFilter) || "all");
const tierFilter = ref<TierFilter>((recall(STORAGE_KEY_TIER) as TierFilter) || "all");
const onlyFilter = ref<OnlyFilter>((recall(STORAGE_KEY_ONLY) as OnlyFilter) || "all");
const contentFilter = ref<ContentFilter>((recall(STORAGE_KEY_CONTENT) as ContentFilter) || "all");
const sortMode = ref<SortMode>((recall(STORAGE_KEY_SORT) as SortMode) || "smart");
const viewMode = ref<"list" | "grid">((recall(STORAGE_KEY_VIEW) as "list" | "grid") || "list");

watch(statusFilter, (v) => remember(STORAGE_KEY_STATUS, v));
watch(typeFilter, (v) => remember(STORAGE_KEY_TYPE, v));
watch(tierFilter, (v) => remember(STORAGE_KEY_TIER, v));
watch(onlyFilter, (v) => remember(STORAGE_KEY_ONLY, v));
watch(contentFilter, (v) => remember(STORAGE_KEY_CONTENT, v));
watch(sortMode, (v) => remember(STORAGE_KEY_SORT, v));
watch(viewMode, (v) => remember(STORAGE_KEY_VIEW, v));

/** Where this provider's recents are kept — the same id under two providers is
 *  two different things, the rule `modelFavourites` already follows. */
const recentScope = computed(() => `models:${selectedProvider.value}`);

// ── the provider's list ──────────────────────────────────────────────────────

const currentModels = computed(() => store.modelsFor(selectedProvider.value));
const visionModels = computed(() => store.visionModelsFor(selectedProvider.value));
const nsfwModels = computed(() => store.nsfwModelsFor(selectedProvider.value));
const verifiedModels = computed(() => store.verifiedModelsFor(selectedProvider.value));
const isLoading = computed(() => store.isLoading(selectedProvider.value));
const probe = computed(() => store.probeState[selectedProvider.value]);
const ageLabel = computed(() => store.cachedAgeLabel(selectedProvider.value, t));

const isLocalProvider = computed(
  () => selectedProvider.value === "ollama" || selectedProvider.value === "lmstudio",
);

function getTier(m: string, p: string): "local" | "free" | "paid" {
  if (p === "ollama" || p === "lmstudio") return "local";
  // Hugging Face, Groq, Google AI Studio, Cloudflare Workers AI provide free API tiers for their models
  if (p === "huggingface" || p === "groq" || p === "google" || p === "cloudflare") return "free";
  if (m.toLowerCase().includes(":free") || m.toLowerCase() === "openrouter/free") return "free";
  return "paid";
}

/**
 * A Set, not `visionModels.includes(m)`.
 *
 * This is asked once per model while filtering and twice more for every row
 * that renders, so a linear scan made the whole thing quadratic: OpenRouter
 * lists 367 models, and each keystroke walked the vision list about a thousand
 * times over. Rebuilt only when the provider's list is replaced.
 */
const visionSet = computed(() => new Set(visionModels.value));
const isVision = (m: string) => visionSet.value.has(m);

const nsfwSet = computed(() => new Set(nsfwModels.value));
const isNsfw = (m: string) => nsfwSet.value.has(m);

const verifiedSet = computed(() => new Set(verifiedModels.value));
const isVerified = (m: string) => verifiedSet.value.has(m);

// `isFavourite` reads a module-level ref, so calling it from a computed is
// enough for Vue to track it — a toggle replaces the Set and everything that
// read it re-evaluates.
const starred = (m: string) => isFavourite(selectedProvider.value, m);

// ── filters ──────────────────────────────────────────────────────────────────

/** Everything except the axis being counted, so each row's number answers
 *  "how many would be left if I clicked this" rather than "how many exist". */
function passes(m: string, skip: "status" | "type" | "tier" | "only" | "content" | null): boolean {
  const p = selectedProvider.value;
  if (skip !== "status" && statusFilter.value !== "all") {
    if (statusFilter.value === "verified" && !isVerified(m)) return false;
  }
  if (skip !== "type" && typeFilter.value !== "all") {
    if (typeFilter.value === "vision" ? !isVision(m) : isVision(m)) return false;
  }
  if (skip !== "tier" && tierFilter.value !== "all" && getTier(m, p) !== tierFilter.value) return false;
  if (skip !== "only" && onlyFilter.value !== "all") {
    if (onlyFilter.value === "fav" ? !starred(m) : !recentsFor(recentScope.value).includes(m)) return false;
  }
  if (skip !== "content" && contentFilter.value !== "all") {
    if (contentFilter.value === "nsfw" ? !isNsfw(m) : isNsfw(m)) return false;
  }
  return true;
}

const SEARCH_FIELDS: SearchField<BrowserItem>[] = [{ weight: 100, read: (item) => item.id }];

function tagsFor(m: string): BrowserTag[] {
  const tier = getTier(m, selectedProvider.value);
  const tags: BrowserTag[] = [];
  if (isVerified(m)) {
    tags.push({ label: t("pmp_badge_verified", "⚡ Verified"), tone: "ok" as const });
  }
  tags.push(
    isVision(m)
      ? { label: t("pmp_tag_vision", "Vision"), tone: "accent" as const }
      : { label: t("pmp_tag_text", "Text"), tone: "neutral" as const },
    {
      label:
        tier === "local"
          ? t("pmp_tag_local", "Local")
          : tier === "free"
            ? t("pmp_tag_free", "Free")
            : t("pmp_tag_paid", "Paid"),
      tone: tier === "free" ? ("ok" as const) : ("neutral" as const),
    },
  );
  if (isNsfw(m)) {
    tags.push({ label: t("pmp_tag_nsfw", "🔞 NSFW"), tone: "warn" as const });
  }
  return tags;
}

function toItem(m: string): BrowserItem {
  return { id: m, label: m, title: m, icon: isVision(m) ? "👁" : "📝", tags: tagsFor(m) };
}

function compareModels(a: string, b: string): number {
  if (sortMode.value === "name-asc") {
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }
  if (sortMode.value === "name-desc") {
    return b.localeCompare(a, undefined, { numeric: true, sensitivity: "base" });
  }
  if (sortMode.value === "verified") {
    const va = isVerified(a) ? 1 : 0;
    const vb = isVerified(b) ? 1 : 0;
    if (va !== vb) return vb - va;
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }
  if (sortMode.value === "fav") {
    const fa = starred(a) ? 1 : 0;
    const fb = starred(b) ? 1 : 0;
    if (fa !== fb) return fb - fa;
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }
  // Default "smart" sort:
  // 1. Favourites first (100)
  // 2. Verified models (50)
  // 3. Alphabetical tie-break
  const scoreA = (starred(a) ? 100 : 0) + (isVerified(a) ? 50 : 0);
  const scoreB = (starred(b) ? 100 : 0) + (isVerified(b) ? 50 : 0);
  if (scoreA !== scoreB) return scoreB - scoreA;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

/** Filtered, then sorted by sortMode, then ranked if a search query is typed. */
const browserItems = computed<BrowserItem[]>(() => {
  const filtered = currentModels.value.filter((m) => passes(m, null));
  filtered.sort(compareModels);
  const items = filtered.map(toItem);
  return rankItems(items, searchQuery.value, SEARCH_FIELDS, (a, b) => compareModels(a.id, b.id));
});

// ── the left column & quick toolbar chips ────────────────────────────────────

const chipVerifiedCount = computed(() => currentModels.value.filter(isVerified).length);
const chipFavCount = computed(() => currentModels.value.filter(starred).length);
const chipFreeCount = computed(
  () =>
    currentModels.value.filter(
      (m) => getTier(m, selectedProvider.value) === "free" || getTier(m, selectedProvider.value) === "local",
    ).length,
);
const chipVisionCount = computed(() => currentModels.value.filter(isVision).length);
const chipNsfwCount = computed(() => currentModels.value.filter(isNsfw).length);

const hasActiveFilters = computed(() => {
  return (
    statusFilter.value !== "all" ||
    onlyFilter.value !== "all" ||
    typeFilter.value !== "all" ||
    tierFilter.value !== "all" ||
    contentFilter.value !== "all" ||
    Boolean(searchQuery.value.trim())
  );
});

function resetAllFilters() {
  statusFilter.value = "all";
  onlyFilter.value = "all";
  typeFilter.value = "all";
  tierFilter.value = "all";
  contentFilter.value = "all";
  searchQuery.value = "";
}

const sidebarSections = computed<BrowserSidebarSection[]>(() => [
  {
    id: "providers",
    heading: t("pmp_group_provider", "Provider"),
    rows: PROVIDER_LIST.map((p) => ({
      id: `provider:${p}`,
      label: PROVIDER_LABEL[p] ?? p,
      iconName: PROVIDER_ICON[p],
      // No number while a provider has never been opened: a bare 0 there
      // reads as "this one is empty" rather than "not loaded yet".
      count: store.modelsFor(p).length || null,
    })),
  },
]);

const activeRows = computed(() => [`provider:${selectedProvider.value}`]);

function onSidebarPick(id: string) {
  if (id.startsWith("provider:")) {
    switchProvider(id.slice("provider:".length));
  }
}

// ── provider switching and loading ───────────────────────────────────────────

async function loadCurrentProviderModels(force = false) {
  try {
    await store.loadModels(selectedProvider.value, force);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : String(err));
  }
}

function switchProvider(p: string) {
  if (p === selectedProvider.value) return;
  selectedProvider.value = p;
  searchQuery.value = "";
  // Drop a tier the new provider cannot have — a kept "free" on Ollama filters
  // the list down to nothing and looks like a broken provider.
  if (isLocalProvider.value) {
    if (tierFilter.value === "free" || tierFilter.value === "paid") tierFilter.value = "all";
  } else if (tierFilter.value === "local") {
    tierFilter.value = "all";
  }
  selectedModel.value = store.modelsFor(p)[0] ?? "";
  void loadCurrentProviderModels();
}

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    selectedProvider.value = props.provider || "ollama";
    selectedModel.value = props.model || "";
    // Search is per-visit: a leftover query silently hiding every model is
    // worse than retyping it. The sidebar filters are visible on screen, so
    // they can safely persist.
    searchQuery.value = "";
    if (isLocalProvider.value && (tierFilter.value === "free" || tierFilter.value === "paid")) {
      tierFilter.value = "all";
    }
    if (!isLocalProvider.value && tierFilter.value === "local") tierFilter.value = "all";
    void loadCurrentProviderModels();
  },
);

// ── the right-hand pane ──────────────────────────────────────────────────────

const detailTags = computed(() => (selectedModel.value ? tagsFor(selectedModel.value) : []));

async function copyModelId() {
  const id = selectedModel.value;
  if (!id) return;
  // `navigator.clipboard` needs a SECURE context, and ComfyUI is very often
  // reached over plain http on a LAN address where the whole API is simply
  // absent — so the textarea trick is the fallback rather than an afterthought.
  try {
    await navigator.clipboard.writeText(id);
    toast.success(t("pmp_copied", "Copied"));
    return;
  } catch {
    // no secure context, or permission refused
  }
  const ta = document.createElement("textarea");
  ta.value = id;
  ta.style.cssText = "position:fixed;top:-1000px;left:-1000px;";
  document.body.append(ta);
  ta.select();
  let ok: boolean;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  ta.remove();
  toast[ok ? "success" : "warning"](ok ? t("pmp_copied", "Copied") : id);
}

// ── the window ───────────────────────────────────────────────────────────────

const isOpen = computed({
  get: () => props.open,
  set: (v: boolean) => emit("update:open", v),
});

const countText = computed(() => {
  const shown = browserItems.value.length;
  const total = currentModels.value.length;
  const noun = tPlural("prov_models", shown, "model", "models", "models");
  return shown === total ? `${total} ${noun}` : `${shown} / ${total} ${noun}`;
});

function toggleStar(m: string) {
  toggleFavourite(selectedProvider.value, m);
}

function confirmSelection(id?: string) {
  const model = id || selectedModel.value;
  if (!model) return;
  selectedModel.value = model;
  noteRecent(recentScope.value, model);
  emit("select", { provider: selectedProvider.value, model });
  emit("update:open", false);
}
</script>

<template>
  <FilBrowser
    v-model:open="isOpen"
    v-model:query="searchQuery"
    v-model:selected="selectedModel"
    v-model:view="viewMode"
    :title="t('pmp_title', '🔌 Provider & model')"
    storage-key="fil_model_picker_rect"
    :items="browserItems"
    :count-text="countText"
    :search-placeholder="t('pmp_search', 'Search models…')"
    :search-title="t('pmp_search_tt', 'Ranks by how well the name matches, best first')"
    :empty-text="t('pmp_no_match', 'No models match these filters.')"
    :loading="isLoading"
    :loading-text="t('pmp_loading_provider', 'Loading models from provider…')"
    starrable
    :is-starred="starred"
    :pref-width="1060"
    @star="toggleStar"
    @confirm="confirmSelection"
  >
    <template #sidebar>
      <FilBrowserSidebar :sections="sidebarSections" :active="activeRows" @select="onSidebarPick" />
    </template>

    <template #toolbar>
      <div class="pmp-sort">
        <select v-model="sortMode" class="pmp-sort-select" :aria-label="t('pmp_sort_smart', 'Sort')">
          <option value="smart">{{ t('pmp_sort_smart', '⚡ Smart (Verified)') }}</option>
          <option value="name-asc">{{ t('pmp_sort_name_asc', '🔤 Name (A → Z)') }}</option>
          <option value="name-desc">{{ t('pmp_sort_name_desc', '🔤 Name (Z → A)') }}</option>
          <option value="fav">{{ t('pmp_sort_fav_first', '⭐ Favourites first') }}</option>
        </select>
      </div>

      <div class="pmp-chips" :aria-label="t('pmp_quick_filters', 'Quick filters')">
        <button
          type="button"
          class="pmp-chip pmp-chip-verified"
          :class="{ on: statusFilter === 'verified', zero: chipVerifiedCount === 0 }"
          :title="t('pmp_status_verified', '⚡ Verified models only')"
          @click="statusFilter = statusFilter === 'verified' ? 'all' : 'verified'"
        >
          <span class="pmp-chip-icon">⚡</span>
          <span class="pmp-chip-label">{{ t('pmp_chip_verified', 'Verified') }}</span>
          <span class="pmp-chip-count">{{ chipVerifiedCount }}</span>
        </button>
        <button
          type="button"
          class="pmp-chip pmp-chip-fav"
          :class="{ on: onlyFilter === 'fav', zero: chipFavCount === 0 }"
          :title="t('pmp_only_fav', 'Favourites only')"
          @click="onlyFilter = onlyFilter === 'fav' ? 'all' : 'fav'"
        >
          <span class="pmp-chip-icon">⭐</span>
          <span class="pmp-chip-label">{{ t('pmp_chip_fav', 'Favourites') }}</span>
          <span class="pmp-chip-count">{{ chipFavCount }}</span>
        </button>
        <button
          type="button"
          class="pmp-chip pmp-chip-free"
          :class="{ on: tierFilter === 'free' || tierFilter === 'local', zero: chipFreeCount === 0 }"
          :title="t('pmp_tier_free', 'Free models only')"
          @click="tierFilter = tierFilter === 'free' || tierFilter === 'local' ? 'all' : (isLocalProvider ? 'local' : 'free')"
        >
          <span class="pmp-chip-icon">🆓</span>
          <span class="pmp-chip-label">{{ t('pmp_chip_free', 'Free') }}</span>
          <span class="pmp-chip-count">{{ chipFreeCount }}</span>
        </button>
        <button
          type="button"
          class="pmp-chip pmp-chip-vision"
          :class="{ on: typeFilter === 'vision', zero: chipVisionCount === 0 }"
          :title="t('pmp_type_vision', 'Vision capable models only')"
          @click="typeFilter = typeFilter === 'vision' ? 'all' : 'vision'"
        >
          <span class="pmp-chip-icon">👁</span>
          <span class="pmp-chip-label">{{ t('pmp_chip_vision', 'Vision') }}</span>
          <span class="pmp-chip-count">{{ chipVisionCount }}</span>
        </button>
        <button
          type="button"
          class="pmp-chip pmp-chip-nsfw"
          :class="{ on: contentFilter === 'nsfw', zero: chipNsfwCount === 0 }"
          :title="t('pmp_content_nsfw', 'Uncensored (NSFW) models only')"
          @click="contentFilter = contentFilter === 'nsfw' ? 'all' : 'nsfw'"
        >
          <span class="pmp-chip-icon">🔞</span>
          <span class="pmp-chip-label">{{ t('pmp_chip_nsfw', 'NSFW') }}</span>
          <span class="pmp-chip-count">{{ chipNsfwCount }}</span>
        </button>
        <button
          v-if="hasActiveFilters"
          type="button"
          class="pmp-chip pmp-chip-reset"
          :title="t('pmp_reset_filters', 'Reset all active filters and search')"
          @click="resetAllFilters"
        >
          <span class="pmp-chip-icon">✕</span>
          <span class="pmp-chip-label">{{ t('pmp_reset', 'Reset') }}</span>
        </button>
      </div>

      <span class="pmp-sp" />

      <span class="pmp-status">
        <span v-if="isLoading" class="pmp-badge loading">⏳ {{ t('pmp_loading', 'Loading…') }}</span>
        <span v-else-if="probe && probe.status && probe.status !== 'available'" class="pmp-badge error">
          ⚠️ {{ probe.message || probe.status }}
        </span>
        <span v-else class="pmp-badge online">● {{ t('pmp_online', 'Online') }}</span>
        <span v-if="ageLabel" class="pmp-age">{{ ageLabel }}</span>
      </span>
      <FilButton
        variant="sm"
        :label="t('pmp_refresh', '↻ Refresh')"
        :loading="isLoading"
        :title="t('tt_refresh', 'Reload models list')"
        @click="loadCurrentProviderModels(true)"
      />
    </template>

    <template #detail>
      <div v-if="!selectedModel" class="pmp-det-empty">
        {{ t('pmp_pick_to_see', 'Pick a model to see what it is.') }}
      </div>
      <div v-else class="pmp-det">
        <div class="pmp-det-provider">{{ PROVIDER_LABEL[selectedProvider] ?? selectedProvider }}</div>
        <!-- The full id, wrapped rather than clipped: this is the one place it
             has to be readable in full, and model names run very long. -->
        <div class="pmp-det-id">{{ selectedModel }}</div>
        <div class="pmp-det-tags">
          <span v-for="tag in detailTags" :key="tag.label" class="pmp-det-tag" :class="tag.tone">{{ tag.label }}</span>
        </div>
        <div class="pmp-det-acts">
          <FilButton
            variant="sm"
            :label="starred(selectedModel) ? t('pmp_unstar', '★ Remove from favourites') : t('pmp_star', '☆ Add to favourites')"
            @click="toggleStar(selectedModel)"
          />
          <FilButton variant="sm" :label="t('pmp_copy_id', '⧉ Copy id')" @click="copyModelId" />
        </div>
      </div>
    </template>

    <template #footer>
      <FilButton
        :label="t('pmp_cancel', 'Cancel')"
        :title="t('pmp_cancel_tt', 'Close without changing the model')"
        @click="isOpen = false"
      />
      <FilButton
        variant="accent"
        :label="t('pmp_apply', '✔ Use this model')"
        :title="t('pmp_apply_tt', 'Use the selected model')"
        :disabled="!selectedModel"
        @click="confirmSelection()"
      />
    </template>
  </FilBrowser>
</template>

<style scoped>
/* ── sort & quick chips in toolbar ── */
.pmp-sort {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.pmp-sort-select {
  height: var(--fil-control-h);
  padding: 0 8px;
  background: var(--fil-panel-alt);
  border: 1px solid var(--fil-border);
  border-radius: var(--fil-field-radius);
  color: var(--fil-text);
  font: inherit;
  font-size: 11px;
  font-weight: 500;
  outline: none;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}
.pmp-sort-select:hover {
  border-color: var(--fil-accent);
}
.pmp-sort-select:focus {
  border-color: var(--fil-accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--fil-accent) 30%, transparent);
}

.pmp-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.pmp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: var(--fil-control-h);
  padding: 0 8px;
  background: var(--fil-panel-alt);
  border: 1px solid var(--fil-border);
  border-radius: var(--fil-field-radius);
  color: var(--fil-muted);
  font: inherit;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
  transition: all 0.15s ease;
}
.pmp-chip:hover {
  background: var(--fil-surface-2);
  color: var(--fil-text);
  border-color: color-mix(in srgb, var(--fil-border) 60%, var(--fil-text));
}
.pmp-chip.on {
  background: color-mix(in srgb, var(--fil-accent) 15%, transparent);
  border-color: var(--fil-accent);
  color: var(--fil-accent-text);
  box-shadow: 0 0 6px color-mix(in srgb, var(--fil-accent) 25%, transparent);
}
.pmp-chip.pmp-chip-verified.on {
  background: color-mix(in srgb, var(--fil-ok) 15%, transparent);
  border-color: var(--fil-ok);
  color: var(--fil-ok);
  box-shadow: 0 0 6px color-mix(in srgb, var(--fil-ok) 25%, transparent);
}
.pmp-chip.pmp-chip-fav.on {
  background: color-mix(in srgb, #f59e0b 15%, transparent);
  border-color: #f59e0b;
  color: #fbbf24;
  box-shadow: 0 0 6px color-mix(in srgb, #f59e0b 25%, transparent);
}
.pmp-chip.pmp-chip-free.on {
  background: color-mix(in srgb, var(--fil-ok) 15%, transparent);
  border-color: var(--fil-ok);
  color: var(--fil-ok);
  box-shadow: 0 0 6px color-mix(in srgb, var(--fil-ok) 25%, transparent);
}
.pmp-chip.pmp-chip-vision.on {
  background: color-mix(in srgb, var(--fil-accent) 18%, transparent);
  border-color: var(--fil-accent);
  color: var(--fil-accent-text);
  box-shadow: 0 0 6px color-mix(in srgb, var(--fil-accent) 25%, transparent);
}
.pmp-chip.pmp-chip-nsfw.on {
  background: color-mix(in srgb, var(--fil-warn) 15%, transparent);
  border-color: var(--fil-warn);
  color: var(--fil-warn);
  box-shadow: 0 0 6px color-mix(in srgb, var(--fil-warn) 25%, transparent);
}
.pmp-chip-icon {
  font-size: 11px;
}
.pmp-chip-count {
  font-size: 10px;
  font-weight: 600;
  opacity: 0.75;
  padding: 1px 5px;
  border-radius: 9px;
  background: var(--fil-surface-2);
  line-height: 1;
}
.pmp-chip.on .pmp-chip-count {
  background: rgba(255, 255, 255, 0.18);
  opacity: 1;
}
.pmp-chip.zero {
  opacity: 0.5;
}
.pmp-chip-reset {
  color: var(--fil-danger);
  border-color: color-mix(in srgb, var(--fil-danger) 40%, transparent);
}
.pmp-chip-reset:hover {
  background: color-mix(in srgb, var(--fil-danger) 15%, transparent);
  border-color: var(--fil-danger);
  color: var(--fil-danger);
}
.pmp-sp {
  flex: 1;
}

@media (max-width: 900px) {
  .pmp-chip-label {
    display: none;
  }
}

.pmp-status {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  font-size: 11px;
  white-space: nowrap;
}
.pmp-badge.online {
  color: var(--fil-ok);
}
.pmp-badge.loading {
  color: var(--fil-accent-text);
}
.pmp-badge.error {
  color: var(--fil-danger);
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pmp-age {
  color: var(--fil-muted);
  font-size: 10px;
}

.pmp-det-empty {
  color: var(--fil-muted);
  font-size: 12px;
  text-align: center;
  padding-top: 24px;
}
.pmp-det {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.pmp-det-provider {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--fil-muted);
}
.pmp-det-id {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
  color: var(--fil-text);
  overflow-wrap: anywhere;
}
.pmp-det-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.pmp-det-tag {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--fil-pill-bg);
  color: var(--fil-muted);
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
}
.pmp-det-tag.accent {
  background: color-mix(in srgb, var(--fil-accent) 18%, transparent);
  color: var(--fil-accent-text);
}
.pmp-det-tag.ok {
  background: color-mix(in srgb, var(--fil-ok) 18%, transparent);
  color: var(--fil-ok);
}
.pmp-det-acts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
}
</style>
