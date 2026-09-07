"""FiL Krea 2 Tiled Diffusion — V3 ComfyNode.

Performs seamless large-scale ultra-high-definition diffusion upscaling
using overlapping tiles, RoPE canvas coordinate offsets, per-tile vision
conditioning, Edge-Aware Adaptive Texture Injection, and color lock.
"""
from __future__ import annotations

import logging

import torch
import folder_paths


from comfy_api.latest import io

from ..common.brand import CATEGORY_IMAGE
from ..common.localization import t as _t
from ..common.krea2_engine import (
    ALL_TILE_GRIDS,
    DEFAULT_TILE_OVERLAP_PIXELS,
    LATENT_SCALE,
    TileRopeOffsetHolder,
    apply_color_matching,
    apply_edge_aware_texture,
    build_post_input_rope_offset_patch,
    calculate_tiles,
    decode_vae_safely,
    denoise_latent_as_fused_tiles,
    scale_image_by_factor,
)

logger = logging.getLogger(__name__)

TILE_OVERLAP_OPTIONS = ["auto (256px)", "128px", "192px", "256px", "384px", "512px"]
COLOR_MATCH_OPTIONS = ["none", "luminance", "wavelet"]


def _get_lora_list() -> list[str]:
    try:
        filenames = folder_paths.get_filename_list("loras")
        return ["none"] + sorted(filenames)
    except Exception:
        return ["none"]


def _parse_overlap_pixels(overlap_str: str) -> int:
    if "auto" in overlap_str:
        return DEFAULT_TILE_OVERLAP_PIXELS
    clean = overlap_str.replace("px", "").strip()
    try:
        return int(clean)
    except ValueError:
        return DEFAULT_TILE_OVERLAP_PIXELS


