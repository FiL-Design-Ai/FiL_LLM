import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { nextTick } from "vue";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import ProviderModelPickerVue from "@/components/nodes/ProviderModelPicker.vue";
import { useProviderStore } from "@/stores/providerStore";
import { _resetFavourites } from "@/stores/modelFavourites";
import { _resetRecents, recentsFor } from "@/stores/browserRecents";

/**
 * `FilBrowser` teleports to `document.body`, so a plain `wrapper.find` never
 * sees any of this — every query goes through the document, and every test
 * unmounts so the teleported nodes do not leak into the next one.
 */
function modelCard(name: string): HTMLElement {
  const cards = Array.from(document.querySelectorAll<HTMLElement>(".fb-card"));
  const card = cards.find((c) => c.textContent?.includes(name));
  if (!card) throw new Error(`no model card for "${name}"`);
  return card;
}

function starFor(name: string): HTMLElement {
  const star = modelCard(name).closest(".fb-item")?.querySelector<HTMLElement>(".fb-star");
  if (!star) throw new Error(`no favourite button for "${name}"`);
  return star;
}

/** A left-column row, by the text on it. */
function sidebarRow(text: string): HTMLElement {
  const rows = Array.from(document.querySelectorAll<HTMLElement>(".fb-row"));
  const row = rows.find((r) => r.textContent?.includes(text));
  if (!row) throw new Error(`no sidebar row for "${text}"`);
  return row;
}

function footerButton(text: string): HTMLButtonElement {
  const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>(".fb-foot button"));
  const btn = buttons.find((b) => b.textContent?.includes(text));
  if (!btn) throw new Error(`no footer button for "${text}"`);
  return btn;
}

function cardCount(): number {
  return document.querySelectorAll(".fb-card").length;
}

function seedModels(
  store: ReturnType<typeof useProviderStore>,
  provider: string,
  list: string[],
  visionModels: string[] = [],
  nsfwModels: string[] = [],
  verifiedModels: string[] = [],
) {
  store.modelsByProvider = {
    ...store.modelsByProvider,
    [provider]: { list, visionModels, nsfwModels, verifiedModels, cachedAt: Date.now(), loading: false },
  };
}

let wrapper: VueWrapper | null = null;

async function openWith(
  provider: string,
  list: string[],
  visionModels: string[] = [],
  nsfwModels: string[] = [],
  verifiedModels: string[] = [],
) {
  wrapper = mount(ProviderModelPickerVue, { props: { open: false, provider, model: "" } });
  seedModels(useProviderStore(), provider, list, visionModels, nsfwModels, verifiedModels);
  await wrapper.setProps({ open: true });
  await nextTick();
  return wrapper;
}

// The panel deliberately keeps its filters across opens, so one test's filter
// would survive into the next within the same jsdom window.
beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  _resetFavourites();
  _resetRecents();
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  document.body.innerHTML = "";
});

describe("ProviderModelPicker visibility", () => {
  it("renders nothing when closed", () => {
    wrapper = mount(ProviderModelPickerVue, { props: { open: false, provider: "ollama", model: "" } });
    expect(document.querySelector(".fb-win")).toBeNull();
  });

  it("renders the model list once opened", async () => {
    await openWith("ollama", ["llama3", "llava"]);
    expect(document.querySelector(".fb-win")).not.toBeNull();
    expect(modelCard("llama3")).toBeTruthy();
    expect(modelCard("llava")).toBeTruthy();
  });
});

