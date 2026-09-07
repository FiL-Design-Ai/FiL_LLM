<script setup lang="ts">
/**
 * AssistSettingsModal — popup modal for tuning live prompt assist actions
 * (rephrase / densify / expand). Lets user pick style/atmosphere, creativity
 * (temperature), length/density, and target language, plus persist defaults
 * across new nodes or reset.
 */
import { computed } from "vue";
import FilModal from "./FilModal.vue";
import FilSegmented from "./FilSegmented.vue";
import FilButton from "./FilButton.vue";
import { useI18n } from "@/composables/useI18n";
import type { AssistSettings, AssistStyle, AssistLength, AssistLanguage } from "@/composables/useAssist";

const props = withDefaults(
  defineProps<{
    settings: AssistSettings;
    context?: "instruction" | "prompt";
  }>(),
  { context: "instruction" },
);

const emit = defineEmits<{
  (e: "save-default"): void;
  (e: "reset-defaults"): void;
}>();

const open = defineModel<boolean>("open", { default: false });
const { t } = useI18n();

const modalTitle = computed(() =>
  props.context === "prompt"
    ? t("pda_title_prompter", "Prompter Settings")
    : t("pda_title_director", "Director Instruction Settings"),
);

// Style / Tone options
const styleOptions: AssistStyle[] = ["neutral", "photorealism", "cinematic", "anime"];
const styleLabels = computed<Record<string, string>>(() => ({
  neutral: t("pda_style_neutral", "⚖️ Neutral"),
  photorealism: t("pda_style_photo", "📸 Photorealism"),
  cinematic: t("pda_style_cinema", "🎬 Cinematic"),
  anime: t("pda_style_anime", "🎌 Anime / Art"),
}));

const toneOptions: AssistStyle[] = ["precise", "creative", "minimal"];
const toneLabels = computed<Record<string, string>>(() => ({
  precise: t("pda_tone_precise", "🎯 Precise"),
  creative: t("pda_tone_creative", "🎨 Creative"),
  minimal: t("pda_tone_minimal", "⚡ Minimal"),
}));

// Length / Scope options
const lengthOptions: AssistLength[] = ["concise", "balanced", "detailed"];
const lengthLabels = computed<Record<string, string>>(() => ({
  concise: t("pda_len_concise", "⚡ Concise"),
  balanced: t("pda_len_balanced", "⚖️ Balanced"),
  detailed: t("pda_len_detailed", "🌌 Detailed"),
}));

const scopeOptions: AssistLength[] = ["targeted", "comprehensive"];
const scopeLabels = computed<Record<string, string>>(() => ({
  targeted: t("pda_scope_targeted", "🎯 Targeted"),
  comprehensive: t("pda_scope_comprehensive", "🌌 Comprehensive"),
}));

const langOptions: AssistLanguage[] = ["auto", "en", "ru"];
const langLabels = computed<Record<AssistLanguage, string>>(() => ({
  auto: t("pda_lang_auto", "🌐 Auto"),
  en: t("pda_lang_en", "🇬🇧 English"),
  ru: t("pda_lang_ru", "🇷🇺 Русский"),
}));

function onSaveDefault() {
  emit("save-default");
}

function onResetDefaults() {
  emit("reset-defaults");
}
</script>

