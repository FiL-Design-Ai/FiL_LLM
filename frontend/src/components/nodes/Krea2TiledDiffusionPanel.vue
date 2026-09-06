<script setup lang="ts">
/**
 * FiLKrea2TiledDiffusion — Krea 2 Ultra-HD Tiled Diffusion panel.
 * Custom Cyberpunk/FiL Design UI with sections, sliders, and socket awareness.
 */
import { computed } from "vue";
import { FilSlider, FilNumberInput, FilSelect, FilSection, FilTextArea } from "@/components/widgets";
import { useI18n } from "@/composables/useI18n";
import { findFilWidget } from "@/nodes2/util";
import { useWidgetSockets } from "@/composables/useWidgetSockets";
import { KREA2_SOCKET_INPUTS } from "@/nodes2/nodes/krea2_tiled_diffusion";
import type { FilNodeState } from "@/nodes2/filState";

const props = defineProps<{ state: FilNodeState }>();
const { t } = useI18n();

const { setFieldEl, isLinked } = useWidgetSockets(props.state, KREA2_SOCKET_INPUTS);
const linkedTip = (name: string, own: string) =>
  isLinked(name) ? t("fld_linked_tt", "Driven by the connected input — disconnect it to edit here.") : own;

function numberField(name: string, fallback: number) {
  return computed({
    get: () => {
      const raw = Number(props.state.nodeState[name] ?? props.state.initialValues[name] ?? fallback);
      return Number.isFinite(raw) ? raw : fallback;
    },
    set: (v: number) => { props.state.nodeState[name] = v; },
  });
}

function stringField(name: string, fallback: string) {
  return computed({
    get: () => String(props.state.nodeState[name] ?? props.state.initialValues[name] ?? fallback),
    set: (v: string) => { props.state.nodeState[name] = v; },
  });
}

function comboOptions(name: string, fallback: string[]): string[] {
  const node = props.state.node;
  const w = node ? findFilWidget(node, name) : null;
  const vals = (w as { options?: { values?: unknown } } | null)?.options?.values;
  return Array.isArray(vals) && vals.length ? (vals as string[]) : fallback;
}

function isCollapsed(section: string): boolean {
  const stored = (props.state.ui as Record<string, unknown>)[`collapsed_${section}`];
  return stored === undefined ? false : Boolean(stored);
}
function setCollapsed(section: string, collapsed: boolean) {
  (props.state.ui as Record<string, unknown>)[`collapsed_${section}`] = collapsed;
}

// Fields
const prompt = stringField("prompt", "hyperrealistic, highly detailed, 8k uhd");
const seed = numberField("seed", 0);
const controlAfterGenerate = stringField("control_after_generate", "randomize");
const steps = numberField("steps", 8);
const denoise = numberField("denoise", 0.22);
const visionWeight = numberField("vision_weight", 1.40);
const upscaleFactor = numberField("upscale_factor", 2.0);
const tileGrid = stringField("tile_grid", "auto");
const tileOverlap = stringField("tile_overlap", "auto (256px)");
const tileBatchSize = numberField("tile_batch_size", 1);
const textureInjection = numberField("texture_injection", 0.20);
const colorMatch = stringField("color_match", "none");
const identityLoraName = stringField("identity_lora_name", "none");
const identityLoraStrength = numberField("identity_lora_strength", 1.0);

// Options from widgets
const controlOptions = computed(() => comboOptions("control_after_generate", ["fixed", "increment", "decrement", "randomize"]));
const tileGridOptions = computed(() => comboOptions("tile_grid", ["auto", "1x1", "1x2", "2x1", "2x2", "2x3", "3x2", "3x3", "4x4"]));
const tileOverlapOptions = computed(() => comboOptions("tile_overlap", ["auto (256px)", "128px", "192px", "256px", "384px", "512px"]));
const colorMatchOptions = computed(() => comboOptions("color_match", ["none", "luminance", "wavelet"]));
const loraOptions = computed(() => comboOptions("identity_lora_name", ["none"]));
</script>