describe("ProviderModelPicker search and filters", () => {
  it("filters the list by the search box", async () => {
    await openWith("openrouter", ["gpt-4o", "gpt-4o:free", "claude-3-haiku"]);
    const search = document.querySelector<HTMLInputElement>(".fb-search-input")!;
    search.value = "claude";
    search.dispatchEvent(new Event("input"));
    await nextTick();

    expect(cardCount()).toBe(1);
    expect(modelCard("claude-3-haiku")).toBeTruthy();
  });

  // The reason search became ranking rather than filtering: the exact name has
  // to come first, whatever order the provider listed things in.
  it("puts an exact name at the top of the results", async () => {
    await openWith("openrouter", ["gpt-4o-mini-audio-preview", "chatgpt-4o-latest", "gpt-4o"]);
    const search = document.querySelector<HTMLInputElement>(".fb-search-input")!;
    search.value = "gpt-4o";
    search.dispatchEvent(new Event("input"));
    await nextTick();

    const first = document.querySelectorAll<HTMLElement>(".fb-card")[0];
    expect(first.textContent).toContain("gpt-4o");
    expect(first.textContent).not.toContain("mini");
  });

  it("shows a no-match message for a query nothing satisfies", async () => {
    await openWith("openrouter", ["gpt-4o"]);
    const search = document.querySelector<HTMLInputElement>(".fb-search-input")!;
    search.value = "does-not-exist";
    search.dispatchEvent(new Event("input"));
    await nextTick();

    expect(cardCount()).toBe(0);
    expect(document.querySelector(".fb-empty")).not.toBeNull();
  });

  it("splits free vs paid OpenRouter models by tier chip", async () => {
    await openWith("openrouter", ["gpt-4o", "gpt-4o:free"]);
    const freeChip = document.querySelector<HTMLButtonElement>(".pmp-chip-free")!;
    expect(freeChip).not.toBeNull();
    freeChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    expect(cardCount()).toBe(1);
    expect(document.querySelectorAll<HTMLElement>(".fb-card")[0].textContent).toContain("gpt-4o:free");
  });

  it("marks Hugging Face models as free tier on quick chip", async () => {
    await openWith("huggingface", ["Qwen/Qwen2.5-VL-72B-Instruct"]);
    const freeChip = document.querySelector<HTMLButtonElement>(".pmp-chip-free")!;
    expect(freeChip.querySelector(".pmp-chip-count")?.textContent).toBe("1");
  });

  it("filters to vision-tagged models only via quick chip", async () => {
    await openWith("openrouter", ["gpt-4o", "text-only-model"], ["gpt-4o"]);
    const visionChip = document.querySelector<HTMLButtonElement>(".pmp-chip-vision")!;
    visionChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    expect(cardCount()).toBe(1);
    expect(modelCard("gpt-4o")).toBeTruthy();
  });

  // Clicking the chip that is already on turns it back off, so a facet never
  // needs an "All" button to be hunted for.
  it("turns a filter off when quick chip is clicked again", async () => {
    await openWith("openrouter", ["gpt-4o", "text-only-model"], ["gpt-4o"]);
    const vision = document.querySelector<HTMLButtonElement>(".pmp-chip-vision")!;
    vision.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(cardCount()).toBe(1);

    vision.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(cardCount()).toBe(2);
  });

  it("sidebar contains only providers list and local provider models count as free", async () => {
    await openWith("ollama", ["llama3"]);
    const headings = Array.from(document.querySelectorAll(".fb-grouphead")).map((h) => h.textContent?.trim());
    expect(headings).toEqual(["Provider"]);

    const rows = Array.from(document.querySelectorAll(".fb-row")).map((r) => r.textContent ?? "");
    expect(rows.some((r) => r.includes("Ollama"))).toBe(true);
    expect(rows.some((r) => r.includes("OpenRouter"))).toBe(true);
    expect(rows.some((r) => r.includes("Status"))).toBe(false);
    expect(rows.some((r) => r.includes("Tier"))).toBe(false);

    const freeChip = document.querySelector<HTMLButtonElement>(".pmp-chip-free")!;
    expect(freeChip.querySelector(".pmp-chip-count")?.textContent).toBe("1");
  });

  it("displays provider model count in sidebar without interference from toolbar chips", async () => {
    await openWith("openrouter", ["a-vision:free", "b-vision", "c-text:free"], ["a-vision:free", "b-vision"]);
    const freeChip = document.querySelector<HTMLButtonElement>(".pmp-chip-free")!;
    freeChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    expect(cardCount()).toBe(2);
    expect(sidebarRow("OpenRouter").querySelector(".fb-row-count")?.textContent).toBe("3");
  });
});