class FiLKrea2TiledDiffusion(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        lora_list = _get_lora_list()
        return io.Schema(
            node_id="FiLKrea2TiledDiffusion",
            display_name="📐 Krea 2 Tiled Diffusion",
            category=CATEGORY_IMAGE,
            description="📐 FiL Krea 2 Tiled Diffusion — ultra-high-definition tiled upscale with RoPE canvas coordinates, edge-aware adaptive texture and color matching.",
            inputs=[
                io.Model.Input("model", tooltip=_t("krea2_model", "Krea2 or compatible diffusion UNet/DiT model.")),
                io.Clip.Input("clip", tooltip=_t("krea2_clip", "CLIP/Vision text encoder (e.g. Qwen3-VL).")),
                io.Vae.Input("vae", tooltip=_t("krea2_vae", "VAE model for latent encode/decode.")),
                io.Image.Input("image", optional=True,
                               tooltip=_t("krea2_image", "Input image to upscale. Optional if latent is connected instead.")),
                io.UpscaleModel.Input("upscale_model", optional=True,
                                      tooltip=_t("krea2_upscale_model", "Optional AI upscale model (e.g. DAT-2, ESRGAN) to produce crisp geometry prior to diffusion.")),
                io.Latent.Input("latent", optional=True,
                                tooltip=_t("krea2_latent", "Optional direct latent input. If provided with image, geometry aligns with image.")),
                io.String.Input("prompt", multiline=True, default="hyperrealistic, highly detailed, 8k uhd",
                                tooltip=_t("krea2_prompt", "Positive prompt describing desired texture and detail.")),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True,
                             tooltip=_t("krea2_seed", "Random seed for diffusion noise.")),
                io.Int.Input("steps", default=8, min=1, max=50,
                             tooltip=_t("krea2_steps", "Sampling steps (8 steps is optimal for Krea2).")),
                io.Float.Input("denoise", default=0.22, min=0.0, max=1.0, step=0.01, display_mode=io.NumberDisplay.slider,
                               tooltip=_t("krea2_denoise", "Denoising strength. 0.20-0.25 recommended for faithful upscale.")),
                io.Float.Input("vision_weight", default=1.40, min=0.0, max=3.0, step=0.05,
                               tooltip=_t("krea2_vision_weight", "Attention weight for image vision tokens.")),
                io.Float.Input("upscale_factor", default=2.0, min=1.0, max=8.0, step=0.1, display_mode=io.NumberDisplay.slider,
                               tooltip=_t("krea2_upscale_factor", "Target upscale multiplier (e.g. 2.0x).")),
                io.Combo.Input("tile_grid", options=ALL_TILE_GRIDS, default="auto",
                               tooltip=_t("krea2_tile_grid", "Tiling layout. 'auto' computes optimal grid based on resolution.")),
                io.Combo.Input("tile_overlap", options=TILE_OVERLAP_OPTIONS, default="auto (256px)",
                               tooltip=_t("krea2_tile_overlap", "Pixel overlap between neighbouring tiles.")),
                io.Int.Input("tile_batch_size", default=1, min=1, max=8,
                             tooltip=_t("krea2_batch_size", "Tiles evaluated in parallel per step.")),
                io.Float.Input("texture_injection", default=0.20, min=0.0, max=1.0, step=0.02, display_mode=io.NumberDisplay.slider,
                               tooltip=_t("krea2_texture_injection", "Edge-Aware Adaptive Texture strength. Enhances pores/hair/decals without noise on flat surfaces.")),
                io.Combo.Input("color_match", options=COLOR_MATCH_OPTIONS, default="none",
                               tooltip=_t("krea2_color_match", "Locks color palette and skin tones to source image.")),
                io.Combo.Input("identity_lora_name", options=lora_list, default="none",
                               tooltip=_t("krea2_identity_lora_name", "Optional identity LoRA.")),
                io.Float.Input("identity_lora_strength", default=1.0, min=0.0, max=2.0, step=0.05,
                               tooltip=_t("krea2_identity_lora_strength", "Weight of identity LoRA.")),
            ],
            outputs=[
                io.Image.Output(display_name="image", tooltip="Final upscaled image with Edge-Aware texture refinement."),
                io.Latent.Output(display_name="latent", tooltip="Final denoised latent representation."),
            ],
            search_aliases=["krea2", "tiled", "diffusion", "upscale", "super resolution"],
        )

    @classmethod
    def execute(cls, model, clip, vae, image=None, upscale_model=None, latent=None,
                prompt: str = "hyperrealistic, highly detailed, 8k uhd", seed: int = 0, steps: int = 8,
                denoise: float = 0.22, vision_weight: float = 1.40, upscale_factor: float = 2.0,
                tile_grid: str = "auto", tile_overlap: str = "auto (256px)", tile_batch_size: int = 1,
                texture_injection: float = 0.20, color_match: str = "none",
                identity_lora_name: str = "none", identity_lora_strength: float = 1.0):
        import comfy.sample
        import comfy.sd

        if image is None and latent is None:
            raise ValueError("FiLKrea2TiledDiffusion requires at least one of 'image' or 'latent' to be connected.")

        # 1. Base upscaled reference
        if image is not None:
            scaled_image = scale_image_by_factor(image, upscale_factor, upscale_model)
        else:
            scaled_image = None

        # 2. Target latent
        if scaled_image is not None:
            target_latent = vae.encode(scaled_image[:, :, :, :3])
        else:
            in_lat = latent["samples"]
            t_w = max(16, int(round(in_lat.shape[-1] * upscale_factor / 2.0)) * 2)
            t_h = max(16, int(round(in_lat.shape[-2] * upscale_factor / 2.0)) * 2)
            target_latent = comfy.utils.common_upscale(in_lat, t_w, t_h, "bislerp", "disabled")

        lat_w = target_latent.shape[-1]
        lat_h = target_latent.shape[-2]

        overlap_px = _parse_overlap_pixels(tile_overlap)
        plan = calculate_tiles(lat_w, lat_h, tile_grid, overlap_px)

        # 3. Apply LoRA if requested
        active_model = model
        active_clip = clip
        if identity_lora_name != "none":
            lora_path = folder_paths.get_full_path("loras", identity_lora_name)
            if lora_path:
                lora_data = comfy.utils.load_torch_file(lora_path, safe_load=True)
                active_model, active_clip = comfy.sd.load_lora_for_models(
                    active_model, active_clip, lora_data, identity_lora_strength, identity_lora_strength)

        # 4. Conditioning
        conditioning_per_tile = None
        global_cond = None

        if hasattr(active_clip, "encode_from_tokens_with_vision") and scaled_image is not None:
            conditioning_per_tile = []
            for t in plan.tiles:
                px_l = t.column_start * LATENT_SCALE
                px_t = t.row_start * LATENT_SCALE
                px_r = min(scaled_image.shape[2], (t.column_start + t.width) * LATENT_SCALE)
                px_b = min(scaled_image.shape[1], (t.row_start + t.height) * LATENT_SCALE)
                tile_crop = scaled_image[:, px_t:px_b, px_l:px_r, :3]

                tokens = active_clip.tokenize(prompt, return_word_ids=True)
                tile_c = active_clip.encode_from_tokens_with_vision(tokens, tile_crop, vision_weight=vision_weight)
                conditioning_per_tile.append([[tile_c, {}]])

            tokens_global = active_clip.tokenize(prompt, return_word_ids=True)
            global_cond = [[active_clip.encode_from_tokens_with_vision(tokens_global, scaled_image[:, :, :, :3], vision_weight=vision_weight), {}]]
        else:
            tokens = active_clip.tokenize(prompt)
            cond_t = active_clip.encode_from_tokens(tokens)
            global_cond = [[cond_t, {}]]

        empty_uncond = [[torch.zeros_like(global_cond[0][0]), {}]]

        # 5. Patch model for RoPE offsets
        cloned_model = active_model.clone()
        rope_holder = TileRopeOffsetHolder()
        cloned_model.set_model_patch(build_post_input_rope_offset_patch(rope_holder), "post_input")

        # 6. Denoise loop wrapper
        def tiled_model_wrapper(apply_model, args):
            latent_in = args["input"]
            timestep = args["timestep"]
            c = args["c"]
            cond_or_uncond = args.get("cond_or_uncond")

            return denoise_latent_as_fused_tiles(
                apply_model=apply_model,
                latent=latent_in,
                timestep=timestep,
                conditioning=c,
                plan=plan,
                rope_offset_holder=rope_holder,
                cond_or_uncond=cond_or_uncond,
                conditioning_per_tile=conditioning_per_tile,
                tile_batch_size=tile_batch_size
            )

        cloned_model.set_model_unet_function_wrapper(tiled_model_wrapper)

        # 7. Sample
        device = target_latent.device
        target_latent = comfy.sample.fix_empty_latent_channels(cloned_model, target_latent)
        sigmas = comfy.samplers.KSampler(
            cloned_model, steps=steps, device=device,
            sampler="euler", scheduler="simple", denoise=denoise
        ).sigmas

        noise = comfy.sample.prepare_noise(target_latent, seed)
        sampler = comfy.samplers.sampler_object("euler")

        samples = comfy.samplers.sample(
            cloned_model, noise, global_cond, empty_uncond, cfg=1.0,
            device=device, sampler=sampler, sigmas=sigmas.to(device),
            model_options=cloned_model.model_options,
            latent_image=target_latent,
            denoise_mask=None,
            disable_pbar=False,
            seed=seed
        )

        cloned_model.model_options.pop("model_function_wrapper", None)
        rope_holder.clear()

        # 8. Decode
        decoded_image = decode_vae_safely(vae, samples)

        # 9. Polish: Edge-Aware Texture & Color Match
        if scaled_image is not None and texture_injection > 0.0:
            decoded_image = apply_edge_aware_texture(decoded_image, scaled_image, blend_strength=texture_injection)

        if scaled_image is not None and color_match != "none":
            decoded_image = apply_color_matching(scaled_image, decoded_image, mode=color_match)

        comfy.model_management.soft_empty_cache()

        return (decoded_image, {"samples": samples})