<template>
  <div class="fil-krea2-root">
    <!-- Prompt Area -->
    <div class="fil-krea2-prompt-row">
      <FilTextArea
        :ref="(el: unknown) => setFieldEl('prompt', el)"
        v-model="prompt"
        :rows="3"
        :disabled="isLinked('prompt')"
        :label="t('krea2_p_prompt', '📝 Prompt')"
        :placeholder="t('krea2_prompt_ph', 'Describe details: hyperrealistic, 8k uhd, fine texture...')"
        :title="linkedTip('prompt', t('krea2_prompt', 'Positive prompt describing desired texture and detail.'))"
      />
    </div>

    <!-- Section 1: Sampling & Denoise -->
    <FilSection
      :title="t('krea2_sec_sampling', '⚡ Sampling & Noise')"
      :collapsed="isCollapsed('sampling')"
      @update:collapsed="(v: boolean) => setCollapsed('sampling', v)"
    >
      <div class="fil-krea2-grid">
        <FilNumberInput
          :ref="(el: unknown) => setFieldEl('steps', el)"
          v-model="steps"
          :min="1"
          :max="50"
          :step="1"
          :disabled="isLinked('steps')"
          :label="t('krea2_p_steps', '🪜 Steps')"
          inline-label
          :title="linkedTip('steps', t('krea2_steps', 'Sampling steps (8 is optimal for Krea2).'))"
        />
        <FilSlider
          :ref="(el: unknown) => setFieldEl('denoise', el)"
          :model-value="denoise"
          :min="0"
          :max="1"
          :step="0.01"
          :disabled="isLinked('denoise')"
          :label="t('krea2_p_denoise', '🌫️ Denoise')"
          inline-label
          :title="linkedTip('denoise', t('krea2_denoise', 'Denoising strength (0.20-0.25 recommended).'))"
          @update:model-value="(v: number) => (denoise = v)"
        />
      </div>

      <div class="fil-krea2-grid">
        <FilNumberInput
          :ref="(el: unknown) => setFieldEl('seed', el)"
          v-model="seed"
          :min="0"
          :max="0xFFFFFFFFFFFFFFFF"
          :step="1"
          :disabled="isLinked('seed')"
          :label="t('krea2_p_seed', '🌱 Seed')"
          inline-label
          :title="linkedTip('seed', t('krea2_seed', 'Random seed for diffusion noise.'))"
        />
        <FilSelect
          v-model="controlAfterGenerate"
          :options="controlOptions"
          :disabled="isLinked('seed')"
          :label="t('krea2_p_after_gen', '🔁 After generate')"
          inline-label
          :title="t('ksp_after_generate_tt', 'What ComfyUI does to the seed after queue.')"
        />
      </div>
    </FilSection>

    <!-- Section 2: Scale & Tiling -->
    <FilSection
      :title="t('krea2_sec_tiling', '📐 Scale & Tiling')"
      :collapsed="isCollapsed('tiling')"
      @update:collapsed="(v: boolean) => setCollapsed('tiling', v)"
    >
      <FilSlider
        :ref="(el: unknown) => setFieldEl('upscale_factor', el)"
        :model-value="upscaleFactor"
        :min="1"
        :max="8"
        :step="0.1"
        :disabled="isLinked('upscale_factor')"
        :label="t('krea2_p_factor', '🔍 Upscale Factor')"
        inline-label
        :title="linkedTip('upscale_factor', t('krea2_upscale_factor', 'Multiplier for target size (e.g. 2.0x).'))"
        @update:model-value="(v: number) => (upscaleFactor = v)"
      />

      <div class="fil-krea2-grid">
        <FilSelect
          :ref="(el: unknown) => setFieldEl('tile_grid', el)"
          v-model="tileGrid"
          :options="tileGridOptions"
          :disabled="isLinked('tile_grid')"
          :label="t('krea2_p_grid', '🔲 Tile Grid')"
          inline-label
          :title="linkedTip('tile_grid', t('krea2_tile_grid', 'Tiling layout (auto adapts to resolution).'))"
        />
        <FilSelect
          :ref="(el: unknown) => setFieldEl('tile_overlap', el)"
          v-model="tileOverlap"
          :options="tileOverlapOptions"
          :disabled="isLinked('tile_overlap')"
          :label="t('krea2_p_overlap', '🔲 Overlap')"
          inline-label
          :title="linkedTip('tile_overlap', t('krea2_tile_overlap', 'Overlap between neighbouring tiles.'))"
        />
      </div>

      <FilNumberInput
        :ref="(el: unknown) => setFieldEl('tile_batch_size', el)"
        v-model="tileBatchSize"
        :min="1"
        :max="8"
        :step="1"
        :disabled="isLinked('tile_batch_size')"
        :label="t('krea2_p_batch', '📦 Tile Batch Size')"
        inline-label
        :title="linkedTip('tile_batch_size', t('krea2_batch_size', 'Tiles evaluated in parallel per step.'))"
      />
    </FilSection>

    <!-- Section 3: Edge-Aware Texture & Refinement -->
    <FilSection
      :title="t('krea2_sec_refinement', '✨ Edge-Aware & Refinement')"
      :collapsed="isCollapsed('refinement')"
      @update:collapsed="(v: boolean) => setCollapsed('refinement', v)"
    >
      <FilSlider
        :ref="(el: unknown) => setFieldEl('texture_injection', el)"
        :model-value="textureInjection"
        :min="0"
        :max="1"
        :step="0.02"
        :disabled="isLinked('texture_injection')"
        :label="t('krea2_p_texture', '⚡ Edge Texture')"
        inline-label
        :title="linkedTip('texture_injection', t('krea2_texture_injection', 'Adaptive Sobel sharpness on edges without flat noise.'))"
        @update:model-value="(v: number) => (textureInjection = v)"
      />

      <FilSlider
        :ref="(el: unknown) => setFieldEl('vision_weight', el)"
        :model-value="visionWeight"
        :min="0"
        :max="3"
        :step="0.05"
        :disabled="isLinked('vision_weight')"
        :label="t('krea2_p_vision', '👁️ Vision Weight')"
        inline-label
        :title="linkedTip('vision_weight', t('krea2_vision_weight', 'Attention weight for image vision tokens.'))"
        @update:model-value="(v: number) => (visionWeight = v)"
      />

      <FilSelect
        :ref="(el: unknown) => setFieldEl('color_match', el)"
        v-model="colorMatch"
        :options="colorMatchOptions"
        :disabled="isLinked('color_match')"
        :label="t('krea2_p_colormatch', '🎨 Color Match')"
        inline-label
        :title="linkedTip('color_match', t('krea2_color_match', 'Locks color palette/tones to source image.'))"
      />

      <div class="fil-krea2-grid">
        <FilSelect
          :ref="(el: unknown) => setFieldEl('identity_lora_name', el)"
          v-model="identityLoraName"
          :options="loraOptions"
          :disabled="isLinked('identity_lora_name')"
          :label="t('krea2_p_lora', '🧬 LoRA')"
          inline-label
          :title="linkedTip('identity_lora_name', t('krea2_identity_lora_name', 'Optional identity LoRA.'))"
        />
        <FilSlider
          :ref="(el: unknown) => setFieldEl('identity_lora_strength', el)"
          :model-value="identityLoraStrength"
          :min="0"
          :max="2"
          :step="0.05"
          :disabled="isLinked('identity_lora_strength')"
          :label="t('krea2_p_lora_str', '⚖️ Strength')"
          inline-label
          :title="linkedTip('identity_lora_strength', t('krea2_identity_lora_strength', 'Weight of identity LoRA.'))"
          @update:model-value="(v: number) => (identityLoraStrength = v)"
        />
      </div>
    </FilSection>
  </div>
</template>

<style scoped>
.fil-krea2-root {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  box-sizing: border-box;
}

.fil-krea2-prompt-row {
  margin-bottom: 2px;
}

.fil-krea2-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
</style>