describe("ProviderModelPicker favourites and recents", () => {
  it("starring a model persists across the favourites filter", async () => {
    await openWith("ollama", ["llama3", "llava"]);
    starFor("llama3").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(starFor("llama3").classList.contains("on")).toBe(true);

    const favChip = document.querySelector<HTMLButtonElement>(".pmp-chip-fav")!;
    favChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(cardCount()).toBe(1);
    expect(modelCard("llama3")).toBeTruthy();
  });

  // Recorded on APPLY, not on highlight: walking the list with the arrow keys
  // would otherwise leave nothing but the last thing scrolled past.
  it("records a model as recent only once it is applied", async () => {
    await openWith("ollama", ["llama3", "llava"]);
    modelCard("llava").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(recentsFor("models:ollama")).toEqual([]);

    footerButton("Use this model").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(recentsFor("models:ollama")).toContain("llava");
  });
});

describe("ProviderModelPicker selection", () => {
  it("clicking a card selects it, and Apply emits provider+model then closes", async () => {
    await openWith("ollama", ["llama3", "llava"]);
    modelCard("llava").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(modelCard("llava").classList.contains("selected")).toBe(true);

    footerButton("Use this model").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    expect(wrapper!.emitted("select")).toEqual([[{ provider: "ollama", model: "llava" }]]);
    expect(wrapper!.emitted("update:open")?.at(-1)).toEqual([false]);
  });

  it("a double click chooses straight away", async () => {
    await openWith("ollama", ["llama3", "llava"]);
    modelCard("llava").dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    await nextTick();
    expect(wrapper!.emitted("select")).toEqual([[{ provider: "ollama", model: "llava" }]]);
  });

  it("Cancel closes without emitting a selection", async () => {
    await openWith("ollama", ["llama3"]);
    footerButton("Cancel").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    expect(wrapper!.emitted("select")).toBeUndefined();
    expect(wrapper!.emitted("update:open")?.at(-1)).toEqual([false]);
  });

  it("Apply stays disabled with nothing selected", async () => {
    await openWith("groq", []);
    expect(footerButton("Use this model").disabled).toBe(true);
    expect(document.querySelector(".fb-empty")).not.toBeNull();
  });

  it("switching providers picks that provider's first cached model", async () => {
    const store = useProviderStore();
    wrapper = mount(ProviderModelPickerVue, { props: { open: false, provider: "ollama", model: "" } });
    seedModels(store, "ollama", ["llama3"]);
    seedModels(store, "groq", ["mixtral-8x7b"]);
    await wrapper.setProps({ open: true });
    await nextTick();

    sidebarRow("Groq").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(modelCard("mixtral-8x7b").classList.contains("selected")).toBe(true);
  });

  it("shows the full model id in the detail pane", async () => {
    await openWith("openrouter", ["meta-llama/llama-3.1-70b-instruct"]);
    modelCard("llama-3.1-70b").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(document.querySelector(".pmp-det-id")?.textContent).toBe("meta-llama/llama-3.1-70b-instruct");
  });

  it("badges NSFW models and filters by uncensored content", async () => {
    await openWith("openrouter", ["magnum-v4-72b", "gpt-4o"], [], ["magnum-v4-72b"]);
    expect(cardCount()).toBe(2);
    expect(modelCard("magnum-v4-72b").textContent).toContain("🔞 NSFW");
    expect(modelCard("gpt-4o").textContent).not.toContain("🔞 NSFW");

    const nsfwChip = document.querySelector<HTMLButtonElement>(".pmp-chip-nsfw")!;
    nsfwChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(cardCount()).toBe(1);
    expect(modelCard("magnum-v4-72b")).not.toBeNull();
  });

  it("badges verified models and filters by verified status", async () => {
    await openWith("groq", ["qwen3.8-27b", "broken-model"], [], [], ["qwen3.8-27b"]);
    expect(cardCount()).toBe(2);
    expect(modelCard("qwen3.8-27b").textContent).toContain("⚡ Verified");
    expect(modelCard("broken-model").textContent).not.toContain("⚡ Verified");

    const verifiedChip = document.querySelector<HTMLButtonElement>(".pmp-chip-verified")!;
    verifiedChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(cardCount()).toBe(1);
    expect(modelCard("qwen3.8-27b")).not.toBeNull();
  });

  it("smart sort puts verified and favourite models ahead of unverified ones", async () => {
    await openWith("groq", ["zebra-plain", "middle-verified", "alpha-plain"], [], [], ["middle-verified"]);
    const cards = Array.from(document.querySelectorAll<HTMLElement>(".fb-card"));
    // In smart mode, verified model "middle-verified" must be first, followed by alphabetical unverified
    expect(cards[0].textContent).toContain("middle-verified");
    expect(cards[1].textContent).toContain("alpha-plain");
    expect(cards[2].textContent).toContain("zebra-plain");
  });

  it("quick filter chips toggle filters directly from the toolbar", async () => {
    await openWith("groq", ["model-a", "model-b"], ["model-a"], [], ["model-a"]);
    expect(cardCount()).toBe(2);

    // Click verified chip
    const verifiedChip = document.querySelector<HTMLButtonElement>(".pmp-chip-verified")!;
    expect(verifiedChip).not.toBeNull();
    verifiedChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    expect(verifiedChip.classList.contains("on")).toBe(true);
    expect(cardCount()).toBe(1);
    expect(modelCard("model-a")).not.toBeNull();

    // Toggle off
    verifiedChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(verifiedChip.classList.contains("on")).toBe(false);
    expect(cardCount()).toBe(2);
  });

  it("allows switching sort mode to alphabetical name-asc and name-desc", async () => {
    await openWith("groq", ["zebra-plain", "middle-verified", "alpha-plain"], [], [], ["middle-verified"]);
    const select = document.querySelector<HTMLSelectElement>(".pmp-sort-select")!;
    expect(select).not.toBeNull();

    select.value = "name-asc";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await nextTick();

    let cards = Array.from(document.querySelectorAll<HTMLElement>(".fb-card"));
    expect(cards[0].textContent).toContain("alpha-plain");
    expect(cards[1].textContent).toContain("middle-verified");
    expect(cards[2].textContent).toContain("zebra-plain");

    select.value = "name-desc";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await nextTick();

    cards = Array.from(document.querySelectorAll<HTMLElement>(".fb-card"));
    expect(cards[0].textContent).toContain("zebra-plain");
    expect(cards[1].textContent).toContain("middle-verified");
    expect(cards[2].textContent).toContain("alpha-plain");
  });

  it("displays accurate counts on quick chips and provides a one-click reset button", async () => {
    await openWith("groq", ["model-v", "model-plain"], ["model-v"], [], ["model-v"]);
    const verifiedChip = document.querySelector<HTMLButtonElement>(".pmp-chip-verified")!;
    expect(verifiedChip.querySelector(".pmp-chip-count")?.textContent).toBe("1");

    // Initially, no reset button since all filters are "all" and search is empty
    expect(document.querySelector(".pmp-chip-reset")).toBeNull();

    // Turn on verified filter
    verifiedChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    // Reset button should now be visible
    const resetBtn = document.querySelector<HTMLButtonElement>(".pmp-chip-reset")!;
    expect(resetBtn).not.toBeNull();
    expect(cardCount()).toBe(1);

    // Click reset button
    resetBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();

    // Filters should be reset, reset button disappears, both cards visible again
    expect(document.querySelector(".pmp-chip-reset")).toBeNull();
    expect(cardCount()).toBe(2);
  });
});