<template>
  <FilModal v-model:open="open" :title="modalTitle" width="480px">
    <div class="fil-asm-body">
      <!-- Section 1: Style & Atmosphere (Prompter) OR Instruction Tone (Director) -->
      <div class="fil-asm-section">
        <div class="fil-asm-label-row">
          <span class="fil-asm-section-label">
            {{ context === "prompt" ? t("pda_sec_style", "Style & Atmosphere") : t("pda_sec_tone", "Instruction Tone") }}
          </span>
        </div>
        <FilSegmented
          v-if="context === 'prompt'"
          v-model="props.settings.style"
          :options="styleOptions"
          :option-labels="styleLabels"
          :title="t('pda_sec_style', 'Style & Atmosphere')"
          class="fil-asm-segmented-full"
        />
        <FilSegmented
          v-else
          v-model="props.settings.style"
          :options="toneOptions"
          :option-labels="toneLabels"
          :title="t('pda_sec_tone', 'Instruction Tone')"
          class="fil-asm-segmented-full"
        />
      </div>

      <!-- Creativity / Temperature Slider -->
      <div class="fil-asm-section">
        <div class="fil-asm-label-row">
          <span class="fil-asm-section-label">{{ t('pda_sec_creativity', 'Creativity (Temperature)') }}</span>
          <span class="fil-asm-badge">{{ props.settings.creativity.toFixed(2) }}</span>
        </div>
        <div class="fil-asm-slider-wrap">
          <input
            type="range"
            class="fil-asm-range"
            min="0.1"
            max="1.0"
            step="0.05"
            v-model.number="props.settings.creativity"
          />
          <div class="fil-asm-slider-hints">
            <span>0.1 ({{ t('pda_cr_exact', 'Exact') }})</span>
            <span>0.7 ({{ t('pda_cr_balanced', 'Balanced') }})</span>
            <span>1.0 ({{ t('pda_cr_creative', 'Creative') }})</span>
          </div>
        </div>
      </div>

      <!-- Section 3: Length & Detail (Prompter) OR Editing Scope (Director) -->
      <div class="fil-asm-section">
        <div class="fil-asm-label-row">
          <span class="fil-asm-section-label">
            {{ context === "prompt" ? t("pda_sec_length", "Length & Detail") : t("pda_sec_scope", "Editing Scope") }}
          </span>
        </div>
        <FilSegmented
          v-if="context === 'prompt'"
          v-model="props.settings.length"
          :options="lengthOptions"
          :option-labels="lengthLabels"
          :title="t('pda_sec_length', 'Length & Detail')"
          class="fil-asm-segmented-full"
        />
        <FilSegmented
          v-else
          v-model="props.settings.length"
          :options="scopeOptions"
          :option-labels="scopeLabels"
          :title="t('pda_sec_scope', 'Editing Scope')"
          class="fil-asm-segmented-full"
        />
      </div>

      <!-- Target Language section -->
      <div class="fil-asm-section">
        <div class="fil-asm-label-row">
          <span class="fil-asm-section-label">
            {{ context === "prompt" ? t("pda_sec_lang", "Output Language") : t("pda_sec_inst_lang", "Instruction Language") }}
          </span>
        </div>
        <FilSegmented
          v-model="props.settings.target_language"
          :options="langOptions"
          :option-labels="langLabels"
          :title="context === 'prompt' ? t('pda_sec_lang', 'Output Language') : t('pda_sec_inst_lang', 'Instruction Language')"
          class="fil-asm-segmented-full"
        />
      </div>

      <!-- Footer action bar -->
      <div class="fil-asm-footer">
        <div class="fil-asm-footer-left">
          <FilButton
            variant="sm"
            :label="t('pda_save_default', 'Save as Default')"
            :title="t('pda_saved_default', 'Assist settings saved as default for new nodes.')"
            @click="onSaveDefault"
          />
          <FilButton
            variant="sm"
            :label="t('pda_reset', 'Reset')"
            :title="t('pda_reset_defaults', 'Assist settings reset to factory defaults.')"
            @click="onResetDefaults"
          />
        </div>
        <FilButton
          variant="accent"
          :label="t('pda_close', 'Done')"
          @click="open = false"
        />
      </div>
    </div>
  </FilModal>
</template>

<style scoped>
.fil-asm-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  color: var(--fil-text, #e2e8f0);
  font-family: ui-sans-serif, system-ui, sans-serif;
}

.fil-asm-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.fil-asm-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.fil-asm-section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--fil-muted, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.fil-asm-segmented-full {
  display: block;
  width: 100%;
}

.fil-asm-segmented-full :deep(.fil-w-pill) {
  grid-column: 1 / -1;
  width: 100%;
  display: flex;
}

.fil-asm-segmented-full :deep(.fil-w-seg) {
  flex: 1 1 0;
  min-width: 0;
  padding: 0 4px;
  font-size: 11.5px;
  justify-content: center;
  white-space: nowrap;
}

.fil-asm-badge {
  font-size: 11px;
  font-weight: 700;
  font-family: ui-monospace, monospace;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--fil-glass-bg, rgba(50, 80, 120, 0.25));
  border: 1px solid var(--fil-glass-border, rgba(0, 150, 200, 0.3));
  color: var(--fil-accent, #38bdf8);
}

.fil-asm-slider-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.fil-asm-range {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: var(--fil-input-bg, rgba(20, 30, 45, 0.6));
  outline: none;
  border: 1px solid var(--fil-glass-border, rgba(0, 150, 200, 0.2));
  cursor: pointer;
}

.fil-asm-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--fil-accent, #38bdf8);
  cursor: pointer;
  box-shadow: 0 0 8px var(--fil-accent, #38bdf8);
  transition: transform 0.1s ease;
}

.fil-asm-range::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.fil-asm-range::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--fil-accent, #38bdf8);
  border: none;
  cursor: pointer;
  box-shadow: 0 0 8px var(--fil-accent, #38bdf8);
  transition: transform 0.1s ease;
}

.fil-asm-range::-moz-range-thumb:hover {
  transform: scale(1.2);
}

.fil-asm-slider-hints {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--fil-muted, #94a3b8);
  opacity: 0.75;
}

.fil-asm-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--fil-glass-border, rgba(0, 150, 200, 0.15));
}

.fil-asm-footer-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
